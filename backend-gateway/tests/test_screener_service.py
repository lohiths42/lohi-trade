"""Unit tests for ScreenerEngine — stock screener with fundamental + technical filters."""

import csv
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.screener_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_PRESETS_PER_USER,
    Range,
    ScreenerEngine,
    ScreenerFilters,
    ScreenerPreset,
    ScreenerResult,
    ScreenerResultItem,
    dict_to_filters,
    filters_to_dict,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_engine(db_pool=None) -> ScreenerEngine:
    return ScreenerEngine(db_pool=db_pool)


def _make_mock_pool():
    """Create a mock asyncpg pool with an async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_count_row(cnt=10):
    row = MagicMock()
    row.__getitem__ = lambda self, key: cnt if key == "cnt" else None
    row.get = lambda key, default=None: cnt if key == "cnt" else default
    return row


def _make_screener_row(
    id=1,
    symbol="RELIANCE",
    company_name="Reliance Industries",
    exchange="NSE",
    sector="Energy",
    market_cap_category="large-cap",
    pe_ratio=Decimal("25.5"),
    pb_ratio=Decimal("2.1"),
    market_cap=Decimal("1500000"),
    dividend_yield=Decimal("1.2"),
    eps=Decimal("85.0"),
    roe=Decimal("12.5"),
    debt_to_equity=Decimal("0.5"),
    revenue_growth_1y=Decimal("15.0"),
    revenue_growth_3y=Decimal("12.0"),
    profit_growth_1y=Decimal("18.0"),
    profit_growth_3y=Decimal("14.0"),
    return_1y=Decimal("22.0"),
    cagr_3y=Decimal("16.0"),
    cagr_5y=Decimal("14.0"),
    high_52w=Decimal("2800.0"),
    low_52w=Decimal("2100.0"),
    rsi_14=Decimal("55.0"),
    sma_50=Decimal("2600.0"),
    sma_200=Decimal("2400.0"),
    avg_volume_20d=5000000,
    price_change_1d=Decimal("1.5"),
    price_change_1w=Decimal("3.2"),
    price_change_1m=Decimal("5.0"),
    price_change_3m=Decimal("8.0"),
    price_change_6m=Decimal("12.0"),
    price_change_1y=Decimal("22.0"),
    price_change_3y=Decimal("45.0"),
    price_change_5y=Decimal("80.0"),
):
    data = {
        "id": id,
        "symbol": symbol,
        "company_name": company_name,
        "exchange": exchange,
        "sector": sector,
        "market_cap_category": market_cap_category,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "market_cap": market_cap,
        "dividend_yield": dividend_yield,
        "eps": eps,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "revenue_growth_1y": revenue_growth_1y,
        "revenue_growth_3y": revenue_growth_3y,
        "profit_growth_1y": profit_growth_1y,
        "profit_growth_3y": profit_growth_3y,
        "return_1y": return_1y,
        "cagr_3y": cagr_3y,
        "cagr_5y": cagr_5y,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "rsi_14": rsi_14,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "avg_volume_20d": avg_volume_20d,
        "price_change_1d": price_change_1d,
        "price_change_1w": price_change_1w,
        "price_change_1m": price_change_1m,
        "price_change_3m": price_change_3m,
        "price_change_6m": price_change_6m,
        "price_change_1y": price_change_1y,
        "price_change_3y": price_change_3y,
        "price_change_5y": price_change_5y,
    }
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    return row


def _make_preset_row(
    id="preset-1",
    user_id="user-1",
    name="My Preset",
    filters=None,
    is_prebuilt=False,
    created_at=None,
):
    if filters is None:
        filters = {"pe_ratio": {"min": 5, "max": 30}}
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    data = {
        "id": id,
        "user_id": user_id,
        "name": name,
        "filters": filters,
        "is_prebuilt": is_prebuilt,
        "created_at": created_at,
    }
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    return row


def _make_insert_row(id="new-preset-id", created_at=None):
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    data = {"id": id, "created_at": created_at}
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    row.get = lambda key, default=None: data.get(key, default)
    return row


# ── Serialization tests ──────────────────────────────────────────────────────


class TestFiltersSerialization:
    def test_empty_filters_to_dict(self):
        f = ScreenerFilters()
        d = filters_to_dict(f)
        assert d == {}

    def test_range_filter_round_trip(self):
        f = ScreenerFilters(pe_ratio=Range(min=5.0, max=30.0))
        d = filters_to_dict(f)
        assert d == {"pe_ratio": {"min": 5.0, "max": 30.0}}
        restored = dict_to_filters(d)
        assert restored.pe_ratio.min == 5.0
        assert restored.pe_ratio.max == 30.0

    def test_boolean_filter_round_trip(self):
        f = ScreenerFilters(near_52w_high=True, near_52w_low=False)
        d = filters_to_dict(f)
        assert d["near_52w_high"] is True
        assert d["near_52w_low"] is False
        restored = dict_to_filters(d)
        assert restored.near_52w_high is True
        assert restored.near_52w_low is False

    def test_ma_crossover_round_trip(self):
        f = ScreenerFilters(ma_crossover_50_200="golden")
        d = filters_to_dict(f)
        assert d["ma_crossover_50_200"] == "golden"
        restored = dict_to_filters(d)
        assert restored.ma_crossover_50_200 == "golden"

    def test_meta_filters_round_trip(self):
        f = ScreenerFilters(exchange="NSE", sector="Energy", market_cap_category="large-cap")
        d = filters_to_dict(f)
        assert d["exchange"] == "NSE"
        assert d["sector"] == "Energy"
        assert d["market_cap_category"] == "large-cap"
        restored = dict_to_filters(d)
        assert restored.exchange == "NSE"
        assert restored.sector == "Energy"
        assert restored.market_cap_category == "large-cap"

    def test_complex_filters_round_trip(self):
        f = ScreenerFilters(
            pe_ratio=Range(min=5.0, max=30.0),
            market_cap=Range(min=100000),
            rsi_14=Range(min=30.0, max=70.0),
            near_52w_high=True,
            ma_crossover_50_200="golden",
            sector="IT/Technology",
            price_change_1m=Range(min=2.0),
            return_1y=Range(min=10.0),
        )
        d = filters_to_dict(f)
        restored = dict_to_filters(d)
        assert restored.pe_ratio.min == 5.0
        assert restored.pe_ratio.max == 30.0
        assert restored.market_cap.min == 100000
        assert restored.market_cap.max is None
        assert restored.rsi_14.min == 30.0
        assert restored.near_52w_high is True
        assert restored.ma_crossover_50_200 == "golden"
        assert restored.sector == "IT/Technology"
        assert restored.price_change_1m.min == 2.0
        assert restored.return_1y.min == 10.0

    def test_dict_to_filters_ignores_unknown_keys(self):
        d = {"unknown_field": "value", "pe_ratio": {"min": 10}}
        f = dict_to_filters(d)
        assert f.pe_ratio.min == 10
        assert not hasattr(f, "unknown_field") or getattr(f, "unknown_field", None) is None


# ── Pre-built templates tests ────────────────────────────────────────────────


class TestPrebuiltTemplates:
    def test_five_templates_defined(self):
        templates = ScreenerEngine.get_prebuilt_templates()
        assert len(templates) == 5

    def test_all_templates_are_prebuilt(self):
        for t in ScreenerEngine.get_prebuilt_templates():
            assert t.is_prebuilt is True

    def test_template_names(self):
        names = {t.name for t in ScreenerEngine.get_prebuilt_templates()}
        expected = {
            "High Dividend Yield",
            "Undervalued Large Caps",
            "Momentum Stocks",
            "Low PE Growth Stocks",
            "52-Week Breakout Candidates",
        }
        assert names == expected

    def test_high_dividend_yield_template(self):
        templates = {t.name: t for t in ScreenerEngine.get_prebuilt_templates()}
        t = templates["High Dividend Yield"]
        assert t.filters.dividend_yield is not None
        assert t.filters.dividend_yield.min == 3.0

    def test_momentum_template(self):
        templates = {t.name: t for t in ScreenerEngine.get_prebuilt_templates()}
        t = templates["Momentum Stocks"]
        assert t.filters.price_change_1m is not None
        assert t.filters.rsi_14 is not None

    def test_returns_new_list(self):
        result = ScreenerEngine.get_prebuilt_templates()
        result.append(ScreenerPreset(name="Extra"))
        assert len(ScreenerEngine.get_prebuilt_templates()) == 5


# ── Screen tests ─────────────────────────────────────────────────────────────


class TestScreen:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        engine = _make_engine(db_pool=None)
        result = await engine.screen(ScreenerFilters())
        assert isinstance(result, ScreenerResult)
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_empty_filters_returns_all_active(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=100)
        conn.fetchrow = AsyncMock(return_value=count_row)

        row = _make_screener_row()
        conn.fetch = AsyncMock(return_value=[row])

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters())

        assert result.total == 100
        assert len(result.items) == 1
        assert result.items[0].symbol == "RELIANCE"
        assert result.page == 1
        assert result.page_size == DEFAULT_PAGE_SIZE

    @pytest.mark.asyncio
    async def test_fundamental_filters_applied(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=5)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(
            pe_ratio=Range(min=10.0, max=25.0),
            market_cap=Range(min=100000),
            dividend_yield=Range(min=2.0),
        )
        result = await engine.screen(filters)

        assert result.total == 5
        # Verify params were passed
        call_args = conn.fetchrow.call_args[0]
        assert 10.0 in call_args
        assert 25.0 in call_args
        assert 100000 in call_args
        assert 2.0 in call_args

    @pytest.mark.asyncio
    async def test_technical_filters_applied(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=3)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(
            rsi_14=Range(min=30.0, max=70.0),
            price_change_1m=Range(min=5.0),
            avg_volume=Range(min=100000),
        )
        result = await engine.screen(filters)

        assert result.total == 3

    @pytest.mark.asyncio
    async def test_return_filters_applied(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=2)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(
            return_1y=Range(min=10.0),
            cagr_3y=Range(min=12.0),
            cagr_5y=Range(min=8.0, max=30.0),
        )
        result = await engine.screen(filters)

        assert result.total == 2

    @pytest.mark.asyncio
    async def test_meta_filters_applied(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=20)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(
            exchange="NSE",
            sector="Energy",
            market_cap_category="large-cap",
        )
        result = await engine.screen(filters)

        assert result.total == 20
        call_args = conn.fetchrow.call_args[0]
        assert "NSE" in call_args
        assert "Energy" in call_args
        assert "large-cap" in call_args

    @pytest.mark.asyncio
    async def test_ma_crossover_golden(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=1)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(ma_crossover_50_200="golden")
        result = await engine.screen(filters)

        assert result.total == 1
        # Verify the golden cross clause was included in the query
        query = conn.fetchrow.call_args[0][0]
        assert "sma_50 > st.sma_200" in query

    @pytest.mark.asyncio
    async def test_ma_crossover_death(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=1)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(ma_crossover_50_200="death")
        result = await engine.screen(filters)

        assert result.total == 1
        query = conn.fetchrow.call_args[0][0]
        assert "sma_50 < st.sma_200" in query

    @pytest.mark.asyncio
    async def test_pagination(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=150)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters(), page=3, page_size=50)

        assert result.total == 150
        assert result.page == 3
        assert result.page_size == 50
        assert result.total_pages == 3
        # Verify offset = (3-1)*50 = 100
        fetch_args = conn.fetch.call_args[0]
        assert 50 in fetch_args  # page_size
        assert 100 in fetch_args  # offset

    @pytest.mark.asyncio
    async def test_page_size_clamped_to_max(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=10)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters(), page_size=500)

        assert result.page_size == MAX_PAGE_SIZE

    @pytest.mark.asyncio
    async def test_invalid_sort_defaults_to_market_cap(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=5)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters(), sort_by="invalid_col")

        query = conn.fetch.call_args[0][0]
        assert "sf.market_cap" in query

    @pytest.mark.asyncio
    async def test_sort_by_symbol_asc(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=5)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters(), sort_by="symbol", order="asc")

        query = conn.fetch.call_args[0][0]
        assert "s.symbol" in query
        assert "asc" in query.lower()

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        engine = _make_engine(db_pool=pool)
        result = await engine.screen(ScreenerFilters())

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_combined_filters_and_logic(self):
        """All filters are combined with AND logic."""
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=1)
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(
            pe_ratio=Range(min=5.0, max=20.0),
            rsi_14=Range(min=40.0),
            return_1y=Range(min=10.0),
            sector="Pharma",
        )
        result = await engine.screen(filters)

        assert result.total == 1
        query = conn.fetchrow.call_args[0][0]
        # All conditions should be AND-ed in the WHERE clause
        assert "AND" in query


# ── Save preset tests ────────────────────────────────────────────────────────


class TestSavePreset:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        engine = _make_engine(db_pool=None)
        result = await engine.save_preset("user-1", "Test", ScreenerFilters())
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_none(self):
        engine = _make_engine(db_pool=MagicMock())
        result = await engine.save_preset("", "Test", ScreenerFilters())
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_name_returns_none(self):
        engine = _make_engine(db_pool=MagicMock())
        result = await engine.save_preset("user-1", "", ScreenerFilters())
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_save(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=3)
        insert_row = _make_insert_row(id="new-id")
        conn.fetchrow = AsyncMock(side_effect=[count_row, insert_row])

        engine = _make_engine(db_pool=pool)
        filters = ScreenerFilters(pe_ratio=Range(min=10.0))
        result = await engine.save_preset("user-1", "My Filter", filters)

        assert result is not None
        assert result.id == "new-id"
        assert result.name == "My Filter"
        assert result.user_id == "user-1"
        assert result.is_prebuilt is False
        assert result.filters.pe_ratio.min == 10.0

    @pytest.mark.asyncio
    async def test_max_presets_exceeded_returns_none(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=MAX_PRESETS_PER_USER)
        conn.fetchrow = AsyncMock(return_value=count_row)

        engine = _make_engine(db_pool=pool)
        result = await engine.save_preset("user-1", "Extra", ScreenerFilters())

        assert result is None

    @pytest.mark.asyncio
    async def test_save_at_limit_minus_one_succeeds(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=MAX_PRESETS_PER_USER - 1)
        insert_row = _make_insert_row(id="last-id")
        conn.fetchrow = AsyncMock(side_effect=[count_row, insert_row])

        engine = _make_engine(db_pool=pool)
        result = await engine.save_preset("user-1", "Last One", ScreenerFilters())

        assert result is not None
        assert result.id == "last-id"

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))

        engine = _make_engine(db_pool=pool)
        result = await engine.save_preset("user-1", "Test", ScreenerFilters())

        assert result is None

    @pytest.mark.asyncio
    async def test_name_is_stripped(self):
        pool, conn = _make_mock_pool()
        count_row = _make_count_row(cnt=0)
        insert_row = _make_insert_row(id="stripped-id")
        conn.fetchrow = AsyncMock(side_effect=[count_row, insert_row])

        engine = _make_engine(db_pool=pool)
        result = await engine.save_preset("user-1", "  Padded Name  ", ScreenerFilters())

        assert result is not None
        assert result.name == "Padded Name"


# ── Get user presets tests ───────────────────────────────────────────────────


class TestGetUserPresets:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        engine = _make_engine(db_pool=None)
        result = await engine.get_user_presets("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_empty(self):
        engine = _make_engine(db_pool=MagicMock())
        result = await engine.get_user_presets("")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_presets(self):
        pool, conn = _make_mock_pool()
        preset_row = _make_preset_row()
        conn.fetch = AsyncMock(return_value=[preset_row])

        engine = _make_engine(db_pool=pool)
        result = await engine.get_user_presets("user-1")

        assert len(result) == 1
        assert result[0].name == "My Preset"
        assert result[0].filters.pe_ratio is not None

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))

        engine = _make_engine(db_pool=pool)
        result = await engine.get_user_presets("user-1")

        assert result == []


# ── Delete preset tests ──────────────────────────────────────────────────────


class TestDeletePreset:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_false(self):
        engine = _make_engine(db_pool=None)
        result = await engine.delete_preset("user-1", "preset-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_false(self):
        engine = _make_engine(db_pool=MagicMock())
        result = await engine.delete_preset("", "preset-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_preset_id_returns_false(self):
        engine = _make_engine(db_pool=MagicMock())
        result = await engine.delete_preset("user-1", "")
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_delete(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        engine = _make_engine(db_pool=pool)
        result = await engine.delete_preset("user-1", "preset-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_preset_not_found_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        engine = _make_engine(db_pool=pool)
        result = await engine.delete_preset("user-1", "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))

        engine = _make_engine(db_pool=pool)
        result = await engine.delete_preset("user-1", "preset-1")

        assert result is False


# ── Export CSV tests ─────────────────────────────────────────────────────────


class TestExportCSV:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty_bytes(self):
        engine = _make_engine(db_pool=None)
        result = await engine.export_csv(ScreenerFilters())
        assert result == b""

    @pytest.mark.asyncio
    async def test_export_with_results(self):
        pool, conn = _make_mock_pool()
        row = _make_screener_row()
        conn.fetch = AsyncMock(return_value=[row])

        engine = _make_engine(db_pool=pool)
        result = await engine.export_csv(ScreenerFilters())

        assert isinstance(result, bytes)
        text = result.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)

        # Header + 1 data row
        assert len(rows) == 2
        assert rows[0][0] == "Symbol"
        assert rows[1][0] == "RELIANCE"
        assert rows[1][1] == "Reliance Industries"

    @pytest.mark.asyncio
    async def test_export_csv_has_all_columns(self):
        pool, conn = _make_mock_pool()
        row = _make_screener_row()
        conn.fetch = AsyncMock(return_value=[row])

        engine = _make_engine(db_pool=pool)
        result = await engine.export_csv(ScreenerFilters())

        text = result.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        headers = next(reader)

        assert "Symbol" in headers
        assert "PE Ratio" in headers
        assert "RSI 14" in headers
        assert "CAGR 5Y" in headers
        assert "Price Change 1Y" in headers
        assert len(headers) == 33

    @pytest.mark.asyncio
    async def test_export_empty_results(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        engine = _make_engine(db_pool=pool)
        result = await engine.export_csv(ScreenerFilters())

        text = result.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        # Only header row
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_export_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))

        engine = _make_engine(db_pool=pool)
        result = await engine.export_csv(ScreenerFilters())

        assert result == b""


# ── Row mapping tests ────────────────────────────────────────────────────────


class TestRowMapping:
    def test_row_to_result_item(self):
        row = _make_screener_row(
            id=5,
            symbol="TCS",
            company_name="TCS Ltd",
            pe_ratio=Decimal("30.0"),
            rsi_14=Decimal("65.0"),
        )
        result = ScreenerEngine._row_to_result_item(row)

        assert isinstance(result, ScreenerResultItem)
        assert result.security_id == 5
        assert result.symbol == "TCS"
        assert result.pe_ratio == Decimal("30.0")
        assert result.rsi_14 == Decimal("65.0")

    def test_row_to_preset(self):
        row = _make_preset_row(
            id="p-1",
            user_id="u-1",
            name="Test Preset",
            filters={"pe_ratio": {"min": 5, "max": 25}},
        )
        result = ScreenerEngine._row_to_preset(row)

        assert isinstance(result, ScreenerPreset)
        assert result.id == "p-1"
        assert result.name == "Test Preset"
        assert result.filters.pe_ratio.min == 5
        assert result.filters.pe_ratio.max == 25

    def test_row_to_preset_with_string_filters(self):
        row = _make_preset_row(
            filters=json.dumps({"dividend_yield": {"min": 3.0}}),
        )
        result = ScreenerEngine._row_to_preset(row)

        assert result.filters.dividend_yield.min == 3.0


# ── Sort column resolution tests ─────────────────────────────────────────────


class TestSortColumnResolution:
    def test_securities_column(self):
        assert ScreenerEngine._resolve_sort_column("symbol") == "s.symbol"

    def test_fundamental_column(self):
        assert ScreenerEngine._resolve_sort_column("pe_ratio") == "sf.pe_ratio"

    def test_technical_column(self):
        assert ScreenerEngine._resolve_sort_column("rsi_14") == "st.rsi_14"

    def test_unknown_column_defaults_to_market_cap(self):
        assert ScreenerEngine._resolve_sort_column("unknown") == "sf.market_cap"


# ── Query builder tests ─────────────────────────────────────────────────────


class TestBuildWhereClauses:
    def test_empty_filters_no_clauses(self):
        engine = _make_engine()
        clauses, params, idx = engine._build_where_clauses(ScreenerFilters())
        assert clauses == []
        assert params == []
        assert idx == 1

    def test_single_range_filter(self):
        engine = _make_engine()
        filters = ScreenerFilters(pe_ratio=Range(min=10.0, max=30.0))
        clauses, params, idx = engine._build_where_clauses(filters)
        assert len(clauses) == 2
        assert params == [10.0, 30.0]
        assert idx == 3

    def test_meta_filter(self):
        engine = _make_engine()
        filters = ScreenerFilters(exchange="NSE")
        clauses, params, idx = engine._build_where_clauses(filters)
        assert len(clauses) == 1
        assert "s.exchange" in clauses[0]
        assert params == ["NSE"]

    def test_golden_cross_filter(self):
        engine = _make_engine()
        filters = ScreenerFilters(ma_crossover_50_200="golden")
        clauses, params, idx = engine._build_where_clauses(filters)
        assert any("sma_50 > st.sma_200" in c for c in clauses)

    def test_death_cross_filter(self):
        engine = _make_engine()
        filters = ScreenerFilters(ma_crossover_50_200="death")
        clauses, params, idx = engine._build_where_clauses(filters)
        assert any("sma_50 < st.sma_200" in c for c in clauses)

    def test_near_52w_high_filter(self):
        engine = _make_engine()
        filters = ScreenerFilters(near_52w_high=True)
        clauses, params, idx = engine._build_where_clauses(filters)
        assert any("high_52w" in c for c in clauses)

    def test_avg_volume_filter_casts_to_int(self):
        engine = _make_engine()
        filters = ScreenerFilters(avg_volume=Range(min=100000.0))
        clauses, params, idx = engine._build_where_clauses(filters)
        assert params == [100000]
        assert isinstance(params[0], int)
