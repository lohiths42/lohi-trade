"""Property-based tests for watchlist capacity limits.

**Validates: Requirements 9.1, 9.2**

Property 13: Watchlist capacity enforcement — adding beyond 20 watchlists
or 100 securities per watchlist is rejected.

Uses Hypothesis with mocked db_pool to test limit enforcement across
many different count values without a real database.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.watchlist_service import (
    WatchlistService,
    WatchlistError,
    MAX_WATCHLISTS_PER_USER,
    MAX_SECURITIES_PER_WATCHLIST,
    REASON_MAX_WATCHLISTS,
    REASON_MAX_SECURITIES,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
WATCHLIST_ID = "11111111-2222-3333-4444-555555555555"


def _make_service(db_pool=None) -> WatchlistService:
    return WatchlistService(db_pool=db_pool)


def _make_mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_mock_row(data: dict):
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: data[key]
    mock_row.get = lambda key, default=None: data.get(key, default)
    return mock_row


# ── Strategies ───────────────────────────────────────────────────────────────

# Counts at or above the watchlist limit (20..50)
at_or_above_watchlist_limit = st.integers(
    min_value=MAX_WATCHLISTS_PER_USER, max_value=50
)

# Counts below the watchlist limit (0..19)
below_watchlist_limit = st.integers(
    min_value=0, max_value=MAX_WATCHLISTS_PER_USER - 1
)

# Counts at or above the securities-per-watchlist limit (100..200)
at_or_above_securities_limit = st.integers(
    min_value=MAX_SECURITIES_PER_WATCHLIST, max_value=200
)

# Counts below the securities-per-watchlist limit (0..99)
below_securities_limit = st.integers(
    min_value=0, max_value=MAX_SECURITIES_PER_WATCHLIST - 1
)

# Valid watchlist names
watchlist_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


# ── Property 13: Watchlist capacity enforcement ──────────────────────────────


class TestWatchlistCapacityEnforcementProperty:
    """**Validates: Requirements 9.1, 9.2**

    Property 13: Watchlist capacity enforcement — adding beyond 20 watchlists
    or 100 securities per watchlist is rejected.
    """

    # ── 9.1: Max 20 watchlists per user ──────────────────────────────────

    @given(existing_count=at_or_above_watchlist_limit, name=watchlist_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_create_watchlist_rejected_at_or_above_limit(
        self, existing_count: int, name: str
    ):
        """When a user already has >= 20 watchlists, creating another must
        raise WatchlistError with reason max_watchlists_reached."""
        pool, conn = _make_mock_pool()
        # _get_watchlist_count returns existing_count
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({"cnt": existing_count}))

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.create_watchlist(USER_ID, name)

        assert exc_info.value.reason == REASON_MAX_WATCHLISTS, (
            f"Expected reason '{REASON_MAX_WATCHLISTS}' when user has "
            f"{existing_count} watchlists, got '{exc_info.value.reason}'"
        )

    @given(existing_count=below_watchlist_limit, name=watchlist_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_create_watchlist_accepted_below_limit(
        self, existing_count: int, name: str
    ):
        """When a user has < 20 watchlists, creating a new one must succeed
        (not raise max_watchlists_reached)."""
        pool, conn = _make_mock_pool()
        now = datetime.now(timezone.utc)

        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_watchlist_count
                return _make_mock_row({"cnt": existing_count})
            else:
                # INSERT RETURNING
                return _make_mock_row({
                    "id": WATCHLIST_ID,
                    "user_id": USER_ID,
                    "name": name.strip(),
                    "is_prebuilt": False,
                    "sort_order": existing_count,
                    "created_at": now,
                })

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

        svc = _make_service(db_pool=pool)
        result = await svc.create_watchlist(USER_ID, name)

        assert result.name == name.strip(), (
            f"Expected watchlist name '{name.strip()}', got '{result.name}'"
        )

    # ── 9.2: Max 100 securities per watchlist ────────────────────────────

    @given(existing_count=at_or_above_securities_limit)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_add_security_rejected_at_or_above_limit(
        self, existing_count: int
    ):
        """When a watchlist already has >= 100 securities, adding another must
        raise WatchlistError with reason max_securities_reached."""
        pool, conn = _make_mock_pool()

        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Watchlist ownership check
                return _make_mock_row({"id": WATCHLIST_ID})
            elif call_count == 2:
                # Security lookup
                return _make_mock_row({"id": 1, "symbol": "RELIANCE", "status": "ACTIVE"})
            elif call_count == 3:
                # Item count
                return _make_mock_row({"cnt": existing_count})
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")

        assert exc_info.value.reason == REASON_MAX_SECURITIES, (
            f"Expected reason '{REASON_MAX_SECURITIES}' when watchlist has "
            f"{existing_count} securities, got '{exc_info.value.reason}'"
        )

    @given(existing_count=below_securities_limit)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_add_security_accepted_below_limit(
        self, existing_count: int
    ):
        """When a watchlist has < 100 securities, adding a new one must succeed
        (not raise max_securities_reached)."""
        pool, conn = _make_mock_pool()
        now = datetime.now(timezone.utc)

        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Watchlist ownership check
                return _make_mock_row({"id": WATCHLIST_ID})
            elif call_count == 2:
                # Security lookup
                return _make_mock_row({"id": 42, "symbol": "TCS", "status": "ACTIVE"})
            elif call_count == 3:
                # Item count
                return _make_mock_row({"cnt": existing_count})
            elif call_count == 4:
                # Duplicate check — no existing
                return None
            elif call_count == 5:
                # INSERT RETURNING
                return _make_mock_row({
                    "id": "new-item-id",
                    "watchlist_id": WATCHLIST_ID,
                    "security_id": 42,
                    "sort_order": existing_count,
                    "added_at": now,
                })
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

        svc = _make_service(db_pool=pool)
        result = await svc.add_security(USER_ID, WATCHLIST_ID, "TCS")

        assert result.symbol == "TCS", (
            f"Expected symbol 'TCS', got '{result.symbol}'"
        )

    # ── Boundary: exact limit values ─────────────────────────────────────

    def test_max_watchlists_constant_is_20(self):
        """MAX_WATCHLISTS_PER_USER must equal 20."""
        assert MAX_WATCHLISTS_PER_USER == 20

    def test_max_securities_constant_is_100(self):
        """MAX_SECURITIES_PER_WATCHLIST must equal 100."""
        assert MAX_SECURITIES_PER_WATCHLIST == 100
