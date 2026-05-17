"""
SQLite-to-PostgreSQL migration script for LOHI-TRADE platform expansion.

Migrates all existing SQLite data into the new PostgreSQL schema, assigning
a user_id to every user-scoped row. Idempotent — safe to re-run without
duplicating data.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/lohi_trade.db \
        --pg "postgresql://lohi:lohi@localhost:5432/lohi_trade" \
        --admin-user-id "00000000-0000-0000-0000-000000000001"

    # Validate only (no writes):
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/lohi_trade.db \
        --pg "postgresql://lohi:lohi@localhost:5432/lohi_trade" \
        --validate-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Tables that get a user_id column in PostgreSQL
USER_SCOPED_TABLES = [
    "trades",
    "orders",
    "sentiment_log",
    "bias_log",
    "audit_log",
    "ml_training_samples",
    "ml_predictions",
]

# Shared tables (no user_id added)
SHARED_TABLES = [
    "news_articles",
    "ml_model_metrics",
]

ALL_TABLES = USER_SCOPED_TABLES + SHARED_TABLES

# Column name mapping: SQLite column → PostgreSQL column (only where names differ)
# Most columns are identical; features BLOB → BYTEA is handled by psycopg2 automatically.


@dataclass
class TableReport:
    table: str
    sqlite_count: int = 0
    pg_count: int = 0
    migrated: int = 0
    skipped: int = 0
    checksum_match: bool = False
    error: Optional[str] = None


@dataclass
class MigrationReport:
    tables: List[TableReport] = field(default_factory=list)
    admin_user_id: Optional[str] = None
    success: bool = True

    def summary(self) -> str:
        lines = ["Migration Report", "=" * 50]
        for t in self.tables:
            status = "OK" if t.error is None else f"ERROR: {t.error}"
            lines.append(
                f"  {t.table:25s}  sqlite={t.sqlite_count:6d}  "
                f"pg={t.pg_count:6d}  migrated={t.migrated:6d}  "
                f"skipped={t.skipped:6d}  checksum={'MATCH' if t.checksum_match else 'MISMATCH'}  {status}"
            )
        lines.append("=" * 50)
        lines.append(f"Overall: {'SUCCESS' if self.success else 'FAILED'}")
        return "\n".join(lines)


@dataclass
class ValidationReport:
    tables: List[TableReport] = field(default_factory=list)
    all_match: bool = True

    def summary(self) -> str:
        lines = ["Validation Report", "=" * 50]
        for t in self.tables:
            lines.append(
                f"  {t.table:25s}  sqlite={t.sqlite_count:6d}  "
                f"pg={t.pg_count:6d}  checksum={'MATCH' if t.checksum_match else 'MISMATCH'}"
            )
        lines.append("=" * 50)
        lines.append(f"Overall: {'ALL MATCH' if self.all_match else 'MISMATCH DETECTED'}")
        return "\n".join(lines)


class SQLiteToPostgresMigrator:
    """Idempotent migration from SQLite to PostgreSQL."""

    TABLES = ALL_TABLES

    def __init__(self, sqlite_path: str, pg_dsn: str):
        self.sqlite_path = sqlite_path
        self.pg_dsn = pg_dsn

    # ── helpers ──────────────────────────────────────────────────

    def _sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _pg_conn(self) -> psycopg2.extensions.connection:
        return psycopg2.connect(self.pg_dsn)

    @staticmethod
    def _get_sqlite_columns(conn: sqlite3.Connection, table: str) -> List[str]:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return [row["name"] for row in cursor.fetchall()]

    @staticmethod
    def _get_pg_columns(conn, table: str) -> List[str]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s ORDER BY ordinal_position",
                (table,),
            )
            return [row[0] for row in cur.fetchall()]

    @staticmethod
    def _checksum_rows(rows: List[Dict[str, Any]], columns: List[str]) -> str:
        """Compute a deterministic SHA-256 checksum over sorted row data."""
        h = hashlib.sha256()
        for row in sorted(rows, key=lambda r: str(r.get("id", ""))):
            for col in columns:
                val = row.get(col, "")
                # Normalise bytes/memoryview to hex for consistent hashing
                if isinstance(val, (bytes, memoryview)):
                    val = bytes(val).hex()
                h.update(str(val).encode())
        return h.hexdigest()

    def _add_user_id_column(self, rows: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
        """Add user_id to all rows for multi-tenant support."""
        for row in rows:
            row["user_id"] = user_id
        return rows

    def _ensure_admin_user(self, pg_conn, admin_user_id: str) -> None:
        """Create the admin user row if it doesn't already exist."""
        with pg_conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (admin_user_id,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO users (id, email, name, role) " "VALUES (%s, %s, %s, %s)",
                    (admin_user_id, "admin@lohi-trade.local", "Admin", "ADMIN"),
                )
                logger.info("Created admin user %s", admin_user_id)
        pg_conn.commit()

    def _read_sqlite_table(self, table: str) -> List[Dict[str, Any]]:
        conn = self._sqlite_conn()
        try:
            cursor = conn.execute(f"SELECT * FROM {table}")  # noqa: S608
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _existing_ids(self, pg_conn, table: str, id_col: str = "id") -> set:
        """Return the set of existing primary-key values in the PG table."""
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT {id_col} FROM {table}")  # noqa: S608
            return {row[0] for row in cur.fetchall()}

    def _unique_key_col(self, table: str) -> str:
        """Return the natural unique key column used for dedup on re-runs."""
        mapping = {
            "trades": "trade_id",
            "orders": "order_id",
            "news_articles": "article_id",
        }
        return mapping.get(table, "id")

    def _existing_unique_keys(self, pg_conn, table: str) -> set:
        col = self._unique_key_col(table)
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT {col} FROM {table}")  # noqa: S608
            return {row[0] for row in cur.fetchall()}

    def _migrate_table(
        self,
        pg_conn,
        table: str,
        rows: List[Dict[str, Any]],
        pg_columns: List[str],
    ) -> TableReport:
        """Insert rows into PG, skipping duplicates. Returns a TableReport."""
        report = TableReport(table=table, sqlite_count=len(rows))

        if not rows:
            report.pg_count = 0
            report.checksum_match = True
            return report

        unique_col = self._unique_key_col(table)
        existing_keys = self._existing_unique_keys(pg_conn, table)

        # Filter to columns that exist in both source rows and PG table,
        # excluding the auto-generated 'id' serial column.
        insert_cols = [c for c in pg_columns if c != "id" and c in rows[0]]

        migrated = 0
        skipped = 0
        with pg_conn.cursor() as cur:
            for row in rows:
                key_val = row.get(unique_col)
                if key_val is not None and key_val in existing_keys:
                    skipped += 1
                    continue

                values = []
                for col in insert_cols:
                    val = row.get(col)
                    # Convert bytes-like objects for psycopg2
                    if isinstance(val, (bytes, memoryview)):
                        val = psycopg2.Binary(bytes(val))
                    values.append(val)

                placeholders = ", ".join(["%s"] * len(insert_cols))
                col_names = ", ".join(insert_cols)
                cur.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    values,
                )
                migrated += 1

        pg_conn.commit()
        report.migrated = migrated
        report.skipped = skipped

        # Count PG rows after insert
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            report.pg_count = cur.fetchone()[0]

        return report

    # ── public API ───────────────────────────────────────────────

    def migrate(self, admin_user_id: str) -> MigrationReport:
        """Full migration: read SQLite → write PostgreSQL with user_id. Idempotent."""
        report = MigrationReport(admin_user_id=admin_user_id)
        pg_conn = self._pg_conn()

        try:
            # Disable RLS for the migration session so we can write freely
            with pg_conn.cursor() as cur:
                cur.execute("SET app.current_user_id = %s", (admin_user_id,))
            pg_conn.commit()

            self._ensure_admin_user(pg_conn, admin_user_id)

            for table in self.TABLES:
                logger.info("Migrating table: %s", table)
                try:
                    rows = self._read_sqlite_table(table)
                    pg_columns = self._get_pg_columns(pg_conn, table)

                    # Add user_id for user-scoped tables
                    if table in USER_SCOPED_TABLES:
                        self._add_user_id_column(rows, admin_user_id)

                    table_report = self._migrate_table(pg_conn, table, rows, pg_columns)
                    report.tables.append(table_report)
                    logger.info(
                        "  %s: migrated=%d skipped=%d total_pg=%d",
                        table,
                        table_report.migrated,
                        table_report.skipped,
                        table_report.pg_count,
                    )
                except Exception as e:
                    logger.error("  %s: FAILED — %s", table, e)
                    tr = TableReport(table=table, error=str(e))
                    report.tables.append(tr)
                    report.success = False
                    pg_conn.rollback()

        finally:
            pg_conn.close()

        # Run validation pass
        validation = self.validate()
        for tr, vr in zip(report.tables, validation.tables):
            tr.checksum_match = vr.checksum_match
        if not validation.all_match:
            report.success = False

        return report

    def validate(self) -> ValidationReport:
        """Compare row counts and checksums per table between SQLite and PostgreSQL."""
        report = ValidationReport()
        sqlite_conn = self._sqlite_conn()
        pg_conn = self._pg_conn()

        try:
            for table in self.TABLES:
                tr = TableReport(table=table)
                try:
                    # SQLite side
                    sqlite_rows = [
                        dict(r) for r in sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
                    ]
                    sqlite_cols = self._get_sqlite_columns(sqlite_conn, table)
                    tr.sqlite_count = len(sqlite_rows)

                    # PostgreSQL side — read only the columns that exist in SQLite
                    col_list = ", ".join(sqlite_cols)
                    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(f"SELECT {col_list} FROM {table}")  # noqa: S608
                        pg_rows = [dict(r) for r in cur.fetchall()]
                    tr.pg_count = len(pg_rows)

                    # Checksum comparison on shared columns
                    sqlite_hash = self._checksum_rows(sqlite_rows, sqlite_cols)
                    pg_hash = self._checksum_rows(pg_rows, sqlite_cols)
                    tr.checksum_match = sqlite_hash == pg_hash

                    if not tr.checksum_match:
                        report.all_match = False

                except Exception as e:
                    tr.error = str(e)
                    tr.checksum_match = False
                    report.all_match = False

                report.tables.append(tr)
        finally:
            sqlite_conn.close()
            pg_conn.close()

        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate LOHI-TRADE SQLite data to PostgreSQL")
    parser.add_argument("--sqlite", default="data/lohi_trade.db", help="Path to SQLite database")
    parser.add_argument(
        "--pg", default="postgresql://lohi:lohi@localhost:5432/lohi_trade", help="PostgreSQL DSN"
    )
    parser.add_argument(
        "--admin-user-id",
        default="00000000-0000-0000-0000-000000000001",
        help="UUID to assign as user_id for all migrated rows",
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Only validate, do not migrate"
    )
    args = parser.parse_args()

    migrator = SQLiteToPostgresMigrator(args.sqlite, args.pg)

    if args.validate_only:
        report = migrator.validate()
        print(report.summary())
        sys.exit(0 if report.all_match else 1)
    else:
        report = migrator.migrate(args.admin_user_id)
        print(report.summary())
        sys.exit(0 if report.success else 1)


if __name__ == "__main__":
    main()
