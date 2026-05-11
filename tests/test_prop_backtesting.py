"""Property-based tests for the BacktestingEngine.

Property 62: Transaction Cost Application
Property 63: Slippage Application
Property 64: Backtest Metrics Calculation
"""

import math

import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.backtesting.backtesting_engine import (
    SLIPPAGE_PCT,
    BacktestingEngine,
    TradeRecord,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    class _Cfg:
        pass
    return BacktestingEngine(config=_Cfg())


def _make_engine():
    class _Cfg:
        pass
    return BacktestingEngine(config=_Cfg())


# Hypothesis strategies
positive_price = st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)
positive_qty = st.integers(min_value=1, max_value=10_000)
side_strategy = st.sampled_from(["BUY", "SELL"])


# ---------------------------------------------------------------------------
# Property 62: Transaction Cost Application
# For any trade, transaction costs should be positive and reduce net P&L.
# ---------------------------------------------------------------------------

class TestProperty62TransactionCosts:
    @given(
        entry_price=positive_price,
        exit_price=positive_price,
        quantity=positive_qty,
    )
    @settings(max_examples=25, deadline=None)
    def test_costs_always_positive(self, entry_price, exit_price, quantity):
        """Transaction costs must always be positive for any valid trade."""
        engine = _make_engine()
        trade = TradeRecord(
            symbol="TEST", strategy="test", side="BUY",
            entry_price=entry_price, exit_price=exit_price,
            quantity=quantity,
            entry_date="2023-01-01", exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade])
        assert trade.transaction_costs > 0

    @given(
        entry_price=positive_price,
        exit_price=positive_price,
        quantity=positive_qty,
    )
    @settings(max_examples=25, deadline=None)
    def test_costs_reduce_net_pnl(self, entry_price, exit_price, quantity):
        """Net P&L must always be less than gross P&L after costs."""
        engine = _make_engine()
        trade = TradeRecord(
            symbol="TEST", strategy="test", side="BUY",
            entry_price=entry_price, exit_price=exit_price,
            quantity=quantity,
            entry_date="2023-01-01", exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade])
        assert trade.net_pnl < trade.gross_pnl

    @given(
        entry_price=positive_price,
        exit_price=positive_price,
        quantity=positive_qty,
    )
    @settings(max_examples=25, deadline=None)
    def test_costs_scale_with_turnover(self, entry_price, exit_price, quantity):
        """Larger turnover should produce larger transaction costs."""
        engine = _make_engine()
        trade_small = TradeRecord(
            symbol="TEST", strategy="test", side="BUY",
            entry_price=entry_price, exit_price=exit_price,
            quantity=1,
            entry_date="2023-01-01", exit_date="2023-01-02",
        )
        trade_large = TradeRecord(
            symbol="TEST", strategy="test", side="BUY",
            entry_price=entry_price, exit_price=exit_price,
            quantity=max(quantity, 2),
            entry_date="2023-01-01", exit_date="2023-01-02",
        )
        engine.apply_transaction_costs([trade_small])
        engine.apply_transaction_costs([trade_large])
        assert trade_large.transaction_costs >= trade_small.transaction_costs


# ---------------------------------------------------------------------------
# Property 63: Slippage Application
# For any order, slippage should worsen the execution price.
# ---------------------------------------------------------------------------

class TestProperty63Slippage:
    @given(price=positive_price)
    @settings(max_examples=25, deadline=None)
    def test_buy_slippage_worsens_price(self, price):
        """Buy slippage must increase the execution price."""
        engine = _make_engine()
        adj = engine.apply_slippage(price, "BUY")
        assert adj >= price  # >= because price * (1 + small) >= price

    @given(price=positive_price)
    @settings(max_examples=25, deadline=None)
    def test_sell_slippage_worsens_price(self, price):
        """Sell slippage must decrease the execution price."""
        engine = _make_engine()
        adj = engine.apply_slippage(price, "SELL")
        assert adj <= price

    @given(price=positive_price)
    @settings(max_examples=25, deadline=None)
    def test_slippage_magnitude_correct(self, price):
        """Slippage magnitude should be exactly SLIPPAGE_PCT of price."""
        engine = _make_engine()
        buy_adj = engine.apply_slippage(price, "BUY")
        sell_adj = engine.apply_slippage(price, "SELL")

        expected_buy = price * (1 + SLIPPAGE_PCT)
        expected_sell = price * (1 - SLIPPAGE_PCT)

        assert abs(buy_adj - expected_buy) < 1e-6
        assert abs(sell_adj - expected_sell) < 1e-6

    @given(price=positive_price)
    @settings(max_examples=25, deadline=None)
    def test_slippage_symmetric(self, price):
        """Buy and sell slippage should be symmetric around the original price."""
        engine = _make_engine()
        buy_adj = engine.apply_slippage(price, "BUY")
        sell_adj = engine.apply_slippage(price, "SELL")
        # Midpoint of buy and sell adjusted prices should be close to original
        midpoint = (buy_adj + sell_adj) / 2
        assert abs(midpoint - price) < price * SLIPPAGE_PCT * 0.01


# ---------------------------------------------------------------------------
# Property 64: Backtest Metrics Calculation
# For any equity curve, metrics should be mathematically correct.
# ---------------------------------------------------------------------------

class TestProperty64Metrics:
    @given(
        values=st.lists(
            st.floats(min_value=10.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=300,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_max_drawdown_non_negative(self, values):
        """Max drawdown must always be non-negative."""
        engine = _make_engine()
        equity = pd.Series(values)
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["max_drawdown"] >= 0

    @given(
        values=st.lists(
            st.floats(min_value=10.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=300,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_max_drawdown_bounded(self, values):
        """Max drawdown must be between 0% and 100%."""
        engine = _make_engine()
        equity = pd.Series(values)
        metrics = engine.calculate_metrics(equity, [])
        assert 0 <= metrics["max_drawdown"] <= 100

    @given(
        initial=st.floats(min_value=100.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        final=st.floats(min_value=100.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25, deadline=None)
    def test_total_return_correct(self, initial, final):
        """Total return should match (final - initial) / initial * 100."""
        engine = _make_engine()
        equity = pd.Series([initial, (initial + final) / 2, final])
        metrics = engine.calculate_metrics(equity, [])
        expected = ((final - initial) / initial) * 100
        assert abs(metrics["total_return"] - expected) < 0.01

    @given(
        values=st.lists(
            st.floats(min_value=10.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=300,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_sharpe_finite(self, values):
        """Sharpe ratio must be a finite number."""
        engine = _make_engine()
        equity = pd.Series(values)
        metrics = engine.calculate_metrics(equity, [])
        assert math.isfinite(metrics["sharpe_ratio"])

    @given(
        n_wins=st.integers(min_value=0, max_value=50),
        n_losses=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=25, deadline=None)
    def test_win_rate_bounded(self, n_wins, n_losses):
        """Win rate must be between 0% and 100%."""
        assume(n_wins + n_losses > 0)
        engine = _make_engine()

        trades = []
        for _ in range(n_wins):
            trades.append(TradeRecord(
                symbol="X", strategy="t", side="BUY",
                entry_price=100, exit_price=110, quantity=1,
                entry_date="2023-01-01", exit_date="2023-01-02",
                net_pnl=10.0,
            ))
        for _ in range(n_losses):
            trades.append(TradeRecord(
                symbol="X", strategy="t", side="BUY",
                entry_price=100, exit_price=90, quantity=1,
                entry_date="2023-01-01", exit_date="2023-01-02",
                net_pnl=-10.0,
            ))

        equity = pd.Series([100_000, 100_100])
        metrics = engine.calculate_metrics(equity, trades)
        assert 0 <= metrics["win_rate"] <= 100

        expected_wr = (n_wins / (n_wins + n_losses)) * 100
        assert abs(metrics["win_rate"] - expected_wr) < 0.01

    @given(
        values=st.lists(
            st.floats(min_value=10.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=300,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_monotonic_equity_zero_drawdown(self, values):
        """A strictly increasing equity curve should have zero drawdown."""
        sorted_values = sorted(values)
        # Make strictly increasing
        for i in range(1, len(sorted_values)):
            if sorted_values[i] <= sorted_values[i - 1]:
                sorted_values[i] = sorted_values[i - 1] + 0.01

        engine = _make_engine()
        equity = pd.Series(sorted_values)
        metrics = engine.calculate_metrics(equity, [])
        assert metrics["max_drawdown"] == pytest.approx(0.0, abs=1e-6)
