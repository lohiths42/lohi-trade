"""
Paper Trading Engine for LOHI-TRADE.

Simulates order execution without calling any broker API. Used for
validating strategies in a risk-free environment before going live.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
"""

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.ingestion.broker_interface import Order, OrderSide, OrderStatus, OrderType
from src.utils.config import PaperTradingConfig
from src.utils.logger import get_logger

logger = get_logger("PaperTrading")

DEFAULT_DB_PATH = "data/paper_trades.db"


class PaperTradingEngine:
    """Simulate order fills without touching the broker API.

    Key behaviours:
    - Fills are based on the next available tick price with configurable slippage.
    - A random delay (default 100-500 ms) is applied to mimic real latency.
    - Paper order IDs follow the pattern ``PAPER-<hex>``.
    - All activity is logged with a ``PAPER`` prefix.
    - An ``api_calls_made`` list is maintained (should always be empty) so
      tests can verify no real broker calls occurred.

    Requirements: 16.2, 16.3, 16.4, 16.5, 16.6
    """

    def __init__(
        self,
        config: PaperTradingConfig,
        db_path: Optional[str] = None,
        sqlite_path: Optional[str] = None,
    ) -> None:
        self._config = config
        self._db_path = db_path
        self._sqlite_path = sqlite_path or "data/lohi_trade.db"
        self.api_calls_made: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        """Return whether paper trading mode is active."""
        return self._config.enabled

    # ------------------------------------------------------------------
    # Database path
    # ------------------------------------------------------------------

    def get_db_path(self) -> str:
        """Return the database path for the current mode.

        When paper trading is enabled the separate ``paper_trades.db`` is
        used so that simulated data never pollutes the production database.

        Requirements: 16.5
        """
        if self._db_path is not None:
            return self._db_path
        if self._config.enabled:
            return DEFAULT_DB_PATH
        return self._sqlite_path

    # ------------------------------------------------------------------
    # Order simulation
    # ------------------------------------------------------------------

    def simulate_order_fill(self, order: Order, next_tick_price: float) -> Order:
        """Simulate filling *order* at *next_tick_price* with slippage.

        The method does **not** call any broker API.  Instead it:
        1. Applies configured slippage to the tick price.
        2. Sleeps for a random duration within the configured delay range.
        3. Sets the order status to FILLED and assigns a paper order ID.

        Args:
            order: The order to fill.
            next_tick_price: The next available market price.

        Returns:
            The same *order* instance, mutated to reflect the fill.

        Requirements: 16.2, 16.3, 16.4
        """
        slippage_pct = self._config.simulated_slippage_pct
        delay_range = self._config.simulated_fill_delay_ms

        # Determine slippage direction based on order side
        if order.side == OrderSide.BUY:
            fill_price = next_tick_price * (1 + slippage_pct / 100.0)
        else:
            fill_price = next_tick_price * (1 - slippage_pct / 100.0)

        # Simulate network / exchange latency
        min_delay_ms = delay_range[0] if len(delay_range) > 0 else 100
        max_delay_ms = delay_range[1] if len(delay_range) > 1 else 500
        delay_s = random.randint(min_delay_ms, max_delay_ms) / 1000.0
        time.sleep(delay_s)

        # Fill the order
        order.status = OrderStatus.FILLED
        order.filled_price = round(fill_price, 2)
        order.filled_qty = order.quantity
        order.broker_order_id = f"PAPER-{uuid.uuid4().hex[:8]}"

        self.log_paper_trade(order, "FILL")
        return order

    def simulate_order_cancel(self, order: Order) -> Order:
        """Cancel *order* without calling the broker API.

        Args:
            order: The order to cancel.

        Returns:
            The same *order* instance with status set to CANCELLED.
        """
        order.status = OrderStatus.CANCELLED
        self.log_paper_trade(order, "CANCEL")
        return order

    # ------------------------------------------------------------------
    # Notification formatting
    # ------------------------------------------------------------------

    def format_paper_notification(self, message: str) -> str:
        """Prepend ``PAPER: `` to *message* for Telegram notifications.

        Requirements: 16.6
        """
        return f"PAPER: {message}"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_paper_trade(self, order: Order, action: str) -> None:
        """Log a paper trade with the ``PAPER`` prefix.

        Args:
            order: The order being logged.
            action: A short label such as ``FILL`` or ``CANCEL``.

        Requirements: 16.6
        """
        logger.info(
            f"PAPER {action}: symbol={order.symbol} side={order.side.value} "
            f"qty={order.quantity} status={order.status.value} "
            f"broker_id={order.broker_order_id} filled_price={order.filled_price}"
        )

    # ------------------------------------------------------------------
    # API call tracking (for test verification)
    # ------------------------------------------------------------------

    def get_api_call_count(self) -> int:
        """Return the number of real broker API calls made (should be 0)."""
        return len(self.api_calls_made)
