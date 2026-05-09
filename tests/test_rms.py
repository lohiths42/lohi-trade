"""
Unit tests for the Risk Management System (RMS).

Tests all 9 pre-order checks and supporting functionality.
Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9
"""

import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.execution.rms import (
    ExposureMetrics,
    RiskManagementSystem,
    ValidationResult,
)
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal
from src.utils.config import (
    CapitalConfig,
    Config,
    MarketConfig,
    RiskLimitsConfig,
    TradingHoursConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_indicator_set(symbol: str = "RELIANCE") -> IndicatorSet:
    """Create a minimal IndicatorSet for testing."""
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 30),
        rsi_14=45.0,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=2600.0,
        bb_middle=2500.0,
        bb_lower=2400.0,
        vwap=2500.0,
        ema_9=2510.0,
        ema_21=2490.0,
        supertrend=2480.0,
        supertrend_direction=1,
        atr_14=30.0,
        volume_avg_20=100000.0,
    )


def _make_signal(
    symbol: str = "RELIANCE",
    side: str = "BUY",
    entry_price: float = 2500.0,
    stop_loss: float = 2470.0,
    target: float = 2560.0,
    quantity: int = 0,
) -> Signal:
    """Create a test Signal."""
    return Signal(
        signal_id="test-signal-001",
        symbol=symbol,
        strategy="MeanReversion",
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        timestamp=datetime(2024, 1, 15, 10, 30),
        indicators=_make_indicator_set(symbol),
    )


def _make_config() -> Config:
    """Create a minimal Config for RMS testing."""
    capital = CapitalConfig(
        total=200000.0,
        risk_per_trade_pct=1.0,
        max_position_size_pct=20.0,
        max_daily_loss_pct=2.0,
    )
    risk_limits = RiskLimitsConfig(
        max_open_positions=5,
        max_orders_per_day=20,
        cooldown_after_loss_minutes=5,
        volatility_guard_threshold_pct=2.0,
        volatility_guard_window_minutes=10,
    )
    trading_hours = TradingHoursConfig(
        market_open="09:15",
        trading_start="09:30",
        trading_end="15:10",
        square_off_time="15:15",
        market_close="15:30",
    )
    market = MarketConfig(
        country="IN",
        country_name="India",
        currency="INR",
        benchmark_index_name="Nifty 50",
        benchmark_redis_key="nifty",
    )
    # Use MagicMock for fields not needed by RMS
    config = MagicMock(spec=Config)
    config.capital = capital
    config.risk_limits = risk_limits
    config.trading_hours = trading_hours
    config.market = market
    return config


def _make_rms(
    now: datetime = datetime(2024, 1, 15, 10, 30),
    kill_switch_active: bool = False,
    daily_pnl: float = 0.0,
    open_positions: int = 0,
    orders_today: int = 0,
    last_trade: dict = None,
    nifty_current: str = None,
    nifty_window_start: str = None,
    bias_map: dict = None,
) -> RiskManagementSystem:
    """Create an RMS instance with mocked dependencies."""
    config = _make_config()
    redis_client = MagicMock()
    event_bus = MagicMock()

    # Set up in-memory SQLite for testing
    db_manager = MagicMock()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT, symbol TEXT, side TEXT, strategy TEXT,
            entry_price REAL, exit_price REAL, quantity INTEGER,
            entry_time TIMESTAMP, exit_time TIMESTAMP,
            realized_pnl REAL, stop_loss REAL, target REAL,
            exit_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT, trade_id TEXT, symbol TEXT, side TEXT,
            order_type TEXT, quantity INTEGER, price REAL,
            trigger_price REAL, status TEXT, broker_order_id TEXT,
            filled_qty INTEGER DEFAULT 0, filled_price REAL,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT, component TEXT, message TEXT,
            metadata TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    today_str = now.strftime("%Y-%m-%d")

    # Insert closed trades for daily P&L
    if daily_pnl != 0.0:
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "exit_price, quantity, entry_time, exit_time, realized_pnl, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "TEST", "BUY", "test", 100, 110, 10, f"{today_str} 09:30:00",
             f"{today_str} 10:00:00", daily_pnl, 95, 115),
        )

    # Insert open positions
    for i in range(open_positions):
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "quantity, entry_time, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"open-{i}", f"SYM{i}", "BUY", "test", 100, 10,
             f"{today_str} 09:30:00", 95, 115),
        )

    # Insert orders for today
    for i in range(orders_today):
        conn.execute(
            "INSERT INTO orders (order_id, symbol, side, order_type, quantity, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"ord-{i}", "TEST", "BUY", "MARKET", 10, "PLACED",
             f"{today_str} 10:00:00"),
        )

    # Insert last closed trade for cooldown check
    if last_trade is not None:
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "exit_price, quantity, entry_time, exit_time, realized_pnl, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("last-trade", "TEST", "BUY", "test", 100, 95, 10,
             f"{today_str} 09:30:00", last_trade["exit_time"],
             last_trade["realized_pnl"], 90, 115),
        )

    conn.commit()
    db_manager.connect_sqlite.return_value = conn
    db_manager.execute_with_retry = MagicMock()

    # Redis mock for kill switch
    def redis_get(key):
        if key == RiskManagementSystem.KILL_SWITCH_KEY:
            return "true" if kill_switch_active else "false"
        if key == "nifty:current_price":
            return nifty_current
        if key == "nifty:window_start_price":
            return nifty_window_start
        if bias_map and key.startswith("bias:"):
            symbol = key.split(":", 1)[1]
            return bias_map.get(symbol)
        return None

    redis_client.get = MagicMock(side_effect=redis_get)

    rms = RiskManagementSystem(
        config=config,
        redis_client=redis_client,
        event_bus=event_bus,
        db_manager=db_manager,
        now_fn=lambda: now,
    )
    return rms


# ---------------------------------------------------------------------------
# Test: All checks pass
# ---------------------------------------------------------------------------

class TestRMSAllChecksPass:
    def test_order_passes_all_checks(self):
        """When all conditions are favorable, order should pass all 9 checks."""
        rms = _make_rms()
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert result.is_valid is True
        assert result.rejection_reason is None
        assert len(result.checks_passed) == 9
        assert len(result.checks_failed) == 0
        assert result.timestamp is not None


# ---------------------------------------------------------------------------
# Test: Check 1 - Kill Switch
# ---------------------------------------------------------------------------

class TestKillSwitchCheck:
    def test_reject_when_kill_switch_active(self):
        """Requirement 9.7: Reject if kill switch is active."""
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert result.is_valid is False
        assert result.rejection_reason == "Kill switch active"
        assert "kill_switch" in result.checks_failed

    def test_pass_when_kill_switch_inactive(self):
        rms = _make_rms(kill_switch_active=False)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert "kill_switch" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 2 - Trading Hours
# ---------------------------------------------------------------------------

class TestTradingHoursCheck:
    def test_reject_before_trading_start(self):
        """Requirement 9.9: Reject before 9:30 AM."""
        rms = _make_rms(now=datetime(2024, 1, 15, 9, 0))
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert result.rejection_reason == "Outside trading hours"
        assert "trading_hours" in result.checks_failed

    def test_reject_after_trading_end(self):
        """Requirement 9.9: Reject after 3:10 PM."""
        rms = _make_rms(now=datetime(2024, 1, 15, 15, 15))
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert "trading_hours" in result.checks_failed

    def test_pass_during_trading_hours(self):
        rms = _make_rms(now=datetime(2024, 1, 15, 10, 30))
        result = rms.validate_order(_make_signal())
        assert "trading_hours" in result.checks_passed

    def test_pass_at_exact_start(self):
        rms = _make_rms(now=datetime(2024, 1, 15, 9, 30))
        result = rms.validate_order(_make_signal())
        assert "trading_hours" in result.checks_passed

    def test_pass_at_exact_end(self):
        rms = _make_rms(now=datetime(2024, 1, 15, 15, 10))
        result = rms.validate_order(_make_signal())
        assert "trading_hours" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 3 - Daily Loss Limit
# ---------------------------------------------------------------------------

class TestDailyLossLimitCheck:
    def test_reject_when_daily_loss_exceeds_limit(self):
        """Requirement 9.2: Reject if daily loss > 2% of capital (₹4,000)."""
        rms = _make_rms(daily_pnl=-5000.0)  # -2.5% of 200k
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert result.rejection_reason == "Daily loss limit exceeded"
        assert "daily_loss_limit" in result.checks_failed

    def test_pass_when_within_loss_limit(self):
        rms = _make_rms(daily_pnl=-3000.0)  # -1.5% of 200k
        result = rms.validate_order(_make_signal())
        assert "daily_loss_limit" in result.checks_passed

    def test_pass_when_profitable(self):
        rms = _make_rms(daily_pnl=5000.0)
        result = rms.validate_order(_make_signal())
        assert "daily_loss_limit" in result.checks_passed

    def test_activates_kill_switch_on_breach(self):
        """Requirement 14.7: Auto-activate kill switch on daily loss limit."""
        rms = _make_rms(daily_pnl=-5000.0)
        rms.validate_order(_make_signal())
        # Kill switch should have been activated via redis.set
        rms._redis.set.assert_any_call(
            RiskManagementSystem.KILL_SWITCH_KEY, "true"
        )


# ---------------------------------------------------------------------------
# Test: Check 4 - Position Limit
# ---------------------------------------------------------------------------

class TestPositionLimitCheck:
    def test_reject_when_at_position_limit(self):
        """Requirement 9.3: Reject if open positions >= 5."""
        rms = _make_rms(open_positions=5)
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert result.rejection_reason == "Position limit reached"
        assert "position_limit" in result.checks_failed

    def test_reject_when_over_position_limit(self):
        rms = _make_rms(open_positions=7)
        result = rms.validate_order(_make_signal())
        assert "position_limit" in result.checks_failed

    def test_pass_when_under_position_limit(self):
        rms = _make_rms(open_positions=4)
        result = rms.validate_order(_make_signal())
        assert "position_limit" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 5 - Position Size Limit
# ---------------------------------------------------------------------------

class TestPositionSizeLimitCheck:
    def test_reject_when_order_value_exceeds_limit(self):
        """Requirement 9.4: Reject if order value > 20% of capital (₹40,000)."""
        # 2500 * 20 = 50,000 > 40,000
        signal = _make_signal(entry_price=2500.0, quantity=20)
        rms = _make_rms()
        result = rms.validate_order(signal)

        assert result.is_valid is False
        assert result.rejection_reason == "Position size limit exceeded"
        assert "position_size_limit" in result.checks_failed

    def test_pass_when_order_value_within_limit(self):
        # 2500 * 10 = 25,000 < 40,000
        signal = _make_signal(entry_price=2500.0, quantity=10)
        rms = _make_rms()
        result = rms.validate_order(signal)
        assert "position_size_limit" in result.checks_passed

    def test_pass_when_quantity_zero_and_price_affordable(self):
        """Pre-sizing check: 1 share at 2500 < 40,000."""
        signal = _make_signal(entry_price=2500.0, quantity=0)
        rms = _make_rms()
        result = rms.validate_order(signal)
        assert "position_size_limit" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 6 - Order Count Limit
# ---------------------------------------------------------------------------

class TestOrderCountLimitCheck:
    def test_reject_when_at_order_limit(self):
        """Requirement 9.5: Reject if orders today >= 20."""
        rms = _make_rms(orders_today=20)
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert result.rejection_reason == "Order count limit reached"
        assert "order_count_limit" in result.checks_failed

    def test_pass_when_under_order_limit(self):
        rms = _make_rms(orders_today=19)
        result = rms.validate_order(_make_signal())
        assert "order_count_limit" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 7 - Cooldown
# ---------------------------------------------------------------------------

class TestCooldownCheck:
    def test_reject_when_cooldown_active(self):
        """Requirement 9.6: Reject if last trade was a loss and < 5 min ago."""
        now = datetime(2024, 1, 15, 10, 30)
        last_exit = (now - timedelta(minutes=2)).isoformat()
        rms = _make_rms(
            now=now,
            last_trade={"realized_pnl": -500.0, "exit_time": last_exit},
        )
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert "Cooldown period active" in result.rejection_reason
        assert "cooldown" in result.checks_failed

    def test_pass_when_cooldown_expired(self):
        now = datetime(2024, 1, 15, 10, 30)
        last_exit = (now - timedelta(minutes=6)).isoformat()
        rms = _make_rms(
            now=now,
            last_trade={"realized_pnl": -500.0, "exit_time": last_exit},
        )
        result = rms.validate_order(_make_signal())
        assert "cooldown" in result.checks_passed

    def test_pass_when_last_trade_was_profit(self):
        now = datetime(2024, 1, 15, 10, 30)
        last_exit = (now - timedelta(minutes=1)).isoformat()
        rms = _make_rms(
            now=now,
            last_trade={"realized_pnl": 500.0, "exit_time": last_exit},
        )
        result = rms.validate_order(_make_signal())
        assert "cooldown" in result.checks_passed

    def test_pass_when_no_previous_trades(self):
        rms = _make_rms()
        result = rms.validate_order(_make_signal())
        assert "cooldown" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Check 8 - Volatility Guard
# ---------------------------------------------------------------------------

class TestVolatilityGuardCheck:
    def test_reject_when_nifty_drops_over_threshold(self):
        """Requirement 9.8: Reject if Nifty dropped > 2% in 10 min."""
        rms = _make_rms(
            nifty_current="19000",
            nifty_window_start="19500",  # ~2.56% drop
        )
        result = rms.validate_order(_make_signal())

        assert result.is_valid is False
        assert result.rejection_reason == "Volatility guard triggered"
        assert "volatility_guard" in result.checks_failed

    def test_pass_when_nifty_drop_within_threshold(self):
        rms = _make_rms(
            nifty_current="19700",
            nifty_window_start="19800",  # ~0.5% drop
        )
        result = rms.validate_order(_make_signal())
        assert "volatility_guard" in result.checks_passed

    def test_pass_when_nifty_data_unavailable(self):
        """When Nifty data is unavailable, volatility guard should pass."""
        rms = _make_rms(nifty_current=None, nifty_window_start=None)
        result = rms.validate_order(_make_signal())
        assert "volatility_guard" in result.checks_passed

    def test_activates_kill_switch_on_trigger(self):
        """Requirement 14.6: Auto-activate kill switch on volatility guard."""
        rms = _make_rms(
            nifty_current="19000",
            nifty_window_start="19500",
        )
        rms.validate_order(_make_signal())
        rms._redis.set.assert_any_call(
            RiskManagementSystem.KILL_SWITCH_KEY, "true"
        )


# ---------------------------------------------------------------------------
# Test: Check 9 - Bias Filter
# ---------------------------------------------------------------------------

class TestBiasFilterCheck:
    def test_reject_buy_when_bearish(self):
        """Requirement 9.1/9.2: Reject BUY if bias is BEARISH."""
        rms = _make_rms(bias_map={"RELIANCE": "BEARISH"})
        signal = _make_signal(side="BUY")
        result = rms.validate_order(signal)

        assert result.is_valid is False
        assert result.rejection_reason == "Bias filter: bearish sentiment"
        assert "bias_filter" in result.checks_failed

    def test_reject_sell_when_bullish(self):
        """Requirement 9.4: Reject SELL if bias is BULLISH."""
        rms = _make_rms(bias_map={"RELIANCE": "BULLISH"})
        signal = _make_signal(side="SELL")
        result = rms.validate_order(signal)

        assert result.is_valid is False
        assert result.rejection_reason == "Bias filter: bullish sentiment"
        assert "bias_filter" in result.checks_failed

    def test_pass_buy_when_bullish(self):
        rms = _make_rms(bias_map={"RELIANCE": "BULLISH"})
        signal = _make_signal(side="BUY")
        result = rms.validate_order(signal)
        assert "bias_filter" in result.checks_passed

    def test_pass_buy_when_neutral(self):
        rms = _make_rms(bias_map={"RELIANCE": "NEUTRAL"})
        signal = _make_signal(side="BUY")
        result = rms.validate_order(signal)
        assert "bias_filter" in result.checks_passed

    def test_pass_when_bias_unavailable(self):
        """Requirement 9.5: Default to NEUTRAL when bias unavailable."""
        rms = _make_rms(bias_map={})
        signal = _make_signal(side="BUY")
        result = rms.validate_order(signal)
        assert "bias_filter" in result.checks_passed


# ---------------------------------------------------------------------------
# Test: Exposure Metrics
# ---------------------------------------------------------------------------

class TestExposureMetrics:
    def test_get_current_exposure(self):
        rms = _make_rms(
            daily_pnl=-1000.0,
            open_positions=3,
            orders_today=10,
        )
        metrics = rms.get_current_exposure()

        assert metrics.total_capital == 200000.0
        assert metrics.available_capital == 199000.0
        assert metrics.open_positions == 3
        assert metrics.daily_pnl == -1000.0
        assert metrics.daily_pnl_pct == pytest.approx(-0.5)
        assert metrics.orders_today == 10
        assert metrics.max_position_size == 40000.0


# ---------------------------------------------------------------------------
# Test: Kill Switch Management
# ---------------------------------------------------------------------------

class TestKillSwitchManagement:
    def test_activate_kill_switch(self):
        rms = _make_rms()
        rms.activate_kill_switch("Test reason")
        rms._redis.set.assert_any_call(
            RiskManagementSystem.KILL_SWITCH_KEY, "true"
        )
        rms._redis.set.assert_any_call(
            RiskManagementSystem.KILL_SWITCH_REASON_KEY, "Test reason"
        )

    def test_deactivate_kill_switch(self):
        rms = _make_rms()
        rms.deactivate_kill_switch()
        rms._redis.set.assert_called_with(
            RiskManagementSystem.KILL_SWITCH_KEY, "false"
        )
        rms._redis.delete.assert_called_with(
            RiskManagementSystem.KILL_SWITCH_REASON_KEY
        )


# ---------------------------------------------------------------------------
# Test: Rejection Logging
# ---------------------------------------------------------------------------

class TestRejectionLogging:
    def test_log_rejection_publishes_to_event_bus(self):
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal()
        result = rms.validate_order(signal)
        rms.log_rejection(signal, result)

        rms._event_bus.publish.assert_called_once()
        call_args = rms._event_bus.publish.call_args
        assert call_args[0][0] == "stream:rejections"

    def test_log_rejection_writes_to_audit_log(self):
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal()
        result = rms.validate_order(signal)
        rms.log_rejection(signal, result)

        rms._db.execute_with_retry.assert_called_once()

    def test_no_logging_for_valid_orders(self):
        rms = _make_rms()
        signal = _make_signal()
        result = rms.validate_order(signal)
        rms.log_rejection(signal, result)

        rms._event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Multiple failures reported
# ---------------------------------------------------------------------------

class TestMultipleFailures:
    def test_all_failed_checks_reported(self):
        """All 9 checks should be evaluated even if early ones fail."""
        rms = _make_rms(
            kill_switch_active=True,
            now=datetime(2024, 1, 15, 8, 0),  # before trading hours
            daily_pnl=-5000.0,
            open_positions=5,
            orders_today=20,
        )
        signal = _make_signal(entry_price=2500.0, quantity=20)
        result = rms.validate_order(signal)

        assert result.is_valid is False
        # At minimum these should fail
        assert "kill_switch" in result.checks_failed
        assert "trading_hours" in result.checks_failed
        assert "position_limit" in result.checks_failed
        assert "order_count_limit" in result.checks_failed
        assert "position_size_limit" in result.checks_failed
        # First rejection reason should be kill switch (first check)
        assert result.rejection_reason == "Kill switch active"


# ---------------------------------------------------------------------------
# Test: Latency Tracking (Requirement 9.10)
# ---------------------------------------------------------------------------

class TestLatencyTracking:
    def test_latency_ms_populated(self):
        """Requirement 9.10: ValidationResult should include latency_ms."""
        rms = _make_rms()
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert hasattr(result, "latency_ms")
        assert isinstance(result.latency_ms, float)
        assert result.latency_ms >= 0

    def test_latency_ms_is_positive(self):
        """Latency should be a positive number (validation takes some time)."""
        rms = _make_rms()
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert result.latency_ms >= 0

    def test_latency_ms_on_rejected_order(self):
        """Latency should be tracked even for rejected orders."""
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert result.is_valid is False
        assert result.latency_ms >= 0

    def test_latency_default_value(self):
        """ValidationResult should default latency_ms to 0.0."""
        result = ValidationResult(
            is_valid=True,
            rejection_reason=None,
            checks_passed=["test"],
            checks_failed=[],
            timestamp=datetime.now(),
        )
        assert result.latency_ms == 0.0
