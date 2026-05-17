"""Property-based tests for SQLite-to-PostgreSQL migration round-trip consistency.

**Validates: Requirements 31.5**

Property 1: Migration round-trip consistency — exporting from SQLite,
    importing to PostgreSQL, then exporting from PostgreSQL produces
    equivalent data sets.

We test the pure/testable functions of the migrator without requiring a real
PostgreSQL database:
  - _checksum_rows() determinism and column-subset stability
  - _add_user_id_column() preserves original column data
  - SQLite write → _read_sqlite_table() → checksum matches original data
"""

from __future__ import annotations

import copy
import os
import sqlite3
import sys
import tempfile
import types

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# The migration script imports psycopg2 which may not be installed in the
# test environment.  We only exercise pure functions (_checksum_rows,
# _add_user_id_column, _read_sqlite_table) that never touch PostgreSQL,
# so we stub psycopg2 at import time.
_pg_stub = types.ModuleType("psycopg2")
_pg_stub.Binary = lambda x: x  # type: ignore[attr-defined]
_pg_extras = types.ModuleType("psycopg2.extras")
_pg_ext = types.ModuleType("psycopg2.extensions")
sys.modules.setdefault("psycopg2", _pg_stub)
sys.modules.setdefault("psycopg2.extras", _pg_extras)
sys.modules.setdefault("psycopg2.extensions", _pg_ext)

from scripts.migrate_sqlite_to_postgres import (
    SQLiteToPostgresMigrator,
)

# ── Strategies ───────────────────────────────────────────────────────────────

# Safe text that avoids null bytes (SQLite doesn't like them)
safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=50,
)

finite_float = st.floats(
    min_value=-1e9,
    max_value=1e9,
    allow_nan=False,
    allow_infinity=False,
)

positive_int = st.integers(min_value=1, max_value=1_000_000)

column_name = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

# Strategy for a single row dict with consistent columns


@st.composite
def row_data(draw, columns: list[str] | None = None):
    """Generate a single row dict with string/int/float values."""
    if columns is None:
        n_cols = draw(st.integers(min_value=2, max_value=6))
        columns = [draw(column_name) for _ in range(n_cols)]
        # Ensure 'id' is present for checksum sorting
        if "id" not in columns:
            columns = ["id"] + columns
    row = {}
    for col in columns:
        if col == "id":
            row[col] = draw(positive_int)
        else:
            val = draw(st.one_of(safe_text, finite_float, positive_int))
            row[col] = val
    return row


@st.composite
def row_list(draw, min_rows=1, max_rows=10):
    """Generate a list of rows sharing the same column set."""
    # Use fixed pool of column names to keep base example small
    all_cols = ["id", "col_a", "col_b", "col_c", "col_d", "col_e"]
    n_cols = draw(st.integers(min_value=2, max_value=5))
    cols = ["id"] + all_cols[1 : n_cols + 1]

    n_rows = draw(st.integers(min_value=min_rows, max_value=max_rows))
    rows = []
    used_ids = set()
    for _ in range(n_rows):
        r = {}
        for col in cols:
            if col == "id":
                rid = draw(positive_int)
                while rid in used_ids:
                    rid = draw(positive_int)
                used_ids.add(rid)
                r[col] = rid
            else:
                r[col] = draw(st.one_of(safe_text, finite_float, positive_int))
        rows.append(r)
    return rows, cols


# Realistic table schemas matching the SQLite schema
TRADES_COLUMNS = [
    "id",
    "trade_id",
    "symbol",
    "side",
    "strategy",
    "entry_price",
    "exit_price",
    "quantity",
    "entry_time",
    "exit_time",
    "realized_pnl",
    "stop_loss",
    "target",
    "exit_reason",
    "created_at",
]

ORDERS_COLUMNS = [
    "id",
    "order_id",
    "trade_id",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "price",
    "trigger_price",
    "status",
    "broker_order_id",
    "filled_qty",
    "filled_price",
    "rejection_reason",
    "created_at",
    "updated_at",
]

NEWS_COLUMNS = [
    "id",
    "article_id",
    "source",
    "title",
    "content",
    "url",
    "published_at",
    "fetched_at",
    "content_hash",
    "sentiment",
    "created_at",
]


@st.composite
def trades_rows(draw, min_rows=1, max_rows=8):
    """Generate realistic trades table rows."""
    n = draw(st.integers(min_value=min_rows, max_value=max_rows))
    rows = []
    for i in range(n):
        entry_price = draw(finite_float.filter(lambda x: x > 0))
        rows.append(
            {
                "id": i + 1,
                "trade_id": f"T{draw(st.integers(min_value=1000, max_value=9999))}_{i}",
                "symbol": draw(st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"])),
                "side": draw(st.sampled_from(["BUY", "SELL"])),
                "strategy": draw(st.sampled_from(["mean_reversion", "trend_following", "orb"])),
                "entry_price": entry_price,
                "exit_price": draw(st.one_of(st.none(), finite_float.filter(lambda x: x > 0))),
                "quantity": draw(st.integers(min_value=1, max_value=1000)),
                "entry_time": "2025-01-15 10:30:00",
                "exit_time": draw(st.one_of(st.none(), st.just("2025-01-15 14:30:00"))),
                "realized_pnl": draw(st.one_of(st.none(), finite_float)),
                "stop_loss": entry_price * 0.98,
                "target": entry_price * 1.04,
                "exit_reason": draw(
                    st.one_of(st.none(), st.sampled_from(["target", "stop_loss", "manual"]))
                ),
                "created_at": "2025-01-15 10:30:00",
            }
        )
    return rows


# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_sqlite_with_rows(
    db_path: str,
    table: str,
    columns: list[str],
    rows: list[dict],
) -> None:
    """Create a SQLite table and insert rows."""
    conn = sqlite3.connect(db_path)
    # Build CREATE TABLE — all columns TEXT except id INTEGER PRIMARY KEY
    col_defs = []
    for c in columns:
        if c == "id":
            col_defs.append("id INTEGER PRIMARY KEY")
        else:
            col_defs.append(f"{c} TEXT")
    create_sql = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"
    conn.execute(create_sql)

    if rows:
        placeholders = ", ".join(["?"] * len(columns))
        insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        for row in rows:
            values = [row.get(c) for c in columns]
            # Convert non-string/non-None values to string for TEXT columns
            converted = []
            for i, v in enumerate(values):
                if columns[i] == "id":
                    converted.append(v)
                elif v is None:
                    converted.append(None)
                else:
                    converted.append(str(v))
            conn.execute(insert_sql, converted)
    conn.commit()
    conn.close()


# ── Property 1: Migration round-trip consistency ─────────────────────────────


class TestMigrationRoundTripProperty:
    """**Validates: Requirements 31.5**

    Property 1: Migration round-trip consistency — exporting from SQLite,
    importing to PostgreSQL, then exporting from PostgreSQL produces
    equivalent data sets.
    """

    @given(data=row_list(min_rows=1, max_rows=10))
    @settings(max_examples=50)
    def test_checksum_deterministic(self, data):
        """_checksum_rows() returns the same hash for the same input data."""
        rows, cols = data
        hash1 = SQLiteToPostgresMigrator._checksum_rows(rows, cols)
        hash2 = SQLiteToPostgresMigrator._checksum_rows(rows, cols)
        assert hash1 == hash2, "Checksum is not deterministic"

    @given(data=row_list(min_rows=1, max_rows=10))
    @settings(max_examples=50)
    def test_checksum_order_independent(self, data):
        """_checksum_rows() produces the same hash regardless of input row order,
        because it sorts rows internally by id.
        """
        rows, cols = data
        import random

        shuffled = rows.copy()
        random.shuffle(shuffled)
        hash_original = SQLiteToPostgresMigrator._checksum_rows(rows, cols)
        hash_shuffled = SQLiteToPostgresMigrator._checksum_rows(shuffled, cols)
        assert hash_original == hash_shuffled, "Checksum changed with row reordering"

    @given(data=row_list(min_rows=1, max_rows=10))
    @settings(max_examples=50)
    def test_add_user_id_preserves_original_columns_checksum(self, data):
        """Adding user_id via _add_user_id_column() must not change the checksum
        computed over the original (non-user_id) columns.
        """
        rows, cols = data
        original_rows = copy.deepcopy(rows)
        hash_before = SQLiteToPostgresMigrator._checksum_rows(original_rows, cols)

        migrator = SQLiteToPostgresMigrator.__new__(SQLiteToPostgresMigrator)
        migrator._add_user_id_column(rows, "00000000-0000-0000-0000-000000000001")

        # Checksum on original columns should be unchanged
        hash_after = SQLiteToPostgresMigrator._checksum_rows(rows, cols)
        assert (
            hash_before == hash_after
        ), "Checksum over original columns changed after adding user_id"

    @given(data=row_list(min_rows=1, max_rows=10))
    @settings(max_examples=25)
    def test_add_user_id_adds_key_to_all_rows(self, data):
        """_add_user_id_column() must add 'user_id' key to every row."""
        rows, cols = data
        uid = "test-user-id-123"
        migrator = SQLiteToPostgresMigrator.__new__(SQLiteToPostgresMigrator)
        migrator._add_user_id_column(rows, uid)
        for row in rows:
            assert "user_id" in row, "Row missing user_id after _add_user_id_column"
            assert row["user_id"] == uid, "user_id value mismatch"

    @given(rows=trades_rows(min_rows=1, max_rows=8))
    @settings(max_examples=25)
    def test_sqlite_roundtrip_checksum_matches(self, rows):
        """Data written to SQLite and read back via _read_sqlite_table()
        must produce the same checksum as the original data.

        This validates the core round-trip property: SQLite export → read back
        produces equivalent data.
        """
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test.db")
        table = "trades"

        _create_sqlite_with_rows(db_path, table, TRADES_COLUMNS, rows)

        migrator = SQLiteToPostgresMigrator(db_path, "unused")
        read_back = migrator._read_sqlite_table(table)

        assert len(read_back) == len(
            rows
        ), f"Row count mismatch: wrote {len(rows)}, read {len(read_back)}"

        # Compute checksum on the original data (stringified to match SQLite storage)
        normalized_original = []
        for row in rows:
            nr = {}
            for col in TRADES_COLUMNS:
                val = row.get(col)
                if col == "id":
                    nr[col] = val
                elif val is None:
                    nr[col] = None
                else:
                    nr[col] = str(val)
            normalized_original.append(nr)

        hash_original = SQLiteToPostgresMigrator._checksum_rows(normalized_original, TRADES_COLUMNS)
        hash_readback = SQLiteToPostgresMigrator._checksum_rows(read_back, TRADES_COLUMNS)

        assert (
            hash_original == hash_readback
        ), "Round-trip checksum mismatch: SQLite write → read produced different data"

    @given(rows=trades_rows(min_rows=1, max_rows=5))
    @settings(max_examples=25)
    def test_sqlite_roundtrip_with_user_id_preserves_shared_columns(self, rows):
        """Full round-trip simulation: write to SQLite → read back → add user_id →
        checksum on shared (SQLite) columns still matches the original data.

        This simulates the migration path without needing PostgreSQL.
        """
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test.db")
        table = "trades"

        _create_sqlite_with_rows(db_path, table, TRADES_COLUMNS, rows)

        migrator = SQLiteToPostgresMigrator(db_path, "unused")
        read_back = migrator._read_sqlite_table(table)

        # Normalize original for comparison
        normalized_original = []
        for row in rows:
            nr = {}
            for col in TRADES_COLUMNS:
                val = row.get(col)
                if col == "id":
                    nr[col] = val
                elif val is None:
                    nr[col] = None
                else:
                    nr[col] = str(val)
            normalized_original.append(nr)

        hash_before = SQLiteToPostgresMigrator._checksum_rows(normalized_original, TRADES_COLUMNS)

        # Simulate PostgreSQL side: add user_id (as migration does for user-scoped tables)
        migrator._add_user_id_column(read_back, "00000000-0000-0000-0000-000000000001")

        # Checksum on shared SQLite columns should still match
        hash_after = SQLiteToPostgresMigrator._checksum_rows(read_back, TRADES_COLUMNS)

        assert (
            hash_before == hash_after
        ), "Round-trip checksum on shared columns changed after adding user_id"

    @given(data=row_list(min_rows=2, max_rows=10))
    @settings(max_examples=25, suppress_health_check=[HealthCheck.large_base_example])
    def test_checksum_column_subset_stability(self, data):
        """Checksum computed on a subset of columns should be stable and
        independent of extra columns in the row dicts.
        """
        rows, cols = data
        assume(len(cols) >= 3)

        subset_cols = cols[: len(cols) - 1]  # Drop last column
        hash_full_cols = SQLiteToPostgresMigrator._checksum_rows(rows, subset_cols)

        # Add an extra column to each row
        augmented = copy.deepcopy(rows)
        for r in augmented:
            r["extra_col_xyz"] = "noise"

        hash_augmented = SQLiteToPostgresMigrator._checksum_rows(augmented, subset_cols)
        assert (
            hash_full_cols == hash_augmented
        ), "Checksum on column subset changed when extra columns were added to rows"
