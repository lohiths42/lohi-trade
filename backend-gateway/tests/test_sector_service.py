"""Unit tests for SectorService — sector classification, aggregation, and filtering."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.sector_service import (
    SECTORS,
    SUB_INDUSTRIES,
    ClassificationUpdate,
    SectorAggregate,
    SectorFilterParams,
    SectorSecurity,
    SectorService,
    SecurityGainerLoser,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> SectorService:
    return SectorService(db_pool=db_pool)


def _make_mock_pool():
    """Create a mock asyncpg pool with an async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_agg_row(total_market_cap=1000000, stock_count=50):
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "total_market_cap": total_market_cap,
        "stock_count": stock_count,
    }[key]
    row.get = lambda key, default=None: {
        "total_market_cap": total_market_cap,
        "stock_count": stock_count,
    }.get(key, default)
    return row


def _make_gainer_loser_row(
    id=1,
    symbol="RELIANCE",
    company_name="Reliance Industries",
    price_change_1d=Decimal("2.50"),
    market_cap=Decimal("1500000"),
):
    row = MagicMock()
    data = {
        "id": id,
        "symbol": symbol,
        "company_name": company_name,
        "price_change_1d": price_change_1d,
        "market_cap": market_cap,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    return row


def _make_sector_security_row(
    id=1,
    symbol="RELIANCE",
    company_name="Reliance Industries",
    industry="Oil & Gas",
    market_cap=Decimal("1500000"),
    pe_ratio=Decimal("25.5"),
    dividend_yield=Decimal("1.2"),
    price_change_1d=Decimal("2.50"),
):
    row = MagicMock()
    data = {
        "id": id,
        "symbol": symbol,
        "company_name": company_name,
        "industry": industry,
        "market_cap": market_cap,
        "pe_ratio": pe_ratio,
        "dividend_yield": dividend_yield,
        "price_change_1d": price_change_1d,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    return row


def _make_count_row(cnt=10):
    row = MagicMock()
    row.__getitem__ = lambda self, key: cnt if key == "cnt" else None
    row.get = lambda key, default=None: cnt if key == "cnt" else default
    return row


# ── Sector constants tests ───────────────────────────────────────────────────


class TestSectorConstants:
    def test_fifteen_sectors_defined(self):
        assert len(SECTORS) == 15

    def test_all_expected_sectors_present(self):
        expected = [
            "Pharma",
            "IT/Technology",
            "AI/Deep Tech",
            "Metals & Mining",
            "Banking & Finance",
            "FMCG",
            "Energy",
            "Automobile",
            "Telecom",
            "Real Estate",
            "Infrastructure",
            "Chemicals",
            "Media & Entertainment",
            "Insurance",
            "Miscellaneous",
        ]
        for s in expected:
            assert s in SECTORS

    def test_sub_industries_defined_for_all_sectors(self):
        for sector in SECTORS:
            assert sector in SUB_INDUSTRIES
            assert len(SUB_INDUSTRIES[sector]) > 0

    def test_banking_sub_industries(self):
        subs = SUB_INDUSTRIES["Banking & Finance"]
        assert "Private Banks" in subs
        assert "PSU Banks" in subs
        assert "NBFCs" in subs


# ── Classification tests ─────────────────────────────────────────────────────


class TestClassifySector:
    def test_valid_sector_returned(self):
        assert SectorService.classify_sector("Pharma") == "Pharma"

    def test_none_returns_miscellaneous(self):
        assert SectorService.classify_sector(None) == "Miscellaneous"

    def test_empty_string_returns_miscellaneous(self):
        assert SectorService.classify_sector("") == "Miscellaneous"

    def test_unknown_sector_returns_miscellaneous(self):
        assert SectorService.classify_sector("Unknown Sector") == "Miscellaneous"

    def test_all_valid_sectors_accepted(self):
        for sector in SECTORS:
            assert SectorService.classify_sector(sector) == sector


class TestClassifySubIndustry:
    def test_valid_sub_industry(self):
        result = SectorService.classify_sub_industry("Banking & Finance", "Private Banks")
        assert result == "Private Banks"

    def test_unknown_sub_industry_returns_default(self):
        result = SectorService.classify_sub_industry("Banking & Finance", "Unknown")
        # Should return last entry in the sub-industries list
        assert result == SUB_INDUSTRIES["Banking & Finance"][-1]

    def test_none_industry_returns_default(self):
        result = SectorService.classify_sub_industry("Energy", None)
        assert result == SUB_INDUSTRIES["Energy"][-1]

    def test_unknown_sector_returns_other(self):
        result = SectorService.classify_sub_industry("NonExistent", "Something")
        assert result == "Other"


class TestGetSectors:
    def test_returns_all_sectors(self):
        result = SectorService.get_sectors()
        assert len(result) == 15
        assert result == SECTORS

    def test_returns_new_list(self):
        result = SectorService.get_sectors()
        result.append("Extra")
        assert len(SectorService.get_sectors()) == 15


class TestGetSubIndustries:
    def test_valid_sector(self):
        result = SectorService.get_sub_industries("Pharma")
        assert "Pharmaceuticals" in result
        assert "Biotechnology" in result

    def test_unknown_sector_returns_empty(self):
        result = SectorService.get_sub_industries("NonExistent")
        assert result == []

    def test_returns_new_list(self):
        result = SectorService.get_sub_industries("Pharma")
        result.append("Extra")
        assert "Extra" not in SectorService.get_sub_industries("Pharma")


# ── get_sector_aggregate tests ───────────────────────────────────────────────


class TestGetSectorAggregate:
    @pytest.mark.asyncio
    async def test_invalid_sector_returns_empty_aggregate(self):
        svc = _make_service()
        result = await svc.get_sector_aggregate("NonExistent")
        assert isinstance(result, SectorAggregate)
        assert result.sector == "NonExistent"
        assert result.stock_count == 0
        assert result.total_market_cap == Decimal("0")

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty_aggregate(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_sector_aggregate("Energy")
        assert result.stock_count == 0
        assert result.total_market_cap == Decimal("0")

    @pytest.mark.asyncio
    async def test_successful_aggregate(self):
        pool, conn = _make_mock_pool()
        agg_row = _make_agg_row(total_market_cap=5000000, stock_count=25)
        conn.fetchrow = AsyncMock(return_value=agg_row)

        gainer = _make_gainer_loser_row(
            id=1,
            symbol="ONGC",
            company_name="ONGC Ltd",
            price_change_1d=Decimal("5.0"),
            market_cap=Decimal("200000"),
        )
        loser = _make_gainer_loser_row(
            id=2,
            symbol="BPCL",
            company_name="BPCL Ltd",
            price_change_1d=Decimal("-3.0"),
            market_cap=Decimal("100000"),
        )
        conn.fetch = AsyncMock(side_effect=[[gainer], [loser]])

        svc = _make_service(db_pool=pool)
        result = await svc.get_sector_aggregate("Energy")

        assert result.sector == "Energy"
        assert result.total_market_cap == Decimal("5000000")
        assert result.stock_count == 25
        assert len(result.top_gainers) == 1
        assert result.top_gainers[0].symbol == "ONGC"
        assert len(result.top_losers) == 1
        assert result.top_losers[0].symbol == "BPCL"

    @pytest.mark.asyncio
    async def test_aggregate_with_no_gainers_losers(self):
        pool, conn = _make_mock_pool()
        agg_row = _make_agg_row(total_market_cap=1000, stock_count=3)
        conn.fetchrow = AsyncMock(return_value=agg_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        result = await svc.get_sector_aggregate("Pharma")

        assert result.stock_count == 3
        assert result.top_gainers == []
        assert result.top_losers == []

    @pytest.mark.asyncio
    async def test_aggregate_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.get_sector_aggregate("Energy")

        assert result.stock_count == 0
        assert result.total_market_cap == Decimal("0")


# ── filter_sector_securities tests ───────────────────────────────────────────


class TestFilterSectorSecurities:
    @pytest.mark.asyncio
    async def test_invalid_sector_returns_empty(self):
        svc = _make_service()
        items, total = await svc.filter_sector_securities("NonExistent")
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        svc = _make_service(db_pool=None)
        items, total = await svc.filter_sector_securities("Energy")
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_filter_without_params(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=5)
        conn.fetchrow = AsyncMock(return_value=count_row)

        sec_row = _make_sector_security_row()
        conn.fetch = AsyncMock(return_value=[sec_row])

        svc = _make_service(db_pool=pool)
        items, total = await svc.filter_sector_securities("Energy")

        assert total == 5
        assert len(items) == 1
        assert items[0].symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_filter_with_market_cap_range(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=2)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        filters = SectorFilterParams(
            market_cap_min=Decimal("100000"),
            market_cap_max=Decimal("5000000"),
        )
        items, total = await svc.filter_sector_securities("Energy", filters=filters)

        assert total == 2
        # Verify filter params were passed to the query
        count_call = conn.fetchrow.call_args
        assert Decimal("100000") in count_call[0]
        assert Decimal("5000000") in count_call[0]

    @pytest.mark.asyncio
    async def test_filter_with_pe_ratio_range(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=3)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        filters = SectorFilterParams(
            pe_ratio_min=Decimal("10"),
            pe_ratio_max=Decimal("30"),
        )
        items, total = await svc.filter_sector_securities("Banking & Finance", filters=filters)

        assert total == 3

    @pytest.mark.asyncio
    async def test_filter_with_dividend_yield_range(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=1)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        filters = SectorFilterParams(
            dividend_yield_min=Decimal("2.0"),
            dividend_yield_max=Decimal("5.0"),
        )
        items, total = await svc.filter_sector_securities("FMCG", filters=filters)

        assert total == 1

    @pytest.mark.asyncio
    async def test_filter_with_all_params(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=0)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        filters = SectorFilterParams(
            market_cap_min=Decimal("100000"),
            market_cap_max=Decimal("5000000"),
            pe_ratio_min=Decimal("10"),
            pe_ratio_max=Decimal("30"),
            dividend_yield_min=Decimal("1.0"),
            dividend_yield_max=Decimal("5.0"),
        )
        items, total = await svc.filter_sector_securities("IT/Technology", filters=filters)

        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_filter_pagination(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=120)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        items, total = await svc.filter_sector_securities("Energy", page=3, page_size=50)

        assert total == 120
        # Verify offset was passed (page 3, size 50 → offset 100)
        fetch_call = conn.fetch.call_args
        assert 50 in fetch_call[0]  # page_size
        assert 100 in fetch_call[0]  # offset

    @pytest.mark.asyncio
    async def test_filter_page_size_clamped(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=10)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        svc = _make_service(db_pool=pool)
        items, total = await svc.filter_sector_securities("Energy", page_size=500)

        # page_size should be clamped to 100
        fetch_call = conn.fetch.call_args
        assert 100 in fetch_call[0]

    @pytest.mark.asyncio
    async def test_filter_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        items, total = await svc.filter_sector_securities("Energy")

        assert items == []
        assert total == 0


# ── update_classifications tests ─────────────────────────────────────────────


class TestUpdateClassifications:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        svc = _make_service(db_pool=None)
        result = await svc.update_classifications([{"security_id": 1, "sector": "Energy"}])
        assert isinstance(result, ClassificationUpdate)
        assert result.updated_count == 0

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications([])
        assert result.updated_count == 0
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_successful_update(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications(
            [
                {"security_id": 1, "sector": "Energy", "industry": "Oil & Gas"},
                {"security_id": 2, "sector": "Pharma", "industry": "Biotechnology"},
            ]
        )

        assert result.updated_count == 2
        assert result.timestamp is not None
        assert conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_sector_mapped_to_miscellaneous(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications(
            [
                {"security_id": 1, "sector": "InvalidSector"},
            ]
        )

        assert result.updated_count == 1
        # Verify "Miscellaneous" was passed to the query
        call_args = conn.execute.call_args[0]
        assert call_args[1] == "Miscellaneous"

    @pytest.mark.asyncio
    async def test_missing_security_id_skipped(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications(
            [
                {"sector": "Energy"},  # no security_id
                {"security_id": 2, "sector": "Pharma"},
            ]
        )

        assert result.updated_count == 1
        assert conn.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_update_not_found_returns_zero_count(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 0")

        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications(
            [
                {"security_id": 999, "sector": "Energy"},
            ]
        )

        assert result.updated_count == 0

    @pytest.mark.asyncio
    async def test_db_error_returns_zero(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))

        svc = _make_service(db_pool=pool)
        result = await svc.update_classifications(
            [
                {"security_id": 1, "sector": "Energy"},
            ]
        )

        assert result.updated_count == 0


# ── Row mapping tests ────────────────────────────────────────────────────────


class TestRowMapping:
    def test_row_to_gainer_loser(self):
        row = _make_gainer_loser_row(
            id=5,
            symbol="ONGC",
            company_name="ONGC Ltd",
            price_change_1d=Decimal("3.5"),
            market_cap=Decimal("200000"),
        )
        result = SectorService._row_to_gainer_loser(row)

        assert isinstance(result, SecurityGainerLoser)
        assert result.security_id == 5
        assert result.symbol == "ONGC"
        assert result.price_change_1d == Decimal("3.5")

    def test_row_to_sector_security(self):
        row = _make_sector_security_row(
            id=10,
            symbol="TCS",
            company_name="TCS Ltd",
            industry="IT Services",
            market_cap=Decimal("1200000"),
            pe_ratio=Decimal("30.0"),
            dividend_yield=Decimal("1.5"),
            price_change_1d=Decimal("-0.5"),
        )
        result = SectorService._row_to_sector_security(row)

        assert isinstance(result, SectorSecurity)
        assert result.security_id == 10
        assert result.symbol == "TCS"
        assert result.industry == "IT Services"
        assert result.pe_ratio == Decimal("30.0")
