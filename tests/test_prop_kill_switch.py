"""Property-based tests for the Kill Switch module.

Properties tested:
- Property 57: Kill Switch Order Cancellation
- Property 58: Automatic Kill Switch on Volatility
- Property 59: Automatic Kill Switch on Daily Loss
- Property 60: Kill Switch Notification
- Property 61: Kill Switch Manual Deactivation

Requirements: 13.1, 13.2, 13.3, 13.6, 13.7, 13.8, 13.9
"""

from datetime import datetime
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.execution.kill_switch import NOTIFICATION_STREAM, KillSwitch
from src.utils.config import CapitalConfig, Config, RiskLimitsConfig, TradingHoursConfig

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_reason = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
    ),
)
_num_orders = st.integers(min_value=0, max_value=20)
_capital = st.floats(
    min_value=10_000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)
_max_loss_pct = st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False)
_volatility_threshold = st.floats(
    min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False
)
_nifty_price = st.floats(min_value=1000.0, max_value=30000.0, allow_nan=False, allow_infinity=False)
_daily_pnl = st.floats(
    min_value=-100_000.0, max_value=100_000.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    capital: float = 200_000.0,
    max_loss_pct: float = 2.0,
    vol_threshold: float = 2.0,
) -> Config:
    cap = CapitalConfig(
        total=capital,
        risk_per_trade_pct=1.0,
        max_position_size_pct=20.0,
        max_daily_loss_pct=max_loss_pct,
    )
    risk = RiskLimitsConfig(
        max_open_positions=5,
        max_orders_per_day=20,
        cooldown_after_loss_minutes=5,
        volatility_guard_threshold_pct=vol_threshold,
        volatility_guard_window_minutes=10,
    )
    hours = TradingHoursConfig(
        market_open="09:15",
        trading_start="09:30",
        trading_end="15:10",
        square_off_time="15:15",
        market_close="15:30",
    )
    config = MagicMock(spec=Config)
    config.capital = cap
    config.risk_limits = risk
    config.trading_hours = hours
    return config


def _make_redis(
    active: bool = False, reason: str = None, nifty_current: str = None, nifty_start: str = None
) -> MagicMock:
    store = {}
    if active:
        store["killswitch:active"] = "true"
    else:
        store["killswitch:active"] = "false"
    if reason:
        store["killswitch:reason"] = reason
    if nifty_current is not None:
        store["nifty:current_price"] = nifty_current
    if nifty_start is not None:
        store["nifty:window_start_price"] = nifty_start

    redis = MagicMock()
    redis.get.side_effect = lambda key: store.get(key)

    def mock_set(key, value, **kwargs):
        store[key] = value
        return True

    def mock_delete(*keys):
        for k in keys:
            store.pop(k, None)
        return len(keys)

    redis.set.side_effect = mock_set
    redis.delete.side_effect = mock_delete
    return redis


def _make_db(daily_pnl: float = 0.0) -> MagicMock:
    db = MagicMock()
    conn = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, key: daily_pnl if key == "total_pnl" else None
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn.execute.return_value = cursor
    db.connect_sqlite.return_value = conn
    db.execute_with_retry.return_value = None
    return db


def _make_oms(order_ids: list = None) -> MagicMock:
    oms = MagicMock()
    if order_ids is None:
        order_ids = []
    oms._pending_orders = {oid: MagicMock() for oid in order_ids}
    oms.cancel_order.return_value = True
    return oms


def _build_ks(
    capital=200_000.0,
    max_loss_pct=2.0,
    vol_threshold=2.0,
    active=False,
    reason=None,
    daily_pnl=0.0,
    nifty_current=None,
    nifty_start=None,
    order_ids=None,
):
    config = _make_config(capital, max_loss_pct, vol_threshold)
    redis = _make_redis(active, reason, nifty_current, nifty_start)
    db = _make_db(daily_pnl)
    oms = _make_oms(order_ids)
    event_bus = MagicMock()
    event_bus.publish.return_value = "msg-id"
    now = datetime(2024, 1, 15, 10, 30)
    ks = KillSwitch(
        config=config,
        redis_client=redis,
        oms=oms,
        db_manager=db,
        event_bus=event_bus,
        now_fn=lambda: now,
    )
    return ks, redis, oms, db, event_bus


# ---------------------------------------------------------------------------
# Property 57: Kill Switch Order Cancellation
# For any kill switch activation, all pending orders should be cancelled.
# ---------------------------------------------------------------------------


@given(
    reason=_reason,
    num_orders=_num_orders,
)
@settings(max_examples=50)
def test_prop_57_kill_switch_order_cancellation(reason, num_orders):
    """Property 57: All pending orders are cancelled on activation."""
    order_ids = [f"order-{i}" for i in range(num_orders)]
    ks, _, oms, _, _ = _build_ks(order_ids=order_ids)

    ks.activate(reason)

    assert ks.is_active() is True
    assert oms.cancel_order.call_count == num_orders
    for oid in order_ids:
        oms.cancel_order.assert_any_call(oid)


# ---------------------------------------------------------------------------
# Property 58: Automatic Kill Switch on Volatility
# For any Nifty drop exceeding threshold, kill switch activates.
# ---------------------------------------------------------------------------


@given(
    start_price=_nifty_price,
    vol_threshold=_volatility_threshold,
    extra_drop_pct=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_prop_58_automatic_kill_switch_on_volatility(
    start_price,
    vol_threshold,
    extra_drop_pct,
):
    """Property 58: Kill switch activates when Nifty drop > threshold."""
    # Compute a current price that drops more than the threshold
    drop_pct = vol_threshold + extra_drop_pct
    current_price = start_price * (1 - drop_pct / 100)

    ks, *_ = _build_ks(
        vol_threshold=vol_threshold,
        nifty_current=str(current_price),
        nifty_start=str(start_price),
    )

    result = ks.check_nifty_volatility()
    assert result is True
    assert ks.is_active() is True


@given(
    start_price=_nifty_price,
    vol_threshold=_volatility_threshold,
    below_drop_pct=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_prop_58_no_activation_below_threshold(
    start_price,
    vol_threshold,
    below_drop_pct,
):
    """Property 58 (negative): No activation when drop < threshold."""
    # Drop is below_drop_pct * threshold, so always < threshold
    drop_pct = vol_threshold * below_drop_pct
    current_price = start_price * (1 - drop_pct / 100)

    ks, *_ = _build_ks(
        vol_threshold=vol_threshold,
        nifty_current=str(current_price),
        nifty_start=str(start_price),
    )

    result = ks.check_nifty_volatility()
    assert result is False
    assert ks.is_active() is False


# ---------------------------------------------------------------------------
# Property 59: Automatic Kill Switch on Daily Loss
# For any daily P&L below -max_daily_loss_pct of capital, activates.
# ---------------------------------------------------------------------------


@given(
    capital=_capital,
    max_loss_pct=_max_loss_pct,
    extra_loss=st.floats(min_value=0.01, max_value=50_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_prop_59_automatic_kill_switch_on_daily_loss(
    capital,
    max_loss_pct,
    extra_loss,
):
    """Property 59: Kill switch activates when daily loss exceeds limit."""
    loss_limit = -(max_loss_pct / 100) * capital
    daily_pnl = loss_limit - extra_loss  # Exceeds the limit

    ks, *_ = _build_ks(
        capital=capital,
        max_loss_pct=max_loss_pct,
        daily_pnl=daily_pnl,
    )

    result = ks.check_daily_loss()
    assert result is True
    assert ks.is_active() is True


@given(
    capital=_capital,
    max_loss_pct=_max_loss_pct,
    within_pct=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_prop_59_no_activation_within_limits(
    capital,
    max_loss_pct,
    within_pct,
):
    """Property 59 (negative): No activation when loss within limits."""
    loss_limit = -(max_loss_pct / 100) * capital
    # daily_pnl is within_pct fraction of the limit (closer to zero)
    daily_pnl = loss_limit * within_pct

    ks, *_ = _build_ks(
        capital=capital,
        max_loss_pct=max_loss_pct,
        daily_pnl=daily_pnl,
    )

    result = ks.check_daily_loss()
    assert result is False
    assert ks.is_active() is False


# ---------------------------------------------------------------------------
# Property 60: Kill Switch Notification
# For any activation, a notification event is published with the reason.
# ---------------------------------------------------------------------------


@given(reason=_reason)
@settings(max_examples=50)
def test_prop_60_kill_switch_notification(reason):
    """Property 60: Notification published on every activation."""
    ks, _, _, _, event_bus = _build_ks()

    ks.activate(reason)

    event_bus.publish.assert_called_once()
    call_args = event_bus.publish.call_args
    stream = call_args[0][0]
    msg = call_args[0][1]

    assert stream == NOTIFICATION_STREAM
    assert msg["type"] == "KILL_SWITCH"
    assert msg["reason"] == reason
    assert "timestamp" in msg


# ---------------------------------------------------------------------------
# Property 61: Kill Switch Manual Deactivation
# Kill switch remains active until manually deactivated.
# ---------------------------------------------------------------------------


@given(
    reason=_reason,
    num_checks=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=50)
def test_prop_61_kill_switch_manual_deactivation(reason, num_checks):
    """Property 61: Kill switch stays active until explicit deactivation."""
    ks, *_ = _build_ks()

    ks.activate(reason)
    assert ks.is_active() is True

    # Running checks multiple times should not deactivate
    for _ in range(num_checks):
        assert ks.is_active() is True

    # Only explicit deactivation clears it
    ks.deactivate()
    assert ks.is_active() is False
    assert ks.get_reason() is None
