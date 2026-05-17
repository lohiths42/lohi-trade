"""Unit tests for TradingQueryHandler — trading data query handlers for chatbot.

Tests cover: time-range parsing, trade detail queries, performance queries,
signal explanation, stock info queries, and edge cases.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.6
"""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.chatbot_service import (
    PerformanceSummary,
    SignalExplanation,
    StockInfo,
    TradeDetail,
    TradingQueryHandler,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_pool():
    """Create a mock asyncpg pool with async context manager for acquire()."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_trade_row(
    id="trade-1",
    symbol="RELIANCE",
    strategy="mean_reversion",
    entry_price=2500.0,
    exit_price=2550.0,
    quantity=10,
    realized_pnl=500.0,
    entry_time="2024-01-15T10:00:00",
    exit_time="2024-01-15T14:00:00",
):
    return {
        "id": id,
        "symbol": symbol,
        "strategy": strategy,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "realized_pnl": realized_pnl,
        "entry_time": entry_time,
        "exit_time": exit_time,
    }


def _make_pnl_row(symbol="RELIANCE", realized_pnl=500.0):
    """Minimal row for performance queries."""
    return {"symbol": symbol, "realized_pnl": realized_pnl}


def _make_signal_row(
    symbol="RELIANCE",
    signal_type="BUY",
    strategy="mean_reversion",
    indicator_values='{"rsi": 30, "sma_50": 2480}',
    bias_state="BULLISH",
    created_at="2024-01-15T09:30:00",
):
    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "strategy": strategy,
        "indicator_values": indicator_values,
        "bias_state": bias_state,
        "created_at": created_at,
    }


def _make_sentiment_row(
    ticker="RELIANCE",
    sentiment="BULLISH",
    score=0.85,
    headline="Reliance Q3 results beat estimates",
    created_at="2024-01-15T09:00:00",
):
    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "score": score,
        "headline": headline,
        "created_at": created_at,
    }


def _make_bias_row(bias="BULLISH"):
    return {"bias": bias}


def _make_handler(db_pool=None) -> TradingQueryHandler:
    return TradingQueryHandler(db_pool=db_pool)


# ── Time-range parsing tests (Req 19.6) ─────────────────────────────────────


class TestParseTimeRange:
    """Tests for TradingQueryHandler.parse_time_range — Req 19.6."""

    def _now(self):
        return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_today(self):
        start, end = TradingQueryHandler.parse_time_range("How did I do today?", self._now())
        assert start == datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert end == self._now()

    def test_yesterday(self):
        start, end = TradingQueryHandler.parse_time_range("Show yesterday's trades", self._now())
        assert start == datetime(2024, 6, 14, 0, 0, 0, tzinfo=timezone.utc)
        assert end.day == 14

    def test_last_week(self):
        start, end = TradingQueryHandler.parse_time_range(
            "How did I perform last week?", self._now()
        )
        assert start == self._now() - timedelta(weeks=1)
        assert end == self._now()

    def test_last_month(self):
        start, end = TradingQueryHandler.parse_time_range(
            "Show my trades from last month", self._now()
        )
        assert start == self._now() - timedelta(days=30)

    def test_last_year(self):
        start, end = TradingQueryHandler.parse_time_range("Performance last year", self._now())
        assert start == self._now() - timedelta(days=365)

    def test_last_n_days(self):
        start, end = TradingQueryHandler.parse_time_range("Show last 5 days", self._now())
        assert start == self._now() - timedelta(days=5)

    def test_last_n_weeks(self):
        start, end = TradingQueryHandler.parse_time_range("Show last 2 weeks", self._now())
        assert start == self._now() - timedelta(weeks=2)

    def test_last_n_months(self):
        start, end = TradingQueryHandler.parse_time_range("Show last 3 months", self._now())
        assert start == self._now() - timedelta(days=90)

    def test_this_week(self):
        start, end = TradingQueryHandler.parse_time_range("This week performance", self._now())
        # June 15, 2024 is a Saturday (weekday=5)
        expected_start = datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        assert start == expected_start

    def test_this_month(self):
        start, end = TradingQueryHandler.parse_time_range("This month trades", self._now())
        assert start == datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_this_year(self):
        start, end = TradingQueryHandler.parse_time_range("This year performance", self._now())
        assert start == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_from_january(self):
        start, end = TradingQueryHandler.parse_time_range(
            "Show my trades from January", self._now()
        )
        assert start == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert end == self._now()

    def test_from_december_wraps_to_previous_year(self):
        now = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        start, end = TradingQueryHandler.parse_time_range("from December", now)
        assert start == datetime(2023, 12, 1, tzinfo=timezone.utc)

    def test_unparseable_returns_none(self):
        start, end = TradingQueryHandler.parse_time_range("Hello there", self._now())
        assert start is None
        assert end is None

    def test_case_insensitive(self):
        start, end = TradingQueryHandler.parse_time_range("LAST WEEK performance", self._now())
        assert start is not None


# ── Trade detail query tests (Req 19.1) ─────────────────────────────────────


class TestGetTradeDetails:
    """Tests for TradingQueryHandler.get_trade_details — Req 19.1."""

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        handler = _make_handler(db_pool=None)
        result = await handler.get_trade_details("user-1", "trade-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_trade_found(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.return_value = _make_trade_row()
        handler = _make_handler(db_pool=pool)
        result = await handler.get_trade_details("user-1", "trade-1")
        assert result is not None
        assert isinstance(result, TradeDetail)
        assert result.symbol == "RELIANCE"
        assert result.entry_price == 2500.0
        assert result.exit_price == 2550.0
        assert result.realized_pnl == 500.0
        assert result.holding_period == "4h"

    @pytest.mark.asyncio
    async def test_trade_not_found(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.return_value = None
        handler = _make_handler(db_pool=pool)
        result = await handler.get_trade_details("user-1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.side_effect = Exception("DB error")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_trade_details("user-1", "trade-1")
        assert result is None


class TestGetTradesBySymbol:
    """Tests for TradingQueryHandler.get_trades_by_symbol — Req 19.1."""

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_empty(self):
        handler = _make_handler(db_pool=None)
        result = await handler.get_trades_by_symbol("user-1", "RELIANCE")
        assert result == []

    @pytest.mark.asyncio
    async def test_trades_found(self):
        pool, conn = _make_mock_pool()
        conn.fetch.return_value = [_make_trade_row(), _make_trade_row(id="trade-2")]
        handler = _make_handler(db_pool=pool)
        result = await handler.get_trades_by_symbol("user-1", "RELIANCE")
        assert len(result) == 2
        assert all(isinstance(t, TradeDetail) for t in result)

    @pytest.mark.asyncio
    async def test_with_time_range(self):
        pool, conn = _make_mock_pool()
        conn.fetch.return_value = [_make_trade_row()]
        handler = _make_handler(db_pool=pool)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        result = await handler.get_trades_by_symbol("user-1", "RELIANCE", start, end)
        assert len(result) == 1
        # Verify the query included time params
        query_str = conn.fetch.call_args[0][0]
        assert ">=" in query_str
        assert "<=" in query_str

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = Exception("DB error")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_trades_by_symbol("user-1", "RELIANCE")
        assert result == []


# ── Holding period calculation tests ─────────────────────────────────────────


class TestHoldingPeriod:
    """Tests for holding period calculation in _row_to_trade_detail."""

    def test_hours_and_minutes(self):
        row = _make_trade_row(entry_time="2024-01-15T10:00:00", exit_time="2024-01-15T14:30:00")
        detail = TradingQueryHandler._row_to_trade_detail(row)
        assert detail.holding_period == "4h 30m"

    def test_days_hours_minutes(self):
        row = _make_trade_row(entry_time="2024-01-15T10:00:00", exit_time="2024-01-17T14:30:00")
        detail = TradingQueryHandler._row_to_trade_detail(row)
        assert detail.holding_period == "2d 4h 30m"

    def test_zero_duration(self):
        row = _make_trade_row(entry_time="2024-01-15T10:00:00", exit_time="2024-01-15T10:00:00")
        detail = TradingQueryHandler._row_to_trade_detail(row)
        assert detail.holding_period == "0m"

    def test_no_exit_time(self):
        row = _make_trade_row(exit_time=None)
        detail = TradingQueryHandler._row_to_trade_detail(row)
        assert detail.holding_period is None

    def test_no_exit_price(self):
        row = _make_trade_row(exit_price=None, realized_pnl=None)
        detail = TradingQueryHandler._row_to_trade_detail(row)
        assert detail.exit_price is None
        assert detail.realized_pnl is None


# ── Performance query tests (Req 19.2) ──────────────────────────────────────


class TestGetPerformanceSummary:
    """Tests for TradingQueryHandler.get_performance_summary — Req 19.2."""

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        handler = _make_handler(db_pool=None)
        result = await handler.get_performance_summary("user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_trades_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetch.return_value = []
        handler = _make_handler(db_pool=pool)
        result = await handler.get_performance_summary("user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_performance_calculated(self):
        pool, conn = _make_mock_pool()
        conn.fetch.return_value = [
            _make_pnl_row("RELIANCE", 500.0),
            _make_pnl_row("TCS", -200.0),
            _make_pnl_row("INFY", 300.0),
        ]
        handler = _make_handler(db_pool=pool)
        result = await handler.get_performance_summary("user-1")
        assert result is not None
        assert isinstance(result, PerformanceSummary)
        assert result.total_pnl == 600.0
        assert result.trade_count == 3
        assert result.win_count == 2
        assert result.loss_count == 1
        assert result.win_rate == pytest.approx(66.67, abs=0.01)
        assert result.avg_profit == 200.0
        assert result.best_trade_pnl == 500.0
        assert result.best_trade_symbol == "RELIANCE"
        assert result.worst_trade_pnl == -200.0
        assert result.worst_trade_symbol == "TCS"
        assert result.sharpe_ratio is not None

    @pytest.mark.asyncio
    async def test_performance_with_time_range(self):
        pool, conn = _make_mock_pool()
        conn.fetch.return_value = [_make_pnl_row("RELIANCE", 100.0)]
        handler = _make_handler(db_pool=pool)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        result = await handler.get_performance_summary("user-1", start, end)
        assert result is not None
        query_str = conn.fetch.call_args[0][0]
        assert ">=" in query_str
        assert "<=" in query_str

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = Exception("DB error")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_performance_summary("user-1")
        assert result is None


class TestComputePerformance:
    """Tests for TradingQueryHandler._compute_performance — Req 19.2."""

    def test_all_wins(self):
        rows = [_make_pnl_row("A", 100), _make_pnl_row("B", 200)]
        result = TradingQueryHandler._compute_performance(rows)
        assert result.win_rate == 100.0
        assert result.loss_count == 0

    def test_all_losses(self):
        rows = [_make_pnl_row("A", -100), _make_pnl_row("B", -200)]
        result = TradingQueryHandler._compute_performance(rows)
        assert result.win_rate == 0.0
        assert result.win_count == 0

    def test_single_trade_no_sharpe(self):
        rows = [_make_pnl_row("A", 100)]
        result = TradingQueryHandler._compute_performance(rows)
        assert result.sharpe_ratio is None

    def test_sharpe_ratio_calculation(self):
        rows = [_make_pnl_row("A", 100), _make_pnl_row("B", 200), _make_pnl_row("C", 150)]
        result = TradingQueryHandler._compute_performance(rows)
        # Mean = 150, std = 50, sharpe = (150/50) * sqrt(252)
        expected = round((150 / 50) * math.sqrt(252), 2)
        assert result.sharpe_ratio == expected

    def test_zero_std_no_sharpe(self):
        rows = [_make_pnl_row("A", 100), _make_pnl_row("B", 100)]
        result = TradingQueryHandler._compute_performance(rows)
        assert result.sharpe_ratio is None


# ── Signal explanation tests (Req 19.3) ──────────────────────────────────────


class TestGetSignalExplanation:
    """Tests for TradingQueryHandler.get_signal_explanation — Req 19.3."""

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        handler = _make_handler(db_pool=None)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result is None

    @pytest.mark.asyncio
    async def test_signal_found(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.return_value = _make_signal_row()
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result is not None
        assert isinstance(result, SignalExplanation)
        assert result.symbol == "RELIANCE"
        assert result.strategy == "mean_reversion"
        assert result.indicator_values == {"rsi": 30, "sma_50": 2480}
        assert result.bias_state == "BULLISH"

    @pytest.mark.asyncio
    async def test_signal_with_entry_time(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.return_value = _make_signal_row()
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation(
            "user-1", "RELIANCE", trade_entry_time="2024-01-15T10:00:00"
        )
        assert result is not None
        query_str = conn.fetchrow.call_args[0][0]
        assert "<=" in query_str

    @pytest.mark.asyncio
    async def test_signal_not_found(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.return_value = None
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "UNKNOWN")
        assert result is None

    @pytest.mark.asyncio
    async def test_indicator_values_already_dict(self):
        pool, conn = _make_mock_pool()
        row = _make_signal_row(indicator_values={"rsi": 45})
        conn.fetchrow.return_value = row
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result.indicator_values == {"rsi": 45}

    @pytest.mark.asyncio
    async def test_indicator_values_invalid_json(self):
        pool, conn = _make_mock_pool()
        row = _make_signal_row(indicator_values="not-json")
        conn.fetchrow.return_value = row
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result.indicator_values == {}

    @pytest.mark.asyncio
    async def test_null_bias_state(self):
        pool, conn = _make_mock_pool()
        row = _make_signal_row(bias_state=None)
        conn.fetchrow.return_value = row
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result.bias_state == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow.side_effect = Exception("DB error")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_signal_explanation("user-1", "RELIANCE")
        assert result is None


# ── Stock info query tests (Req 19.4) ───────────────────────────────────────


class TestGetStockInfo:
    """Tests for TradingQueryHandler.get_stock_info — Req 19.4."""

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        handler = _make_handler(db_pool=None)
        result = await handler.get_stock_info("user-1", "RELIANCE")
        assert result is None

    @pytest.mark.asyncio
    async def test_full_stock_info(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = [
            [_make_sentiment_row()],  # sentiment
            [
                {
                    "id": "t1",
                    "symbol": "RELIANCE",
                    "strategy": "orb",
                    "entry_price": 2500,
                    "quantity": 10,
                    "entry_time": "2024-01-15T10:00:00",
                }
            ],  # open positions
            [_make_trade_row()],  # recent trades
        ]
        conn.fetchrow.return_value = _make_bias_row("BULLISH")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_stock_info("user-1", "RELIANCE")
        assert result is not None
        assert isinstance(result, StockInfo)
        assert result.symbol == "RELIANCE"
        assert len(result.recent_sentiment) == 1
        assert result.bias_status == "BULLISH"
        assert len(result.open_positions) == 1
        assert len(result.recent_trades) == 1

    @pytest.mark.asyncio
    async def test_no_bias_data(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = [[], [], []]
        conn.fetchrow.return_value = None
        handler = _make_handler(db_pool=pool)
        result = await handler.get_stock_info("user-1", "RELIANCE")
        assert result is not None
        assert result.bias_status is None
        assert result.recent_sentiment == []
        assert result.open_positions == []
        assert result.recent_trades == []

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetch.side_effect = Exception("DB error")
        handler = _make_handler(db_pool=pool)
        result = await handler.get_stock_info("user-1", "RELIANCE")
        assert result is None
