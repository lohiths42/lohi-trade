"""Property-based tests for RMS rejection logging.

**Property 38: Rejection Logging**

For any order rejected by RMS, the rejection reason SHALL be published
to stream:rejections and logged to the audit_log table. Valid orders
SHALL NOT trigger rejection logging.

**Validates: Requirements 9.11**
"""

import json
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.execution.rms import (
    REJECTION_STREAM,
    RiskManagementSystem,
)
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal
from src.utils.config import (
    CapitalConfig,
    Config,
    RiskLimitsConfig,
    TradingHoursConfig,
)

# ---------------------------------------------------------------------------
# Shared helpers (following patterns from tests/test_prop_rms_individual_checks.py)
# ---------------------------------------------------------------------------

CAPITAL = 200000.0


def _make_indicator_set(symbol: str = "RELIANCE") -> IndicatorSet:
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
    signal_id: str = "prop-test-signal",
) -> Signal:
    return Signal(
        signal_id=signal_id,
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


def _make_config(capital: float = CAPITAL) -> Config:
    capital_cfg = CapitalConfig(
        total=capital,
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
    config = MagicMock(spec=Config)
    config.capital = capital_cfg
    config.risk_limits = risk_limits
    config.trading_hours = trading_hours
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
    capital: float = CAPITAL,
) -> RiskManagementSystem:
    """Create an RMS instance with mocked dependencies."""
    config = _make_config(capital=capital)
    redis_client = MagicMock()
    event_bus = MagicMock()
    db_manager = MagicMock()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
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
    """
    )

    today_str = now.strftime("%Y-%m-%d")

    if daily_pnl != 0.0:
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "exit_price, quantity, entry_time, exit_time, realized_pnl, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "t1",
                "TEST",
                "BUY",
                "test",
                100,
                110,
                10,
                f"{today_str} 09:30:00",
                f"{today_str} 10:00:00",
                daily_pnl,
                95,
                115,
            ),
        )

    for i in range(open_positions):
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "quantity, entry_time, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"open-{i}", f"SYM{i}", "BUY", "test", 100, 10, f"{today_str} 09:30:00", 95, 115),
        )

    for i in range(orders_today):
        conn.execute(
            "INSERT INTO orders (order_id, symbol, side, order_type, quantity, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"ord-{i}", "TEST", "BUY", "MARKET", 10, "PLACED", f"{today_str} 10:00:00"),
        )

    if last_trade is not None:
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "exit_price, quantity, entry_time, exit_time, realized_pnl, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "last-trade",
                "TEST",
                "BUY",
                "test",
                100,
                95,
                10,
                f"{today_str} 09:30:00",
                last_trade["exit_time"],
                last_trade["realized_pnl"],
                90,
                115,
            ),
        )

    conn.commit()
    db_manager.connect_sqlite.return_value = conn
    db_manager.execute_with_retry = MagicMock()

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

    return RiskManagementSystem(
        config=config,
        redis_client=redis_client,
        event_bus=event_bus,
        db_manager=db_manager,
        now_fn=lambda: now,
    )


# ---------------------------------------------------------------------------
# Rejection cause strategies – generate signals that will be rejected
# ---------------------------------------------------------------------------

# Strategy: generate a time outside trading hours (before 9:30 or after 15:10)
outside_trading_hours = st.one_of(
    # Before 9:30 AM
    st.builds(
        lambda h, m: datetime(2024, 1, 15, h, m),
        h=st.integers(min_value=0, max_value=9),
        m=st.integers(min_value=0, max_value=29),
    ),
    # After 3:10 PM
    st.builds(
        lambda h, m: datetime(2024, 1, 15, h, m),
        h=st.integers(min_value=15, max_value=23),
        m=st.integers(min_value=11, max_value=59),
    ),
)


# ---------------------------------------------------------------------------
# Property 38: Rejection Logging
# ---------------------------------------------------------------------------


class TestRejectionLoggingKillSwitch:
    """**Property 38: Rejection Logging**
    **Validates: Requirements 9.11**

    For any rejected order (kill switch active), the rejection SHALL be
    published to stream:rejections and logged to audit_log table.
    """

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY"]),
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_kill_switch_rejection_publishes_and_logs(self, symbol, side, entry_price):
        """When kill switch is active, validate_order rejects and log_rejection
        publishes to stream:rejections and writes to audit_log.

        **Validates: Requirements 9.11**
        """
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal(symbol=symbol, side=side, entry_price=entry_price)
        result = rms.validate_order(signal)

        assert not result.is_valid
        assert result.rejection_reason is not None

        # Call log_rejection
        rms.log_rejection(signal, result)

        # Verify event_bus.publish was called with stream:rejections
        rms._event_bus.publish.assert_called_once()
        call_args = rms._event_bus.publish.call_args
        assert (
            call_args[0][0] == REJECTION_STREAM
        ), f"Expected publish to '{REJECTION_STREAM}', got '{call_args[0][0]}'"
        published_msg = call_args[0][1]
        assert published_msg["symbol"] == symbol
        assert published_msg["side"] == side
        assert published_msg["rejection_reason"] == result.rejection_reason

        # Verify db.execute_with_retry was called for audit_log insertion
        rms._db.execute_with_retry.assert_called_once()
        db_call_args = rms._db.execute_with_retry.call_args
        query = db_call_args[0][0]
        assert "audit_log" in query
        assert "INSERT" in query.upper()
        params = db_call_args[0][1]
        assert params[0] == "ORDER_REJECTED"
        assert params[1] == "RMS"


class TestRejectionLoggingOutsideTradingHours:
    """**Property 38: Rejection Logging**
    **Validates: Requirements 9.11**

    For any rejected order (outside trading hours), the rejection SHALL be
    published to stream:rejections and logged to audit_log table.
    """

    @given(
        now=outside_trading_hours,
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK"]),
    )
    @settings(max_examples=100)
    def test_trading_hours_rejection_publishes_and_logs(self, now, symbol):
        """When outside trading hours, validate_order rejects and log_rejection
        publishes to stream:rejections and writes to audit_log.

        **Validates: Requirements 9.11**
        """
        rms = _make_rms(now=now)
        signal = _make_signal(symbol=symbol)
        result = rms.validate_order(signal)

        assert not result.is_valid

        rms.log_rejection(signal, result)

        # Verify event_bus.publish was called with stream:rejections
        rms._event_bus.publish.assert_called_once()
        call_args = rms._event_bus.publish.call_args
        assert call_args[0][0] == REJECTION_STREAM

        # Verify db.execute_with_retry was called for audit_log insertion
        rms._db.execute_with_retry.assert_called_once()
        db_call_args = rms._db.execute_with_retry.call_args
        query = db_call_args[0][0]
        assert "audit_log" in query
        params = db_call_args[0][1]
        assert params[0] == "ORDER_REJECTED"


class TestRejectionLoggingMetadataCompleteness:
    """**Property 38: Rejection Logging**
    **Validates: Requirements 9.11**

    For any rejected order, the published rejection message and audit_log
    entry SHALL contain the signal details and rejection reason.
    """

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]),
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_rejection_metadata_contains_signal_details(self, symbol, side, entry_price):
        """The audit_log metadata for a rejection SHALL contain signal_id,
        symbol, side, strategy, entry_price, and check results.

        **Validates: Requirements 9.11**
        """
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal(symbol=symbol, side=side, entry_price=entry_price)
        result = rms.validate_order(signal)

        rms.log_rejection(signal, result)

        # Verify audit_log metadata contains signal details
        db_call_args = rms._db.execute_with_retry.call_args
        params = db_call_args[0][1]
        metadata = json.loads(params[3])

        assert metadata["signal_id"] == signal.signal_id
        assert metadata["symbol"] == symbol
        assert metadata["side"] == side
        assert metadata["strategy"] == signal.strategy
        assert metadata["entry_price"] == entry_price
        assert "checks_passed" in metadata
        assert "checks_failed" in metadata


class TestValidOrdersDoNotTriggerRejectionLogging:
    """**Property 38: Rejection Logging**
    **Validates: Requirements 9.11**

    For any valid order, log_rejection SHALL NOT publish to
    stream:rejections or write to audit_log.
    """

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]),
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0, max_value=2000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_valid_orders_skip_rejection_logging(self, symbol, side, entry_price):
        """When an order passes all checks, calling log_rejection SHALL
        not publish or write anything.

        **Validates: Requirements 9.11**
        """
        # Create RMS with all checks passing (within trading hours, no kill switch, etc.)
        rms = _make_rms(
            now=datetime(2024, 1, 15, 10, 30),
            kill_switch_active=False,
            daily_pnl=0.0,
            open_positions=0,
            orders_today=0,
        )
        signal = _make_signal(symbol=symbol, side=side, entry_price=entry_price)
        result = rms.validate_order(signal)

        assert result.is_valid, f"Expected valid order but got rejection: {result.rejection_reason}"

        # Call log_rejection with a valid result – should be a no-op
        rms.log_rejection(signal, result)

        # Verify event_bus.publish was NOT called
        rms._event_bus.publish.assert_not_called()

        # Verify db.execute_with_retry was NOT called
        rms._db.execute_with_retry.assert_not_called()
