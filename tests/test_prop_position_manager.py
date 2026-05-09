"""
Property-based tests for the Position Manager.

Uses hypothesis to verify PositionManager properties across randomly
generated positions and price movements.

Properties tested:
- Property 52: Stop-Loss Placement       (Validates: Requirements 12.1)
- Property 53: Target Order Placement     (Validates: Requirements 12.2)
- Property 54: Trailing Stop-Loss         (Validates: Requirements 12.3)
- Property 55: Position Closing           (Validates: Requirements 12.4)
- Property 56: OCO Order Cancellation     (Validates: Requirements 12.5)
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.execution.position_manager import PositionManager, Position
from src.execution.oms import OrderResult
from src.ingestion.broker_interface import (
    OrderSide,
    OrderType,
    ProductType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades_db() -> MagicMock:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            strategy TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity INTEGER NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            exit_time TIMESTAMP,
            realized_pnl REAL,
            stop_loss REAL NOT NULL,
            target REAL NOT NULL,
            exit_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    db = MagicMock()
    db.connect_sqlite.return_value = conn
    return db


def _make_oms() -> MagicMock:
    oms = MagicMock()
    oms.place_order.return_value = OrderResult(
        success=True, order_id="mock-order", broker_order_id="BROKER-1"
    )
    oms.cancel_order.return_value = True
    return oms


def _make_pm(
    oms: MagicMock = None,
    db: MagicMock = None,
    now: datetime = datetime(2024, 1, 15, 10, 30),
) -> PositionManager:
    config = MagicMock()
    oms = oms or _make_oms()
    db = db or _make_trades_db()
    event_bus = MagicMock()
    redis_client = MagicMock()
    return PositionManager(
        config=config,
        oms=oms,
        db_manager=db,
        event_bus=event_bus,
        redis_client=redis_client,
        now_fn=lambda: now,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

symbols = st.sampled_from([
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
])
strategies_names = st.sampled_from([
    "MeanReversion", "TrendFollowing", "OpeningRangeBreakout",
])
quantities = st.integers(min_value=1, max_value=500)
prices = st.floats(min_value=50.0, max_value=10000.0, allow_nan=False, allow_infinity=False)


@st.composite
def buy_position_params(draw):
    """Generate valid BUY position parameters with SL < entry < target."""
    entry = draw(st.floats(min_value=100.0, max_value=9000.0, allow_nan=False, allow_infinity=False))
    sl_offset = draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    target_offset = draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    return {
        "side": "BUY",
        "entry_price": entry,
        "stop_loss": entry - sl_offset,
        "target": entry + target_offset,
        "quantity": draw(quantities),
        "symbol": draw(symbols),
        "strategy": draw(strategies_names),
    }


@st.composite
def sell_position_params(draw):
    """Generate valid SELL position parameters with SL > entry > target."""
    entry = draw(st.floats(min_value=100.0, max_value=9000.0, allow_nan=False, allow_infinity=False))
    sl_offset = draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    target_offset = draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    return {
        "side": "SELL",
        "entry_price": entry,
        "stop_loss": entry + sl_offset,
        "target": entry - target_offset,
        "quantity": draw(quantities),
        "symbol": draw(symbols),
        "strategy": draw(strategies_names),
    }


@st.composite
def any_position_params(draw):
    """Generate either BUY or SELL position parameters."""
    if draw(st.booleans()):
        return draw(buy_position_params())
    else:
        return draw(sell_position_params())


# ---------------------------------------------------------------------------
# Property 52: Stop-Loss Placement
# **Validates: Requirements 12.1**
# ---------------------------------------------------------------------------

class TestProperty52StopLossPlacement:
    """
    For any filled position, a stop-loss order should be placed at the
    signal's stop price immediately.

    **Validates: Requirements 12.1**
    """

    @given(params=buy_position_params())
    @settings(max_examples=25)
    def test_sl_placed_at_signal_stop_price_buy(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        # First OMS call is the stop-loss
        sl_order = oms.place_order.call_args_list[0][0][0]
        assert sl_order.order_type == OrderType.SL_M
        assert sl_order.side == OrderSide.SELL
        assert sl_order.trigger_price == params["stop_loss"]
        assert sl_order.quantity == params["quantity"]

    @given(params=sell_position_params())
    @settings(max_examples=25)
    def test_sl_placed_at_signal_stop_price_sell(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="SELL",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        sl_order = oms.place_order.call_args_list[0][0][0]
        assert sl_order.order_type == OrderType.SL_M
        assert sl_order.side == OrderSide.BUY
        assert sl_order.trigger_price == params["stop_loss"]
        assert sl_order.quantity == params["quantity"]

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_sl_order_id_tracked(self, params):
        pm = _make_pm()

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        assert pos.stop_order_id is not None


# ---------------------------------------------------------------------------
# Property 53: Target Order Placement
# **Validates: Requirements 12.2**
# ---------------------------------------------------------------------------

class TestProperty53TargetOrderPlacement:
    """
    For any filled position, a target limit order should be placed at the
    signal's target price.

    **Validates: Requirements 12.2**
    """

    @given(params=buy_position_params())
    @settings(max_examples=25)
    def test_target_placed_at_signal_target_buy(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        # Second OMS call is the target
        target_order = oms.place_order.call_args_list[1][0][0]
        assert target_order.order_type == OrderType.LIMIT
        assert target_order.side == OrderSide.SELL
        assert target_order.price == params["target"]
        assert target_order.quantity == params["quantity"]

    @given(params=sell_position_params())
    @settings(max_examples=25)
    def test_target_placed_at_signal_target_sell(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="SELL",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        target_order = oms.place_order.call_args_list[1][0][0]
        assert target_order.order_type == OrderType.LIMIT
        assert target_order.side == OrderSide.BUY
        assert target_order.price == params["target"]

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_target_order_id_tracked(self, params):
        pm = _make_pm()

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        assert pos.target_order_id is not None


# ---------------------------------------------------------------------------
# Property 54: Trailing Stop-Loss
# **Validates: Requirements 12.3**
# ---------------------------------------------------------------------------

class TestProperty54TrailingStopLoss:
    """
    For any profitable position, the trailing stop should move by 50% of
    profit and never move backward.

    **Validates: Requirements 12.3**
    """

    @given(
        params=buy_position_params(),
        price_increase=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_trailing_stop_moves_by_50pct_profit_buy(self, params, price_increase):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        new_price = params["entry_price"] + price_increase
        pm.update_price(pos.position_id, new_price)

        expected_stop = params["entry_price"] + 0.5 * price_increase
        # Trailing stop should be at least the expected value
        # (it could be higher if initial SL was already above)
        if expected_stop > params["stop_loss"]:
            assert pos.trailing_stop >= expected_stop - 1e-6

    @given(
        params=sell_position_params(),
        price_decrease=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_trailing_stop_moves_by_50pct_profit_sell(self, params, price_decrease):
        assume(params["entry_price"] - price_decrease > 0)

        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="SELL",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        new_price = params["entry_price"] - price_decrease
        pm.update_price(pos.position_id, new_price)

        expected_stop = params["entry_price"] - 0.5 * price_decrease
        # For SELL, trailing stop should be at most the expected value
        if expected_stop < params["stop_loss"]:
            assert pos.trailing_stop <= expected_stop + 1e-6

    @given(
        params=buy_position_params(),
        increases=st.lists(
            st.floats(min_value=0.01, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=25)
    def test_trailing_stop_never_moves_backward_buy(self, params, increases):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        prev_stop = pos.trailing_stop
        cumulative = 0.0
        for inc in increases:
            cumulative += inc
            new_price = params["entry_price"] + cumulative
            pm.update_price(pos.position_id, new_price)
            assert pos.trailing_stop >= prev_stop, (
                f"Trailing stop moved backward: {pos.trailing_stop} < {prev_stop}"
            )
            prev_stop = pos.trailing_stop

    @given(
        params=sell_position_params(),
        decreases=st.lists(
            st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=25)
    def test_trailing_stop_never_moves_backward_sell(self, params, decreases):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="SELL",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        prev_stop = pos.trailing_stop
        cumulative = 0.0
        for dec in decreases:
            cumulative += dec
            new_price = params["entry_price"] - cumulative
            assume(new_price > 0)
            pm.update_price(pos.position_id, new_price)
            assert pos.trailing_stop <= prev_stop, (
                f"Trailing stop moved backward (up): {pos.trailing_stop} > {prev_stop}"
            )
            prev_stop = pos.trailing_stop


# ---------------------------------------------------------------------------
# Property 55: Position Closing on Stop/Target Hit
# **Validates: Requirements 12.4**
# ---------------------------------------------------------------------------

class TestProperty55PositionClosing:
    """
    For any position where stop or target is hit, the position should be
    marked CLOSED with correct realized P&L.

    **Validates: Requirements 12.4**
    """

    @given(
        params=buy_position_params(),
        exit_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_buy_position_pnl_on_stop_hit(self, params, exit_price):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        closed = pm.on_stop_hit(pos.stop_order_id, exit_price)

        assert closed is not None
        assert closed.status == "CLOSED"
        expected_pnl = (exit_price - params["entry_price"]) * params["quantity"]
        assert closed.realized_pnl == pytest.approx(expected_pnl, abs=1e-4)

    @given(
        params=sell_position_params(),
        exit_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_sell_position_pnl_on_stop_hit(self, params, exit_price):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="SELL",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        closed = pm.on_stop_hit(pos.stop_order_id, exit_price)

        assert closed is not None
        assert closed.status == "CLOSED"
        expected_pnl = (params["entry_price"] - exit_price) * params["quantity"]
        assert closed.realized_pnl == pytest.approx(expected_pnl, abs=1e-4)

    @given(
        params=buy_position_params(),
        exit_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_buy_position_pnl_on_target_hit(self, params, exit_price):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side="BUY",
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        closed = pm.on_target_hit(pos.target_order_id, exit_price)

        assert closed is not None
        assert closed.status == "CLOSED"
        expected_pnl = (exit_price - params["entry_price"]) * params["quantity"]
        assert closed.realized_pnl == pytest.approx(expected_pnl, abs=1e-4)

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_closed_position_has_exit_time(self, params):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        closed = pm.on_stop_hit(pos.stop_order_id, params["entry_price"])
        assert closed is not None
        assert closed.exit_time is not None


# ---------------------------------------------------------------------------
# Property 56: OCO Order Cancellation
# **Validates: Requirements 12.5**
# ---------------------------------------------------------------------------

class TestProperty56OCOOrderCancellation:
    """
    For any position where one exit order (stop or target) is filled,
    the other should be cancelled.

    **Validates: Requirements 12.5**
    """

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_target_cancelled_when_stop_fills(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        target_order_id = pos.target_order_id
        pm.on_stop_hit(pos.stop_order_id, params["stop_loss"])

        cancel_calls = [c[0][0] for c in oms.cancel_order.call_args_list]
        assert target_order_id in cancel_calls, (
            f"Target order {target_order_id} was not cancelled after stop hit"
        )

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_stop_cancelled_when_target_fills(self, params):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        stop_order_id = pos.stop_order_id
        pm.on_target_hit(pos.target_order_id, params["target"])

        cancel_calls = [c[0][0] for c in oms.cancel_order.call_args_list]
        assert stop_order_id in cancel_calls, (
            f"Stop order {stop_order_id} was not cancelled after target hit"
        )

    @given(params=any_position_params())
    @settings(max_examples=25)
    def test_position_closed_after_oco(self, params):
        pm = _make_pm()

        pos = pm.on_fill(
            signal_id="prop-sig",
            symbol=params["symbol"],
            side=params["side"],
            entry_price=params["entry_price"],
            quantity=params["quantity"],
            stop_loss=params["stop_loss"],
            target=params["target"],
            strategy=params["strategy"],
        )

        pm.on_stop_hit(pos.stop_order_id, params["stop_loss"])
        assert pos.status == "CLOSED"

        # Second close attempt should return None (already closed)
        result = pm.on_target_hit(pos.target_order_id, params["target"])
        assert result is None
