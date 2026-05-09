"""
Tests for BrokerManager - primary/backup broker switching.

Validates:
- Health monitoring and failure tracking
- Automatic failover on repeated failures
- Recovery monitoring to switch back to primary
- Delegated operations with failover
- Requirements: 1.5
"""

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from src.ingestion.broker_interface import (
    BrokerCredentials,
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    Tick,
)
from src.ingestion.broker_manager import (
    BrokerHealth,
    BrokerManager,
    BrokerState,
)


# ---- Fixtures ----

@pytest.fixture
def primary_broker():
    broker = MagicMock(spec=BrokerInterface)
    broker.is_connected.return_value = True
    broker.connect.return_value = True
    return broker


@pytest.fixture
def backup_broker():
    broker = MagicMock(spec=BrokerInterface)
    broker.is_connected.return_value = True
    broker.connect.return_value = True
    return broker


@pytest.fixture
def primary_creds():
    return BrokerCredentials(api_key="pk", client_id="pc", password="pp")


@pytest.fixture
def backup_creds():
    return BrokerCredentials(api_key="bk", client_id="bc", password="bp")


@pytest.fixture
def manager(primary_broker, backup_broker):
    return BrokerManager(
        primary_broker=primary_broker,
        backup_broker=backup_broker,
        failure_threshold=3,
        recovery_check_interval=0.1,  # Fast for tests
    )


@pytest.fixture
def connected_manager(manager, primary_creds, backup_creds):
    """A manager that's already connected to the primary broker."""
    manager.connect(primary_creds, backup_creds)
    yield manager
    manager.disconnect()


# ---- Connection Tests ----

class TestBrokerManagerConnection:
    def test_connect_primary_success(self, manager, primary_broker, primary_creds, backup_creds):
        result = manager.connect(primary_creds, backup_creds)
        assert result is True
        primary_broker.connect.assert_called_once_with(primary_creds)
        assert manager.active_broker_name == "primary"
        assert manager.health["primary"].state == BrokerState.CONNECTED

    def test_connect_primary_fails_switches_to_backup(
        self, manager, primary_broker, backup_broker, primary_creds, backup_creds
    ):
        primary_broker.connect.return_value = False
        result = manager.connect(primary_creds, backup_creds)
        assert result is True
        backup_broker.connect.assert_called_once_with(backup_creds)
        assert manager.active_broker_name == "backup"
        assert manager.health["primary"].state == BrokerState.FAILED

    def test_connect_primary_raises_switches_to_backup(
        self, manager, primary_broker, backup_broker, primary_creds, backup_creds
    ):
        primary_broker.connect.side_effect = Exception("connection refused")
        result = manager.connect(primary_creds, backup_creds)
        assert result is True
        assert manager.active_broker_name == "backup"

    def test_connect_both_fail(
        self, manager, primary_broker, backup_broker, primary_creds, backup_creds
    ):
        primary_broker.connect.return_value = False
        backup_broker.connect.return_value = False
        result = manager.connect(primary_creds, backup_creds)
        assert result is False

    def test_disconnect_both_brokers(self, connected_manager, primary_broker, backup_broker):
        connected_manager.disconnect()
        primary_broker.disconnect.assert_called_once()
        backup_broker.disconnect.assert_called_once()

    def test_disconnect_handles_errors(self, connected_manager, primary_broker, backup_broker):
        primary_broker.disconnect.side_effect = Exception("disconnect error")
        # Should not raise
        connected_manager.disconnect()
        backup_broker.disconnect.assert_called_once()

    def test_is_connected_delegates(self, connected_manager, primary_broker):
        primary_broker.is_connected.return_value = True
        assert connected_manager.is_connected() is True
        primary_broker.is_connected.return_value = False
        assert connected_manager.is_connected() is False


# ---- Health Tracking Tests ----

class TestHealthTracking:
    def test_success_resets_consecutive_failures(self, connected_manager, primary_broker):
        # Simulate some failures first
        connected_manager._health["primary"].consecutive_failures = 2
        connected_manager._health["primary"].state = BrokerState.DEGRADED

        primary_broker.get_positions.return_value = []
        connected_manager.get_positions()

        health = connected_manager.health["primary"]
        assert health.consecutive_failures == 0
        assert health.total_successes >= 1
        assert health.state == BrokerState.CONNECTED

    def test_failure_increments_counter(self, connected_manager, primary_broker):
        primary_broker.get_positions.side_effect = Exception("timeout")

        with pytest.raises(BrokerError):
            connected_manager.get_positions()

        health = connected_manager.health["primary"]
        assert health.consecutive_failures == 1
        assert health.total_failures == 1
        assert health.state == BrokerState.DEGRADED

    def test_degraded_state_below_threshold(self, connected_manager, primary_broker):
        primary_broker.get_positions.side_effect = Exception("timeout")

        # Fail twice (threshold is 3)
        for _ in range(2):
            with pytest.raises(BrokerError):
                connected_manager.get_positions()

        assert connected_manager.health["primary"].state == BrokerState.DEGRADED
        assert connected_manager.active_broker_name == "primary"  # Not switched yet

    def test_failed_state_at_threshold(self, connected_manager, primary_broker, backup_broker):
        primary_broker.get_positions.side_effect = Exception("timeout")
        # Primary is down, so is_connected should return False for recovery monitor
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.return_value = []

        # Fail 3 times (threshold)
        for _ in range(3):
            try:
                connected_manager.get_positions()
            except BrokerError:
                pass

        assert connected_manager.health["primary"].state == BrokerState.FAILED


# ---- Failover Tests ----

class TestBrokerFailover:
    def test_switches_after_threshold_failures(
        self, connected_manager, primary_broker, backup_broker
    ):
        primary_broker.get_positions.side_effect = Exception("timeout")
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.return_value = [{"symbol": "RELIANCE"}]

        # First two failures stay on primary
        for _ in range(2):
            with pytest.raises(BrokerError):
                connected_manager.get_positions()
        assert connected_manager.active_broker_name == "primary"

        # Third failure triggers switch and retries on backup
        result = connected_manager.get_positions()
        assert result == [{"symbol": "RELIANCE"}]
        assert connected_manager.active_broker_name == "backup"

    def test_both_brokers_fail_raises(
        self, connected_manager, primary_broker, backup_broker
    ):
        primary_broker.get_positions.side_effect = Exception("primary down")
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.side_effect = Exception("backup down")
        backup_broker.is_connected.return_value = False

        # Exhaust threshold
        for _ in range(2):
            with pytest.raises(BrokerError):
                connected_manager.get_positions()

        # Third failure triggers switch, backup also fails
        with pytest.raises(BrokerError, match="Both brokers failed"):
            connected_manager.get_positions()

    def test_switch_callback_called(
        self, connected_manager, primary_broker, backup_broker
    ):
        callback = MagicMock()
        connected_manager.on_switch(callback)

        primary_broker.get_positions.side_effect = Exception("timeout")
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.return_value = []

        for _ in range(3):
            try:
                connected_manager.get_positions()
            except BrokerError:
                pass

        callback.assert_called()
        args = callback.call_args[0]
        assert args[0] == "primary"
        assert args[1] == "backup"

    def test_switch_callback_error_does_not_propagate(
        self, connected_manager, primary_broker, backup_broker
    ):
        bad_callback = MagicMock(side_effect=Exception("callback error"))
        connected_manager.on_switch(bad_callback)

        primary_broker.get_positions.side_effect = Exception("timeout")
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.return_value = []

        for _ in range(3):
            try:
                connected_manager.get_positions()
            except BrokerError:
                pass

        # Should have switched despite callback error
        assert connected_manager.active_broker_name == "backup"


# ---- Delegated Operations Tests ----

class TestDelegatedOperations:
    def test_subscribe_delegates(self, connected_manager, primary_broker):
        on_tick = MagicMock()
        primary_broker.subscribe.return_value = True
        result = connected_manager.subscribe(["RELIANCE", "TCS"], on_tick)
        assert result is True
        primary_broker.subscribe.assert_called_once_with(["RELIANCE", "TCS"], on_tick)

    def test_unsubscribe_delegates(self, connected_manager, primary_broker):
        primary_broker.unsubscribe.return_value = True
        result = connected_manager.unsubscribe(["RELIANCE"])
        assert result is True
        primary_broker.unsubscribe.assert_called_once_with(["RELIANCE"])

    def test_place_order_delegates(self, connected_manager, primary_broker):
        order = Order(
            order_id="test-1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        primary_broker.place_order.return_value = "broker-order-123"
        result = connected_manager.place_order(order)
        assert result == "broker-order-123"
        primary_broker.place_order.assert_called_once_with(order)

    def test_cancel_order_delegates(self, connected_manager, primary_broker):
        primary_broker.cancel_order.return_value = True
        result = connected_manager.cancel_order("broker-order-123")
        assert result is True

    def test_get_order_status_delegates(self, connected_manager, primary_broker):
        mock_order = MagicMock()
        primary_broker.get_order_status.return_value = mock_order
        result = connected_manager.get_order_status("broker-order-123")
        assert result == mock_order

    def test_get_positions_delegates(self, connected_manager, primary_broker):
        primary_broker.get_positions.return_value = [{"symbol": "TCS"}]
        result = connected_manager.get_positions()
        assert result == [{"symbol": "TCS"}]

    def test_get_instrument_master_delegates(self, connected_manager, primary_broker):
        primary_broker.get_instrument_master.return_value = [{"symbol": "INFY"}]
        result = connected_manager.get_instrument_master()
        assert result == [{"symbol": "INFY"}]


# ---- Recovery Monitor Tests ----

class TestRecoveryMonitor:
    def test_recovery_switches_back_to_primary(
        self, primary_broker, backup_broker, primary_creds, backup_creds
    ):
        manager = BrokerManager(
            primary_broker=primary_broker,
            backup_broker=backup_broker,
            failure_threshold=1,
            recovery_check_interval=0.05,
        )

        # Connect, then force switch to backup
        manager.connect(primary_creds, backup_creds)
        primary_broker.get_positions.side_effect = Exception("down")
        backup_broker.get_positions.return_value = []

        try:
            manager.get_positions()
        except BrokerError:
            pass

        assert manager.active_broker_name == "backup"

        # Simulate primary recovery
        primary_broker.is_connected.return_value = True

        # Wait for recovery monitor to detect it
        time.sleep(0.2)

        assert manager.active_broker_name == "primary"
        manager.disconnect()

    def test_recovery_monitor_stops_on_disconnect(
        self, connected_manager, primary_broker, backup_broker
    ):
        # Force switch to backup to start recovery monitor
        primary_broker.get_positions.side_effect = Exception("down")
        primary_broker.is_connected.return_value = False
        primary_broker.connect.return_value = False
        backup_broker.get_positions.return_value = []

        connected_manager._failure_threshold = 1
        try:
            connected_manager.get_positions()
        except BrokerError:
            pass

        connected_manager.disconnect()
        # Recovery thread should have stopped
        assert (
            connected_manager._recovery_thread is None
            or not connected_manager._recovery_thread.is_alive()
        )


# ---- Edge Cases ----

class TestEdgeCases:
    def test_active_broker_property_thread_safe(self, connected_manager, primary_broker):
        """Concurrent reads of active_broker should not crash."""
        results = []

        def read_broker():
            for _ in range(100):
                results.append(connected_manager.active_broker_name)

        threads = [threading.Thread(target=read_broker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 400
        assert all(r in ("primary", "backup") for r in results)

    def test_no_backup_credentials_prevents_switch(self, primary_broker, backup_broker):
        manager = BrokerManager(primary_broker, backup_broker, failure_threshold=1)
        # Connect only primary, no backup creds stored
        primary_broker.connect.return_value = True
        manager._primary_credentials = BrokerCredentials("k", "c", "p")
        manager._active_broker_key = "primary"
        manager._health["primary"].state = BrokerState.CONNECTED

        primary_broker.get_positions.side_effect = Exception("down")

        with pytest.raises(BrokerError):
            manager.get_positions()

        # Should still be on primary since no backup creds
        assert manager.active_broker_name == "primary"

    def test_initial_state(self, manager):
        assert manager.active_broker_name == "primary"
        assert manager.health["primary"].state == BrokerState.DISCONNECTED
        assert manager.health["backup"].state == BrokerState.DISCONNECTED
        assert manager.health["primary"].consecutive_failures == 0
        assert manager.health["backup"].consecutive_failures == 0


# ---- Property-Based Tests ----

from hypothesis import given, strategies as st, settings


@given(
    num_ticks_before_switch=st.integers(min_value=1, max_value=50),
    num_ticks_after_switch=st.integers(min_value=1, max_value=50),
    num_symbols=st.integers(min_value=1, max_value=5),
    failure_threshold=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=5, deadline=None)
def test_property_broker_switch_data_continuity(
    num_ticks_before_switch,
    num_ticks_after_switch,
    num_symbols,
    failure_threshold,
):
    """
    Property 3: Broker Switch Data Continuity

    For any broker API switch during operation, no duplicate ticks should
    appear in the Event Bus and no ticks should be lost.

    This property validates:
    - Every tick produced by the primary broker before the switch is delivered
      exactly once to the tick callback.
    - Every tick produced by the backup broker after the switch is delivered
      exactly once to the tick callback.
    - No tick is delivered more than once (no duplicates).
    - The total number of delivered ticks equals the sum of ticks from both
      brokers.
    - Per-symbol tick ordering is preserved across the switch.

    Validates: Requirements 1.6

    Feature: lohi-trade, Property 3: Broker Switch Data Continuity
    """
    symbols = [f"SYM{i}" for i in range(num_symbols)]

    # ---- Build tick sequences ----
    primary_ticks = []
    for i in range(num_ticks_before_switch):
        sym = symbols[i % num_symbols]
        primary_ticks.append(
            Tick(
                symbol=sym,
                token=1000 + (i % num_symbols),
                ltp=100.0 + i * 0.1,
                volume=100 + i,
                timestamp=datetime(2025, 1, 1, 9, 15, 0, i * 1000),
                exchange="NSE",
            )
        )

    backup_ticks = []
    for i in range(num_ticks_after_switch):
        sym = symbols[i % num_symbols]
        backup_ticks.append(
            Tick(
                symbol=sym,
                token=1000 + (i % num_symbols),
                ltp=200.0 + i * 0.1,
                volume=200 + i,
                timestamp=datetime(
                    2025, 1, 1, 9, 16, 0, i * 1000
                ),
                exchange="NSE",
            )
        )

    # ---- Set up brokers ----
    primary_broker = MagicMock(spec=BrokerInterface)
    primary_broker.is_connected.return_value = True
    primary_broker.connect.return_value = True

    backup_broker = MagicMock(spec=BrokerInterface)
    backup_broker.is_connected.return_value = True
    backup_broker.connect.return_value = True

    manager = BrokerManager(
        primary_broker=primary_broker,
        backup_broker=backup_broker,
        failure_threshold=failure_threshold,
        recovery_check_interval=999,  # Disable recovery for this test
    )

    primary_creds = BrokerCredentials(api_key="pk", client_id="pc", password="pp")
    backup_creds = BrokerCredentials(api_key="bk", client_id="bc", password="bp")
    manager.connect(primary_creds, backup_creds)

    # ---- Simulate tick delivery ----
    # The tick callback collects all delivered ticks.
    delivered_ticks = []

    def tick_callback(tick: Tick):
        delivered_ticks.append(tick)

    # Capture the on_tick callback that subscribe passes to the broker.
    # Primary broker delivers ticks before the switch.
    captured_primary_cb = None

    def primary_subscribe(syms, on_tick):
        nonlocal captured_primary_cb
        captured_primary_cb = on_tick
        return True

    primary_broker.subscribe.side_effect = primary_subscribe

    # Subscribe via manager (routes to primary)
    manager.subscribe(symbols, tick_callback)
    assert captured_primary_cb is not None

    # Deliver primary ticks through the captured callback
    for tick in primary_ticks:
        captured_primary_cb(tick)

    # ---- Force broker switch ----
    # Make primary fail enough times to trigger failover.
    primary_broker.get_positions.side_effect = Exception("primary down")
    primary_broker.is_connected.return_value = False
    primary_broker.connect.return_value = False
    backup_broker.get_positions.return_value = []

    for _ in range(failure_threshold):
        try:
            manager.get_positions()
        except BrokerError:
            pass

    assert manager.active_broker_name == "backup", (
        "Manager should have switched to backup broker"
    )

    # Backup broker delivers ticks after the switch.
    captured_backup_cb = None

    def backup_subscribe(syms, on_tick):
        nonlocal captured_backup_cb
        captured_backup_cb = on_tick
        return True

    backup_broker.subscribe.side_effect = backup_subscribe

    # Re-subscribe on the backup broker (as the real system would)
    manager.subscribe(symbols, tick_callback)
    assert captured_backup_cb is not None

    # Deliver backup ticks
    for tick in backup_ticks:
        captured_backup_cb(tick)

    # ---- Assertions ----

    total_expected = num_ticks_before_switch + num_ticks_after_switch

    # 1. No data loss: every tick is delivered
    assert len(delivered_ticks) == total_expected, (
        f"Expected {total_expected} ticks, got {len(delivered_ticks)}. "
        f"Data loss detected during broker switch."
    )

    # 2. No duplicates: each tick object appears exactly once
    # Use (symbol, timestamp, ltp) as a unique key since tick objects
    # from different brokers have distinct price ranges.
    tick_keys = [(t.symbol, t.timestamp, t.ltp) for t in delivered_ticks]
    assert len(tick_keys) == len(set(tick_keys)), (
        "Duplicate ticks detected during broker switch"
    )

    # 3. Primary ticks come first, then backup ticks (ordering preserved)
    primary_delivered = delivered_ticks[:num_ticks_before_switch]
    backup_delivered = delivered_ticks[num_ticks_before_switch:]

    for i, tick in enumerate(primary_delivered):
        assert tick is primary_ticks[i], (
            f"Primary tick {i} mismatch: ordering not preserved"
        )

    for i, tick in enumerate(backup_delivered):
        assert tick is backup_ticks[i], (
            f"Backup tick {i} mismatch: ordering not preserved"
        )

    # 4. Per-symbol ordering is preserved across the switch
    for sym in symbols:
        sym_ticks = [t for t in delivered_ticks if t.symbol == sym]
        sym_timestamps = [t.timestamp for t in sym_ticks]
        assert sym_timestamps == sorted(sym_timestamps), (
            f"Per-symbol tick ordering violated for {sym} during broker switch"
        )

    # 5. All primary ticks have prices in the primary range,
    #    all backup ticks have prices in the backup range (no cross-contamination)
    for tick in primary_delivered:
        assert 100.0 <= tick.ltp < 200.0, (
            f"Primary tick has unexpected price {tick.ltp}"
        )
    for tick in backup_delivered:
        assert tick.ltp >= 200.0, (
            f"Backup tick has unexpected price {tick.ltp}"
        )

    # Cleanup
    manager._stop_recovery_monitor()
