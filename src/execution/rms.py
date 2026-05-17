"""Risk Management System (RMS) for LOHI-TRADE.

Validates all orders against 9 pre-order checks before forwarding to OMS.
The checks are executed in order and all must pass for an order to proceed.

9 Pre-Order Checks:
1. Kill Switch - reject if kill switch is active
2. Trading Hours - reject if outside 9:30 AM - 3:10 PM IST
3. Daily Loss Limit - reject if realized P&L < -2% of capital
4. Position Limit - reject if open positions >= 5
5. Position Size Limit - reject if order value > 20% of capital
6. Order Count Limit - reject if orders today >= 20
7. Cooldown - reject if last trade was a loss and < 5 minutes ago
8. Volatility Guard - reject if Nifty dropped > 2% in 10 minutes
9. Bias Filter - reject BUY if BEARISH, reject SELL if BULLISH

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 10.1-10.11
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.soldier.strategy_engine import Signal
from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus
from src.state.redis_client import RedisClient
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger("RMS")

REJECTION_STREAM = "stream:rejections"
REJECTION_STREAM_MAXLEN = 1000


@dataclass
class ValidationResult:
    """Result of RMS pre-order validation.

    Attributes:
        is_valid: Whether the order passed all checks.
        rejection_reason: Reason for rejection (None if valid).
        checks_passed: List of check names that passed.
        checks_failed: List of check names that failed.
        timestamp: When validation was performed.
        latency_ms: Time taken for validation in milliseconds.

    """

    is_valid: bool
    rejection_reason: str | None
    checks_passed: list[str]
    checks_failed: list[str]
    timestamp: datetime
    latency_ms: float = 0.0


@dataclass
class ExposureMetrics:
    """Current exposure and risk metrics.

    Attributes:
        total_capital: Total trading capital.
        available_capital: Capital not currently in positions.
        open_positions: Number of open positions.
        daily_pnl: Realized P&L for today.
        daily_pnl_pct: Daily P&L as percentage of capital.
        orders_today: Number of orders placed today.
        max_position_size: Maximum allowed position value.

    """

    total_capital: float
    available_capital: float
    open_positions: int
    daily_pnl: float
    daily_pnl_pct: float
    orders_today: int
    max_position_size: float


class RiskManagementSystem:
    """Validates all orders against 9 pre-order checks before forwarding to OMS.

    The RMS consumes signals from stream:signals, fetches bias from
    stream:bias:{symbol}, and performs sequential validation checks.
    If any check fails, the order is rejected immediately.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 10.1-10.11
    """

    # Redis keys for kill switch state
    KILL_SWITCH_KEY = "killswitch:active"
    KILL_SWITCH_REASON_KEY = "killswitch:reason"

    def __init__(
        self,
        config: Config,
        redis_client: RedisClient,
        event_bus: EventBus,
        db_manager: DatabaseConnectionManager,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the Risk Management System.

        Args:
            config: Application configuration.
            redis_client: Redis client for kill switch and bias state.
            event_bus: Event bus for publishing rejections.
            db_manager: Database manager for querying trades/orders and logging.
            now_fn: Optional callable returning current datetime (for testing).

        """
        self._config = config
        self._redis = redis_client
        self._event_bus = event_bus
        self._db = db_manager
        self._now_fn = now_fn or datetime.now

        # Parse trading hours from config
        start_parts = config.trading_hours.trading_start.split(":")
        self._trading_start_hour = int(start_parts[0])
        self._trading_start_minute = int(start_parts[1])

        end_parts = config.trading_hours.trading_end.split(":")
        self._trading_end_hour = int(end_parts[0])
        self._trading_end_minute = int(end_parts[1])

        # Capital and risk limits from config
        self._total_capital = config.capital.total
        self._max_daily_loss_pct = config.capital.max_daily_loss_pct
        self._max_position_size_pct = config.capital.max_position_size_pct
        self._max_open_positions = config.risk_limits.max_open_positions
        self._max_orders_per_day = config.risk_limits.max_orders_per_day
        self._cooldown_minutes = config.risk_limits.cooldown_after_loss_minutes
        self._volatility_threshold_pct = config.risk_limits.volatility_guard_threshold_pct
        self._volatility_window_minutes = config.risk_limits.volatility_guard_window_minutes

        # Market-specific benchmark for volatility guard
        # Uses config/market.yaml settings (defaults to Nifty for backward compatibility)
        market_config = getattr(config, "market", None)
        self._benchmark_redis_key = self._resolve_market_setting(
            market_config,
            "benchmark_redis_key",
            "nifty",
        )
        self._benchmark_index_name = self._resolve_market_setting(
            market_config,
            "benchmark_index_name",
            "Nifty 50",
        )

        logger.info(
            f"RMS initialized: capital={self._total_capital}, "
            f"max_loss={self._max_daily_loss_pct}%, "
            f"max_positions={self._max_open_positions}, "
            f"max_orders={self._max_orders_per_day}, "
            f"volatility_benchmark={self._benchmark_index_name}",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_order(self, signal: Signal) -> ValidationResult:
        """Validate a signal against all 9 pre-order checks.

        Checks are executed in order. All must pass for the order to be valid.
        On first failure, remaining checks are still evaluated so that the
        full list of passed/failed checks is available for diagnostics.

        Measures validation latency and logs a warning if it exceeds 50ms.

        Args:
            signal: The trading signal to validate.

        Returns:
            ValidationResult with pass/fail status, details, and latency_ms.

        """
        start_time = time.monotonic()

        now = self._now_fn()
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        first_rejection: str | None = None

        checks: list[tuple[str, Callable[..., str | None]]] = [
            ("kill_switch", lambda: self._check_kill_switch()),
            ("trading_hours", lambda: self._check_trading_hours(now)),
            ("daily_loss_limit", lambda: self._check_daily_loss_limit()),
            ("position_limit", lambda: self._check_position_limit()),
            ("position_size_limit", lambda: self._check_position_size_limit(signal)),
            ("order_count_limit", lambda: self._check_order_count_limit()),
            ("cooldown", lambda: self._check_cooldown(now)),
            ("volatility_guard", lambda: self._check_volatility_guard(now)),
            ("bias_filter", lambda: self._check_bias_filter(signal)),
        ]

        for check_name, check_fn in checks:
            rejection = check_fn()
            if rejection is None:
                checks_passed.append(check_name)
            else:
                checks_failed.append(check_name)
                if first_rejection is None:
                    first_rejection = rejection

        end_time = time.monotonic()
        latency_ms = (end_time - start_time) * 1000

        is_valid = len(checks_failed) == 0

        result = ValidationResult(
            is_valid=is_valid,
            rejection_reason=first_rejection,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            timestamp=now,
            latency_ms=latency_ms,
        )

        # Always log latency at INFO level
        logger.info(
            f"Order validation latency: {latency_ms:.2f}ms "
            f"symbol={signal.symbol} side={signal.side}",
        )

        # Warn if latency exceeds 50ms threshold
        if latency_ms > 50:
            logger.warning(
                f"Order validation latency exceeded 50ms: {latency_ms:.2f}ms "
                f"symbol={signal.symbol} side={signal.side}",
            )

        if is_valid:
            logger.info(
                f"Order PASSED all RMS checks: symbol={signal.symbol} "
                f"side={signal.side} strategy={signal.strategy}",
            )
        else:
            logger.warning(
                f"Order REJECTED: symbol={signal.symbol} side={signal.side} "
                f"reason='{first_rejection}' failed_checks={checks_failed}",
            )

        return result

    def get_current_exposure(self) -> ExposureMetrics:
        """Get current exposure and risk metrics.

        Returns:
            ExposureMetrics with current capital, positions, and P&L data.

        """
        open_positions = self._get_open_position_count()
        daily_pnl = self._get_daily_pnl()
        orders_today = self._get_orders_today_count()
        daily_pnl_pct = (daily_pnl / self._total_capital) * 100 if self._total_capital > 0 else 0.0
        max_position_size = self._total_capital * (self._max_position_size_pct / 100)

        return ExposureMetrics(
            total_capital=self._total_capital,
            available_capital=self._total_capital + daily_pnl,
            open_positions=open_positions,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            orders_today=orders_today,
            max_position_size=max_position_size,
        )

    def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch, halting all new orders.

        Args:
            reason: Reason for activation.

        """
        self._redis.set(self.KILL_SWITCH_KEY, "true")
        self._redis.set(self.KILL_SWITCH_REASON_KEY, reason)
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch, allowing orders again."""
        self._redis.set(self.KILL_SWITCH_KEY, "false")
        self._redis.delete(self.KILL_SWITCH_REASON_KEY)
        logger.info("Kill switch deactivated")

    def is_kill_switch_active(self) -> bool:
        """Check if the kill switch is currently active."""
        value = self._redis.get(self.KILL_SWITCH_KEY)
        return value == "true"

    # ------------------------------------------------------------------
    # Pre-order checks (return None if passed, rejection reason if failed)
    # ------------------------------------------------------------------

    def _check_kill_switch(self) -> str | None:
        """Check 1: Reject if kill switch is active."""
        if self.is_kill_switch_active():
            return "Kill switch active"
        return None

    def _check_trading_hours(self, now: datetime) -> str | None:
        """Check 2: Reject if outside trading hours (9:30 AM - 3:10 PM IST)."""
        current_minutes = now.hour * 60 + now.minute
        start_minutes = self._trading_start_hour * 60 + self._trading_start_minute
        end_minutes = self._trading_end_hour * 60 + self._trading_end_minute

        if current_minutes < start_minutes or current_minutes > end_minutes:
            return "Outside trading hours"
        return None

    def _check_daily_loss_limit(self) -> str | None:
        """Check 3: Reject if realized P&L today < -2% of capital."""
        daily_pnl = self._get_daily_pnl()
        loss_limit = -(self._max_daily_loss_pct / 100) * self._total_capital

        if daily_pnl < loss_limit:
            # Auto-activate kill switch on daily loss limit breach
            self.activate_kill_switch(
                f"Daily loss limit exceeded: P&L={daily_pnl:.2f}, limit={loss_limit:.2f}",
            )
            return "Daily loss limit exceeded"
        return None

    def _check_position_limit(self) -> str | None:
        """Check 4: Reject if open positions >= max (default 5)."""
        open_count = self._get_open_position_count()
        if open_count >= self._max_open_positions:
            return "Position limit reached"
        return None

    def _check_position_size_limit(self, signal: Signal) -> str | None:
        """Check 5: Reject if order value > 20% of capital."""
        max_value = self._total_capital * (self._max_position_size_pct / 100)
        # Use entry_price * quantity if quantity is set, otherwise just entry_price
        # for pre-sizing validation. If quantity is 0 (not yet sized), we check
        # if the entry price alone exceeds max (i.e., can't even buy 1 share).
        if signal.quantity > 0:
            order_value = signal.entry_price * signal.quantity
        else:
            # Before position sizing, just verify the signal is viable
            # (at least 1 share must be affordable within limits)
            order_value = signal.entry_price  # value of 1 share

        if order_value > max_value:
            return "Position size limit exceeded"
        return None

    def _check_order_count_limit(self) -> str | None:
        """Check 6: Reject if orders placed today >= max (default 20)."""
        orders_today = self._get_orders_today_count()
        if orders_today >= self._max_orders_per_day:
            return "Order count limit reached"
        return None

    def _check_cooldown(self, now: datetime) -> str | None:
        """Check 7: Reject if last trade was a loss and < 5 minutes ago."""
        last_trade = self._get_last_closed_trade()
        if last_trade is None:
            return None

        pnl = last_trade.get("realized_pnl")
        exit_time_str = last_trade.get("exit_time")

        if pnl is None or exit_time_str is None:
            return None

        if pnl >= 0:
            return None  # Last trade was not a loss

        # Parse exit time
        try:
            exit_time = datetime.fromisoformat(str(exit_time_str))
        except (ValueError, TypeError):
            return None

        elapsed = now - exit_time
        cooldown_delta = timedelta(minutes=self._cooldown_minutes)

        if elapsed < cooldown_delta:
            remaining = cooldown_delta - elapsed
            return f"Cooldown period active ({remaining.seconds}s remaining)"
        return None

    def _check_volatility_guard(self, now: datetime) -> str | None:
        """Check 8: Reject if benchmark index dropped > threshold in configured window.

        Uses the market-specific benchmark (Nifty 50 for India, S&P 500 for US, etc.)
        configured via config/market.yaml.
        """
        benchmark_drop_pct = self._get_benchmark_drop_pct(now)

        if benchmark_drop_pct is not None and benchmark_drop_pct > self._volatility_threshold_pct:
            # Auto-activate kill switch on volatility guard trigger
            self.activate_kill_switch(
                f"Volatility guard triggered: {self._benchmark_index_name} dropped "
                f"{benchmark_drop_pct:.2f}% in {self._volatility_window_minutes} minutes",
            )
            return "Volatility guard triggered"
        return None

    def _check_bias_filter(self, signal: Signal) -> str | None:
        """Check 9: Reject BUY if BEARISH, reject SELL if BULLISH."""
        bias = self._get_current_bias(signal.symbol)

        if bias is None:
            # Default to NEUTRAL when bias unavailable
            return None

        if signal.side == "BUY" and bias == "BEARISH":
            return "Bias filter: bearish sentiment"

        if signal.side == "SELL" and bias == "BULLISH":
            return "Bias filter: bullish sentiment"

        return None

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_market_setting(market_config: object, attr: str, default: str) -> str:
        """Resolve a string market setting while ignoring mock objects and nulls."""
        value = getattr(market_config, attr, default) if market_config is not None else default
        return value if isinstance(value, str) and value else default

    def _get_daily_pnl(self) -> float:
        """Get realized P&L for today from the trades table."""
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
        except Exception as e:
            logger.error(f"Failed to get daily P&L: {e}")
            return 0.0

    def _get_open_position_count(self) -> int:
        """Get count of open positions (trades without exit_time)."""
        try:
            conn = self._db.connect_sqlite()
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE exit_time IS NULL",
            )
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        except Exception as e:
            logger.error(f"Failed to get open position count: {e}")
            return 0

    def _get_orders_today_count(self) -> int:
        """Get count of orders placed today."""
        try:
            conn = self._db.connect_sqlite()
            today = self._now_fn().strftime("%Y-%m-%d")
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM orders WHERE DATE(created_at) = ?",
                (today,),
            )
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        except Exception as e:
            logger.error(f"Failed to get orders today count: {e}")
            return 0

    def _get_last_closed_trade(self) -> dict | None:
        """Get the most recently closed trade."""
        try:
            conn = self._db.connect_sqlite()
            cursor = conn.execute(
                "SELECT realized_pnl, exit_time FROM trades "
                "WHERE exit_time IS NOT NULL "
                "ORDER BY exit_time DESC LIMIT 1",
            )
            row = cursor.fetchone()
            if row:
                return {"realized_pnl": row["realized_pnl"], "exit_time": row["exit_time"]}
            return None
        except Exception as e:
            logger.error(f"Failed to get last closed trade: {e}")
            return None

    def _get_nifty_drop_pct(self, now: datetime) -> float | None:
        """Get benchmark index percentage drop in the volatility window.

        Reads benchmark tick data from Redis to calculate the drop
        over the configured window (default 10 minutes).

        Uses the market-specific Redis key prefix (e.g., 'nifty' for India,
        'sp500' for US, 'ftse100' for UK) from config/market.yaml.

        Returns:
            Percentage drop (positive means drop), or None if data unavailable.

        """
        return self._get_benchmark_drop_pct(now)

    def _get_benchmark_drop_pct(self, now: datetime) -> float | None:
        """Get benchmark index percentage drop in the volatility window.

        Uses configurable Redis keys based on the active market's benchmark.
        Backward compatible: falls back to 'nifty:*' keys if market not configured.

        Returns:
            Percentage drop (positive means drop), or None if data unavailable.

        """
        try:
            key_prefix = self._benchmark_redis_key
            current_price_str = self._redis.get(f"{key_prefix}:current_price")
            window_start_price_str = self._redis.get(f"{key_prefix}:window_start_price")

            if current_price_str is None or window_start_price_str is None:
                return None

            current_price = float(current_price_str)
            window_start_price = float(window_start_price_str)

            if window_start_price <= 0:
                return None

            drop_pct = ((window_start_price - current_price) / window_start_price) * 100
            return drop_pct
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to calculate {self._benchmark_index_name} drop: {e}")
            return None

    def _get_current_bias(self, symbol: str) -> str | None:
        """Get current bias for a symbol from Redis.

        Reads the latest bias from stream:bias:{symbol}.

        Args:
            symbol: Trading symbol.

        Returns:
            Bias string ('BULLISH', 'BEARISH', 'NEUTRAL') or None if unavailable.

        """
        try:
            bias_key = f"bias:{symbol}"
            bias_value = self._redis.get(bias_key)
            if bias_value and bias_value in ("BULLISH", "BEARISH", "NEUTRAL"):
                return bias_value
            return None
        except Exception as e:
            logger.error(f"Failed to get bias for {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    # Rejection logging
    # ------------------------------------------------------------------

    def log_rejection(self, signal: Signal, result: ValidationResult) -> None:
        """Log a rejection to the Event Bus and SQLite audit_log.

        Args:
            signal: The rejected signal.
            result: The validation result with rejection details.

        """
        if result.is_valid:
            return

        # Publish to rejection stream
        try:
            rejection_msg = {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "side": signal.side,
                "strategy": signal.strategy,
                "rejection_reason": result.rejection_reason or "Unknown",
                "checks_passed": json.dumps(result.checks_passed),
                "checks_failed": json.dumps(result.checks_failed),
                "timestamp": result.timestamp.isoformat(),
            }
            self._event_bus.publish(
                REJECTION_STREAM,
                rejection_msg,
                maxlen=REJECTION_STREAM_MAXLEN,
            )
        except Exception as e:
            logger.error(f"Failed to publish rejection to Event Bus: {e}")

        # Log to audit_log table
        try:
            metadata = json.dumps(
                {
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                    "side": signal.side,
                    "strategy": signal.strategy,
                    "entry_price": signal.entry_price,
                    "checks_passed": result.checks_passed,
                    "checks_failed": result.checks_failed,
                }
            )
            self._db.execute_with_retry(
                "INSERT INTO audit_log (event_type, component, message, metadata) "
                "VALUES (?, ?, ?, ?)",
                (
                    "ORDER_REJECTED",
                    "RMS",
                    f"Order rejected: {result.rejection_reason}",
                    metadata,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log rejection to audit_log: {e}")
