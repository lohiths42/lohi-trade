"""Position Manager for LOHI-TRADE.

Manages open positions with stop-loss, target, and trailing stop orders.
Handles OCO (One-Cancels-Other) logic, position closing with P&L
calculation, and forced square-off at 3:15 PM IST.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.execution.oms import OrderManagementSystem
from src.ingestion.broker_interface import (
    Order,
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

logger = get_logger("PositionManager")

SQUARE_OFF_HOUR = 15
SQUARE_OFF_MINUTE = 15


@dataclass
class Position:
    """Represents an open or closed trading position."""

    position_id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    quantity: int
    current_price: float
    unrealized_pnl: float
    stop_loss: float
    target: float
    trailing_stop: float
    entry_time: datetime
    exit_time: datetime | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    strategy: str = ""
    status: str = "OPEN"
    stop_order_id: str | None = None
    target_order_id: str | None = None
    signal_id: str = ""


class PositionManager:
    """Manage positions with stop-loss, target, trailing stop, and OCO logic.

    Key behaviours:
    - On fill: place SL-M stop-loss and LIMIT target orders.
    - Trailing stop: move stop up by 50% of profit when price moves favourably.
    - OCO: when one exit order fills, cancel the other.
    - Position closing: calculate realized P&L, persist to SQLite, publish event.
    - Forced square-off at 3:15 PM IST.
    """

    def __init__(
        self,
        config: Config,
        oms: OrderManagementSystem,
        db_manager: DatabaseConnectionManager,
        event_bus: EventBus,
        redis_client: RedisClient,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._oms = oms
        self._db = db_manager
        self._event_bus = event_bus
        self._redis = redis_client
        self._now_fn = now_fn or datetime.now

        # In-memory position index keyed by position_id
        self._positions: dict[str, Position] = {}

        # Reverse lookup: order_id -> position_id for stop/target orders
        self._order_to_position: dict[str, str] = {}

        logger.info("PositionManager initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_fill(
        self,
        signal_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        target: float,
        strategy: str,
    ) -> Position:
        """Handle a fill event by creating a position and placing SL/target orders.

        Args:
            signal_id: ID of the originating signal.
            symbol: Trading symbol.
            side: 'BUY' or 'SELL'.
            entry_price: Fill price.
            quantity: Filled quantity.
            stop_loss: Stop-loss price from the signal.
            target: Target price from the signal.
            strategy: Strategy name.

        Returns:
            The newly created Position.

        """
        position_id = str(uuid.uuid4())
        now = self._now_fn()

        position = Position(
            position_id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            current_price=entry_price,
            unrealized_pnl=0.0,
            stop_loss=stop_loss,
            target=target,
            trailing_stop=stop_loss,
            entry_time=now,
            strategy=strategy,
            signal_id=signal_id,
        )

        self._positions[position_id] = position

        # Persist the new position
        self._store_position(position)

        # Place stop-loss order
        self._place_stop_loss(position)

        # Place target order
        self._place_target(position)

        logger.info(
            f"Position opened: {position_id} symbol={symbol} side={side} "
            f"entry={entry_price} qty={quantity} sl={stop_loss} target={target}",
        )

        return position

    def update_price(self, position_id: str, current_price: float) -> None:
        """Update current price and trailing stop for a position.

        Args:
            position_id: Position to update.
            current_price: Latest market price.

        """
        position = self._positions.get(position_id)
        if position is None or position.status != "OPEN":
            return

        position.current_price = current_price

        # Update unrealized P&L
        if position.side == "BUY":
            position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.quantity

        # Trailing stop logic
        self._update_trailing_stop(position, current_price)

    def on_stop_hit(self, order_id: str, fill_price: float) -> Position | None:
        """Handle stop-loss order fill.

        Args:
            order_id: The stop-loss order ID that was filled.
            fill_price: The fill price of the stop-loss order.

        Returns:
            The closed Position, or None if order not tracked.

        """
        position_id = self._order_to_position.get(order_id)
        if position_id is None:
            return None

        position = self._positions.get(position_id)
        if position is None or position.status != "OPEN":
            return None

        return self._close_position(position, fill_price, "STOP_LOSS")

    def on_target_hit(self, order_id: str, fill_price: float) -> Position | None:
        """Handle target order fill.

        Args:
            order_id: The target order ID that was filled.
            fill_price: The fill price of the target order.

        Returns:
            The closed Position, or None if order not tracked.

        """
        position_id = self._order_to_position.get(order_id)
        if position_id is None:
            return None

        position = self._positions.get(position_id)
        if position is None or position.status != "OPEN":
            return None

        return self._close_position(position, fill_price, "TARGET")

    def force_square_off(self) -> list[Position]:
        """Force close all open positions at market price.

        Returns:
            List of positions that were squared off.

        """
        squared_off: list[Position] = []

        for position in list(self._positions.values()):
            if position.status != "OPEN":
                continue

            # Cancel pending SL and target orders
            if position.stop_order_id:
                self._oms.cancel_order(position.stop_order_id)
            if position.target_order_id:
                self._oms.cancel_order(position.target_order_id)

            # Place market order to close
            close_side = OrderSide.SELL if position.side == "BUY" else OrderSide.BUY
            close_order = Order(
                order_id=str(uuid.uuid4()),
                symbol=position.symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
                product_type=ProductType.MIS,
                status=OrderStatus.PENDING,
                timestamp=self._now_fn(),
            )

            result = self._oms.place_order(close_order)

            # Close position at current price (market order)
            exit_price = position.current_price
            self._close_position(position, exit_price, "SQUARE_OFF")
            squared_off.append(position)

            logger.info(
                f"Forced square-off: {position.position_id} symbol={position.symbol} "
                f"side={position.side} exit_price={exit_price}",
            )

        return squared_off

    def check_square_off_time(self) -> bool:
        """Check if current time is at or past 3:15 PM IST.

        Returns:
            True if square-off was triggered.

        """
        now = self._now_fn()
        current_minutes = now.hour * 60 + now.minute
        square_off_minutes = SQUARE_OFF_HOUR * 60 + SQUARE_OFF_MINUTE

        if current_minutes >= square_off_minutes:
            open_positions = [
                p for p in self._positions.values() if p.status == "OPEN"
            ]
            if open_positions:
                logger.info(
                    f"Square-off time reached ({now.strftime('%H:%M')}), "
                    f"closing {len(open_positions)} open positions",
                )
                self.force_square_off()
                return True
        return False

    def get_position(self, position_id: str) -> Position | None:
        """Get a position by ID."""
        return self._positions.get(position_id)

    def get_open_positions(self) -> list[Position]:
        """Get all open positions."""
        return [p for p in self._positions.values() if p.status == "OPEN"]

    # ------------------------------------------------------------------
    # Stop-loss and target placement
    # ------------------------------------------------------------------

    def _place_stop_loss(self, position: Position) -> None:
        """Place a stop-loss market order for a position."""
        # For BUY positions, SL is a SELL; for SELL positions, SL is a BUY
        sl_side = OrderSide.SELL if position.side == "BUY" else OrderSide.BUY

        sl_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=sl_side,
            order_type=OrderType.SL_M,
            quantity=position.quantity,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
            trigger_price=position.trailing_stop,
            timestamp=self._now_fn(),
        )

        result = self._oms.place_order(sl_order)
        if result.success:
            position.stop_order_id = sl_order.order_id
            self._order_to_position[sl_order.order_id] = position.position_id
            logger.info(
                f"Stop-loss placed: order={sl_order.order_id} "
                f"position={position.position_id} trigger={position.trailing_stop}",
            )
        else:
            logger.error(
                f"Failed to place stop-loss for position {position.position_id}: "
                f"{result.error_message}",
            )

    def _place_target(self, position: Position) -> None:
        """Place a target limit order for a position."""
        # For BUY positions, target is a SELL limit; for SELL, target is a BUY limit
        target_side = OrderSide.SELL if position.side == "BUY" else OrderSide.BUY

        target_order = Order(
            order_id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=target_side,
            order_type=OrderType.LIMIT,
            quantity=position.quantity,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
            price=position.target,
            timestamp=self._now_fn(),
        )

        result = self._oms.place_order(target_order)
        if result.success:
            position.target_order_id = target_order.order_id
            self._order_to_position[target_order.order_id] = position.position_id
            logger.info(
                f"Target placed: order={target_order.order_id} "
                f"position={position.position_id} price={position.target}",
            )
        else:
            logger.error(
                f"Failed to place target for position {position.position_id}: "
                f"{result.error_message}",
            )

    # ------------------------------------------------------------------
    # Trailing stop
    # ------------------------------------------------------------------

    def _update_trailing_stop(self, position: Position, current_price: float) -> None:
        """Update trailing stop if price has moved favourably.

        For BUY: new_stop = entry + 0.5 * (current - entry), only if > current trailing.
        For SELL: new_stop = entry - 0.5 * (entry - current), only if < current trailing.
        """
        if position.side == "BUY":
            if current_price > position.entry_price:
                new_stop = position.entry_price + 0.5 * (current_price - position.entry_price)
                if new_stop > position.trailing_stop:
                    old_stop = position.trailing_stop
                    position.trailing_stop = new_stop
                    self._replace_stop_order(position)
                    logger.info(
                        f"Trailing stop updated (BUY): position={position.position_id} "
                        f"old={old_stop:.2f} new={new_stop:.2f}",
                    )
        elif current_price < position.entry_price:
            new_stop = position.entry_price - 0.5 * (position.entry_price - current_price)
            if new_stop < position.trailing_stop:
                old_stop = position.trailing_stop
                position.trailing_stop = new_stop
                self._replace_stop_order(position)
                logger.info(
                    f"Trailing stop updated (SELL): position={position.position_id} "
                    f"old={old_stop:.2f} new={new_stop:.2f}",
                )

    def _replace_stop_order(self, position: Position) -> None:
        """Cancel old stop order and place a new one at the updated trailing stop."""
        if position.stop_order_id:
            self._oms.cancel_order(position.stop_order_id)
            self._order_to_position.pop(position.stop_order_id, None)

        self._place_stop_loss(position)

    # ------------------------------------------------------------------
    # Position closing
    # ------------------------------------------------------------------

    def _close_position(
        self, position: Position, exit_price: float, exit_reason: str,
    ) -> Position:
        """Close a position, calculate P&L, cancel remaining orders, persist, publish."""
        position.status = "CLOSED"
        position.exit_price = exit_price
        position.exit_time = self._now_fn()

        # Calculate realized P&L
        if position.side == "BUY":
            position.realized_pnl = (exit_price - position.entry_price) * position.quantity
        else:
            position.realized_pnl = (position.entry_price - exit_price) * position.quantity

        # OCO: cancel the remaining order
        if exit_reason == "STOP_LOSS" and position.target_order_id:
            self._oms.cancel_order(position.target_order_id)
            self._order_to_position.pop(position.target_order_id, None)
        elif exit_reason == "TARGET" and position.stop_order_id:
            self._oms.cancel_order(position.stop_order_id)
            self._order_to_position.pop(position.stop_order_id, None)

        # Clean up order mappings
        if position.stop_order_id:
            self._order_to_position.pop(position.stop_order_id, None)
        if position.target_order_id:
            self._order_to_position.pop(position.target_order_id, None)

        # Persist to SQLite
        self._update_position_closed(position, exit_reason)

        # Publish close event
        self._publish_close_event(position, exit_reason)

        logger.info(
            f"Position closed: {position.position_id} reason={exit_reason} "
            f"exit_price={exit_price} pnl={position.realized_pnl:.2f}",
        )

        return position

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _store_position(self, position: Position) -> None:
        """Insert a new position into the trades table."""
        try:
            conn = self._db.connect_sqlite()
            conn.execute(
                "INSERT INTO trades "
                "(trade_id, symbol, side, strategy, entry_price, quantity, "
                "entry_time, stop_loss, target) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    position.position_id,
                    position.symbol,
                    position.side,
                    position.strategy,
                    position.entry_price,
                    position.quantity,
                    position.entry_time.isoformat(),
                    position.stop_loss,
                    position.target,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.error(
                f"Failed to store position {position.position_id}: {exc}",
                exc_info=True,
            )

    def _update_position_closed(self, position: Position, exit_reason: str) -> None:
        """Update the trades table when a position is closed."""
        try:
            conn = self._db.connect_sqlite()
            conn.execute(
                "UPDATE trades SET exit_price=?, exit_time=?, realized_pnl=?, "
                "exit_reason=? WHERE trade_id=?",
                (
                    position.exit_price,
                    position.exit_time.isoformat() if position.exit_time else None,
                    position.realized_pnl,
                    exit_reason,
                    position.position_id,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.error(
                f"Failed to update closed position {position.position_id}: {exc}",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _publish_close_event(self, position: Position, exit_reason: str) -> None:
        """Publish a position closed event to Redis stream."""
        try:
            self._event_bus.publish(
                "stream:position_closed",
                {
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "entry_price": position.entry_price,
                    "exit_price": position.exit_price,
                    "quantity": position.quantity,
                    "realized_pnl": position.realized_pnl,
                    "exit_reason": exit_reason,
                    "strategy": position.strategy,
                    "timestamp": self._now_fn().isoformat(),
                },
                maxlen=1000,
            )
        except Exception as exc:
            logger.error(
                f"Failed to publish close event for {position.position_id}: {exc}",
                exc_info=True,
            )
