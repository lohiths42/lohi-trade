"""Property-based tests for RMS Pre-Order Check Execution.

Verifies that for any signal submitted to the RMS, all 9 pre-order checks
are executed and the result contains exactly 9 check names across
checks_passed and checks_failed combined.

**Property 27: RMS Pre-Order Check Execution**
**Validates: Requirements 9.1**

The 9 expected check names are:
  kill_switch, trading_hours, daily_loss_limit, position_limit,
  position_size_limit, order_count_limit, cooldown, volatility_guard,
  bias_filter
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

from hypothesis import given, settings
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

# The 9 expected check names in execution order
EXPECTED_CHECKS = frozenset({
    "kill_switch",
    "trading_hours",
    "daily_loss_limit",
    "position_limit",
    "position_size_limit",
    "order_count_limit",
    "cooldown",
    "volatility_guard",
    "bias_filter",
})

# NSE symbols for generation
NSE_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT",
    "WIPRO", "AXISBANK", "MARUTI", "TATAMOTORS", "SUNPHARMA",
]

STRATEGIES = ["MeanReversion", "TrendFollowing", "ORB"]
SIDES = ["BUY", "SELL"]
BIASES = ["BULLISH", "BEARISH", "NEUTRAL", None]


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_symbol = st.sampled_from(NSE_SYMBOLS)
_side = st.sampled_from(SIDES)
_entry_price = st.floats(min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False)
_quantity = st.integers(min_value=0, max_value=100)
_strategy = st.sampled_from(STRATEGIES)
_bias = st.sampled_from(BIASES)
_kill_switch = st.booleans()
_daily_pnl = st.floats(min_value=-10000.0, max_value=10000.0, allow_nan=False, allow_infinity=False)
_open_positions = st.integers(min_value=0, max_value=10)
_orders_today = st.integers(min_value=0, max_value=30)
_capital = st.floats(min_value=50000.0, max_value=500000.0, allow_nan=False, allow_infinity=False)
_max_positions = st.integers(min_value=1, max_value=10)
_max_orders = st.integers(min_value=5, max_value=50)


def _make_indicator_set(symbol: str) -> IndicatorSet:
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


def _make_signal(symbol: str, side: str, entry_price: float, quantity: int, strategy: str) -> Signal:
    """Create a Signal with the given parameters and derived stop/target."""
    if side == "BUY":
        stop_loss = entry_price * 0.98  # 2% below entry
        target = entry_price * 1.03     # 3% above entry
    else:
        stop_loss = entry_price * 1.02  # 2% above entry
        target = entry_price * 0.97     # 3% below entry

    return Signal(
        signal_id="prop-test-signal",
        symbol=symbol,
        strategy=strategy,
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        timestamp=datetime(2024, 1, 15, 10, 30),
        indicators=_make_indicator_set(symbol),
    )


def _make_config(capital: float = 200000.0, max_positions: int = 5, max_orders: int = 20) -> Config:
    """Create a Config with the given parameters."""
    capital_cfg = CapitalConfig(
        total=capital,
        risk_per_trade_pct=1.0,
        max_position_size_pct=20.0,
        max_daily_loss_pct=2.0,
    )
    risk_limits = RiskLimitsConfig(
        max_open_positions=max_positions,
        max_orders_per_day=max_orders,
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
    config: Config,
    kill_switch_active: bool = False,
    daily_pnl: float = 0.0,
    open_positions: int = 0,
    orders_today: int = 0,
    bias_value: str = None,
    signal_symbol: str = "RELIANCE",
) -> RiskManagementSystem:
    """Create an RMS with mocked dependencies for property testing."""
    now = datetime(2024, 1, 15, 10, 30)  # During trading hours

    redis_client = MagicMock()
    event_bus = MagicMock()
    db_manager = MagicMock()

    # In-memory SQLite
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

    # Insert daily P&L trade if non-zero
    if daily_pnl != 0.0:
        conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, "
            "exit_price, quantity, entry_time, exit_time, realized_pnl, stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "TEST", "BUY", "test", 100, 110, 10,
             f"{today_str} 09:30:00", f"{today_str} 10:00:00", daily_pnl, 95, 115),
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

    conn.commit()
    db_manager.connect_sqlite.return_value = conn
    db_manager.execute_with_retry = MagicMock()

    # Redis mock
    def redis_get(key):
        if key == RiskManagementSystem.KILL_SWITCH_KEY:
            return "true" if kill_switch_active else "false"
        if key == "nifty:current_price":
            return None  # No volatility data by default
        if key == "nifty:window_start_price":
            return None
        if bias_value and key == f"bias:{signal_symbol}":
            return bias_value
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
# Property tests
# ---------------------------------------------------------------------------


class TestRMSPreOrderCheckExecution:
    """**Property 27: RMS Pre-Order Check Execution**
    **Validates: Requirements 9.1**

    For any signal submitted to the RMS, all 9 pre-order checks SHALL be
    executed and the result SHALL contain exactly 9 check names across
    checks_passed and checks_failed combined.
    """

    @given(
        symbol=_symbol,
        side=_side,
        entry_price=_entry_price,
        quantity=_quantity,
        strategy=_strategy,
        kill_switch=_kill_switch,
        bias=_bias,
    )
    @settings(max_examples=100)
    def test_always_executes_all_9_checks(
        self, symbol, side, entry_price, quantity, strategy, kill_switch, bias,
    ):
        """For any valid signal and RMS configuration, validate_order always
        returns a ValidationResult with exactly 9 checks total.

        **Validates: Requirements 9.1**
        """
        config = _make_config()
        rms = _make_rms(
            config=config,
            kill_switch_active=kill_switch,
            bias_value=bias,
            signal_symbol=symbol,
        )
        signal = _make_signal(symbol, side, entry_price, quantity, strategy)

        result = rms.validate_order(signal)

        total_checks = set(result.checks_passed) | set(result.checks_failed)
        assert len(result.checks_passed) + len(result.checks_failed) == 9, (
            f"Expected 9 total checks, got {len(result.checks_passed)} passed + "
            f"{len(result.checks_failed)} failed = "
            f"{len(result.checks_passed) + len(result.checks_failed)}"
        )
        assert total_checks == EXPECTED_CHECKS, (
            f"Expected checks {EXPECTED_CHECKS}, got {total_checks}"
        )

    @given(
        symbol=_symbol,
        side=_side,
        entry_price=_entry_price,
        quantity=_quantity,
        strategy=_strategy,
        daily_pnl=_daily_pnl,
        open_positions=_open_positions,
        orders_today=_orders_today,
    )
    @settings(max_examples=100)
    def test_check_count_with_varied_state(
        self, symbol, side, entry_price, quantity, strategy,
        daily_pnl, open_positions, orders_today,
    ):
        """For any combination of RMS state (daily P&L, open positions,
        order count), all 9 checks are still executed.

        **Validates: Requirements 9.1**
        """
        config = _make_config()
        rms = _make_rms(
            config=config,
            daily_pnl=daily_pnl,
            open_positions=open_positions,
            orders_today=orders_today,
            signal_symbol=symbol,
        )
        signal = _make_signal(symbol, side, entry_price, quantity, strategy)

        result = rms.validate_order(signal)

        total_checks = set(result.checks_passed) | set(result.checks_failed)
        assert len(result.checks_passed) + len(result.checks_failed) == 9, (
            f"Expected 9 total checks, got {len(result.checks_passed)} passed + "
            f"{len(result.checks_failed)} failed = "
            f"{len(result.checks_passed) + len(result.checks_failed)}"
        )
        assert total_checks == EXPECTED_CHECKS, (
            f"Expected checks {EXPECTED_CHECKS}, got {total_checks}"
        )

    @given(
        symbol=_symbol,
        side=_side,
        entry_price=_entry_price,
        quantity=_quantity,
        strategy=_strategy,
        capital=_capital,
        max_positions=_max_positions,
        max_orders=_max_orders,
    )
    @settings(max_examples=100)
    def test_check_names_with_varied_config(
        self, symbol, side, entry_price, quantity, strategy,
        capital, max_positions, max_orders,
    ):
        """For any RMS configuration (capital, position limits, order limits),
        the exact 9 check names always appear in the result.

        **Validates: Requirements 9.1**
        """
        config = _make_config(
            capital=capital,
            max_positions=max_positions,
            max_orders=max_orders,
        )
        rms = _make_rms(config=config, signal_symbol=symbol)
        signal = _make_signal(symbol, side, entry_price, quantity, strategy)

        result = rms.validate_order(signal)

        all_check_names = result.checks_passed + result.checks_failed
        assert len(all_check_names) == 9, (
            f"Expected 9 check names, got {len(all_check_names)}: {all_check_names}"
        )
        assert set(all_check_names) == EXPECTED_CHECKS, (
            f"Check names mismatch: expected {EXPECTED_CHECKS}, got {set(all_check_names)}"
        )

    @given(
        symbol=_symbol,
        side=_side,
        entry_price=_entry_price,
        quantity=_quantity,
        strategy=_strategy,
    )
    @settings(max_examples=50)
    def test_no_duplicate_check_names(
        self, symbol, side, entry_price, quantity, strategy,
    ):
        """No check name appears in both checks_passed and checks_failed.

        **Validates: Requirements 9.1**
        """
        config = _make_config()
        rms = _make_rms(config=config, signal_symbol=symbol)
        signal = _make_signal(symbol, side, entry_price, quantity, strategy)

        result = rms.validate_order(signal)

        overlap = set(result.checks_passed) & set(result.checks_failed)
        assert len(overlap) == 0, (
            f"Check names appear in both passed and failed: {overlap}"
        )
