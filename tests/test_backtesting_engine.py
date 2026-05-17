"""Unit tests for the BacktestingEngine.

Covers: transaction costs, slippage, metrics calculation,
trade logging, threshold validation, and full backtest runs.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtesting.backtesting_engine import (
    BROKERAGE_PER_ORDER,
    SLIPPAGE_PCT,
    STAMP_DUTY_RATE,
    STT_RATE,
    BacktestingEngine,
    BacktestResult,
    TradeRecord,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Create a BacktestingEngine with a minimal config stub."""

    class _Cfg:
        pass

    return BacktestingEngine(config=_Cfg())


@pytest.fixture
def sample_ohlcv():
    """Generate a simple OHLCV DataFrame with 100 rows."""
    np.random.seed(42)
    n = 100
    close = 1000 + np.cumsum(np.random.randn(n) * 5)
    df = pd.DataFrame(
        {
            "symbol": "RELIANCE",
            "open": close - np.random.rand(n) * 2,
            "high": close + np.random.rand(n) * 5,
            "low": close - np.random.rand(n) * 5,
            "close": close,
            "volume": np.random.randint(100_000, 500_000, n),
        }
    )
    return df


@pytest.fixture
def sample_trades():
    """Create a list of sample TradeRecord objects."""
    return [
        TradeRecord(
            symbol="RELIANCE",
            strategy="mean_reversion",
            side="BUY",
            entry_price=1000.0,
            exit_price=1050.0,
            quantity=10,
            entry_date="2023-01-01",
            exit_date="2023-01-05",
            holding_period=4,
        ),
        TradeRecord(
            symbol="TCS",
            strategy="mean_reversion",
            side="BUY",
            entry_price=3000.0,
            exit_price=2950.0,
            quantity=5,
            entry_date="2023-01-10",
            exit_date="2023-01-12",
            holding_period=2,
        ),
    ]


# ---------------------------------------------------------------------------
# Transaction cost tests
# ---------------------------------------------------------------------------


class TestTransactionCosts:
    def test_costs_are_positive(self, engine, sample_trades):
        result = engine.apply_transaction_costs(sample_trades)
        for t in result:
            assert t.transaction_costs > 0, "Transaction costs must be positive"

    def test_costs_reduce_net_pnl(self, engine, sample_trades):
        result = engine.apply_transaction_costs(sample_trades)
        for t in result:
            assert t.net_pnl < t.gross_pnl, "Net P&L must be less than gross P&L"

    def test_stt_applied_on_sell_side(self, engine):
        trade = TradeRecord(
            symbol="X",
            strategy="test",
            side="BUY",
            entry_price=100.0,
            exit_price=110.0,
            quantity=100,
            entry_date="2023-01-01",
            exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade])
        sell_turnover = 110.0 * 100
        expected_stt = sell_turnover * STT_RATE
        # STT is part of total costs; verify it's included
        assert trade.transaction_costs >= expected_stt

    def test_brokerage_flat_fee(self, engine):
        trade = TradeRecord(
            symbol="X",
            strategy="test",
            side="BUY",
            entry_price=100.0,
            exit_price=100.0,
            quantity=1,
            entry_date="2023-01-01",
            exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade])
        # Minimum cost is at least 2 × brokerage
        assert trade.transaction_costs >= BROKERAGE_PER_ORDER * 2

    def test_stamp_duty_on_buy_side(self, engine):
        trade = TradeRecord(
            symbol="X",
            strategy="test",
            side="BUY",
            entry_price=500.0,
            exit_price=510.0,
            quantity=200,
            entry_date="2023-01-01",
            exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade])
        buy_turnover = 500.0 * 200
        expected_stamp = buy_turnover * STAMP_DUTY_RATE
        assert trade.transaction_costs >= expected_stamp


# ---------------------------------------------------------------------------
# Slippage tests
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_buy_slippage_increases_price(self, engine):
        price = 1000.0
        adj = engine.apply_slippage(price, "BUY")
        assert adj > price

    def test_sell_slippage_decreases_price(self, engine):
        price = 1000.0
        adj = engine.apply_slippage(price, "SELL")
        assert adj < price

    def test_slippage_magnitude(self, engine):
        price = 1000.0
        buy_adj = engine.apply_slippage(price, "BUY")
        sell_adj = engine.apply_slippage(price, "SELL")
        assert abs(buy_adj - price) == pytest.approx(price * SLIPPAGE_PCT, rel=1e-9)
        assert abs(sell_adj - price) == pytest.approx(price * SLIPPAGE_PCT, rel=1e-9)

    def test_slippage_zero_price(self, engine):
        assert engine.apply_slippage(0.0, "BUY") == 0.0
        assert engine.apply_slippage(0.0, "SELL") == 0.0


# ---------------------------------------------------------------------------
# Metrics calculation tests
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_total_return(self, engine):
        equity = pd.Series([100_000, 105_000, 110_000])
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["total_return"] == pytest.approx(10.0)

    def test_max_drawdown(self, engine):
        equity = pd.Series([100, 110, 90, 95, 100])
        metrics = engine.calculate_metrics(equity, [])
        # Peak was 110, trough was 90 → DD = 20/110 * 100 ≈ 18.18%
        assert metrics["max_drawdown"] == pytest.approx(18.1818, rel=0.01)

    def test_win_rate(self, engine, sample_trades):
        engine.apply_transaction_costs(sample_trades)
        equity = pd.Series([100_000, 100_500])
        metrics = engine.calculate_metrics(equity, sample_trades)
        # First trade wins, second loses
        assert 0 <= metrics["win_rate"] <= 100

    def test_profit_factor_no_losses(self, engine):
        trades = [
            TradeRecord(
                symbol="X",
                strategy="test",
                side="BUY",
                entry_price=100,
                exit_price=110,
                quantity=10,
                entry_date="2023-01-01",
                exit_date="2023-01-02",
                net_pnl=100,
            ),
        ]
        equity = pd.Series([100_000, 100_100])
        metrics = engine.calculate_metrics(equity, trades)
        assert metrics["profit_factor"] == float("inf")

    def test_sharpe_flat_returns(self, engine):
        equity = pd.Series([100_000] * 10)
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["sharpe_ratio"] == 0.0

    def test_empty_equity(self, engine):
        equity = pd.Series(dtype=float)
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["sharpe_ratio"] == 0.0
        assert metrics["total_return"] == 0.0

    def test_single_point_equity(self, engine):
        equity = pd.Series([100_000])
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["total_return"] == 0.0


# ---------------------------------------------------------------------------
# Trade log tests
# ---------------------------------------------------------------------------


class TestTradeLog:
    def test_trade_log_columns(self, engine, sample_trades):
        log = engine.generate_trade_log(sample_trades)
        expected_cols = {
            "symbol",
            "strategy",
            "side",
            "entry_price",
            "exit_price",
            "quantity",
            "entry_date",
            "exit_date",
            "gross_pnl",
            "transaction_costs",
            "net_pnl",
            "holding_period",
        }
        assert set(log.columns) == expected_cols

    def test_trade_log_row_count(self, engine, sample_trades):
        log = engine.generate_trade_log(sample_trades)
        assert len(log) == len(sample_trades)

    def test_empty_trade_log(self, engine):
        log = engine.generate_trade_log([])
        assert len(log) == 0
        assert "symbol" in log.columns


# ---------------------------------------------------------------------------
# Threshold validation tests
# ---------------------------------------------------------------------------


class TestThresholdValidation:
    def test_all_pass(self, engine):
        metrics = {
            "sharpe_ratio": 2.0,
            "max_drawdown": 3.0,
            "win_rate": 55.0,
            "profit_factor": 2.0,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is True

    def test_sharpe_fails(self, engine):
        metrics = {
            "sharpe_ratio": 1.0,
            "max_drawdown": 3.0,
            "win_rate": 55.0,
            "profit_factor": 2.0,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is False
        assert result["checks"]["sharpe_ratio"] is False

    def test_drawdown_fails(self, engine):
        metrics = {
            "sharpe_ratio": 2.0,
            "max_drawdown": 6.0,
            "win_rate": 55.0,
            "profit_factor": 2.0,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is False
        assert result["checks"]["max_drawdown"] is False

    def test_win_rate_fails(self, engine):
        metrics = {
            "sharpe_ratio": 2.0,
            "max_drawdown": 3.0,
            "win_rate": 40.0,
            "profit_factor": 2.0,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is False

    def test_profit_factor_fails(self, engine):
        metrics = {
            "sharpe_ratio": 2.0,
            "max_drawdown": 3.0,
            "win_rate": 55.0,
            "profit_factor": 1.0,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is False

    def test_boundary_values(self, engine):
        # Exactly at thresholds should fail (strict >)
        metrics = {
            "sharpe_ratio": 1.5,
            "max_drawdown": 5.0,
            "win_rate": 45.0,
            "profit_factor": 1.5,
        }
        result = engine.validate_thresholds(metrics)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Backtest run tests
# ---------------------------------------------------------------------------


class TestBacktestRun:
    def test_run_mean_reversion(self, engine, sample_ohlcv):
        result = engine.run_backtest("mean_reversion", sample_ohlcv)
        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "mean_reversion"
        assert "sharpe_ratio" in result.metrics

    def test_run_trend_following(self, engine, sample_ohlcv):
        result = engine.run_backtest("trend_following", sample_ohlcv)
        assert result.strategy_name == "trend_following"

    def test_run_orb(self, engine, sample_ohlcv):
        result = engine.run_backtest("orb", sample_ohlcv)
        assert result.strategy_name == "orb"

    def test_run_unknown_strategy(self, engine, sample_ohlcv):
        result = engine.run_backtest("unknown", sample_ohlcv)
        assert result.strategy_name == "unknown"
        assert result.metrics == {}

    def test_run_empty_data(self, engine):
        empty = pd.DataFrame(columns=["close"])
        result = engine.run_backtest("mean_reversion", empty)
        assert result.trades == []

    def test_run_all_strategies(self, engine, sample_ohlcv):
        results = engine.run_all_strategies(sample_ohlcv)
        assert set(results.keys()) == {"mean_reversion", "trend_following", "orb"}
        for name, res in results.items():
            assert isinstance(res, BacktestResult)

    def test_equity_curve_starts_at_capital(self, engine, sample_ohlcv):
        capital = 500_000.0
        result = engine.run_backtest("mean_reversion", sample_ohlcv, capital)
        if result.equity_curve is not None and len(result.equity_curve) > 0:
            assert result.equity_curve.iloc[0] == capital

    def test_trade_log_generated(self, engine, sample_ohlcv):
        result = engine.run_backtest("mean_reversion", sample_ohlcv)
        assert result.trade_log is not None
        assert isinstance(result.trade_log, pd.DataFrame)

    def test_with_signal_column(self, engine):
        """Test backtest with pre-computed signals."""
        df = pd.DataFrame(
            {
                "symbol": "TEST",
                "close": [100, 102, 104, 103, 101, 99, 100, 105, 110, 108],
                "high": [101, 103, 105, 104, 102, 100, 101, 106, 111, 109],
                "low": [99, 101, 103, 102, 100, 98, 99, 104, 109, 107],
                "signal": [0, 1, 0, 0, 0, -1, 0, 1, 0, -1],
            }
        )
        result = engine.run_backtest("mean_reversion", df, 100_000)
        assert len(result.trades) >= 1
