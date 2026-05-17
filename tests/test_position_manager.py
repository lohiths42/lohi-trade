"""Unit tests for the Position Manager.

Covers:
- Stop-loss order placement after fill (BUY and SELL)
- Target order placement after fill (BUY and SELL)
- Trailing stop-loss updates (moves up for BUY, down for SELL)
- Trailing stop never moves backward
- Position closing on stop hit (correct P&L)
- Position closing on target hit (correct P&L)
- OCO cancellation
- Forced square-off at 3:15 PM
- Position persistence in SQLite trades table
- Event publishing on position close

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.execution.oms import OrderResult
from src.execution.position_manager import PositionManager
from src.ingestion.broker_interface import (
    OrderSide,
    OrderType,
    ProductType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trades_db() -> MagicMock:
    """Create a MagicMock db_manager backed by an in-memory SQLite with trades table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
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
    """
    )
    conn.commit()
    db = MagicMock()
    db.connect_sqlite.return_value = conn
    db._conn = conn
    return db


def _make_oms() -> MagicMock:
    """Create a mock OMS that returns successful order results."""
    oms = MagicMock()
    oms.place_order.return_value = OrderResult(
        success=True,
        order_id="mock-order",
        broker_order_id="BROKER-1",
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

    pm = PositionManager(
        config=config,
        oms=oms,
        db_manager=db,
        event_bus=event_bus,
        redis_client=redis_client,
        now_fn=lambda: now,
    )
    return pm


def _get_trade_row(db: MagicMock, trade_id: str) -> sqlite3.Row:
    conn = db.connect_sqlite()
    return conn.execute(
        "SELECT * FROM trades WHERE trade_id=?",
        (trade_id,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Tests: Stop-loss placement after fill
# ---------------------------------------------------------------------------


class TestStopLossPlacement:
    """Verify stop-loss order is placed immediately after fill."""

    def test_sl_placed_for_buy_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-1",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        # OMS should have been called at least twice (SL + target)
        assert oms.place_order.call_count >= 2

        # First call should be the stop-loss
        sl_order = oms.place_order.call_args_list[0][0][0]
        assert sl_order.order_type == OrderType.SL_M
        assert sl_order.side == OrderSide.SELL  # opposite of BUY
        assert sl_order.trigger_price == 2450.0
        assert sl_order.quantity == 10
        assert sl_order.product_type == ProductType.MIS

    def test_sl_placed_for_sell_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-2",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        sl_order = oms.place_order.call_args_list[0][0][0]
        assert sl_order.order_type == OrderType.SL_M
        assert sl_order.side == OrderSide.BUY  # opposite of SELL
        assert sl_order.trigger_price == 3550.0

    def test_sl_order_id_stored_in_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-3",
            symbol="INFY",
            side="BUY",
            entry_price=1500.0,
            quantity=20,
            stop_loss=1470.0,
            target=1550.0,
            strategy="MeanReversion",
        )

        assert pos.stop_order_id is not None


# ---------------------------------------------------------------------------
# Tests: Target order placement after fill
# ---------------------------------------------------------------------------


class TestTargetPlacement:
    """Verify target limit order is placed after fill."""

    def test_target_placed_for_buy_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-4",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        # Second call should be the target
        target_order = oms.place_order.call_args_list[1][0][0]
        assert target_order.order_type == OrderType.LIMIT
        assert target_order.side == OrderSide.SELL  # opposite of BUY
        assert target_order.price == 2600.0
        assert target_order.quantity == 10

    def test_target_placed_for_sell_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-5",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        target_order = oms.place_order.call_args_list[1][0][0]
        assert target_order.order_type == OrderType.LIMIT
        assert target_order.side == OrderSide.BUY  # opposite of SELL
        assert target_order.price == 3400.0

    def test_target_order_id_stored_in_position(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)

        pos = pm.on_fill(
            signal_id="sig-6",
            symbol="INFY",
            side="BUY",
            entry_price=1500.0,
            quantity=20,
            stop_loss=1470.0,
            target=1550.0,
            strategy="MeanReversion",
        )

        assert pos.target_order_id is not None


# ---------------------------------------------------------------------------
# Tests: Trailing stop-loss
# ---------------------------------------------------------------------------


class TestTrailingStop:
    """Verify trailing stop moves correctly and never moves backward."""

    def test_trailing_stop_moves_up_for_buy(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-7",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        # Price moves up to 2560 -> new_stop = 2500 + 0.5*(2560-2500) = 2530
        pm.update_price(pos.position_id, 2560.0)
        assert pos.trailing_stop == pytest.approx(2530.0)

    def test_trailing_stop_moves_down_for_sell(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-8",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        # Price moves down to 3440 -> new_stop = 3500 - 0.5*(3500-3440) = 3470
        pm.update_price(pos.position_id, 3440.0)
        assert pos.trailing_stop == pytest.approx(3470.0)

    def test_trailing_stop_never_moves_backward_buy(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-9",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        # Move price up
        pm.update_price(pos.position_id, 2560.0)
        high_stop = pos.trailing_stop  # 2530

        # Move price back down (but still above entry)
        pm.update_price(pos.position_id, 2520.0)
        # new_stop would be 2500 + 0.5*(2520-2500) = 2510, which is < 2530
        assert pos.trailing_stop == high_stop  # should not move backward

    def test_trailing_stop_never_moves_backward_sell(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-10",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        # Move price down
        pm.update_price(pos.position_id, 3440.0)
        low_stop = pos.trailing_stop  # 3470

        # Move price back up (but still below entry)
        pm.update_price(pos.position_id, 3480.0)
        # new_stop would be 3500 - 0.5*(3500-3480) = 3490, which is > 3470
        assert pos.trailing_stop == low_stop  # should not move backward (up)

    def test_trailing_stop_no_change_when_price_unfavourable_buy(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-11",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        original_stop = pos.trailing_stop
        # Price drops below entry
        pm.update_price(pos.position_id, 2480.0)
        assert pos.trailing_stop == original_stop

    def test_trailing_stop_replaces_sl_order(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)
        pos = pm.on_fill(
            signal_id="sig-12",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        initial_call_count = oms.place_order.call_count
        initial_cancel_count = oms.cancel_order.call_count

        # Price moves up -> trailing stop should update
        pm.update_price(pos.position_id, 2560.0)

        # Should have cancelled old SL and placed new one
        assert oms.cancel_order.call_count > initial_cancel_count
        assert oms.place_order.call_count > initial_call_count


# ---------------------------------------------------------------------------
# Tests: Position closing on stop hit
# ---------------------------------------------------------------------------


class TestPositionClosingOnStopHit:
    """Verify position closes correctly when stop-loss is hit."""

    def test_buy_position_closed_on_stop_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-13",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        closed = pm.on_stop_hit(pos.stop_order_id, 2450.0)

        assert closed is not None
        assert closed.status == "CLOSED"
        assert closed.exit_price == 2450.0
        # P&L = (2450 - 2500) * 10 = -500
        assert closed.realized_pnl == pytest.approx(-500.0)

    def test_sell_position_closed_on_stop_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-14",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        closed = pm.on_stop_hit(pos.stop_order_id, 3550.0)

        assert closed is not None
        assert closed.status == "CLOSED"
        # P&L = (3500 - 3550) * 5 = -250
        assert closed.realized_pnl == pytest.approx(-250.0)

    def test_stop_hit_unknown_order_returns_none(self):
        pm = _make_pm()
        result = pm.on_stop_hit("unknown-order", 100.0)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: Position closing on target hit
# ---------------------------------------------------------------------------


class TestPositionClosingOnTargetHit:
    """Verify position closes correctly when target is hit."""

    def test_buy_position_closed_on_target_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-15",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        closed = pm.on_target_hit(pos.target_order_id, 2600.0)

        assert closed is not None
        assert closed.status == "CLOSED"
        assert closed.exit_price == 2600.0
        # P&L = (2600 - 2500) * 10 = 1000
        assert closed.realized_pnl == pytest.approx(1000.0)

    def test_sell_position_closed_on_target_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-16",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        closed = pm.on_target_hit(pos.target_order_id, 3400.0)

        assert closed is not None
        assert closed.status == "CLOSED"
        # P&L = (3500 - 3400) * 5 = 500
        assert closed.realized_pnl == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Tests: OCO cancellation
# ---------------------------------------------------------------------------


class TestOCOCancellation:
    """Verify OCO: when one exit order fills, the other is cancelled."""

    def test_target_cancelled_when_stop_hits(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)
        pos = pm.on_fill(
            signal_id="sig-17",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        target_order_id = pos.target_order_id
        pm.on_stop_hit(pos.stop_order_id, 2450.0)

        # Verify target order was cancelled
        cancel_calls = [c[0][0] for c in oms.cancel_order.call_args_list]
        assert target_order_id in cancel_calls

    def test_stop_cancelled_when_target_hits(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)
        pos = pm.on_fill(
            signal_id="sig-18",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        stop_order_id = pos.stop_order_id
        pm.on_target_hit(pos.target_order_id, 2600.0)

        cancel_calls = [c[0][0] for c in oms.cancel_order.call_args_list]
        assert stop_order_id in cancel_calls


# ---------------------------------------------------------------------------
# Tests: Forced square-off at 3:15 PM
# ---------------------------------------------------------------------------


class TestForcedSquareOff:
    """Verify forced square-off closes all open positions."""

    def test_square_off_closes_all_positions(self):
        pm = _make_pm()
        pos1 = pm.on_fill(
            signal_id="sig-19",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )
        pos2 = pm.on_fill(
            signal_id="sig-20",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        squared = pm.force_square_off()

        assert len(squared) == 2
        assert all(p.status == "CLOSED" for p in squared)

    def test_square_off_cancels_pending_orders(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)
        pos = pm.on_fill(
            signal_id="sig-21",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        stop_id = pos.stop_order_id
        target_id = pos.target_order_id

        pm.force_square_off()

        cancel_calls = [c[0][0] for c in oms.cancel_order.call_args_list]
        assert stop_id in cancel_calls
        assert target_id in cancel_calls

    def test_square_off_places_market_close_orders(self):
        oms = _make_oms()
        pm = _make_pm(oms=oms)
        pm.on_fill(
            signal_id="sig-22",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        initial_place_count = oms.place_order.call_count
        pm.force_square_off()

        # Should have placed one more market order for the close
        assert oms.place_order.call_count > initial_place_count
        # Last placed order should be a MARKET SELL
        last_order = oms.place_order.call_args_list[-1][0][0]
        assert last_order.order_type == OrderType.MARKET
        assert last_order.side == OrderSide.SELL

    def test_check_square_off_time_triggers_at_315pm(self):
        now = datetime(2024, 1, 15, 15, 15)
        pm = _make_pm(now=now)
        pm.on_fill(
            signal_id="sig-23",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        triggered = pm.check_square_off_time()
        assert triggered is True
        assert all(p.status == "CLOSED" for p in pm._positions.values())

    def test_check_square_off_time_no_trigger_before_315pm(self):
        now = datetime(2024, 1, 15, 14, 30)
        pm = _make_pm(now=now)
        pm.on_fill(
            signal_id="sig-24",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        triggered = pm.check_square_off_time()
        assert triggered is False


# ---------------------------------------------------------------------------
# Tests: Position persistence in SQLite
# ---------------------------------------------------------------------------


class TestPositionPersistence:
    """Verify positions are stored and updated in the trades table."""

    def test_position_stored_on_fill(self):
        db = _make_trades_db()
        pm = _make_pm(db=db)

        pos = pm.on_fill(
            signal_id="sig-25",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        row = _get_trade_row(db, pos.position_id)
        assert row is not None
        assert row["symbol"] == "RELIANCE"
        assert row["side"] == "BUY"
        assert row["entry_price"] == 2500.0
        assert row["quantity"] == 10
        assert row["stop_loss"] == 2450.0
        assert row["target"] == 2600.0
        assert row["strategy"] == "MeanReversion"

    def test_position_updated_on_close(self):
        db = _make_trades_db()
        pm = _make_pm(db=db)

        pos = pm.on_fill(
            signal_id="sig-26",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.on_target_hit(pos.target_order_id, 2600.0)

        row = _get_trade_row(db, pos.position_id)
        assert row["exit_price"] == 2600.0
        assert row["realized_pnl"] == pytest.approx(1000.0)
        assert row["exit_reason"] == "TARGET"
        assert row["exit_time"] is not None


# ---------------------------------------------------------------------------
# Tests: Event publishing on position close
# ---------------------------------------------------------------------------


class TestEventPublishing:
    """Verify events are published when positions close."""

    def test_close_event_published_on_stop_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-27",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.on_stop_hit(pos.stop_order_id, 2450.0)

        pm._event_bus.publish.assert_called_once()
        call_args = pm._event_bus.publish.call_args
        assert call_args[0][0] == "stream:position_closed"
        payload = call_args[0][1]
        assert payload["position_id"] == pos.position_id
        assert payload["exit_reason"] == "STOP_LOSS"
        assert float(payload["realized_pnl"]) == pytest.approx(-500.0)

    def test_close_event_published_on_target_hit(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-28",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.on_target_hit(pos.target_order_id, 2600.0)

        pm._event_bus.publish.assert_called_once()
        call_args = pm._event_bus.publish.call_args
        assert call_args[0][0] == "stream:position_closed"
        payload = call_args[0][1]
        assert payload["exit_reason"] == "TARGET"

    def test_close_event_contains_required_fields(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-29",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.on_target_hit(pos.target_order_id, 2600.0)

        payload = pm._event_bus.publish.call_args[0][1]
        required_fields = [
            "position_id",
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "quantity",
            "realized_pnl",
            "exit_reason",
            "strategy",
            "timestamp",
        ]
        for field in required_fields:
            assert field in payload, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Verify edge case handling."""

    def test_update_price_on_closed_position_is_noop(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-30",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.on_stop_hit(pos.stop_order_id, 2450.0)
        old_trailing = pos.trailing_stop

        pm.update_price(pos.position_id, 2700.0)
        assert pos.trailing_stop == old_trailing  # no change

    def test_get_open_positions(self):
        pm = _make_pm()
        pos1 = pm.on_fill(
            signal_id="sig-31",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )
        pos2 = pm.on_fill(
            signal_id="sig-32",
            symbol="TCS",
            side="SELL",
            entry_price=3500.0,
            quantity=5,
            stop_loss=3550.0,
            target=3400.0,
            strategy="TrendFollowing",
        )

        # Close one
        pm.on_stop_hit(pos1.stop_order_id, 2450.0)

        open_positions = pm.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].position_id == pos2.position_id

    def test_unrealized_pnl_updated_on_price_change(self):
        pm = _make_pm()
        pos = pm.on_fill(
            signal_id="sig-33",
            symbol="RELIANCE",
            side="BUY",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2450.0,
            target=2600.0,
            strategy="MeanReversion",
        )

        pm.update_price(pos.position_id, 2550.0)
        # unrealized = (2550 - 2500) * 10 = 500
        assert pos.unrealized_pnl == pytest.approx(500.0)

    def test_square_off_no_open_positions(self):
        pm = _make_pm()
        squared = pm.force_square_off()
        assert len(squared) == 0
