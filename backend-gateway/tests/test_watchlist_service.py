"""Unit tests for WatchlistService — CRUD, limits, price enrichment, pre-built watchlists."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.watchlist_service import (
    WatchlistService,
    Watchlist,
    WatchlistItem,
    WatchlistWithPrices,
    SecurityPrice,
    WatchlistError,
    MAX_WATCHLISTS_PER_USER,
    MAX_SECURITIES_PER_WATCHLIST,
    PREBUILT_WATCHLISTS,
    REASON_MAX_WATCHLISTS,
    REASON_MAX_SECURITIES,
    REASON_SECURITY_NOT_FOUND,
    REASON_SECURITY_NOT_ACTIVE,
    REASON_WATCHLIST_NOT_FOUND,
    REASON_DUPLICATE_SECURITY,
    REASON_SECURITY_NOT_IN_WATCHLIST,
    REASON_EMPTY_NAME,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
WATCHLIST_ID = "11111111-2222-3333-4444-555555555555"


def _make_service(db_pool=None, redis_client=None) -> WatchlistService:
    return WatchlistService(db_pool=db_pool, redis_client=redis_client)


def _make_mock_pool():
    """Create a mock asyncpg pool with an async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_mock_row(data: dict):
    """Create a dict-like mock row for asyncpg results."""
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: data[key]
    mock_row.get = lambda key, default=None: data.get(key, default)
    return mock_row


def _watchlist_row(
    id=WATCHLIST_ID,
    user_id=USER_ID,
    name="My Watchlist",
    is_prebuilt=False,
    sort_order=0,
    created_at=None,
):
    return _make_mock_row({
        "id": id,
        "user_id": user_id,
        "name": name,
        "is_prebuilt": is_prebuilt,
        "sort_order": sort_order,
        "created_at": created_at or datetime.now(timezone.utc),
    })


def _security_row(id=1, symbol="RELIANCE", status="ACTIVE"):
    return _make_mock_row({"id": id, "symbol": symbol, "status": status})


def _count_row(cnt):
    return _make_mock_row({"cnt": cnt})


def _item_row(
    id="item-1",
    watchlist_id=WATCHLIST_ID,
    security_id=1,
    sort_order=0,
    added_at=None,
):
    return _make_mock_row({
        "id": id,
        "watchlist_id": watchlist_id,
        "security_id": security_id,
        "sort_order": sort_order,
        "added_at": added_at or datetime.now(timezone.utc),
    })


# ── Create watchlist tests ───────────────────────────────────────────────────


class TestCreateWatchlist:
    @pytest.mark.asyncio
    async def test_create_success(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _count_row(0),  # _get_watchlist_count
            _watchlist_row(name="Tech Stocks"),  # INSERT RETURNING
        ])

        svc = _make_service(db_pool=pool)
        result = await svc.create_watchlist(USER_ID, "Tech Stocks")

        assert isinstance(result, Watchlist)
        assert result.name == "Tech Stocks"
        assert result.id == WATCHLIST_ID

    @pytest.mark.asyncio
    async def test_create_empty_name_raises(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.create_watchlist(USER_ID, "")
        assert exc_info.value.reason == REASON_EMPTY_NAME

    @pytest.mark.asyncio
    async def test_create_whitespace_name_raises(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.create_watchlist(USER_ID, "   ")
        assert exc_info.value.reason == REASON_EMPTY_NAME

    @pytest.mark.asyncio
    async def test_create_max_watchlists_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_count_row(MAX_WATCHLISTS_PER_USER))

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.create_watchlist(USER_ID, "One More")
        assert exc_info.value.reason == REASON_MAX_WATCHLISTS

    @pytest.mark.asyncio
    async def test_create_no_db_raises(self):
        svc = _make_service(db_pool=None)

        with pytest.raises(WatchlistError):
            await svc.create_watchlist(USER_ID, "Test")


# ── Rename watchlist tests ───────────────────────────────────────────────────


class TestRenameWatchlist:
    @pytest.mark.asyncio
    async def test_rename_success(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_watchlist_row(name="New Name"))

        svc = _make_service(db_pool=pool)
        result = await svc.rename_watchlist(USER_ID, WATCHLIST_ID, "New Name")

        assert result.name == "New Name"

    @pytest.mark.asyncio
    async def test_rename_empty_name_raises(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.rename_watchlist(USER_ID, WATCHLIST_ID, "")
        assert exc_info.value.reason == REASON_EMPTY_NAME

    @pytest.mark.asyncio
    async def test_rename_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.rename_watchlist(USER_ID, WATCHLIST_ID, "New Name")
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND


# ── Delete watchlist tests ───────────────────────────────────────────────────


class TestDeleteWatchlist:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.delete_watchlist(USER_ID, WATCHLIST_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.delete_watchlist(USER_ID, WATCHLIST_ID)
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_no_db_raises(self):
        svc = _make_service(db_pool=None)

        with pytest.raises(WatchlistError):
            await svc.delete_watchlist(USER_ID, WATCHLIST_ID)


# ── Add security tests ───────────────────────────────────────────────────────


class TestAddSecurity:
    @pytest.mark.asyncio
    async def test_add_success(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist ownership
            _security_row(),  # security lookup
            _count_row(5),  # item count
            None,  # duplicate check (no existing)
            _item_row(),  # INSERT RETURNING
        ])

        svc = _make_service(db_pool=pool)
        result = await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")

        assert isinstance(result, WatchlistItem)
        assert result.symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_add_watchlist_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND

    @pytest.mark.asyncio
    async def test_add_security_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            None,  # security not found
        ])

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "NONEXISTENT")
        assert exc_info.value.reason == REASON_SECURITY_NOT_FOUND

    @pytest.mark.asyncio
    async def test_add_inactive_security_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            _security_row(status="INACTIVE"),  # security inactive
        ])

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "DELISTED")
        assert exc_info.value.reason == REASON_SECURITY_NOT_ACTIVE

    @pytest.mark.asyncio
    async def test_add_max_securities_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            _security_row(),  # security found
            _count_row(MAX_SECURITIES_PER_WATCHLIST),  # at limit
        ])

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert exc_info.value.reason == REASON_MAX_SECURITIES

    @pytest.mark.asyncio
    async def test_add_duplicate_security_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            _security_row(),  # security found
            _count_row(5),  # under limit
            _make_mock_row({"id": "existing-item"}),  # duplicate exists
        ])

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert exc_info.value.reason == REASON_DUPLICATE_SECURITY

    @pytest.mark.asyncio
    async def test_add_no_db_raises(self):
        svc = _make_service(db_pool=None)

        with pytest.raises(WatchlistError):
            await svc.add_security(USER_ID, WATCHLIST_ID, "RELIANCE")


# ── Remove security tests ───────────────────────────────────────────────────


class TestRemoveSecurity:
    @pytest.mark.asyncio
    async def test_remove_success(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            _security_row(),  # security found
        ])
        conn.execute = AsyncMock(return_value="DELETE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.remove_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_watchlist_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.remove_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND

    @pytest.mark.asyncio
    async def test_remove_security_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            None,  # security not found
        ])

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.remove_security(USER_ID, WATCHLIST_ID, "NONEXISTENT")
        assert exc_info.value.reason == REASON_SECURITY_NOT_FOUND

    @pytest.mark.asyncio
    async def test_remove_not_in_watchlist_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            _make_mock_row({"id": WATCHLIST_ID}),  # watchlist found
            _security_row(),  # security found
        ])
        conn.execute = AsyncMock(return_value="DELETE 0")

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.remove_security(USER_ID, WATCHLIST_ID, "RELIANCE")
        assert exc_info.value.reason == REASON_SECURITY_NOT_IN_WATCHLIST


# ── Reorder securities tests ─────────────────────────────────────────────────


class TestReorderSecurities:
    @pytest.mark.asyncio
    async def test_reorder_success(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({"id": WATCHLIST_ID}))
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.reorder_securities(USER_ID, WATCHLIST_ID, [3, 1, 2])
        assert result is True
        assert conn.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_reorder_watchlist_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.reorder_securities(USER_ID, WATCHLIST_ID, [1, 2])
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND


# ── Get user watchlists tests ────────────────────────────────────────────────


class TestGetUserWatchlists:
    @pytest.mark.asyncio
    async def test_returns_watchlists(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[
            _watchlist_row(name="WL1", sort_order=0),
            _watchlist_row(name="WL2", sort_order=1),
        ])

        svc = _make_service(db_pool=pool)
        result = await svc.get_user_watchlists(USER_ID)

        assert len(result) == 2
        assert result[0].name == "WL1"
        assert result[1].name == "WL2"

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_user_watchlists(USER_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.get_user_watchlists(USER_ID)
        assert result == []


# ── Get watchlist with prices tests ──────────────────────────────────────────


class TestGetWatchlistWithPrices:
    @pytest.mark.asyncio
    async def test_returns_prices_from_redis_hash(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({
            "id": WATCHLIST_ID,
            "name": "My WL",
            "is_prebuilt": False,
        }))
        conn.fetch = AsyncMock(return_value=[
            _make_mock_row({"sort_order": 0, "symbol": "RELIANCE", "company_name": "Reliance Industries"}),
            _make_mock_row({"sort_order": 1, "symbol": "TCS", "company_name": "TCS Ltd"}),
        ])

        redis = MagicMock()
        redis.hgetall.side_effect = [
            {"ltp": "2500.50", "close": "2450.00", "volume": "1000000"},
            {"ltp": "3800.00", "close": "3750.00", "volume": "500000"},
        ]

        svc = _make_service(db_pool=pool, redis_client=redis)
        result = await svc.get_watchlist_with_prices(USER_ID, WATCHLIST_ID)

        assert isinstance(result, WatchlistWithPrices)
        assert result.name == "My WL"
        assert len(result.securities) == 2
        assert result.securities[0].symbol == "RELIANCE"
        assert result.securities[0].ltp == 2500.50
        assert result.securities[0].volume == 1000000
        # change_percent = ((2500.50 - 2450) / 2450) * 100 ≈ 2.06
        assert abs(result.securities[0].change_percent - 2.06) < 0.1

    @pytest.mark.asyncio
    async def test_returns_prices_from_redis_string_fallback(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({
            "id": WATCHLIST_ID,
            "name": "My WL",
            "is_prebuilt": False,
        }))
        conn.fetch = AsyncMock(return_value=[
            _make_mock_row({"sort_order": 0, "symbol": "INFY", "company_name": "Infosys"}),
        ])

        redis = MagicMock()
        redis.hgetall.return_value = {}  # No hash data
        redis.get.return_value = "1500.25"  # Simple string fallback

        svc = _make_service(db_pool=pool, redis_client=redis)
        result = await svc.get_watchlist_with_prices(USER_ID, WATCHLIST_ID)

        assert len(result.securities) == 1
        assert result.securities[0].ltp == 1500.25
        assert result.securities[0].change_percent == 0.0

    @pytest.mark.asyncio
    async def test_no_redis_returns_zero_prices(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({
            "id": WATCHLIST_ID,
            "name": "My WL",
            "is_prebuilt": False,
        }))
        conn.fetch = AsyncMock(return_value=[
            _make_mock_row({"sort_order": 0, "symbol": "RELIANCE", "company_name": "Reliance"}),
        ])

        svc = _make_service(db_pool=pool, redis_client=None)
        result = await svc.get_watchlist_with_prices(USER_ID, WATCHLIST_ID)

        assert len(result.securities) == 1
        assert result.securities[0].ltp == 0.0

    @pytest.mark.asyncio
    async def test_watchlist_not_found_raises(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)

        with pytest.raises(WatchlistError) as exc_info:
            await svc.get_watchlist_with_prices(USER_ID, WATCHLIST_ID)
        assert exc_info.value.reason == REASON_WATCHLIST_NOT_FOUND

    @pytest.mark.asyncio
    async def test_no_db_raises(self):
        svc = _make_service(db_pool=None)

        with pytest.raises(WatchlistError):
            await svc.get_watchlist_with_prices(USER_ID, WATCHLIST_ID)


# ── Pre-built watchlists tests ───────────────────────────────────────────────


class TestPrebuiltWatchlists:
    @pytest.mark.asyncio
    async def test_get_prebuilt_returns_list(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[
            _watchlist_row(name="Nifty 50", is_prebuilt=True, user_id=None),
            _watchlist_row(name="Nifty Bank", is_prebuilt=True, user_id=None),
        ])

        svc = _make_service(db_pool=pool)
        result = await svc.get_prebuilt_watchlists()

        assert len(result) == 2
        assert result[0].name == "Nifty 50"
        assert result[0].is_prebuilt is True

    @pytest.mark.asyncio
    async def test_get_prebuilt_no_db_returns_empty(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_prebuilt_watchlists()
        assert result == []

    @pytest.mark.asyncio
    async def test_ensure_prebuilt_creates_missing(self):
        pool, conn = _make_mock_pool()
        # All 5 pre-built watchlists don't exist yet
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value="INSERT 0 1")

        svc = _make_service(db_pool=pool)
        count = await svc.ensure_prebuilt_watchlists()

        assert count == len(PREBUILT_WATCHLISTS)

    @pytest.mark.asyncio
    async def test_ensure_prebuilt_skips_existing(self):
        pool, conn = _make_mock_pool()
        # All already exist
        conn.fetchrow = AsyncMock(return_value=_make_mock_row({"id": "existing"}))

        svc = _make_service(db_pool=pool)
        count = await svc.ensure_prebuilt_watchlists()

        assert count == 0

    @pytest.mark.asyncio
    async def test_ensure_prebuilt_no_db_returns_zero(self):
        svc = _make_service(db_pool=None)
        count = await svc.ensure_prebuilt_watchlists()
        assert count == 0

    def test_prebuilt_names(self):
        names = [wl["name"] for wl in PREBUILT_WATCHLISTS]
        assert "Nifty 50" in names
        assert "Nifty Bank" in names
        assert "Nifty IT" in names
        assert "Nifty Pharma" in names
        assert "Nifty Next 50" in names


# ── Redis price helper tests ─────────────────────────────────────────────────


class TestGetPriceFromRedis:
    def test_hash_format(self):
        redis = MagicMock()
        redis.hgetall.return_value = {
            "ltp": "100.50",
            "close": "98.00",
            "volume": "50000",
        }

        svc = _make_service(redis_client=redis)
        result = svc._get_price_from_redis("TEST")

        assert result["ltp"] == 100.50
        assert result["volume"] == 50000
        assert abs(result["change_percent"] - 2.55) < 0.1

    def test_string_fallback(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}
        redis.get.return_value = "250.75"

        svc = _make_service(redis_client=redis)
        result = svc._get_price_from_redis("TEST")

        assert result["ltp"] == 250.75
        assert result["change_percent"] == 0.0
        assert result["volume"] == 0

    def test_no_redis_returns_zeros(self):
        svc = _make_service(redis_client=None)
        result = svc._get_price_from_redis("TEST")

        assert result == {"ltp": 0.0, "change_percent": 0.0, "volume": 0}

    def test_redis_error_returns_zeros(self):
        redis = MagicMock()
        redis.hgetall.side_effect = Exception("Redis down")

        svc = _make_service(redis_client=redis)
        result = svc._get_price_from_redis("TEST")

        assert result == {"ltp": 0.0, "change_percent": 0.0, "volume": 0}

    def test_zero_close_no_division_error(self):
        redis = MagicMock()
        redis.hgetall.return_value = {
            "ltp": "100.00",
            "close": "0",
            "volume": "1000",
        }

        svc = _make_service(redis_client=redis)
        result = svc._get_price_from_redis("TEST")

        assert result["ltp"] == 100.0
        assert result["change_percent"] == 0.0


# ── Row mapping tests ────────────────────────────────────────────────────────


class TestRowToWatchlist:
    def test_maps_all_fields(self):
        now = datetime.now(timezone.utc)
        row = _watchlist_row(
            id="wl-1",
            user_id=USER_ID,
            name="Test WL",
            is_prebuilt=False,
            sort_order=3,
            created_at=now,
        )
        result = WatchlistService._row_to_watchlist(row)

        assert result.id == "wl-1"
        assert result.user_id == USER_ID
        assert result.name == "Test WL"
        assert result.is_prebuilt is False
        assert result.sort_order == 3
        assert result.created_at == now

    def test_maps_null_user_id(self):
        row = _watchlist_row(user_id=None, is_prebuilt=True)
        result = WatchlistService._row_to_watchlist(row)
        assert result.user_id is None
