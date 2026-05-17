"""Order Management System (OMS) for LOHI-TRADE.

Handles order placement via broker API, fill monitoring, and order lifecycle
management. All orders use MIS (Margin Intraday Square-off) product type
for intraday trading.

Requirements: 11.1, 11.2, 11.4, 11.5, 11.6, 11.7, 11.8
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


class TokenBucketRateLimiter:
    """Token bucket rate limiter for broker API requests.

    Limits requests to a configurable rate (default 8/second) to comply
    with broker API limits.

    Requirements: 11.3
    """

    def __init__(self, rate: float = 8.0, capacity: float = 8.0) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def acquire(self) -> float:
        """Attempt to acquire a token.

        Returns:
            Wait time in seconds.  ``0.0`` if a token was available
            immediately, otherwise the time the caller should wait
            before retrying.

        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
        if self._tokens >= 1:
            self._tokens -= 1
            return 0.0
        wait = (1 - self._tokens) / self._rate
        return wait


from src.ingestion.broker_interface import (
    BrokerInterface,
    Order,
    OrderRejectionError,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus
from src.state.redis_client import RedisClient
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger("OMS")


@dataclass
class OrderResult:
    """Result of an order placement attempt.

    Attributes:
        success: Whether the order was placed successfully.
        order_id: Internal UUID for the order.
        broker_order_id: Broker-assigned order ID (None on failure).
        error_message: Error description (None on success).

    """

    success: bool
    order_id: str
    broker_order_id: str | None = None
    error_message: str | None = None


class OrderManagementSystem:
    """Place and manage orders via broker API with SQLite persistence.

    Key behaviours:
    - All orders use MIS product type (intraday).
    - Orders are stored in the SQLite ``orders`` table on placement.
    - Fill monitoring polls pending orders and publishes fill events.
    - Square-off closes all open positions at market price.
    """

    # Retry configuration
    MAX_RETRIES = 2
    RETRY_DELAY_S = 0.5

    # Fill monitoring
    POLL_INTERVAL_S = 1.0
    ORDER_TIMEOUT_S = 60.0

    def __init__(
        self,
        config: Config,
        broker: BrokerInterface,
        db_manager: DatabaseConnectionManager,
        event_bus: EventBus,
        redis_client: RedisClient,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._broker = broker
        self._db = db_manager
        self._event_bus = event_bus
        self._redis = redis_client
        self._now_fn = now_fn or datetime.now

        # Rate limiter for broker API calls (8 req/s default)
        self._rate_limiter = TokenBucketRateLimiter()

        # In-memory index of pending orders for monitoring
        self._pending_orders: dict[str, Order] = {}

        logger.info("OrderManagementSystem initialised")

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_order(self, order: Order) -> OrderResult:
        """Place an order via the broker API and persist to SQLite.

        The order's ``product_type`` is forced to MIS regardless of the
        incoming value.  On broker rejection the order is retried up to
        ``MAX_RETRIES`` times with a ``RETRY_DELAY_S`` pause between
        attempts.

        Args:
            order: The order to place.  ``product_type`` will be
                overridden to MIS.

        Returns:
            OrderResult indicating success/failure.

        """
        # Enforce MIS product type
        order.product_type = ProductType.MIS

        # Ensure we have an order_id
        if not order.order_id:
            order.order_id = str(uuid.uuid4())

        # Set timestamp
        if order.timestamp is None:
            order.timestamp = self._now_fn()

        order.status = OrderStatus.PENDING

        # Persist the order before attempting placement
        self._store_order(order)

        # Rate-limit broker API calls
        wait = self._rate_limiter.acquire()
        if wait > 0:
            time.sleep(wait)

        # Attempt placement with retries
        last_error: str | None = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                broker_order_id = self._broker.place_order(order)
                order.broker_order_id = broker_order_id
                order.status = OrderStatus.PLACED
                self._update_order_status(order)
                self._pending_orders[order.order_id] = order

                logger.info(
                    f"Order placed: {order.order_id} broker_id={broker_order_id} "
                    f"symbol={order.symbol} side={order.side.value} qty={order.quantity}",
                )

                return OrderResult(
                    success=True,
                    order_id=order.order_id,
                    broker_order_id=broker_order_id,
                )

            except (OrderRejectionError, Exception) as exc:
                last_error = str(exc)
                logger.warning(
                    f"Order placement attempt {attempt + 1} failed for "
                    f"{order.order_id}: {last_error}",
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_S)

        # All attempts exhausted
        order.status = OrderStatus.REJECTED
        order.rejection_reason = last_error
        self._update_order_status(order)

        logger.error(
            f"Order rejected after {1 + self.MAX_RETRIES} attempts: "
            f"{order.order_id} reason={last_error}",
        )

        return OrderResult(
            success=False,
            order_id=order.order_id,
            error_message=last_error,
        )

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order via the broker API.

        Args:
            order_id: Internal order UUID.

        Returns:
            True if cancellation succeeded, False otherwise.

        """
        order = self._pending_orders.get(order_id)
        if order is None:
            # Try to load from DB
            order = self._load_order(order_id)
            if order is None:
                logger.warning(f"Cannot cancel unknown order: {order_id}")
                return False

        if not order.broker_order_id:
            logger.warning(f"No broker_order_id for order {order_id}, marking cancelled")
            order.status = OrderStatus.CANCELLED
            self._update_order_status(order)
            self._pending_orders.pop(order_id, None)
            return True

        try:
            success = self._broker.cancel_order(order.broker_order_id)
            if success:
                order.status = OrderStatus.CANCELLED
                self._update_order_status(order)
                self._pending_orders.pop(order_id, None)
                logger.info(f"Order cancelled: {order_id}")
                return True
            logger.warning(f"Broker returned False for cancel of {order_id}")
            return False
        except Exception as exc:
            logger.error(f"Failed to cancel order {order_id}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Order status
    # ------------------------------------------------------------------

    def get_order_status(self, order_id: str) -> OrderStatus | None:
        """Get the current status of an order from the broker.

        Args:
            order_id: Internal order UUID.

        Returns:
            Current OrderStatus, or None if the order is unknown.

        """
        order = self._pending_orders.get(order_id)
        if order is None:
            order = self._load_order(order_id)
        if order is None:
            return None

        if order.broker_order_id:
            try:
                broker_order = self._broker.get_order_status(order.broker_order_id)
                order.status = broker_order.status
                order.filled_qty = broker_order.filled_qty
                order.filled_price = broker_order.filled_price
                self._update_order_status(order)
            except Exception as exc:
                logger.error(f"Failed to fetch status for {order_id}: {exc}")

        return order.status

    # ------------------------------------------------------------------
    # Fill monitoring
    # ------------------------------------------------------------------

    def monitor_fills(self) -> list[Order]:
        """Poll pending orders for fills and publish fill events.

        Iterates over all tracked pending orders, queries the broker for
        their current status, and:
        - Updates SQLite on any status change.
        - Publishes a fill event to the Event Bus when an order is filled.
        - Cancels orders that have been pending longer than ORDER_TIMEOUT_S.

        Returns:
            List of orders whose status changed during this poll cycle.

        """
        changed: list[Order] = []
        now = self._now_fn()

        for order_id in list(self._pending_orders.keys()):
            order = self._pending_orders[order_id]

            if not order.broker_order_id:
                continue

            try:
                broker_order = self._broker.get_order_status(order.broker_order_id)
            except Exception as exc:
                logger.error(f"Error polling order {order_id}: {exc}")
                continue

            if broker_order.status == order.status:
                # Check timeout for still-pending orders
                if (
                    order.status in (OrderStatus.PENDING, OrderStatus.PLACED)
                    and order.timestamp
                    and (now - order.timestamp).total_seconds() > self.ORDER_TIMEOUT_S
                ):
                    self._timeout_order(order)
                    changed.append(order)
                continue

            # Status changed
            order.status = broker_order.status
            order.filled_qty = broker_order.filled_qty
            order.filled_price = broker_order.filled_price
            self._update_order_status(order)
            changed.append(order)

            if broker_order.status == OrderStatus.FILLED:
                self._publish_fill_event(order)
                self._pending_orders.pop(order_id, None)
                logger.info(
                    f"Order filled: {order_id} price={order.filled_price} "
                    f"qty={order.filled_qty}",
                )
            elif broker_order.status in (
                OrderStatus.REJECTED,
                OrderStatus.CANCELLED,
            ):
                self._pending_orders.pop(order_id, None)
                logger.info(f"Order {broker_order.status.value}: {order_id}")

        return changed

    # ------------------------------------------------------------------
    # Square-off
    # ------------------------------------------------------------------

    def square_off_all_positions(self) -> list[OrderResult]:
        """Close all open positions at market price.

        Queries the broker for open positions and places opposing market
        orders to flatten each one.

        Returns:
            List of OrderResult for each square-off order placed.

        """
        results: list[OrderResult] = []

        try:
            positions = self._broker.get_positions()
        except Exception as exc:
            logger.error(f"Failed to fetch positions for square-off: {exc}")
            return results

        for pos in positions:
            symbol = pos.get("symbol", "")
            qty = int(pos.get("quantity", 0))
            side_str = pos.get("side", "BUY")

            if qty <= 0:
                continue

            # Opposite side to close
            close_side = OrderSide.SELL if side_str == "BUY" else OrderSide.BUY

            order = Order(
                order_id=str(uuid.uuid4()),
                symbol=symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=qty,
                product_type=ProductType.MIS,
                status=OrderStatus.PENDING,
                timestamp=self._now_fn(),
            )

            result = self.place_order(order)
            results.append(result)
            logger.info(
                f"Square-off order for {symbol}: side={close_side.value} "
                f"qty={qty} success={result.success}",
            )

        return results

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _store_order(self, order: Order) -> None:
        """Insert a new order row into the SQLite orders table."""
        conn = self._db.connect_sqlite()
        try:
            conn.execute(
                "INSERT INTO orders "
                "(order_id, symbol, side, order_type, quantity, price, "
                "trigger_price, status, broker_order_id, filled_qty, "
                "filled_price, rejection_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order.order_id,
                    order.symbol,
                    order.side.value,
                    order.order_type.value,
                    order.quantity,
                    order.price,
                    order.trigger_price,
                    order.status.value,
                    order.broker_order_id,
                    order.filled_qty,
                    order.filled_price,
                    order.rejection_reason,
                    order.timestamp.isoformat() if order.timestamp else None,
                    order.timestamp.isoformat() if order.timestamp else None,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.error(f"Failed to store order {order.order_id}: {exc}", exc_info=True)

    def _update_order_status(self, order: Order) -> None:
        """Update an existing order row in SQLite."""
        conn = self._db.connect_sqlite()
        try:
            conn.execute(
                "UPDATE orders SET status=?, broker_order_id=?, filled_qty=?, "
                "filled_price=?, rejection_reason=?, updated_at=? "
                "WHERE order_id=?",
                (
                    order.status.value,
                    order.broker_order_id,
                    order.filled_qty,
                    order.filled_price,
                    order.rejection_reason,
                    self._now_fn().isoformat(),
                    order.order_id,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.error(
                f"Failed to update order {order.order_id}: {exc}",
                exc_info=True,
            )

    def _load_order(self, order_id: str) -> Order | None:
        """Load an order from SQLite by its internal order_id."""
        conn = self._db.connect_sqlite()
        try:
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id=?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            return Order(
                order_id=row["order_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                order_type=OrderType(row["order_type"]),
                quantity=row["quantity"],
                product_type=ProductType.MIS,
                status=OrderStatus(row["status"]),
                price=row["price"],
                trigger_price=row["trigger_price"],
                broker_order_id=row["broker_order_id"],
                filled_qty=row["filled_qty"] or 0,
                filled_price=row["filled_price"],
                timestamp=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                rejection_reason=row["rejection_reason"],
            )
        except Exception as exc:
            logger.error(f"Failed to load order {order_id}: {exc}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _publish_fill_event(self, order: Order) -> None:
        """Publish a fill event to the Event Bus."""
        try:
            self._event_bus.publish(
                "stream:fills",
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": order.filled_qty,
                    "price": order.filled_price,
                    "broker_order_id": order.broker_order_id or "",
                    "timestamp": self._now_fn().isoformat(),
                },
                maxlen=1000,
            )
            logger.info(f"Fill event published for order {order.order_id}")
        except Exception as exc:
            logger.error(
                f"Failed to publish fill event for {order.order_id}: {exc}",
                exc_info=True,
            )

    def _timeout_order(self, order: Order) -> None:
        """Cancel an order that has exceeded the timeout threshold."""
        logger.warning(
            f"Order {order.order_id} timed out after {self.ORDER_TIMEOUT_S}s, cancelling",
        )
        if order.broker_order_id:
            try:
                self._broker.cancel_order(order.broker_order_id)
            except Exception as exc:
                logger.error(f"Failed to cancel timed-out order {order.order_id}: {exc}")

        order.status = OrderStatus.CANCELLED
        order.rejection_reason = "Order timeout"
        self._update_order_status(order)
        self._pending_orders.pop(order.order_id, None)
