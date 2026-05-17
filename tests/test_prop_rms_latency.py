"""Property-based test for RMS order validation latency.

**Property 37: Order Validation Latency**
For any order submitted to the RMS, the validation latency_ms SHALL be a
non-negative number and SHALL be recorded in the ValidationResult.
Under normal conditions (in-memory SQLite, no network), latency is under 50ms.

**Validates: Requirements 9.10**
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.execution.rms import RiskManagementSystem, ValidationResult
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal
from src.utils.config import (
    CapitalConfig,
    Config,
    RiskLimitsConfig,
    TradingHoursConfig,
)

# ---------------------------------------------------------------------------
# Shared helpers (same pattern as tests/test_prop_rms_individual_checks.py)
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
) -> Signal:
    return Signal(
        signal_id="prop-latency-test-signal",
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
    bias_map: dict = None,
    capital: float = CAPITAL,
) -> RiskManagementSystem:
    """Create an RMS instance with mocked dependencies for latency testing."""
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
    conn.commit()
    db_manager.connect_sqlite.return_value = conn
    db_manager.execute_with_retry = MagicMock()

    def redis_get(key):
        if key == RiskManagementSystem.KILL_SWITCH_KEY:
            return "true" if kill_switch_active else "false"
        if key == "nifty:current_price":
            return None
        if key == "nifty:window_start_price":
            return None
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
# Property 37: Order Validation Latency
# ---------------------------------------------------------------------------


class TestOrderValidationLatency:
    """**Property 37: Order Validation Latency**
    **Validates: Requirements 9.10**

    For any signal submitted to the RMS, the validation latency_ms SHALL be
    a non-negative number and SHALL be recorded in the ValidationResult.
    Under normal conditions (in-memory SQLite, no network), latency is under 50ms.
    """

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]),
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=25)
    def test_latency_is_non_negative_float(self, symbol, side, entry_price):
        """For any valid signal, validate_order returns a ValidationResult
        with latency_ms that is a non-negative float.

        **Validates: Requirements 9.10**
        """
        rms = _make_rms()
        signal = _make_signal(symbol=symbol, side=side, entry_price=entry_price)
        result = rms.validate_order(signal)

        assert isinstance(result, ValidationResult)
        assert isinstance(
            result.latency_ms, float
        ), f"latency_ms should be a float, got {type(result.latency_ms)}"
        assert result.latency_ms >= 0, f"latency_ms should be non-negative, got {result.latency_ms}"

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]),
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=25)
    def test_latency_under_50ms_normal_conditions(self, symbol, side, entry_price):
        """Under normal conditions (in-memory SQLite, no network), validation
        latency should be under 50ms.

        **Validates: Requirements 9.10**
        """
        rms = _make_rms()
        signal = _make_signal(symbol=symbol, side=side, entry_price=entry_price)
        result = rms.validate_order(signal)

        assert result.latency_ms < 50, (
            f"Validation latency {result.latency_ms:.2f}ms exceeds 50ms threshold "
            f"for symbol={symbol} side={side}"
        )

    @given(
        kill_switch=st.booleans(),
        bias=st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL", None]),
    )
    @settings(max_examples=25)
    def test_latency_recorded_regardless_of_outcome(self, kill_switch, bias):
        """Whether the order is accepted or rejected, latency_ms SHALL always
        be recorded as a non-negative float in the ValidationResult.

        **Validates: Requirements 9.10**
        """
        bias_map = {"RELIANCE": bias} if bias else None
        rms = _make_rms(kill_switch_active=kill_switch, bias_map=bias_map)
        signal = _make_signal(symbol="RELIANCE", side="BUY")
        result = rms.validate_order(signal)

        assert isinstance(
            result.latency_ms, float
        ), f"latency_ms should be a float, got {type(result.latency_ms)}"
        assert result.latency_ms >= 0, f"latency_ms should be non-negative, got {result.latency_ms}"
