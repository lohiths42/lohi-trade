"""Kill Switch module for LOHI-TRADE.

Manages the emergency kill switch that halts all trading activity.
Supports manual activation/deactivation and automatic triggers based on
Nifty volatility and daily loss limits.

When activated:
- All new orders are rejected by the RMS (via Redis state check)
- All pending orders are cancelled via OMS
- A notification event is published for Telegram delivery
- An audit log entry is created

The kill switch requires manual deactivation — there is no automatic reset.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9
"""

import json
from collections.abc import Callable
from datetime import datetime

from src.execution.oms import OrderManagementSystem
from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus
from src.state.redis_client import RedisClient
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger("KillSwitch")

NOTIFICATION_STREAM = "stream:notifications"
NOTIFICATION_STREAM_MAXLEN = 500


class KillSwitch:
    """Emergency kill switch for halting all trading activity.

    State is persisted in Redis so that all system components (RMS, OMS,
    dashboard, Telegram bot) share a single source of truth.

    Redis keys:
        ``killswitch:active``  – ``"true"`` or ``"false"``
        ``killswitch:reason``  – human-readable activation reason
    """

    KILL_SWITCH_KEY = "killswitch:active"
    KILL_SWITCH_REASON_KEY = "killswitch:reason"

    def __init__(
        self,
        config: Config,
        redis_client: RedisClient,
        oms: OrderManagementSystem,
        db_manager: DatabaseConnectionManager,
        event_bus: EventBus,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialise the kill switch.

        Args:
            config: Application configuration.
            redis_client: Redis client for state storage.
            oms: Order Management System for cancelling pending orders.
            db_manager: Database manager for audit logging.
            event_bus: Event bus for publishing notifications.
            now_fn: Optional callable returning current datetime (for testing).

        """
        self._config = config
        self._redis = redis_client
        self._oms = oms
        self._db = db_manager
        self._event_bus = event_bus
        self._now_fn = now_fn or datetime.now

        # Config values
        self._total_capital = config.capital.total
        self._max_daily_loss_pct = config.capital.max_daily_loss_pct
        self._volatility_threshold_pct = config.risk_limits.volatility_guard_threshold_pct
        self._volatility_window_minutes = config.risk_limits.volatility_guard_window_minutes

        logger.info(
            f"KillSwitch initialised: capital={self._total_capital}, "
            f"max_loss={self._max_daily_loss_pct}%, "
            f"volatility_threshold={self._volatility_threshold_pct}%",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def activate(self, reason: str) -> None:
        """Activate the kill switch.

        Sets Redis state, cancels all pending orders, publishes a
        notification event, and logs to the audit table.

        Args:
            reason: Human-readable reason for activation.

        """
        self._redis.set(self.KILL_SWITCH_KEY, "true")
        self._redis.set(self.KILL_SWITCH_REASON_KEY, reason)

        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

        # Cancel all pending orders
        self.cancel_all_pending_orders()

        # Publish notification for Telegram delivery
        self._send_notification(reason)

        # Audit log
        self._log_audit("KILL_SWITCH_ACTIVATED", reason)

    def deactivate(self) -> None:
        """Deactivate the kill switch (manual only)."""
        self._redis.set(self.KILL_SWITCH_KEY, "false")
        self._redis.delete(self.KILL_SWITCH_REASON_KEY)

        logger.info("Kill switch deactivated")
        self._log_audit("KILL_SWITCH_DEACTIVATED", "Manual deactivation")

    def is_active(self) -> bool:
        """Return ``True`` if the kill switch is currently active."""
        value = self._redis.get(self.KILL_SWITCH_KEY)
        return value == "true"

    def get_reason(self) -> str | None:
        """Return the activation reason, or ``None`` if inactive."""
        return self._redis.get(self.KILL_SWITCH_REASON_KEY)

    # ------------------------------------------------------------------
    # Automatic trigger checks
    # ------------------------------------------------------------------

    def check_nifty_volatility(self) -> bool:
        """Check if Nifty has dropped beyond the volatility threshold.

        Reads ``nifty:current_price`` and ``nifty:window_start_price``
        from Redis and computes the percentage drop.

        Returns:
            ``True`` if the kill switch was activated by this check.

        """
        try:
            current_str = self._redis.get("nifty:current_price")
            start_str = self._redis.get("nifty:window_start_price")

            if current_str is None or start_str is None:
                return False

            current_price = float(current_str)
            start_price = float(start_str)

            if start_price <= 0:
                return False

            drop_pct = ((start_price - current_price) / start_price) * 100

            if drop_pct > self._volatility_threshold_pct:
                reason = (
                    f"Nifty volatility guard: dropped {drop_pct:.2f}% "
                    f"in {self._volatility_window_minutes} minutes "
                    f"(threshold {self._volatility_threshold_pct}%)"
                )
                self.activate(reason)
                return True

            return False
        except (ValueError, TypeError) as exc:
            logger.error(f"Failed to check Nifty volatility: {exc}")
            return False

    def check_daily_loss(self) -> bool:
        """Check if daily realised loss exceeds the configured limit.

        Queries the ``trades`` table for today's total realised P&L.

        Returns:
            ``True`` if the kill switch was activated by this check.

        """
        try:
            daily_pnl = self._get_daily_pnl()
            loss_limit = -(self._max_daily_loss_pct / 100) * self._total_capital

            if daily_pnl < loss_limit:
                reason = (
                    f"Daily loss limit exceeded: P&L={daily_pnl:.2f}, "
                    f"limit={loss_limit:.2f} "
                    f"({self._max_daily_loss_pct}% of {self._total_capital:.0f})"
                )
                self.activate(reason)
                return True

            return False
        except Exception as exc:
            logger.error(f"Failed to check daily loss: {exc}")
            return False

    def run_checks(self) -> bool:
        """Run all automatic trigger checks.

        Returns:
            ``True`` if the kill switch was activated by any check.

        """
        if self.is_active():
            return False  # Already active, nothing to do

        if self.check_nifty_volatility():
            return True

        if self.check_daily_loss():
            return True

        return False

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    def cancel_all_pending_orders(self) -> int:
        """Cancel all pending orders tracked by the OMS.

        Returns:
            Number of orders cancelled.

        """
        cancelled = 0
        for order_id in list(self._oms._pending_orders.keys()):
            try:
                if self._oms.cancel_order(order_id):
                    cancelled += 1
            except Exception as exc:
                logger.error(f"Failed to cancel order {order_id}: {exc}")

        if cancelled > 0:
            logger.info(f"Cancelled {cancelled} pending orders")

        return cancelled

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _send_notification(self, reason: str) -> None:
        """Publish a kill-switch notification event."""
        try:
            self._event_bus.publish(
                NOTIFICATION_STREAM,
                {
                    "type": "KILL_SWITCH",
                    "reason": reason,
                    "timestamp": self._now_fn().isoformat(),
                },
                maxlen=NOTIFICATION_STREAM_MAXLEN,
            )
        except Exception as exc:
            logger.error(f"Failed to send kill switch notification: {exc}")

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _log_audit(self, event_type: str, message: str) -> None:
        """Write an entry to the ``audit_log`` table."""
        try:
            metadata = json.dumps({
                "timestamp": self._now_fn().isoformat(),
            })
            self._db.execute_with_retry(
                "INSERT INTO audit_log (event_type, component, message, metadata) "
                "VALUES (?, ?, ?, ?)",
                (event_type, "KillSwitch", message, metadata),
            )
        except Exception as exc:
            logger.error(f"Failed to log audit event: {exc}")

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    def _get_daily_pnl(self) -> float:
        """Get today's realised P&L from the trades table."""
        try:
            conn = self._db.connect_sqlite()
            today = self._now_fn().strftime("%Y-%m-%d")
            cursor = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) as total_pnl "
                "FROM trades WHERE DATE(exit_time) = ? AND realized_pnl IS NOT NULL",
                (today,),
            )
            row = cursor.fetchone()
            return float(row["total_pnl"]) if row else 0.0
        except Exception as exc:
            logger.error(f"Failed to get daily P&L: {exc}")
            return 0.0
