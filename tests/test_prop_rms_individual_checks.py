"""Property-based tests for each individual RMS pre-order check.

Tests Properties 28-36 from the design document, verifying that each
of the 9 RMS checks correctly rejects orders when their specific
conditions are violated.

**Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9**
"""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.execution.rms import RiskManagementSystem
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal
from src.utils.config import (
    CapitalConfig,
    Config,
    RiskLimitsConfig,
    TradingHoursConfig,
)

# ---------------------------------------------------------------------------
# Shared helpers (following patterns from tests/test_rms.py)
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
        signal_id="prop-test-signal",
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
# Property 28: Daily Loss Limit Enforcement
# ---------------------------------------------------------------------------


class TestDailyLossLimitEnforcement:
    """**Property 28: Daily Loss Limit Enforcement**
    **Validates: Requirements 9.2**

    For any daily P&L that exceeds -2% of capital, the daily_loss_limit
    check SHALL fail.
    """

    @given(
        loss_pct=st.floats(min_value=2.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        capital=st.floats(
            min_value=50000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=25)
    def test_rejects_when_daily_loss_exceeds_limit(self, loss_pct, capital):
        """For any daily P&L worse than -2% of capital, the daily_loss_limit
        check must appear in checks_failed.

        **Validates: Requirements 9.2**
        """
        daily_pnl = -(loss_pct / 100) * capital  # negative P&L exceeding limit

        rms = _make_rms(daily_pnl=daily_pnl, capital=capital)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert "daily_loss_limit" in result.checks_failed, (
            f"daily_loss_limit should fail for P&L={daily_pnl:.2f} "
            f"(limit={-(2.0/100)*capital:.2f})"
        )


# ---------------------------------------------------------------------------
# Property 29: Position Count Limit Enforcement
# ---------------------------------------------------------------------------


class TestPositionCountLimitEnforcement:
    """**Property 29: Position Count Limit Enforcement**
    **Validates: Requirements 9.3**

    For any open position count >= 5, the position_limit check SHALL fail.
    """

    @given(
        open_positions=st.integers(min_value=5, max_value=20),
    )
    @settings(max_examples=25)
    def test_rejects_when_position_count_at_or_above_limit(self, open_positions):
        """For any open position count >= 5, position_limit must fail.

        **Validates: Requirements 9.3**
        """
        rms = _make_rms(open_positions=open_positions)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert (
            "position_limit" in result.checks_failed
        ), f"position_limit should fail for {open_positions} open positions (limit=5)"


# ---------------------------------------------------------------------------
# Property 30: Position Size Limit Enforcement
# ---------------------------------------------------------------------------


class TestPositionSizeLimitEnforcement:
    """**Property 30: Position Size Limit Enforcement**
    **Validates: Requirements 9.4**

    For any order value > 20% of capital, the position_size_limit check
    SHALL fail.
    """

    @given(
        entry_price=st.floats(
            min_value=100.0, max_value=10000.0, allow_nan=False, allow_infinity=False
        ),
        quantity=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=25)
    def test_rejects_when_order_value_exceeds_limit(self, entry_price, quantity):
        """For any order where entry_price * quantity > 20% of capital,
        position_size_limit must fail.

        **Validates: Requirements 9.4**
        """
        order_value = entry_price * quantity
        max_value = CAPITAL * 0.20
        assume(order_value > max_value)

        rms = _make_rms()
        signal = _make_signal(entry_price=entry_price, quantity=quantity)
        result = rms.validate_order(signal)

        assert "position_size_limit" in result.checks_failed, (
            f"position_size_limit should fail for order_value={order_value:.2f} "
            f"(limit={max_value:.2f})"
        )


# ---------------------------------------------------------------------------
# Property 31: Order Count Limit Enforcement
# ---------------------------------------------------------------------------


class TestOrderCountLimitEnforcement:
    """**Property 31: Order Count Limit Enforcement**
    **Validates: Requirements 9.5**

    For any order count >= 20, the order_count_limit check SHALL fail.
    """

    @given(
        orders_today=st.integers(min_value=20, max_value=50),
    )
    @settings(max_examples=25)
    def test_rejects_when_order_count_at_or_above_limit(self, orders_today):
        """For any order count >= 20, order_count_limit must fail.

        **Validates: Requirements 9.5**
        """
        rms = _make_rms(orders_today=orders_today)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert (
            "order_count_limit" in result.checks_failed
        ), f"order_count_limit should fail for {orders_today} orders (limit=20)"


# ---------------------------------------------------------------------------
# Property 32: Cooldown Period Enforcement
# ---------------------------------------------------------------------------


class TestCooldownPeriodEnforcement:
    """**Property 32: Cooldown Period Enforcement**
    **Validates: Requirements 9.6**

    For any losing trade exited < 5 minutes ago, the cooldown check
    SHALL fail.
    """

    @given(
        seconds_ago=st.integers(min_value=0, max_value=299),
        loss_amount=st.floats(
            min_value=0.01, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=25)
    def test_rejects_during_cooldown_after_loss(self, seconds_ago, loss_amount):
        """For any losing trade exited less than 5 minutes (300s) ago,
        cooldown must fail.

        **Validates: Requirements 9.6**
        """
        now = datetime(2024, 1, 15, 10, 30)
        exit_time = now - timedelta(seconds=seconds_ago)

        rms = _make_rms(
            now=now,
            last_trade={
                "exit_time": exit_time.isoformat(),
                "realized_pnl": -loss_amount,
            },
        )
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert "cooldown" in result.checks_failed, (
            f"cooldown should fail for losing trade exited {seconds_ago}s ago " f"(cooldown=300s)"
        )


# ---------------------------------------------------------------------------
# Property 33: Kill Switch Enforcement
# ---------------------------------------------------------------------------


class TestKillSwitchEnforcement:
    """**Property 33: Kill Switch Enforcement**
    **Validates: Requirements 9.7**

    When kill switch is active, the kill_switch check SHALL always fail.
    """

    @given(
        side=st.sampled_from(["BUY", "SELL"]),
        entry_price=st.floats(
            min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
        quantity=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=25)
    def test_always_rejects_when_kill_switch_active(self, side, entry_price, quantity):
        """For any signal, when kill switch is active, kill_switch must fail.

        **Validates: Requirements 9.7**
        """
        rms = _make_rms(kill_switch_active=True)
        signal = _make_signal(side=side, entry_price=entry_price, quantity=quantity)
        result = rms.validate_order(signal)

        assert (
            "kill_switch" in result.checks_failed
        ), "kill_switch should fail when kill switch is active"
        assert not result.is_valid, "Order should be rejected when kill switch is active"


# ---------------------------------------------------------------------------
# Property 34: Volatility Guard Enforcement
# ---------------------------------------------------------------------------


class TestVolatilityGuardEnforcement:
    """**Property 34: Volatility Guard Enforcement**
    **Validates: Requirements 9.8**

    For any Nifty drop > 2% in 10 minutes, the volatility_guard check
    SHALL fail.
    """

    @given(
        drop_pct=st.floats(min_value=2.01, max_value=20.0, allow_nan=False, allow_infinity=False),
        window_start_price=st.floats(
            min_value=15000.0, max_value=25000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=25)
    def test_rejects_when_nifty_drops_over_threshold(self, drop_pct, window_start_price):
        """For any Nifty drop > 2%, volatility_guard must fail.

        **Validates: Requirements 9.8**
        """
        current_price = window_start_price * (1 - drop_pct / 100)

        rms = _make_rms(
            nifty_current=str(current_price),
            nifty_window_start=str(window_start_price),
        )
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert "volatility_guard" in result.checks_failed, (
            f"volatility_guard should fail for Nifty drop of {drop_pct:.2f}% " f"(threshold=2%)"
        )


# ---------------------------------------------------------------------------
# Property 35: Trading Hours Enforcement
# ---------------------------------------------------------------------------


class TestTradingHoursEnforcement:
    """**Property 35: Trading Hours Enforcement**
    **Validates: Requirements 9.9**

    For any time outside 9:30 AM - 3:10 PM, the trading_hours check
    SHALL fail.
    """

    @given(
        hour=st.integers(min_value=0, max_value=9),
        minute=st.integers(min_value=0, max_value=59),
    )
    @settings(max_examples=25)
    def test_rejects_before_trading_start(self, hour, minute):
        """For any time before 9:30 AM, trading_hours must fail.

        **Validates: Requirements 9.9**
        """
        # Ensure we're strictly before 9:30
        total_minutes = hour * 60 + minute
        assume(total_minutes < 9 * 60 + 30)

        now = datetime(2024, 1, 15, hour, minute)
        rms = _make_rms(now=now)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert (
            "trading_hours" in result.checks_failed
        ), f"trading_hours should fail at {hour:02d}:{minute:02d} (before 09:30)"

    @given(
        hour=st.integers(min_value=15, max_value=23),
        minute=st.integers(min_value=0, max_value=59),
    )
    @settings(max_examples=25)
    def test_rejects_after_trading_end(self, hour, minute):
        """For any time after 3:10 PM, trading_hours must fail.

        **Validates: Requirements 9.9**
        """
        total_minutes = hour * 60 + minute
        assume(total_minutes > 15 * 60 + 10)

        now = datetime(2024, 1, 15, hour, minute)
        rms = _make_rms(now=now)
        signal = _make_signal()
        result = rms.validate_order(signal)

        assert (
            "trading_hours" in result.checks_failed
        ), f"trading_hours should fail at {hour:02d}:{minute:02d} (after 15:10)"


# ---------------------------------------------------------------------------
# Property 36: Bias Filter for BUY Signals
# ---------------------------------------------------------------------------


class TestBiasFilterBuySignals:
    """**Property 36: Bias Filter for BUY Signals**
    **Validates: Requirements 9.9**

    For any BUY signal with BEARISH bias, the bias_filter check SHALL fail.
    """

    @given(
        symbol=st.sampled_from(["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]),
        entry_price=st.floats(
            min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=25)
    def test_rejects_buy_when_bearish(self, symbol, entry_price):
        """For any BUY signal with BEARISH bias, bias_filter must fail.

        **Validates: Requirements 9.9**
        """
        rms = _make_rms(bias_map={symbol: "BEARISH"})
        signal = _make_signal(symbol=symbol, side="BUY", entry_price=entry_price)
        result = rms.validate_order(signal)

        assert (
            "bias_filter" in result.checks_failed
        ), f"bias_filter should fail for BUY signal on {symbol} with BEARISH bias"
