"""Property-based tests for Row-Level Security (RLS) user data isolation.

**Validates: Requirements 29.4**

Property 2: User data isolation — queries with user_id context only return
    rows belonging to that user.

We simulate the RLS policy logic that PostgreSQL enforces via
    USING (user_id = current_setting('app.current_user_id')::UUID)
and for nullable user_id tables (watchlists, screener_presets):
    USING (user_id IS NULL OR user_id = current_setting('app.current_user_id')::UUID)

Tests are pure/in-memory — no real database needed.
"""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

# ── RLS policy simulation ────────────────────────────────────────────────────

# Tables with strict user_id isolation (NOT NULL user_id)
STRICT_RLS_TABLES = [
    "trades",
    "orders",
    "sentiment_log",
    "bias_log",
    "audit_log",
    "ml_training_samples",
    "ml_predictions",
    "social_logins",
    "refresh_tokens",
    "pan_verifications",
    "kyc_verifications",
    "dmat_accounts",
    "bank_accounts",
    "fund_transactions",
    "broker_connections",
    "chatbot_sessions",
    "trading_balances",
    "api_request_log",
]

# Tables with nullable user_id (pre-built items visible to all)
NULLABLE_RLS_TABLES = [
    "watchlists",
    "screener_presets",
]


def apply_strict_rls_policy(rows: list[dict], current_user_id: str) -> list[dict]:
    """Simulate strict RLS: USING (user_id = current_setting('app.current_user_id')::UUID)."""
    return [r for r in rows if r["user_id"] == current_user_id]


def apply_nullable_rls_policy(rows: list[dict], current_user_id: str) -> list[dict]:
    """Simulate nullable RLS: USING (user_id IS NULL OR user_id = current_setting(...))."""
    return [r for r in rows if r["user_id"] is None or r["user_id"] == current_user_id]


# ── Strategies ───────────────────────────────────────────────────────────────

user_id_strategy = st.builds(lambda: str(uuid.uuid4()))


@st.composite
def strict_row(draw, user_ids: list[str]):
    """Generate a row with a non-null user_id chosen from the provided pool."""
    uid = draw(st.sampled_from(user_ids))
    row_id = draw(st.integers(min_value=1, max_value=1_000_000))
    return {"id": row_id, "user_id": uid}


@st.composite
def nullable_row(draw, user_ids: list[str]):
    """Generate a row with user_id that can be None (pre-built) or a user UUID."""
    is_prebuilt = draw(st.booleans())
    if is_prebuilt:
        uid = None
    else:
        uid = draw(st.sampled_from(user_ids))
    row_id = draw(st.integers(min_value=1, max_value=1_000_000))
    return {"id": row_id, "user_id": uid}


@st.composite
def multi_user_strict_dataset(draw, min_users=2, max_users=5, min_rows=1, max_rows=30):
    """Generate a dataset of rows belonging to multiple users (strict RLS)."""
    n_users = draw(st.integers(min_value=min_users, max_value=max_users))
    user_ids = [str(uuid.uuid4()) for _ in range(n_users)]
    n_rows = draw(st.integers(min_value=min_rows, max_value=max_rows))
    rows = [draw(strict_row(user_ids)) for _ in range(n_rows)]
    table = draw(st.sampled_from(STRICT_RLS_TABLES))
    return user_ids, rows, table


@st.composite
def multi_user_nullable_dataset(draw, min_users=2, max_users=5, min_rows=1, max_rows=30):
    """Generate a dataset with nullable user_id rows (watchlists/screener_presets)."""
    n_users = draw(st.integers(min_value=min_users, max_value=max_users))
    user_ids = [str(uuid.uuid4()) for _ in range(n_users)]
    n_rows = draw(st.integers(min_value=min_rows, max_value=max_rows))
    rows = [draw(nullable_row(user_ids)) for _ in range(n_rows)]
    table = draw(st.sampled_from(NULLABLE_RLS_TABLES))
    return user_ids, rows, table


# ── Property 2: User data isolation ─────────────────────────────────────────


class TestRLSIsolationProperty:
    """**Validates: Requirements 29.4**

    Property 2: User data isolation — queries with user_id context only
    return rows belonging to that user. No cross-user data leakage occurs
    regardless of the number of users or rows.
    """

    @given(data=multi_user_strict_dataset())
    @settings(max_examples=50)
    def test_strict_rls_returns_only_own_rows(self, data):
        """For strict RLS tables, filtering with a user_id context must return
        only rows where user_id matches exactly.
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_strict_rls_policy(rows, uid)
            for row in filtered:
                assert row["user_id"] == uid, (
                    f"Table '{table}': RLS returned row with user_id={row['user_id']} "
                    f"when context was {uid}"
                )

    @given(data=multi_user_strict_dataset())
    @settings(max_examples=50)
    def test_strict_rls_no_cross_user_leakage(self, data):
        """For strict RLS tables, no row belonging to another user should
        appear in the filtered result.
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_strict_rls_policy(rows, uid)
            other_user_ids = {u for u in user_ids if u != uid}
            leaked = [r for r in filtered if r["user_id"] in other_user_ids]
            assert len(leaked) == 0, (
                f"Table '{table}': {len(leaked)} rows leaked from other users "
                f"when context was {uid}"
            )

    @given(data=multi_user_strict_dataset())
    @settings(max_examples=50)
    def test_strict_rls_completeness(self, data):
        """For strict RLS tables, all rows belonging to the querying user
        must be returned (no rows dropped).
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_strict_rls_policy(rows, uid)
            expected = [r for r in rows if r["user_id"] == uid]
            assert len(filtered) == len(expected), (
                f"Table '{table}': expected {len(expected)} rows for user {uid}, "
                f"got {len(filtered)}"
            )

    @given(data=multi_user_strict_dataset(min_users=2, max_users=6, min_rows=5, max_rows=50))
    @settings(max_examples=25)
    def test_strict_rls_partition_covers_all_rows(self, data):
        """The union of RLS-filtered results across all users must equal
        the full dataset (every row is visible to exactly one user).
        """
        user_ids, rows, table = data

        total_filtered = 0
        for uid in user_ids:
            total_filtered += len(apply_strict_rls_policy(rows, uid))

        assert total_filtered == len(rows), (
            f"Table '{table}': union of per-user filtered rows ({total_filtered}) "
            f"!= total rows ({len(rows)})"
        )

    @given(data=multi_user_nullable_dataset())
    @settings(max_examples=50)
    def test_nullable_rls_prebuilt_visible_to_all(self, data):
        """For nullable RLS tables (watchlists, screener_presets), rows with
        user_id=NULL (pre-built) must be visible to every user.
        """
        user_ids, rows, table = data

        prebuilt_rows = [r for r in rows if r["user_id"] is None]
        if not prebuilt_rows:
            return  # no pre-built rows to check

        for uid in user_ids:
            filtered = apply_nullable_rls_policy(rows, uid)
            prebuilt_in_result = [r for r in filtered if r["user_id"] is None]
            assert len(prebuilt_in_result) == len(prebuilt_rows), (
                f"Table '{table}': user {uid} sees {len(prebuilt_in_result)} pre-built rows, "
                f"expected {len(prebuilt_rows)}"
            )

    @given(data=multi_user_nullable_dataset())
    @settings(max_examples=50)
    def test_nullable_rls_user_rows_isolated(self, data):
        """For nullable RLS tables, user-specific rows (non-NULL user_id)
        must only be visible to their owner.
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_nullable_rls_policy(rows, uid)
            for row in filtered:
                assert row["user_id"] is None or row["user_id"] == uid, (
                    f"Table '{table}': RLS returned row with user_id={row['user_id']} "
                    f"when context was {uid} (expected NULL or {uid})"
                )

    @given(data=multi_user_nullable_dataset())
    @settings(max_examples=50)
    def test_nullable_rls_no_cross_user_leakage(self, data):
        """For nullable RLS tables, no row belonging to another user should
        appear in the filtered result (pre-built NULL rows are allowed).
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_nullable_rls_policy(rows, uid)
            other_user_ids = {u for u in user_ids if u != uid}
            leaked = [
                r for r in filtered
                if r["user_id"] is not None and r["user_id"] in other_user_ids
            ]
            assert len(leaked) == 0, (
                f"Table '{table}': {len(leaked)} user-specific rows leaked "
                f"from other users when context was {uid}"
            )

    @given(
        data=multi_user_nullable_dataset(min_users=2, max_users=5, min_rows=5, max_rows=40),
    )
    @settings(max_examples=25)
    def test_nullable_rls_completeness(self, data):
        """For nullable RLS tables, all pre-built rows plus all rows belonging
        to the querying user must be returned.
        """
        user_ids, rows, table = data

        for uid in user_ids:
            filtered = apply_nullable_rls_policy(rows, uid)
            expected = [
                r for r in rows
                if r["user_id"] is None or r["user_id"] == uid
            ]
            assert len(filtered) == len(expected), (
                f"Table '{table}': expected {len(expected)} rows for user {uid}, "
                f"got {len(filtered)}"
            )

    @given(
        unknown_uid=user_id_strategy,
        data=multi_user_strict_dataset(min_users=2, min_rows=5),
    )
    @settings(max_examples=25)
    def test_strict_rls_unknown_user_sees_nothing(self, unknown_uid, data):
        """A user_id not present in the dataset should see zero rows
        through strict RLS.
        """
        user_ids, rows, table = data

        # Ensure the unknown user is truly not in the dataset
        if unknown_uid in user_ids:
            return

        filtered = apply_strict_rls_policy(rows, unknown_uid)
        assert len(filtered) == 0, (
            f"Table '{table}': unknown user {unknown_uid} saw {len(filtered)} rows"
        )

    @given(
        unknown_uid=user_id_strategy,
        data=multi_user_nullable_dataset(min_users=2, min_rows=5),
    )
    @settings(max_examples=25)
    def test_nullable_rls_unknown_user_sees_only_prebuilt(self, unknown_uid, data):
        """A user_id not present in the dataset should see only pre-built
        (NULL user_id) rows through nullable RLS.
        """
        user_ids, rows, table = data

        if unknown_uid in user_ids:
            return

        filtered = apply_nullable_rls_policy(rows, unknown_uid)
        prebuilt_count = sum(1 for r in rows if r["user_id"] is None)
        assert len(filtered) == prebuilt_count, (
            f"Table '{table}': unknown user saw {len(filtered)} rows, "
            f"expected only {prebuilt_count} pre-built rows"
        )
