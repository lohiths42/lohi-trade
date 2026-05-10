"""Unit tests for the Order Management System (OMS).

Covers:
- Order placement with MIS product type enforcement
- Order storage in SQLite
- Order cancellation
- Fill monitoring and event publishing
- Retry logic on broker rejection
- Order timeout cancellation
- Square-off all positions
- Error handling

Requirements: 11.1, 11.2, 11.4
"""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.execution.oms import OrderManagementSystem, OrderResult
from src.ingestion.broker_interface import (
    Order,
    OrderRejectionError,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_in_memory_db() -> MagicMock:
    """Create a MagicMock db_manager backed by an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            trade_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL,
            trigger_price REAL,
            status TEXT NOT NULL,
            broker_order_id TEXT,
            filled_qty INTEGER DEFAULT 0,
            filled_price REAL,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    db_manager = MagicMock()
    db_manager.connect_sqlite.return_value = conn
    db_manager._conn = conn  # expose for assertions
    return db_manager


def _make_order(
    order_id: str = "test-order-001",
    symbol: str = "RELIANCE",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: int = 10,
    price: float = None,
    trigger_price: float = None,
    product_type: ProductType = ProductType.CNC,  # should be overridden to MIS
) -> Order:
    return Order(
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        product_type=product_type,
        status=OrderStatus.PENDING,
        price=price,
        trigger_price=trigger_price,
        timestamp=datetime(2024, 1, 15, 10, 30),
    )


def _make_oms(
    broker: MagicMock = None,
    db_manager: MagicMock = None,
    now: datetime = datetime(2024, 1, 15, 10, 30),
) -> OrderManagementSystem:
    config = MagicMock()
    broker = broker or MagicMock()
    db_manager = db_manager or _make_in_memory_db()
    event_bus = MagicMock()
    redis_client = MagicMock()

    oms = OrderManagementSystem(
        config=config,
        broker=broker,
        db_manager=db_manager,
        event_bus=event_bus,
        redis_client=redis_client,
        now_fn=lambda: now,
    )
    return oms


def _get_order_row(db_manager: MagicMock, order_id: str) -> sqlite3.Row:
    """Fetch an order row from the in-memory SQLite."""
    conn = db_manager.connect_sqlite()
    return conn.execute(
        "SELECT * FROM orders WHERE order_id=?", (order_id,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Tests: Order placement with MIS product type
# ---------------------------------------------------------------------------


class TestOrderPlacementMIS:
    """Verify that all orders are placed with MIS product type."""

    def test_product_type_forced_to_mis(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-001"
        oms = _make_oms(broker=broker)

        order = _make_order(product_type=ProductType.CNC)
        result = oms.place_order(order)

        assert result.success is True
        # The order passed to broker should have MIS
        placed_order = broker.place_order.call_args[0][0]
        assert placed_order.product_type == ProductType.MIS

    def test_product_type_mis_when_already_mis(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-002"
        oms = _make_oms(broker=broker)

        order = _make_order(product_type=ProductType.MIS)
        result = oms.place_order(order)

        assert result.success is True
        placed_order = broker.place_order.call_args[0][0]
        assert placed_order.product_type == ProductType.MIS

    def test_product_type_nrml_overridden_to_mis(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-003"
        oms = _make_oms(broker=broker)

        order = _make_order(product_type=ProductType.NRML)
        result = oms.place_order(order)

        assert result.success is True
        placed_order = broker.place_order.call_args[0][0]
        assert placed_order.product_type == ProductType.MIS


# ---------------------------------------------------------------------------
# Tests: Order storage in SQLite
# ---------------------------------------------------------------------------


class TestOrderStorage:
    """Verify orders are persisted to the SQLite orders table."""

    def test_order_stored_on_placement(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-100"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="store-001")
        oms.place_order(order)

        row = _get_order_row(db, "store-001")
        assert row is not None
        assert row["symbol"] == "RELIANCE"
        assert row["side"] == "BUY"
        assert row["order_type"] == "MARKET"
        assert row["quantity"] == 10
        assert row["status"] == "PLACED"
        assert row["broker_order_id"] == "BROKER-100"

    def test_order_stored_on_rejection(self):
        broker = MagicMock()
        broker.place_order.side_effect = OrderRejectionError("Insufficient margin")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="store-002")
        result = oms.place_order(order)

        assert result.success is False
        row = _get_order_row(db, "store-002")
        assert row is not None
        assert row["status"] == "REJECTED"
        assert "Insufficient margin" in row["rejection_reason"]

    def test_order_fields_persisted_correctly(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-200"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(
            order_id="store-003",
            symbol="TCS",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=50,
            price=3500.0,
            trigger_price=3480.0,
        )
        oms.place_order(order)

        row = _get_order_row(db, "store-003")
        assert row["symbol"] == "TCS"
        assert row["side"] == "SELL"
        assert row["order_type"] == "LIMIT"
        assert row["quantity"] == 50
        assert row["price"] == 3500.0
        assert row["trigger_price"] == 3480.0


# ---------------------------------------------------------------------------
# Tests: Order cancellation
# ---------------------------------------------------------------------------


class TestOrderCancellation:
    """Verify order cancellation via broker API and SQLite update."""

    def test_cancel_pending_order(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-300"
        broker.cancel_order.return_value = True
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="cancel-001")
        oms.place_order(order)

        success = oms.cancel_order("cancel-001")
        assert success is True

        row = _get_order_row(db, "cancel-001")
        assert row["status"] == "CANCELLED"

    def test_cancel_unknown_order(self):
        oms = _make_oms()
        success = oms.cancel_order("nonexistent-order")
        assert success is False

    def test_cancel_order_without_broker_id(self):
        """Order that was never placed with broker can still be cancelled."""
        broker = MagicMock()
        broker.place_order.side_effect = OrderRejectionError("fail")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        # Place order that gets rejected (no broker_order_id)
        order = _make_order(order_id="cancel-002")
        oms.place_order(order)

        # Manually insert a pending order without broker_order_id for cancel test
        conn = db.connect_sqlite()
        conn.execute(
            "INSERT INTO orders (order_id, symbol, side, order_type, quantity, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("cancel-003", "INFY", "BUY", "MARKET", 5, "PENDING"),
        )
        conn.commit()

        # Cancel via DB lookup (no broker_order_id)
        success = oms.cancel_order("cancel-003")
        assert success is True

        row = _get_order_row(db, "cancel-003")
        assert row["status"] == "CANCELLED"

    def test_cancel_broker_failure(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-400"
        broker.cancel_order.side_effect = Exception("Network error")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="cancel-004")
        oms.place_order(order)

        success = oms.cancel_order("cancel-004")
        assert success is False


# ---------------------------------------------------------------------------
# Tests: Fill monitoring
# ---------------------------------------------------------------------------


class TestFillMonitoring:
    """Verify fill monitoring polls orders and publishes events."""

    def test_filled_order_publishes_event(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-500"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="fill-001")
        oms.place_order(order)

        # Simulate broker returning FILLED status
        filled_order = MagicMock()
        filled_order.status = OrderStatus.FILLED
        filled_order.filled_qty = 10
        filled_order.filled_price = 2505.0
        broker.get_order_status.return_value = filled_order

        changed = oms.monitor_fills()

        assert len(changed) == 1
        assert changed[0].status == OrderStatus.FILLED

        # Verify fill event was published
        oms._event_bus.publish.assert_called_once()
        call_args = oms._event_bus.publish.call_args
        assert call_args[0][0] == "stream:fills"
        assert call_args[0][1]["order_id"] == "fill-001"
        assert call_args[0][1]["symbol"] == "RELIANCE"

    def test_filled_order_removed_from_pending(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-501"
        oms = _make_oms(broker=broker)

        order = _make_order(order_id="fill-002")
        oms.place_order(order)
        assert "fill-002" in oms._pending_orders

        filled_order = MagicMock()
        filled_order.status = OrderStatus.FILLED
        filled_order.filled_qty = 10
        filled_order.filled_price = 2500.0
        broker.get_order_status.return_value = filled_order

        oms.monitor_fills()
        assert "fill-002" not in oms._pending_orders

    def test_no_change_when_status_unchanged(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-502"
        now = datetime(2024, 1, 15, 10, 30)
        oms = _make_oms(broker=broker, now=now)

        order = _make_order(order_id="fill-003")
        oms.place_order(order)

        # Broker returns same PLACED status
        placed_order = MagicMock()
        placed_order.status = OrderStatus.PLACED
        broker.get_order_status.return_value = placed_order

        changed = oms.monitor_fills()
        assert len(changed) == 0

    def test_fill_monitoring_updates_sqlite(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-503"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        order = _make_order(order_id="fill-004")
        oms.place_order(order)

        filled_order = MagicMock()
        filled_order.status = OrderStatus.FILLED
        filled_order.filled_qty = 10
        filled_order.filled_price = 2510.0
        broker.get_order_status.return_value = filled_order

        oms.monitor_fills()

        row = _get_order_row(db, "fill-004")
        assert row["status"] == "FILLED"
        assert row["filled_qty"] == 10
        assert row["filled_price"] == 2510.0

    def test_rejected_order_removed_from_pending(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-504"
        oms = _make_oms(broker=broker)

        order = _make_order(order_id="fill-005")
        oms.place_order(order)

        rejected_order = MagicMock()
        rejected_order.status = OrderStatus.REJECTED
        rejected_order.filled_qty = 0
        rejected_order.filled_price = None
        broker.get_order_status.return_value = rejected_order

        changed = oms.monitor_fills()
        assert len(changed) == 1
        assert "fill-005" not in oms._pending_orders


# ---------------------------------------------------------------------------
# Tests: Order timeout
# ---------------------------------------------------------------------------


class TestOrderTimeout:
    """Verify orders are cancelled after timeout."""

    def test_order_cancelled_after_timeout(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-600"
        broker.cancel_order.return_value = True
        db = _make_in_memory_db()

        order_time = datetime(2024, 1, 15, 10, 30)
        # OMS now_fn returns time 61 seconds after order placement
        after_timeout = order_time + timedelta(seconds=61)
        oms = _make_oms(broker=broker, db_manager=db, now=after_timeout)

        order = _make_order(order_id="timeout-001")
        order.timestamp = order_time
        oms.place_order(order)
        # Reset the order timestamp to the original time (place_order may override)
        oms._pending_orders["timeout-001"].timestamp = order_time

        # Broker still returns PLACED
        placed_order = MagicMock()
        placed_order.status = OrderStatus.PLACED
        broker.get_order_status.return_value = placed_order

        changed = oms.monitor_fills()

        assert len(changed) == 1
        assert changed[0].status == OrderStatus.CANCELLED

        row = _get_order_row(db, "timeout-001")
        assert row["status"] == "CANCELLED"
        assert row["rejection_reason"] == "Order timeout"


# ---------------------------------------------------------------------------
# Tests: Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Verify order placement retries on broker rejection."""

    def test_retry_on_rejection_then_success(self):
        broker = MagicMock()
        broker.place_order.side_effect = [
            OrderRejectionError("Temporary error"),
            "BROKER-700",
        ]
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)
        # Speed up retries for testing
        oms.RETRY_DELAY_S = 0.0

        order = _make_order(order_id="retry-001")
        result = oms.place_order(order)

        assert result.success is True
        assert result.broker_order_id == "BROKER-700"
        assert broker.place_order.call_count == 2

    def test_all_retries_exhausted(self):
        broker = MagicMock()
        broker.place_order.side_effect = OrderRejectionError("Persistent error")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)
        oms.RETRY_DELAY_S = 0.0

        order = _make_order(order_id="retry-002")
        result = oms.place_order(order)

        assert result.success is False
        assert "Persistent error" in result.error_message
        # 1 initial + 2 retries = 3 total
        assert broker.place_order.call_count == 3

        row = _get_order_row(db, "retry-002")
        assert row["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify graceful error handling in various scenarios."""

    def test_broker_exception_during_placement(self):
        broker = MagicMock()
        broker.place_order.side_effect = Exception("Connection lost")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)
        oms.RETRY_DELAY_S = 0.0

        order = _make_order(order_id="err-001")
        result = oms.place_order(order)

        assert result.success is False
        assert "Connection lost" in result.error_message

    def test_broker_error_during_fill_monitoring(self):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-800"
        broker.get_order_status.side_effect = Exception("API timeout")
        oms = _make_oms(broker=broker)

        order = _make_order(order_id="err-002")
        oms.place_order(order)

        # Should not raise, just log the error
        changed = oms.monitor_fills()
        assert len(changed) == 0

    def test_get_order_status_unknown_order(self):
        oms = _make_oms()
        status = oms.get_order_status("nonexistent")
        assert status is None

    def test_square_off_with_no_positions(self):
        broker = MagicMock()
        broker.get_positions.return_value = []
        oms = _make_oms(broker=broker)

        results = oms.square_off_all_positions()
        assert len(results) == 0

    def test_square_off_broker_error(self):
        broker = MagicMock()
        broker.get_positions.side_effect = Exception("Cannot fetch positions")
        oms = _make_oms(broker=broker)

        results = oms.square_off_all_positions()
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests: Square-off
# ---------------------------------------------------------------------------


class TestSquareOff:
    """Verify square-off places opposing market orders."""

    def test_square_off_buy_position(self):
        broker = MagicMock()
        broker.get_positions.return_value = [
            {"symbol": "RELIANCE", "quantity": 10, "side": "BUY"},
        ]
        broker.place_order.return_value = "BROKER-900"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        results = oms.square_off_all_positions()

        assert len(results) == 1
        assert results[0].success is True

        # Verify the order was a SELL MARKET MIS
        placed_order = broker.place_order.call_args[0][0]
        assert placed_order.side == OrderSide.SELL
        assert placed_order.order_type == OrderType.MARKET
        assert placed_order.product_type == ProductType.MIS
        assert placed_order.quantity == 10

    def test_square_off_sell_position(self):
        broker = MagicMock()
        broker.get_positions.return_value = [
            {"symbol": "TCS", "quantity": 20, "side": "SELL"},
        ]
        broker.place_order.return_value = "BROKER-901"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        results = oms.square_off_all_positions()

        assert len(results) == 1
        placed_order = broker.place_order.call_args[0][0]
        assert placed_order.side == OrderSide.BUY

    def test_square_off_multiple_positions(self):
        broker = MagicMock()
        broker.get_positions.return_value = [
            {"symbol": "RELIANCE", "quantity": 10, "side": "BUY"},
            {"symbol": "TCS", "quantity": 5, "side": "SELL"},
        ]
        broker.place_order.return_value = "BROKER-902"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        results = oms.square_off_all_positions()
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Tests: OrderResult dataclass
# ---------------------------------------------------------------------------


class TestOrderResult:
    """Verify OrderResult fields."""

    def test_successful_result(self):
        result = OrderResult(
            success=True,
            order_id="r-001",
            broker_order_id="B-001",
        )
        assert result.success is True
        assert result.error_message is None

    def test_failed_result(self):
        result = OrderResult(
            success=False,
            order_id="r-002",
            error_message="Rejected",
        )
        assert result.success is False
        assert result.broker_order_id is None
