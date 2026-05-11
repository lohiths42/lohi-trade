"""Tests for BrokerRouter — unified broker routing with per-user failover.

Validates:
- Broker registry management
- Per-user primary/backup preference
- Order routing to primary broker
- Automatic failover to backup on primary unavailability
- Common broker interface contract (place_order, cancel_order, get_order_status,
  get_positions, get_holdings)
- Broker connection status reporting
- Audit logging of all broker API interactions

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
"""

from unittest.mock import MagicMock

import pytest

from src.ingestion.broker_interface import (
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.ingestion.broker_router import (
    SUPPORTED_BROKERS,
    BrokerConnectionStatus,
    BrokerRouter,
)

# ── Fixtures ──────────────────────────────────────────────────────


def _mock_broker(connected: bool = True) -> MagicMock:
    broker = MagicMock(spec=BrokerInterface)
    broker.is_connected.return_value = connected
    broker.place_order.return_value = "ORD-001"
    broker.cancel_order.return_value = True
    broker.get_order_status.return_value = MagicMock(spec=Order)
    broker.get_positions.return_value = [{"symbol": "RELIANCE"}]
    broker.get_holdings = MagicMock(return_value=[{"symbol": "TCS"}])
    return broker


@pytest.fixture
def shoonya():
    return _mock_broker()


@pytest.fixture
def angelone():
    return _mock_broker()


@pytest.fixture
def kite():
    return _mock_broker()


@pytest.fixture
def groww():
    return _mock_broker()


@pytest.fixture
def registry(shoonya, angelone, kite, groww):
    return {
        "shoonya": shoonya,
        "angelone": angelone,
        "kite": kite,
        "groww": groww,
    }


@pytest.fixture
def router(registry):
    return BrokerRouter(registry=registry)


@pytest.fixture
def sample_order():
    return Order(
        order_id="int-001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product_type=ProductType.MIS,
        status=OrderStatus.PENDING,
    )


USER = "user-1"


# ── Registry Tests ────────────────────────────────────────────────


class TestBrokerRegistry:
    """Requirement 17.1: broker registry supporting shoonya, angelone, kite, groww."""

    def test_register_all_supported_brokers(self, router):
        registered = router.get_registered_brokers()
        assert set(registered) == SUPPORTED_BROKERS

    def test_register_unsupported_broker_raises(self):
        router = BrokerRouter()
        with pytest.raises(ValueError, match="Unsupported broker"):
            router.register_broker("unknown_broker", _mock_broker())

    def test_register_broker_case_insensitive(self):
        router = BrokerRouter()
        router.register_broker("Kite", _mock_broker())
        assert "kite" in router.get_registered_brokers()

    def test_empty_registry(self):
        router = BrokerRouter()
        assert router.get_registered_brokers() == []


# ── User Preference Tests ────────────────────────────────────────


class TestUserPreference:
    """Requirement 17.2: user sets primary and optional backup broker."""

    def test_set_and_get_preference(self, router):
        router.set_user_preference(USER, "kite", "shoonya")
        pref = router.get_user_preference(USER)
        assert pref is not None
        assert pref.primary_broker == "kite"
        assert pref.backup_broker == "shoonya"

    def test_set_preference_primary_only(self, router):
        router.set_user_preference(USER, "groww")
        pref = router.get_user_preference(USER)
        assert pref.primary_broker == "groww"
        assert pref.backup_broker is None

    def test_set_preference_unregistered_primary_raises(self, router):
        with pytest.raises(ValueError, match="not registered"):
            router.set_user_preference(USER, "nonexistent")

    def test_set_preference_unregistered_backup_raises(self, router):
        # Remove groww from registry to test
        r = BrokerRouter({"shoonya": _mock_broker()})
        with pytest.raises(ValueError, match="not registered"):
            r.set_user_preference(USER, "shoonya", "groww")

    def test_set_preference_same_primary_backup_raises(self, router):
        with pytest.raises(ValueError, match="must differ"):
            router.set_user_preference(USER, "kite", "kite")

    def test_get_preference_unknown_user(self, router):
        assert router.get_user_preference("unknown") is None

    def test_preference_case_insensitive(self, router):
        router.set_user_preference(USER, "Kite", "Shoonya")
        pref = router.get_user_preference(USER)
        assert pref.primary_broker == "kite"
        assert pref.backup_broker == "shoonya"


# ── Broker Status Tests ──────────────────────────────────────────


class TestBrokerStatus:
    """Requirement 17.7: broker connection status."""

    def test_connected_broker(self, router, kite):
        kite.is_connected.return_value = True
        assert router.get_broker_status("kite") == BrokerConnectionStatus.CONNECTED

    def test_disconnected_broker(self, router, kite):
        kite.is_connected.return_value = False
        assert router.get_broker_status("kite") == BrokerConnectionStatus.DISCONNECTED

    def test_unregistered_broker_is_disconnected(self, router):
        assert router.get_broker_status("nonexistent") == BrokerConnectionStatus.DISCONNECTED

    def test_broker_raises_returns_disconnected(self, router, kite):
        kite.is_connected.side_effect = Exception("boom")
        assert router.get_broker_status("kite") == BrokerConnectionStatus.DISCONNECTED

    def test_get_all_statuses(self, router):
        statuses = router.get_all_broker_statuses()
        assert set(statuses.keys()) == SUPPORTED_BROKERS
        for status in statuses.values():
            assert status == BrokerConnectionStatus.CONNECTED


# ── Order Routing Tests ──────────────────────────────────────────


class TestRouteOrder:
    """Requirement 17.3: route to primary broker."""

    def test_route_to_primary(self, router, kite, sample_order):
        router.set_user_preference(USER, "kite", "shoonya")
        result = router.route_order(USER, sample_order)
        assert result == "ORD-001"
        kite.place_order.assert_called_once_with(sample_order)

    def test_no_preference_raises(self, router, sample_order):
        with pytest.raises(ValueError, match="No broker preference"):
            router.route_order("unknown-user", sample_order)


# ── Failover Tests ────────────────────────────────────────────────


class TestFailover:
    """Requirement 17.4: auto-failover to backup on primary unavailability."""

    def test_failover_on_primary_failure(self, router, kite, shoonya, sample_order):
        kite.place_order.side_effect = Exception("API down")
        shoonya.place_order.return_value = "BACKUP-001"
        router.set_user_preference(USER, "kite", "shoonya")

        result = router.route_order(USER, sample_order)
        assert result == "BACKUP-001"
        shoonya.place_order.assert_called_once_with(sample_order)

    def test_both_brokers_fail_raises(self, router, kite, shoonya, sample_order):
        kite.place_order.side_effect = Exception("primary down")
        shoonya.place_order.side_effect = Exception("backup down")
        router.set_user_preference(USER, "kite", "shoonya")

        with pytest.raises(BrokerError, match="Both primary.*and backup.*failed"):
            router.route_order(USER, sample_order)

    def test_no_backup_configured_raises(self, router, kite, sample_order):
        kite.place_order.side_effect = Exception("API down")
        router.set_user_preference(USER, "kite")

        with pytest.raises(BrokerError, match="no backup broker configured"):
            router.route_order(USER, sample_order)

    def test_failover_logged_in_audit(self, router, kite, shoonya, sample_order):
        kite.place_order.side_effect = Exception("timeout")
        shoonya.place_order.return_value = "BACKUP-002"
        router.set_user_preference(USER, "kite", "shoonya")

        router.route_order(USER, sample_order)

        audit = router.get_audit_log(user_id=USER)
        assert len(audit) == 2
        # First entry: failed primary
        assert audit[0].broker_name == "kite"
        assert audit[0].success is False
        assert audit[0].failover is False
        # Second entry: successful backup
        assert audit[1].broker_name == "shoonya"
        assert audit[1].success is True
        assert audit[1].failover is True


# ── Common Interface Contract Tests ──────────────────────────────


class TestCommonInterface:
    """Requirement 17.5: common broker interface contract."""

    def test_cancel_order_routes_to_primary(self, router, kite):
        router.set_user_preference(USER, "kite")
        result = router.cancel_order(USER, "ORD-X")
        assert result is True
        kite.cancel_order.assert_called_once_with("ORD-X")

    def test_cancel_order_failover(self, router, kite, shoonya):
        kite.cancel_order.side_effect = Exception("down")
        shoonya.cancel_order.return_value = True
        router.set_user_preference(USER, "kite", "shoonya")
        result = router.cancel_order(USER, "ORD-X")
        assert result is True

    def test_get_order_status_routes(self, router, groww):
        router.set_user_preference(USER, "groww")
        router.get_order_status(USER, "ORD-Y")
        groww.get_order_status.assert_called_once_with("ORD-Y")

    def test_get_positions_routes(self, router, angelone):
        router.set_user_preference(USER, "angelone")
        result = router.get_positions(USER)
        assert result == [{"symbol": "RELIANCE"}]
        angelone.get_positions.assert_called_once()

    def test_get_holdings_routes(self, router, kite):
        router.set_user_preference(USER, "kite")
        result = router.get_holdings(USER)
        assert result == [{"symbol": "TCS"}]

    def test_get_positions_failover(self, router, kite, shoonya):
        kite.get_positions.side_effect = Exception("down")
        shoonya.get_positions.return_value = [{"symbol": "INFY"}]
        router.set_user_preference(USER, "kite", "shoonya")
        result = router.get_positions(USER)
        assert result == [{"symbol": "INFY"}]

    def test_get_holdings_failover(self, router, kite, shoonya):
        kite.get_holdings.side_effect = Exception("down")
        shoonya.get_holdings = MagicMock(return_value=[{"symbol": "HDFC"}])
        router.set_user_preference(USER, "kite", "shoonya")
        result = router.get_holdings(USER)
        assert result == [{"symbol": "HDFC"}]


# ── Audit Logging Tests ──────────────────────────────────────────


class TestAuditLogging:
    """Requirement 17.6: log all broker API interactions."""

    def test_successful_order_logged(self, router, kite, sample_order):
        router.set_user_preference(USER, "kite")
        router.route_order(USER, sample_order)

        audit = router.get_audit_log(user_id=USER)
        assert len(audit) == 1
        entry = audit[0]
        assert entry.broker_name == "kite"
        assert entry.operation == "place_order"
        assert entry.success is True
        assert entry.user_id == USER
        assert "RELIANCE" in entry.request_summary
        assert entry.duration_ms >= 0

    def test_failed_order_logged(self, router, kite, sample_order):
        kite.place_order.side_effect = Exception("rejected")
        router.set_user_preference(USER, "kite")

        with pytest.raises(BrokerError):
            router.route_order(USER, sample_order)

        audit = router.get_audit_log(user_id=USER)
        assert len(audit) == 1
        assert audit[0].success is False
        assert "error=" in audit[0].response_summary

    def test_audit_log_limit(self, router, kite, sample_order):
        router.set_user_preference(USER, "kite")
        for _ in range(5):
            router.route_order(USER, sample_order)

        assert len(router.get_audit_log(user_id=USER, limit=3)) == 3

    def test_audit_log_filter_by_user(self, router, kite, shoonya, sample_order):
        router.set_user_preference("user-a", "kite")
        router.set_user_preference("user-b", "shoonya")
        router.route_order("user-a", sample_order)
        router.route_order("user-b", sample_order)

        assert len(router.get_audit_log(user_id="user-a")) == 1
        assert len(router.get_audit_log(user_id="user-b")) == 1
        assert len(router.get_audit_log()) == 2

    def test_cancel_order_audited(self, router, kite):
        router.set_user_preference(USER, "kite")
        router.cancel_order(USER, "ORD-Z")
        audit = router.get_audit_log(user_id=USER)
        assert len(audit) == 1
        assert audit[0].operation == "cancel_order"
