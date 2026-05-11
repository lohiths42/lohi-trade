"""Property-based tests for broker routing: failover and order format mapping.

**Property 15: Broker failover** — when primary broker is unavailable,
orders route to backup broker.

**Property 16: Order format mapping** — internal order format maps correctly
to each broker's API format and back.

**Validates: Requirements 17.4, 15.5, 16.4**

Uses Hypothesis to generate random orders and verify:
- Property 15: When primary broker raises an exception, the order is routed
  to the backup broker.
- Property 16: Mapping internal order → broker format → back to internal
  preserves the order type and product type.
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.ingestion.broker_interface import (
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.ingestion.broker_router import BrokerRouter

# Groww mapping helpers
from src.ingestion.groww_broker import (
    _ORDER_TYPE_MAP as GROWW_ORDER_TYPE_MAP,
)
from src.ingestion.groww_broker import (
    _PRODUCT_TYPE_MAP as GROWW_PRODUCT_TYPE_MAP,
)
from src.ingestion.groww_broker import (
    _reverse_order_type as groww_reverse_order_type,
)
from src.ingestion.groww_broker import (
    _reverse_product_type as groww_reverse_product_type,
)

# Kite mapping helpers
from src.ingestion.kite_broker import (
    _ORDER_TYPE_MAP as KITE_ORDER_TYPE_MAP,
)
from src.ingestion.kite_broker import (
    _PRODUCT_TYPE_MAP as KITE_PRODUCT_TYPE_MAP,
)
from src.ingestion.kite_broker import (
    _reverse_order_type as kite_reverse_order_type,
)
from src.ingestion.kite_broker import (
    _reverse_product_type as kite_reverse_product_type,
)

# ── Strategies ────────────────────────────────────────────────────

NSE_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "WIPRO",
]

order_strategy = st.builds(
    Order,
    order_id=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"),
    symbol=st.sampled_from(NSE_SYMBOLS),
    side=st.sampled_from(list(OrderSide)),
    order_type=st.sampled_from(list(OrderType)),
    quantity=st.integers(min_value=1, max_value=10000),
    product_type=st.sampled_from(list(ProductType)),
    status=st.just(OrderStatus.PENDING),
    price=st.one_of(st.none(), st.floats(min_value=0.05, max_value=100000, allow_nan=False, allow_infinity=False)),
    trigger_price=st.one_of(st.none(), st.floats(min_value=0.05, max_value=100000, allow_nan=False, allow_infinity=False)),
)


def _mock_broker(connected: bool = True) -> MagicMock:
    """Create a mock broker implementing BrokerInterface."""
    broker = MagicMock(spec=BrokerInterface)
    broker.is_connected.return_value = connected
    broker.place_order.return_value = "ORD-MOCK-001"
    broker.cancel_order.return_value = True
    broker.get_positions.return_value = []
    broker.get_holdings = MagicMock(return_value=[])
    return broker


# ── Property 15: Broker failover ─────────────────────────────────


class TestBrokerFailoverProperty:
    """**Property 15: Broker failover**

    For any valid order, when the primary broker raises an exception,
    the BrokerRouter routes the order to the backup broker and returns
    the backup broker's order ID.

    **Validates: Requirements 17.4**
    """

    @given(order=order_strategy)
    @settings(max_examples=25, deadline=None)
    def test_failover_routes_to_backup(self, order: Order):
        """When primary broker fails, order is placed on backup broker."""
        primary = _mock_broker()
        backup = _mock_broker()

        primary.place_order.side_effect = Exception("Primary API down")
        backup.place_order.return_value = "BACKUP-ORDER-ID"

        router = BrokerRouter(registry={
            "shoonya": MagicMock(spec=BrokerInterface),
            "angelone": MagicMock(spec=BrokerInterface),
            "kite": primary,
            "groww": backup,
        })
        router.set_user_preference("user-1", "kite", "groww")

        result = router.route_order("user-1", order)

        assert result == "BACKUP-ORDER-ID"
        backup.place_order.assert_called_once_with(order)

    @given(order=order_strategy)
    @settings(max_examples=25, deadline=None)
    def test_failover_audit_records(self, order: Order):
        """Failover produces two audit entries: failed primary + successful backup."""
        primary = _mock_broker()
        backup = _mock_broker()

        primary.place_order.side_effect = Exception("timeout")
        backup.place_order.return_value = "BACKUP-002"

        router = BrokerRouter(registry={
            "shoonya": MagicMock(spec=BrokerInterface),
            "angelone": MagicMock(spec=BrokerInterface),
            "kite": primary,
            "groww": backup,
        })
        router.set_user_preference("user-1", "kite", "groww")

        router.route_order("user-1", order)

        audit = router.get_audit_log(user_id="user-1")
        assert len(audit) == 2
        # First: failed primary
        assert audit[0].broker_name == "kite"
        assert audit[0].success is False
        assert audit[0].failover is False
        # Second: successful backup
        assert audit[1].broker_name == "groww"
        assert audit[1].success is True
        assert audit[1].failover is True


# ── Property 16: Order format mapping ────────────────────────────


class TestOrderFormatMappingProperty:
    """**Property 16: Order format mapping**

    For every internal OrderType and ProductType, mapping to a broker's
    API format and then reversing the mapping back to internal format
    preserves the original value (round-trip).

    **Validates: Requirements 15.5, 16.4**
    """

    @given(order_type=st.sampled_from(list(OrderType)))
    @settings(max_examples=5, deadline=None)
    def test_kite_order_type_round_trip(self, order_type: OrderType):
        """Internal OrderType → Kite format → internal preserves value."""
        kite_format = KITE_ORDER_TYPE_MAP[order_type]
        restored = kite_reverse_order_type(kite_format)
        assert restored == order_type

    @given(product_type=st.sampled_from(list(ProductType)))
    @settings(max_examples=5, deadline=None)
    def test_kite_product_type_round_trip(self, product_type: ProductType):
        """Internal ProductType → Kite format → internal preserves value."""
        kite_format = KITE_PRODUCT_TYPE_MAP[product_type]
        restored = kite_reverse_product_type(kite_format)
        assert restored == product_type

    @given(order_type=st.sampled_from([OrderType.MARKET, OrderType.LIMIT, OrderType.SL]))
    @settings(max_examples=5, deadline=None)
    def test_groww_order_type_round_trip(self, order_type: OrderType):
        """Internal OrderType → Groww format → internal preserves value.

        Note: Groww maps both SL and SL_M to "SL", so SL_M cannot
        round-trip. We test only the types that have a unique mapping.
        """
        groww_format = GROWW_ORDER_TYPE_MAP[order_type]
        restored = groww_reverse_order_type(groww_format)
        assert restored == order_type

    @given(product_type=st.sampled_from([ProductType.MIS]))
    @settings(max_examples=5, deadline=None)
    def test_groww_product_type_mis_round_trip(self, product_type: ProductType):
        """Internal ProductType MIS → Groww INTRADAY → internal MIS.

        Groww maps both CNC and NRML to "DELIVERY", so only MIS
        has a unique round-trip.
        """
        groww_format = GROWW_PRODUCT_TYPE_MAP[product_type]
        restored = groww_reverse_product_type(groww_format)
        assert restored == product_type

    def test_groww_non_unique_order_type_mapping(self):
        """SL_M maps to "SL" in Groww (same as SL). Reverse of "SL"
        returns OrderType.SL — this is expected lossy behaviour.
        """
        groww_format = GROWW_ORDER_TYPE_MAP[OrderType.SL_M]
        assert groww_format == "SL"
        restored = groww_reverse_order_type(groww_format)
        assert restored == OrderType.SL  # lossy: SL_M → SL

    def test_groww_non_unique_product_type_mapping(self):
        """CNC and NRML both map to "DELIVERY" in Groww. Reverse of
        "DELIVERY" returns ProductType.CNC — this is expected lossy
        behaviour.
        """
        assert GROWW_PRODUCT_TYPE_MAP[ProductType.CNC] == "DELIVERY"
        assert GROWW_PRODUCT_TYPE_MAP[ProductType.NRML] == "DELIVERY"
        restored = groww_reverse_product_type("DELIVERY")
        assert restored == ProductType.CNC  # lossy: NRML → CNC
