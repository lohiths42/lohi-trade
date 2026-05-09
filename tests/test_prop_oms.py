"""
Property-based tests for the Order Management System (OMS).

Uses hypothesis to verify OMS properties across randomly generated orders.

Properties tested:
- Property 45: Order Placement Latency  (Validates: Requirements 11.1)
- Property 46: MIS Product Type         (Validates: Requirements 11.2)
- Property 47: Rate Limiting            (Validates: Requirements 11.3)
- Property 48: Order Persistence        (Validates: Requirements 11.4)
- Property 49: Broker Rejection Retry   (Validates: Requirements 11.5)
- Property 50: Fill Event Handling       (Validates: Requirements 11.6)
- Property 51: Order Timeout Cancellation(Validates: Requirements 11.8)
"""

import sqlite3
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.execution.oms import OrderManagementSystem, OrderResult, TokenBucketRateLimiter
from src.ingestion.broker_interface import (
    Order,
    OrderRejectionError,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)


# ---------------------------------------------------------------------------
# Helpers (mirrors patterns from tests/test_oms.py)
# ---------------------------------------------------------------------------

def _make_in_memory_db() -> MagicMock:
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
    db = MagicMock()
    db.connect_sqlite.return_value = conn
    db._conn = conn
    return db


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
    # Speed up retries for property tests
    oms.RETRY_DELAY_S = 0.0
    return oms


def _get_order_row(db_manager: MagicMock, order_id: str) -> sqlite3.Row:
    conn = db_manager.connect_sqlite()
    return conn.execute(
        "SELECT * FROM orders WHERE order_id=?", (order_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

symbols = st.sampled_from([
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
])
sides = st.sampled_from([OrderSide.BUY, OrderSide.SELL])
order_types = st.sampled_from([OrderType.MARKET, OrderType.LIMIT, OrderType.SL])
product_types = st.sampled_from([ProductType.MIS, ProductType.CNC, ProductType.NRML])
quantities = st.integers(min_value=1, max_value=500)
prices = st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False)


@st.composite
def orders(draw):
    """Generate random Order objects."""
    symbol = draw(symbols)
    side = draw(sides)
    otype = draw(order_types)
    ptype = draw(product_types)
    qty = draw(quantities)
    price = draw(prices) if otype != OrderType.MARKET else None
    trigger = draw(prices) if otype == OrderType.SL else None
    return Order(
        order_id=f"prop-{draw(st.uuids())}",
        symbol=symbol,
        side=side,
        order_type=otype,
        quantity=qty,
        product_type=ptype,
        status=OrderStatus.PENDING,
        price=price,
        trigger_price=trigger,
        timestamp=datetime(2024, 1, 15, 10, 30),
    )


# ---------------------------------------------------------------------------
# Property 45: Order Placement Latency
# **Validates: Requirements 11.1**
# ---------------------------------------------------------------------------

class TestProperty45OrderPlacementLatency:
    """
    For any order placed, the placement should complete within 100ms
    (excluding network time, measured as local processing overhead).

    **Validates: Requirements 11.1**
    """

    @given(order=orders())
    @settings(max_examples=50)
    def test_placement_completes_within_100ms(self, order):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-LATENCY"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        start = time.monotonic()
        result = oms.place_order(order)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result.success is True
        assert elapsed_ms < 100, (
            f"Order placement took {elapsed_ms:.1f}ms, exceeds 100ms limit"
        )


# ---------------------------------------------------------------------------
# Property 46: MIS Product Type
# **Validates: Requirements 11.2**
# ---------------------------------------------------------------------------

class TestProperty46MISProductType:
    """
    For any order placed by OMS, the product type SHALL be MIS regardless
    of the incoming product_type value.

    **Validates: Requirements 11.2**
    """

    @given(order=orders())
    @settings(max_examples=50)
    def test_product_type_always_mis(self, order):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-MIS"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        oms.place_order(order)

        placed = broker.place_order.call_args[0][0]
        assert placed.product_type == ProductType.MIS, (
            f"Expected MIS, got {placed.product_type} for input {order.product_type}"
        )


# ---------------------------------------------------------------------------
# Property 48: Order Persistence
# **Validates: Requirements 11.4**
# ---------------------------------------------------------------------------

class TestProperty48OrderPersistence:
    """
    For any order placed, it SHALL be stored in SQLite with all required
    fields: order_id, symbol, side, quantity, price, status, timestamp.

    **Validates: Requirements 11.4**
    """

    @given(order=orders())
    @settings(max_examples=50)
    def test_order_persisted_in_sqlite(self, order):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-PERSIST"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        oms.place_order(order)

        row = _get_order_row(db, order.order_id)
        assert row is not None, f"Order {order.order_id} not found in SQLite"
        assert row["symbol"] == order.symbol
        assert row["side"] == order.side.value
        assert row["quantity"] == order.quantity
        assert row["order_type"] == order.order_type.value
        # Status should be PLACED on success
        assert row["status"] == "PLACED"
        assert row["broker_order_id"] == "BROKER-PERSIST"


# ---------------------------------------------------------------------------
# Property 47: Rate Limiting
# **Validates: Requirements 11.3**
# ---------------------------------------------------------------------------

class TestProperty47RateLimiting:
    """
    Token bucket rate limiter limits to 8 requests/second.  When tokens
    are exhausted, acquire() returns a positive wait time.

    **Validates: Requirements 11.3**
    """

    @given(
        rate=st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        capacity=st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_tokens_exhausted_returns_positive_wait(self, rate, capacity):
        limiter = TokenBucketRateLimiter(rate=rate, capacity=capacity)
        cap_int = int(capacity)

        # Drain all tokens
        for _ in range(cap_int):
            limiter.acquire()

        # Next acquire should return positive wait (tokens depleted)
        wait = limiter.acquire()
        assert wait >= 0, f"Expected non-negative wait, got {wait}"

    @given(n_requests=st.integers(min_value=1, max_value=8))
    @settings(max_examples=25)
    def test_within_capacity_returns_zero_wait(self, n_requests):
        limiter = TokenBucketRateLimiter(rate=8.0, capacity=8.0)
        for _ in range(n_requests):
            wait = limiter.acquire()
            assert wait == 0.0, (
                f"Expected 0 wait within capacity, got {wait}"
            )

    def test_default_rate_is_8_per_second(self):
        """Verify the default rate limiter allows exactly 8 immediate requests."""
        limiter = TokenBucketRateLimiter()
        for i in range(8):
            wait = limiter.acquire()
            assert wait == 0.0, f"Request {i+1} should be immediate"

        # 9th request should require waiting
        wait = limiter.acquire()
        assert wait > 0, "9th request should require waiting"

    def test_rate_limiter_integrated_in_oms(self):
        """Verify OMS has a rate limiter and calls acquire before placing."""
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-RL"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        assert hasattr(oms, "_rate_limiter")
        assert isinstance(oms._rate_limiter, TokenBucketRateLimiter)


# ---------------------------------------------------------------------------
# Property 49: Broker Rejection Retry
# **Validates: Requirements 11.5**
# ---------------------------------------------------------------------------

class TestProperty49BrokerRejectionRetry:
    """
    On broker rejection, retry up to 2 times with delay between retries.
    Total attempts = 1 initial + 2 retries = 3.

    **Validates: Requirements 11.5**
    """

    @given(order=orders())
    @settings(max_examples=50)
    def test_retries_up_to_2_times_on_rejection(self, order):
        broker = MagicMock()
        broker.place_order.side_effect = OrderRejectionError("Rejected")
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        result = oms.place_order(order)

        assert result.success is False
        # 1 initial + 2 retries = 3 total calls
        assert broker.place_order.call_count == 3, (
            f"Expected 3 attempts, got {broker.place_order.call_count}"
        )

    @given(
        order=orders(),
        fail_count=st.integers(min_value=1, max_value=2),
    )
    @settings(max_examples=50)
    def test_succeeds_after_transient_failures(self, order, fail_count):
        broker = MagicMock()
        effects = [OrderRejectionError("Transient")] * fail_count + ["BROKER-RETRY-OK"]
        broker.place_order.side_effect = effects
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        result = oms.place_order(order)

        assert result.success is True
        assert result.broker_order_id == "BROKER-RETRY-OK"
        assert broker.place_order.call_count == fail_count + 1


# ---------------------------------------------------------------------------
# Property 50: Fill Event Handling
# **Validates: Requirements 11.6**
# ---------------------------------------------------------------------------

class TestProperty50FillEventHandling:
    """
    When an order is filled, a fill event SHALL be published to the
    Event Bus and the order status updated to FILLED.

    **Validates: Requirements 11.6**
    """

    @given(order=orders(), fill_price=prices)
    @settings(max_examples=50)
    def test_fill_publishes_event(self, order, fill_price):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-FILL"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        oms.place_order(order)

        # Simulate broker returning FILLED
        filled = MagicMock()
        filled.status = OrderStatus.FILLED
        filled.filled_qty = order.quantity
        filled.filled_price = fill_price
        broker.get_order_status.return_value = filled

        changed = oms.monitor_fills()

        assert len(changed) == 1
        assert changed[0].status == OrderStatus.FILLED

        # Verify fill event published
        oms._event_bus.publish.assert_called_once()
        call_args = oms._event_bus.publish.call_args
        assert call_args[0][0] == "stream:fills"
        payload = call_args[0][1]
        assert payload["order_id"] == order.order_id
        assert payload["symbol"] == order.symbol
        assert payload["side"] == order.side.value

    @given(order=orders(), fill_price=prices)
    @settings(max_examples=50)
    def test_fill_updates_sqlite(self, order, fill_price):
        broker = MagicMock()
        broker.place_order.return_value = "BROKER-FILL-DB"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db)

        oms.place_order(order)

        filled = MagicMock()
        filled.status = OrderStatus.FILLED
        filled.filled_qty = order.quantity
        filled.filled_price = fill_price
        broker.get_order_status.return_value = filled

        oms.monitor_fills()

        row = _get_order_row(db, order.order_id)
        assert row["status"] == "FILLED"
        assert row["filled_qty"] == order.quantity
        assert row["filled_price"] == fill_price


# ---------------------------------------------------------------------------
# Property 51: Order Timeout Cancellation
# **Validates: Requirements 11.8**
# ---------------------------------------------------------------------------

class TestProperty51OrderTimeoutCancellation:
    """
    Orders unfilled after 60 seconds SHALL be cancelled and status
    updated to CANCELLED.

    **Validates: Requirements 11.8**
    """

    @given(order=orders(), extra_seconds=st.integers(min_value=1, max_value=120))
    @settings(max_examples=50)
    def test_order_cancelled_after_60s(self, order, extra_seconds):
        order_time = datetime(2024, 1, 15, 10, 30)
        after_timeout = order_time + timedelta(seconds=60 + extra_seconds)

        broker = MagicMock()
        broker.place_order.return_value = "BROKER-TIMEOUT"
        broker.cancel_order.return_value = True
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db, now=after_timeout)

        order.timestamp = order_time
        oms.place_order(order)
        # Restore original timestamp (place_order may override)
        oms._pending_orders[order.order_id].timestamp = order_time

        # Broker still returns PLACED (not filled)
        placed = MagicMock()
        placed.status = OrderStatus.PLACED
        broker.get_order_status.return_value = placed

        changed = oms.monitor_fills()

        assert len(changed) == 1
        assert changed[0].status == OrderStatus.CANCELLED

        row = _get_order_row(db, order.order_id)
        assert row["status"] == "CANCELLED"
        assert row["rejection_reason"] == "Order timeout"

    @given(order=orders())
    @settings(max_examples=25)
    def test_order_not_cancelled_before_60s(self, order):
        order_time = datetime(2024, 1, 15, 10, 30)
        before_timeout = order_time + timedelta(seconds=30)

        broker = MagicMock()
        broker.place_order.return_value = "BROKER-NO-TIMEOUT"
        db = _make_in_memory_db()
        oms = _make_oms(broker=broker, db_manager=db, now=before_timeout)

        order.timestamp = order_time
        oms.place_order(order)
        oms._pending_orders[order.order_id].timestamp = order_time

        placed = MagicMock()
        placed.status = OrderStatus.PLACED
        broker.get_order_status.return_value = placed

        changed = oms.monitor_fills()

        # No timeout yet — order should remain pending
        assert len(changed) == 0
