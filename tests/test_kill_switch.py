"""
Unit tests for the Kill Switch module.

Tests state management, automatic triggers, order cancellation,
notifications, audit logging, and manual deactivation requirement.

Requirements: 13.1, 13.2, 13.3, 13.6, 13.7, 13.8, 13.9
"""

import json
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from src.execution.kill_switch import KillSwitch, NOTIFICATION_STREAM
from src.utils.config import CapitalConfig, Config, RiskLimitsConfig, TradingHoursConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config() -> Config:
    """Create a minimal Config for KillSwitch testing."""
    capital = CapitalConfig(
        total=200_000.0,
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
    config.capital = capital
    config.risk_limits = risk_limits
    config.trading_hours = trading_hours
    return config


def _make_redis(kill_switch_active: bool = False, reason: str = None,
                nifty_current: str = None, nifty_start: str = None) -> MagicMock:
    """Create a mock Redis client."""
    store = {}
    if kill_switch_active:
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
    """Create a mock DatabaseConnectionManager."""
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


def _make_oms(pending_order_ids: list = None) -> MagicMock:
    """Create a mock OMS with pending orders."""
    oms = MagicMock()
    if pending_order_ids is None:
        pending_order_ids = []
    oms._pending_orders = {oid: MagicMock() for oid in pending_order_ids}
    oms.cancel_order.return_value = True
    return oms


def _make_kill_switch(
    kill_switch_active: bool = False,
    reason: str = None,
    daily_pnl: float = 0.0,
    nifty_current: str = None,
    nifty_start: str = None,
    pending_order_ids: list = None,
    now: datetime = None,
) -> tuple:
    """Create a KillSwitch with all mocked dependencies.

    Returns (kill_switch, redis, oms, db, event_bus).
    """
    config = _make_config()
    redis = _make_redis(kill_switch_active, reason, nifty_current, nifty_start)
    db = _make_db(daily_pnl)
    oms = _make_oms(pending_order_ids)
    event_bus = MagicMock()
    event_bus.publish.return_value = "msg-id-1"

    if now is None:
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
# State management tests
# ---------------------------------------------------------------------------


class TestKillSwitchState:
    """Tests for activate/deactivate/is_active/get_reason."""

    def test_activate_sets_redis_state(self):
        ks, redis, *_ = _make_kill_switch()
        ks.activate("Manual activation")
        redis.set.assert_any_call("killswitch:active", "true")
        redis.set.assert_any_call("killswitch:reason", "Manual activation")

    def test_deactivate_sets_redis_state(self):
        ks, redis, *_ = _make_kill_switch(kill_switch_active=True, reason="test")
        ks.deactivate()
        redis.set.assert_any_call("killswitch:active", "false")
        redis.delete.assert_called_with("killswitch:reason")

    def test_is_active_returns_true_when_active(self):
        ks, *_ = _make_kill_switch(kill_switch_active=True)
        assert ks.is_active() is True

    def test_is_active_returns_false_when_inactive(self):
        ks, *_ = _make_kill_switch(kill_switch_active=False)
        assert ks.is_active() is False

    def test_get_reason_returns_reason_when_active(self):
        ks, *_ = _make_kill_switch(kill_switch_active=True, reason="Nifty crash")
        assert ks.get_reason() == "Nifty crash"

    def test_get_reason_returns_none_when_inactive(self):
        ks, *_ = _make_kill_switch(kill_switch_active=False)
        assert ks.get_reason() is None

    def test_deactivation_clears_reason(self):
        ks, redis, *_ = _make_kill_switch(kill_switch_active=True, reason="test")
        ks.deactivate()
        # After deactivation, get_reason should return None
        assert ks.get_reason() is None

    def test_multiple_activations_update_reason(self):
        ks, redis, *_ = _make_kill_switch()
        ks.activate("First reason")
        assert ks.get_reason() == "First reason"
        ks.activate("Second reason")
        assert ks.get_reason() == "Second reason"


# ---------------------------------------------------------------------------
# Automatic trigger tests
# ---------------------------------------------------------------------------


class TestAutomaticTriggers:
    """Tests for check_nifty_volatility and check_daily_loss."""

    def test_nifty_volatility_activates_on_large_drop(self):
        # 3% drop: start=20000, current=19400
        ks, *_ = _make_kill_switch(
            nifty_current="19400", nifty_start="20000"
        )
        result = ks.check_nifty_volatility()
        assert result is True
        assert ks.is_active() is True

    def test_nifty_volatility_no_activation_below_threshold(self):
        # 1% drop: start=20000, current=19800
        ks, *_ = _make_kill_switch(
            nifty_current="19800", nifty_start="20000"
        )
        result = ks.check_nifty_volatility()
        assert result is False
        assert ks.is_active() is False

    def test_nifty_volatility_no_activation_on_rise(self):
        # Price went up
        ks, *_ = _make_kill_switch(
            nifty_current="20500", nifty_start="20000"
        )
        result = ks.check_nifty_volatility()
        assert result is False

    def test_nifty_volatility_no_data(self):
        ks, *_ = _make_kill_switch()  # No nifty prices in Redis
        result = ks.check_nifty_volatility()
        assert result is False

    def test_nifty_volatility_invalid_data(self):
        ks, *_ = _make_kill_switch(
            nifty_current="invalid", nifty_start="20000"
        )
        result = ks.check_nifty_volatility()
        assert result is False

    def test_daily_loss_activates_on_excess_loss(self):
        # Capital=200000, max_loss=2% => limit=-4000
        # daily_pnl=-5000 exceeds limit
        ks, *_ = _make_kill_switch(daily_pnl=-5000.0)
        result = ks.check_daily_loss()
        assert result is True
        assert ks.is_active() is True

    def test_daily_loss_no_activation_within_limits(self):
        # daily_pnl=-3000 is within -4000 limit
        ks, *_ = _make_kill_switch(daily_pnl=-3000.0)
        result = ks.check_daily_loss()
        assert result is False
        assert ks.is_active() is False

    def test_daily_loss_no_activation_on_profit(self):
        ks, *_ = _make_kill_switch(daily_pnl=5000.0)
        result = ks.check_daily_loss()
        assert result is False

    def test_run_checks_activates_on_volatility(self):
        ks, *_ = _make_kill_switch(
            nifty_current="19400", nifty_start="20000"
        )
        result = ks.run_checks()
        assert result is True
        assert ks.is_active() is True

    def test_run_checks_activates_on_daily_loss(self):
        ks, *_ = _make_kill_switch(daily_pnl=-5000.0)
        result = ks.run_checks()
        assert result is True

    def test_run_checks_no_activation_when_all_ok(self):
        ks, *_ = _make_kill_switch(
            nifty_current="19900", nifty_start="20000",
            daily_pnl=-1000.0,
        )
        result = ks.run_checks()
        assert result is False

    def test_run_checks_skips_when_already_active(self):
        ks, *_ = _make_kill_switch(
            kill_switch_active=True,
            nifty_current="19400", nifty_start="20000",
        )
        result = ks.run_checks()
        assert result is False  # Already active, no re-activation


# ---------------------------------------------------------------------------
# Order cancellation tests
# ---------------------------------------------------------------------------


class TestOrderCancellation:
    """Tests for cancel_all_pending_orders."""

    def test_all_pending_orders_cancelled(self):
        ks, _, oms, *_ = _make_kill_switch(
            pending_order_ids=["order-1", "order-2", "order-3"]
        )
        cancelled = ks.cancel_all_pending_orders()
        assert cancelled == 3
        assert oms.cancel_order.call_count == 3

    def test_no_pending_orders(self):
        ks, _, oms, *_ = _make_kill_switch(pending_order_ids=[])
        cancelled = ks.cancel_all_pending_orders()
        assert cancelled == 0
        oms.cancel_order.assert_not_called()

    def test_activation_cancels_orders(self):
        ks, _, oms, *_ = _make_kill_switch(
            pending_order_ids=["order-1", "order-2"]
        )
        ks.activate("Test activation")
        assert oms.cancel_order.call_count == 2

    def test_cancel_handles_failure_gracefully(self):
        ks, _, oms, *_ = _make_kill_switch(
            pending_order_ids=["order-1", "order-2"]
        )
        oms.cancel_order.side_effect = [True, Exception("Broker error")]
        cancelled = ks.cancel_all_pending_orders()
        assert cancelled == 1  # Only first succeeded


# ---------------------------------------------------------------------------
# Notification tests
# ---------------------------------------------------------------------------


class TestNotifications:
    """Tests for notification publishing on activation."""

    def test_notification_published_on_activation(self):
        ks, _, _, _, event_bus = _make_kill_switch()
        ks.activate("Test reason")
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == NOTIFICATION_STREAM
        msg = call_args[0][1]
        assert msg["type"] == "KILL_SWITCH"
        assert msg["reason"] == "Test reason"
        assert "timestamp" in msg

    def test_notification_not_published_on_deactivation(self):
        ks, _, _, _, event_bus = _make_kill_switch(kill_switch_active=True)
        ks.deactivate()
        event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Audit log tests
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for audit log entries."""

    def test_audit_log_on_activation(self):
        ks, _, _, db, _ = _make_kill_switch()
        ks.activate("Audit test")
        db.execute_with_retry.assert_called_once()
        call_args = db.execute_with_retry.call_args
        assert "KILL_SWITCH_ACTIVATED" in call_args[0][1]
        assert "KillSwitch" in call_args[0][1]

    def test_audit_log_on_deactivation(self):
        ks, _, _, db, _ = _make_kill_switch(kill_switch_active=True)
        ks.deactivate()
        db.execute_with_retry.assert_called_once()
        call_args = db.execute_with_retry.call_args
        assert "KILL_SWITCH_DEACTIVATED" in call_args[0][1]


# ---------------------------------------------------------------------------
# Manual deactivation requirement
# ---------------------------------------------------------------------------


class TestManualDeactivation:
    """Tests that kill switch requires manual deactivation."""

    def test_stays_active_after_activation(self):
        ks, *_ = _make_kill_switch()
        ks.activate("Test")
        # No automatic reset — still active
        assert ks.is_active() is True

    def test_stays_active_after_run_checks(self):
        ks, *_ = _make_kill_switch(
            nifty_current="19400", nifty_start="20000"
        )
        ks.run_checks()
        assert ks.is_active() is True
        # Running checks again doesn't deactivate
        ks.run_checks()
        assert ks.is_active() is True

    def test_only_deactivate_clears_state(self):
        ks, *_ = _make_kill_switch()
        ks.activate("Test")
        assert ks.is_active() is True
        ks.deactivate()
        assert ks.is_active() is False
        assert ks.get_reason() is None
