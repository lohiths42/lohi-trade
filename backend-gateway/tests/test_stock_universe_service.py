"""Unit tests for StockUniverseService — search, listing, refresh, new listings, delistings."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.services.stock_universe_service import (
    SECTORS,
    PaginatedResult,
    StockUniverseService,
    _parse_date,
    _parse_decimal,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> StockUniverseService:
    return StockUniverseService(
        db_pool=db_pool,
        nse_url="https://test.nse.co.in/api/listings",
        bse_url="https://test.bse.co.in/api/listings",
    )


def _make_mock_pool():
    """Create a mock asyncpg pool with an async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_security_row(
    id=1,
    symbol="RELIANCE",
    isin="INE002A01018",
    company_name="Reliance Industries Limited",
    exchange="NSE",
    sector="Energy",
    industry="Oil & Gas",
    market_cap_category="large-cap",
    listing_date=date(1977, 11, 29),
    face_value=Decimal("10.00"),
    status="ACTIVE",
    updated_at=None,
):
    """Create a dict-like mock row for asyncpg results."""
    row = {
        "id": id,
        "symbol": symbol,
        "isin": isin,
        "company_name": company_name,
        "exchange": exchange,
        "sector": sector,
        "industry": industry,
        "market_cap_category": market_cap_category,
        "listing_date": listing_date,
        "face_value": face_value,
        "status": status,
        "updated_at": updated_at or datetime.now(timezone.utc),
    }
    # asyncpg Records support both dict-style and attribute access
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: row[key]
    mock_row.get = lambda key, default=None: row.get(key, default)
    return mock_row


# ── Utility function tests ───────────────────────────────────────────────────


class TestParseDate:
    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_date_object_returned_as_is(self):
        d = date(2024, 1, 15)
        assert _parse_date(d) == d

    def test_iso_string_parsed(self):
        assert _parse_date("2024-01-15") == date(2024, 1, 15)

    def test_datetime_string_truncated(self):
        assert _parse_date("2024-01-15T10:30:00") == date(2024, 1, 15)

    def test_invalid_string_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None


class TestParseDecimal:
    def test_none_returns_none(self):
        assert _parse_decimal(None) is None

    def test_int_parsed(self):
        assert _parse_decimal(10) == Decimal("10")

    def test_float_parsed(self):
        assert _parse_decimal(10.5) == Decimal("10.5")

    def test_string_parsed(self):
        assert _parse_decimal("25.00") == Decimal("25.00")

    def test_invalid_returns_none(self):
        assert _parse_decimal("abc") is None


# ── Search tests ─────────────────────────────────────────────────────────────


class TestSearchSecurities:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        svc = _make_service()
        result = await svc.search_securities("")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty(self):
        svc = _make_service()
        result = await svc.search_securities("   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        svc = _make_service(db_pool=None)
        result = await svc.search_securities("RELIANCE")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_returns_matching_securities(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row()
        conn.fetch = AsyncMock(return_value=[row])

        svc = _make_service(db_pool=pool)
        result = await svc.search_securities("RELIANCE")

        assert len(result) == 1
        assert result[0].symbol == "RELIANCE"
        assert result[0].isin == "INE002A01018"

    @pytest.mark.asyncio
    async def test_search_fallback_to_ilike(self):
        """When tsquery returns no results, falls back to ILIKE."""
        pool, conn = _make_mock_pool()
        row = _make_security_row(
            symbol="TCS", isin="INE467B01029", company_name="Tata Consultancy Services"
        )
        # First call (tsquery) returns empty, second call (ILIKE) returns result
        conn.fetch = AsyncMock(side_effect=[[], [row]])

        svc = _make_service(db_pool=pool)
        result = await svc.search_securities("TCS")

        assert len(result) == 1
        assert result[0].symbol == "TCS"
        assert conn.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_search_limit_clamped(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        await svc.search_securities("TEST", limit=200)

        # Limit should be clamped to 100
        call_args = conn.fetch.call_args_list[0]
        assert call_args[0][2] == 100  # third positional arg is limit

    @pytest.mark.asyncio
    async def test_search_limit_minimum_one(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        await svc.search_securities("TEST", limit=-5)

        call_args = conn.fetch.call_args_list[0]
        assert call_args[0][2] == 1

    @pytest.mark.asyncio
    async def test_search_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(side_effect=Exception("DB connection lost"))

        svc = _make_service(db_pool=pool)
        result = await svc.search_securities("RELIANCE")
        assert result == []


# ── List securities tests ────────────────────────────────────────────────────


class TestListSecurities:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        svc = _make_service(db_pool=None)
        result = await svc.list_securities()
        assert isinstance(result, PaginatedResult)
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_without_filters(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 1 if key == "cnt" else None
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[row])

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities()

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].symbol == "RELIANCE"
        assert result.page == 1
        assert result.page_size == 50

    @pytest.mark.asyncio
    async def test_list_with_exchange_filter(self):
        pool, conn = _make_mock_pool()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 5 if key == "cnt" else None
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities(exchange="NSE")

        # Verify the exchange filter was passed
        count_call = conn.fetchrow.call_args
        assert "NSE" in count_call[0]

    @pytest.mark.asyncio
    async def test_list_with_all_filters(self):
        pool, conn = _make_mock_pool()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 0 if key == "cnt" else None
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities(
            exchange="NSE",
            sector="Energy",
            market_cap_category="large-cap",
            status="ACTIVE",
        )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_pagination(self):
        pool, conn = _make_mock_pool()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 120 if key == "cnt" else None
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities(page=3, page_size=50)

        assert result.total == 120
        assert result.page == 3
        assert result.total_pages == 3

    @pytest.mark.asyncio
    async def test_list_page_size_clamped(self):
        pool, conn = _make_mock_pool()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 10 if key == "cnt" else None
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities(page_size=500)

        assert result.page_size == 100

    @pytest.mark.asyncio
    async def test_list_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.list_securities()
        assert result.total == 0


# ── Get security by symbol tests ─────────────────────────────────────────────


class TestGetSecurityBySymbol:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_security_by_symbol("RELIANCE")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_symbol_returns_none(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_security_by_symbol("")
        assert result is None

    @pytest.mark.asyncio
    async def test_found_returns_security(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row()
        conn.fetchrow = AsyncMock(return_value=row)

        svc = _make_service(db_pool=pool)
        result = await svc.get_security_by_symbol("reliance")

        assert result is not None
        assert result.symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)
        result = await svc.get_security_by_symbol("NONEXISTENT")
        assert result is None


# ── Refresh catalog tests ────────────────────────────────────────────────────


class TestRefreshCatalog:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_zero(self):
        svc = _make_service(db_pool=None)
        result = await svc.refresh_catalog()
        assert result == 0

    @pytest.mark.asyncio
    async def test_refresh_upserts_securities(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="INSERT 0 1")

        svc = _make_service(db_pool=pool)

        nse_data = [
            {
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "company_name": "Reliance Industries",
                "exchange": "NSE",
            },
            {
                "symbol": "TCS",
                "isin": "INE467B01029",
                "company_name": "Tata Consultancy Services",
                "exchange": "NSE",
            },
        ]
        bse_data = [
            {
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "company_name": "Reliance Industries",
                "exchange": "BSE",
            },
        ]

        with patch.object(svc, "_fetch_nse_listings", return_value=nse_data):
            with patch.object(svc, "_fetch_bse_listings", return_value=bse_data):
                count = await svc.refresh_catalog()

        # 2 unique ISINs: RELIANCE (dual-listed → BOTH) and TCS
        assert count == 2

    @pytest.mark.asyncio
    async def test_refresh_marks_delisted_inactive(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)

        nse_data = [
            {"symbol": "TCS", "isin": "INE467B01029", "company_name": "TCS", "exchange": "NSE"},
        ]

        with patch.object(svc, "_fetch_nse_listings", return_value=nse_data):
            with patch.object(svc, "_fetch_bse_listings", return_value=[]):
                await svc.refresh_catalog()

        # The last execute call should be the UPDATE for delisted securities
        calls = conn.execute.call_args_list
        last_call_sql = calls[-1][0][0]
        assert "INACTIVE" in last_call_sql

    @pytest.mark.asyncio
    async def test_refresh_empty_exchange_data(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="INSERT 0 1")

        svc = _make_service(db_pool=pool)

        with patch.object(svc, "_fetch_nse_listings", return_value=[]):
            with patch.object(svc, "_fetch_bse_listings", return_value=[]):
                count = await svc.refresh_catalog()

        assert count == 0

    @pytest.mark.asyncio
    async def test_refresh_db_error_returns_zero(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)

        with patch.object(
            svc,
            "_fetch_nse_listings",
            return_value=[
                {"symbol": "TCS", "isin": "INE467B01029", "company_name": "TCS", "exchange": "NSE"},
            ],
        ):
            with patch.object(svc, "_fetch_bse_listings", return_value=[]):
                count = await svc.refresh_catalog()

        assert count == 0


# ── Delist security tests ────────────────────────────────────────────────────


class TestDelistSecurity:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_false(self):
        svc = _make_service(db_pool=None)
        result = await svc.delist_security("INE002A01018")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_isin_returns_false(self):
        svc = _make_service(db_pool=None)
        result = await svc.delist_security("")
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_delist(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.delist_security("INE002A01018")
        assert result is True

    @pytest.mark.asyncio
    async def test_delist_not_found(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 0")

        svc = _make_service(db_pool=pool)
        result = await svc.delist_security("NONEXISTENT")
        assert result is False

    @pytest.mark.asyncio
    async def test_delist_db_error(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.delist_security("INE002A01018")
        assert result is False


# ── Add new listing tests ────────────────────────────────────────────────────


class TestAddNewListing:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        svc = _make_service(db_pool=None)
        result = await svc.add_new_listing(
            {"isin": "INE123", "symbol": "TEST", "company_name": "Test Co"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_isin_returns_none(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        result = await svc.add_new_listing({"symbol": "TEST", "company_name": "Test Co"})
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_symbol_returns_none(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        result = await svc.add_new_listing({"isin": "INE123", "company_name": "Test Co"})
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_company_name_returns_none(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        result = await svc.add_new_listing({"isin": "INE123", "symbol": "TEST"})
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_add(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row(
            symbol="NEWCO", isin="INE999Z01010", company_name="New Company Ltd"
        )
        conn.fetchrow = AsyncMock(return_value=row)

        svc = _make_service(db_pool=pool)
        result = await svc.add_new_listing(
            {
                "isin": "INE999Z01010",
                "symbol": "NEWCO",
                "company_name": "New Company Ltd",
                "exchange": "NSE",
                "sector": "IT/Technology",
            }
        )

        assert result is not None
        assert result.symbol == "NEWCO"

    @pytest.mark.asyncio
    async def test_add_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.add_new_listing(
            {
                "isin": "INE999Z01010",
                "symbol": "NEWCO",
                "company_name": "New Company Ltd",
            }
        )
        assert result is None


# ── Is tradeable tests ───────────────────────────────────────────────────────


class TestIsTradeable:
    @pytest.mark.asyncio
    async def test_active_security_is_tradeable(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row(status="ACTIVE")
        conn.fetchrow = AsyncMock(return_value=row)

        svc = _make_service(db_pool=pool)
        assert await svc.is_tradeable("RELIANCE") is True

    @pytest.mark.asyncio
    async def test_inactive_security_not_tradeable(self):
        pool, conn = _make_mock_pool()
        row = _make_security_row(status="INACTIVE")
        conn.fetchrow = AsyncMock(return_value=row)

        svc = _make_service(db_pool=pool)
        assert await svc.is_tradeable("DELISTED") is False

    @pytest.mark.asyncio
    async def test_nonexistent_security_not_tradeable(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = _make_service(db_pool=pool)
        assert await svc.is_tradeable("NONEXISTENT") is False


# ── Exchange data parsing tests ──────────────────────────────────────────────


class TestParseExchangeResponse:
    def test_parse_nse_format(self):
        data = {
            "data": [
                {
                    "symbol": "RELIANCE",
                    "isin": "INE002A01018",
                    "companyName": "Reliance Industries",
                    "sector": "Energy",
                },
                {"symbol": "TCS", "isin": "INE467B01029", "companyName": "TCS Ltd"},
            ]
        }
        result = StockUniverseService._parse_exchange_response(data, "NSE")
        assert len(result) == 2
        assert result[0]["symbol"] == "RELIANCE"
        assert result[0]["exchange"] == "NSE"

    def test_parse_list_format(self):
        data = [
            {"symbol": "INFY", "isin": "INE009A01021", "company_name": "Infosys Limited"},
        ]
        result = StockUniverseService._parse_exchange_response(data, "BSE")
        assert len(result) == 1
        assert result[0]["symbol"] == "INFY"
        assert result[0]["exchange"] == "BSE"

    def test_parse_skips_missing_isin(self):
        data = [{"symbol": "TEST", "company_name": "Test"}]
        result = StockUniverseService._parse_exchange_response(data, "NSE")
        assert len(result) == 0

    def test_parse_skips_missing_symbol(self):
        data = [{"isin": "INE123", "company_name": "Test"}]
        result = StockUniverseService._parse_exchange_response(data, "NSE")
        assert len(result) == 0

    def test_parse_non_dict_data_returns_empty(self):
        result = StockUniverseService._parse_exchange_response("invalid", "NSE")
        assert result == []

    def test_parse_non_dict_items_skipped(self):
        data = [42, "string", None, {"symbol": "OK", "isin": "INE001"}]
        result = StockUniverseService._parse_exchange_response(data, "NSE")
        assert len(result) == 1

    def test_parse_with_listing_date_and_face_value(self):
        data = [
            {
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "company_name": "Reliance",
                "listing_date": "1977-11-29",
                "face_value": "10.00",
            }
        ]
        result = StockUniverseService._parse_exchange_response(data, "NSE")
        assert result[0]["listing_date"] == date(1977, 11, 29)
        assert result[0]["face_value"] == Decimal("10.00")


# ── Fetch exchange data tests ────────────────────────────────────────────────


class TestFetchExchangeData:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        svc = _make_service()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"symbol": "RELIANCE", "isin": "INE002A01018", "company_name": "Reliance"},
        ]

        with patch("app.services.stock_universe_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc._fetch_exchange_data("https://test.url", "NSE")

        assert len(result) == 1
        assert result[0]["symbol"] == "RELIANCE"

    @pytest.mark.asyncio
    async def test_api_failure_retries_and_returns_empty(self):
        svc = _make_service()

        with patch("app.services.stock_universe_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_cls.return_value = mock_client

            with patch("app.services.stock_universe_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc._fetch_exchange_data("https://test.url", "NSE")

        assert result == []
        assert mock_client.get.call_count == 3  # MAX_RETRIES

    @pytest.mark.asyncio
    async def test_non_200_status_retries(self):
        svc = _make_service()
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("app.services.stock_universe_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            with patch("app.services.stock_universe_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc._fetch_exchange_data("https://test.url", "NSE")

        assert result == []


# ── Row mapping tests ────────────────────────────────────────────────────────


class TestRowToSecurity:
    def test_maps_all_fields(self):
        row = _make_security_row()
        sec = StockUniverseService._row_to_security(row)

        assert sec.id == 1
        assert sec.symbol == "RELIANCE"
        assert sec.isin == "INE002A01018"
        assert sec.company_name == "Reliance Industries Limited"
        assert sec.exchange == "NSE"
        assert sec.sector == "Energy"
        assert sec.industry == "Oil & Gas"
        assert sec.market_cap_category == "large-cap"
        assert sec.listing_date == date(1977, 11, 29)
        assert sec.face_value == Decimal("10.00")
        assert sec.status == "ACTIVE"


# ── Sectors constant test ────────────────────────────────────────────────────


class TestSectors:
    def test_fifteen_sectors_defined(self):
        assert len(SECTORS) == 15

    def test_key_sectors_present(self):
        assert "Pharma" in SECTORS
        assert "IT/Technology" in SECTORS
        assert "Banking & Finance" in SECTORS
        assert "Energy" in SECTORS
        assert "Miscellaneous" in SECTORS
