"""Tests for order book depth collection (Requirement 25.3).

Covers: OrderBookDepth dataclass, Redis hash serialization/deserialization,
collect_order_book(), _store_order_book_depth(), get_order_book_depth(),
and edge cases.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.market_data_collector import (
    IST,
    MarketDataCollector,
    OrderBookDepth,
    OrderBookLevel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_bus() -> MagicMock:
    """Create a mock EventBus with a mock redis_client that has hset/hgetall."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="1234567890-0")
    bus.redis_client = MagicMock()
    bus.redis_client.hset = MagicMock(return_value=0)
    bus.redis_client.hgetall = MagicMock(return_value={})
    return bus


def _make_depth(
    symbol: str = "RELIANCE",
    num_levels: int = 5,
    base_bid: float = 2499.0,
    base_ask: float = 2501.0,
    base_qty: int = 100,
    timestamp: datetime = None,
) -> OrderBookDepth:
    """Create a sample OrderBookDepth with the given number of levels."""
    if timestamp is None:
        timestamp = datetime(2024, 6, 15, 10, 30, 0, tzinfo=IST)
    bids = [
        OrderBookLevel(price=base_bid - i * 0.5, quantity=base_qty + i * 50)
        for i in range(num_levels)
    ]
    asks = [
        OrderBookLevel(price=base_ask + i * 0.5, quantity=base_qty + i * 50)
        for i in range(num_levels)
    ]
    return OrderBookDepth(symbol=symbol, bids=bids, asks=asks, timestamp=timestamp)


# ---------------------------------------------------------------------------
# Tests: OrderBookLevel dataclass
# ---------------------------------------------------------------------------

class TestOrderBookLevel:
    def test_create_level(self):
        level = OrderBookLevel(price=2500.0, quantity=100)
        assert level.price == 2500.0
        assert level.quantity == 100

    def test_level_with_zero_values(self):
        level = OrderBookLevel(price=0.0, quantity=0)
        assert level.price == 0.0
        assert level.quantity == 0


# ---------------------------------------------------------------------------
# Tests: OrderBookDepth dataclass
# ---------------------------------------------------------------------------

class TestOrderBookDepth:
    def test_create_depth(self):
        depth = _make_depth()
        assert depth.symbol == "RELIANCE"
        assert len(depth.bids) == 5
        assert len(depth.asks) == 5
        assert depth.timestamp is not None

    def test_create_empty_depth(self):
        depth = OrderBookDepth(symbol="TCS")
        assert depth.symbol == "TCS"
        assert depth.bids == []
        assert depth.asks == []
        assert depth.timestamp is None

    def test_bid_ask_ordering(self):
        """Bids should be in descending price, asks in ascending price."""
        depth = _make_depth()
        for i in range(len(depth.bids) - 1):
            assert depth.bids[i].price >= depth.bids[i + 1].price
        for i in range(len(depth.asks) - 1):
            assert depth.asks[i].price <= depth.asks[i + 1].price


# ---------------------------------------------------------------------------
# Tests: OrderBookDepth.to_redis_hash()
# ---------------------------------------------------------------------------

class TestOrderBookDepthToRedisHash:
    def test_full_5_levels(self):
        depth = _make_depth()
        h = depth.to_redis_hash()

        assert h["symbol"] == "RELIANCE"
        assert "timestamp" in h

        # Check all 5 bid/ask levels exist
        for i in range(1, 6):
            assert f"bid_{i}" in h
            assert f"ask_{i}" in h
            assert f"bid_qty_{i}" in h
            assert f"ask_qty_{i}" in h

        # Verify first level values
        assert float(h["bid_1"]) == 2499.0
        assert float(h["ask_1"]) == 2501.0
        assert int(h["bid_qty_1"]) == 100
        assert int(h["ask_qty_1"]) == 100

    def test_partial_levels_padded_with_zeros(self):
        """When fewer than 5 levels, remaining are padded with 0."""
        depth = _make_depth(num_levels=2)
        h = depth.to_redis_hash()

        # Levels 1-2 should have real data
        assert float(h["bid_1"]) > 0
        assert float(h["bid_2"]) > 0

        # Levels 3-5 should be zero
        assert h["bid_3"] == "0.0"
        assert h["bid_4"] == "0.0"
        assert h["bid_5"] == "0.0"
        assert h["bid_qty_3"] == "0"
        assert h["ask_3"] == "0.0"
        assert h["ask_qty_5"] == "0"

    def test_empty_depth_all_zeros(self):
        depth = OrderBookDepth(symbol="TCS")
        h = depth.to_redis_hash()

        assert h["symbol"] == "TCS"
        for i in range(1, 6):
            assert h[f"bid_{i}"] == "0.0"
            assert h[f"ask_{i}"] == "0.0"
            assert h[f"bid_qty_{i}"] == "0"
            assert h[f"ask_qty_{i}"] == "0"

    def test_no_timestamp(self):
        depth = OrderBookDepth(symbol="TCS")
        h = depth.to_redis_hash()
        assert "timestamp" not in h

    def test_hash_has_exactly_expected_keys(self):
        depth = _make_depth()
        h = depth.to_redis_hash()

        expected_keys = {"symbol", "timestamp"}
        for i in range(1, 6):
            expected_keys.update({
                f"bid_{i}", f"ask_{i}", f"bid_qty_{i}", f"ask_qty_{i}",
            })
        assert set(h.keys()) == expected_keys

    def test_all_values_are_strings(self):
        """Redis hashes store string values."""
        depth = _make_depth()
        h = depth.to_redis_hash()
        for v in h.values():
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# Tests: OrderBookDepth.from_redis_hash()
# ---------------------------------------------------------------------------

class TestOrderBookDepthFromRedisHash:
    def test_roundtrip_full_depth(self):
        """to_redis_hash → from_redis_hash preserves data."""
        original = _make_depth()
        h = original.to_redis_hash()
        restored = OrderBookDepth.from_redis_hash(h)

        assert restored.symbol == original.symbol
        assert len(restored.bids) == len(original.bids)
        assert len(restored.asks) == len(original.asks)

        for orig, rest in zip(original.bids, restored.bids):
            assert rest.price == orig.price
            assert rest.quantity == orig.quantity
        for orig, rest in zip(original.asks, restored.asks):
            assert rest.price == orig.price
            assert rest.quantity == orig.quantity

    def test_roundtrip_partial_depth(self):
        original = _make_depth(num_levels=3)
        h = original.to_redis_hash()
        restored = OrderBookDepth.from_redis_hash(h)

        assert len(restored.bids) == 3
        assert len(restored.asks) == 3

    def test_roundtrip_empty_depth(self):
        original = OrderBookDepth(symbol="TCS")
        h = original.to_redis_hash()
        restored = OrderBookDepth.from_redis_hash(h)

        assert restored.symbol == "TCS"
        assert restored.bids == []
        assert restored.asks == []

    def test_from_empty_dict(self):
        restored = OrderBookDepth.from_redis_hash({})
        assert restored.symbol == ""
        assert restored.bids == []
        assert restored.asks == []

    def test_timestamp_roundtrip(self):
        ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=IST)
        original = _make_depth(timestamp=ts)
        h = original.to_redis_hash()
        restored = OrderBookDepth.from_redis_hash(h)

        assert restored.timestamp is not None
        assert restored.timestamp == ts


# ---------------------------------------------------------------------------
# Tests: MarketDataCollector._store_order_book_depth()
# ---------------------------------------------------------------------------

class TestStoreOrderBookDepth:
    def test_stores_to_correct_redis_key(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        depth = _make_depth(symbol="RELIANCE")

        collector._store_order_book_depth(depth)

        bus.redis_client.hset.assert_called_once()
        call_args = bus.redis_client.hset.call_args
        # key is passed as first positional arg
        assert call_args[0][0] == "depth:RELIANCE"

    def test_stores_correct_hash_data(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        depth = _make_depth(symbol="TCS")

        collector._store_order_book_depth(depth)

        call_kwargs = bus.redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["symbol"] == "TCS"
        assert "bid_1" in mapping
        assert "ask_5" in mapping

    def test_store_handles_redis_error(self):
        """Redis errors are caught and logged, not raised."""
        bus = _make_event_bus()
        bus.redis_client.hset.side_effect = Exception("Redis down")
        collector = MarketDataCollector(event_bus=bus)
        depth = _make_depth()

        # Should not raise
        collector._store_order_book_depth(depth)


# ---------------------------------------------------------------------------
# Tests: MarketDataCollector.get_order_book_depth()
# ---------------------------------------------------------------------------

class TestGetOrderBookDepth:
    def test_retrieves_from_correct_key(self):
        bus = _make_event_bus()
        depth = _make_depth(symbol="INFY")
        bus.redis_client.hgetall.return_value = depth.to_redis_hash()
        collector = MarketDataCollector(event_bus=bus)

        result = collector.get_order_book_depth("INFY")

        bus.redis_client.hgetall.assert_called_once_with("depth:INFY")
        assert result is not None
        assert result.symbol == "INFY"

    def test_returns_none_when_key_missing(self):
        bus = _make_event_bus()
        bus.redis_client.hgetall.return_value = {}
        collector = MarketDataCollector(event_bus=bus)

        result = collector.get_order_book_depth("NONEXISTENT")

        assert result is None

    def test_returns_none_on_redis_error(self):
        bus = _make_event_bus()
        bus.redis_client.hgetall.side_effect = Exception("Redis down")
        collector = MarketDataCollector(event_bus=bus)

        result = collector.get_order_book_depth("RELIANCE")

        assert result is None

    def test_roundtrip_store_and_get(self):
        """Store then get returns equivalent data."""
        bus = _make_event_bus()
        original = _make_depth(symbol="RELIANCE")
        stored_data = {}

        def mock_hset(key, mapping):
            stored_data.update(mapping)
            return 0

        bus.redis_client.hset.side_effect = mock_hset
        bus.redis_client.hgetall.side_effect = lambda key: dict(stored_data)

        collector = MarketDataCollector(event_bus=bus)
        collector._store_order_book_depth(original)
        result = collector.get_order_book_depth("RELIANCE")

        assert result is not None
        assert result.symbol == original.symbol
        assert len(result.bids) == len(original.bids)
        assert len(result.asks) == len(original.asks)
        for orig, rest in zip(original.bids, result.bids):
            assert rest.price == orig.price
            assert rest.quantity == orig.quantity


# ---------------------------------------------------------------------------
# Tests: MarketDataCollector.collect_order_book() (async)
# ---------------------------------------------------------------------------

class TestCollectOrderBook:
    @pytest.mark.asyncio
    async def test_uses_subscribed_symbols_by_default(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus, subscribed_symbols=["RELIANCE", "TCS"],
        )

        # _fetch_order_book_depth returns None by default
        results = await collector.collect_order_book()

        assert results == {}

    @pytest.mark.asyncio
    async def test_uses_provided_symbols(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        depth = _make_depth(symbol="INFY")

        async def mock_fetch(symbol):
            if symbol == "INFY":
                return depth
            return None

        with patch.object(collector, "_fetch_order_book_depth", side_effect=mock_fetch):
            results = await collector.collect_order_book(symbols=["INFY", "TCS"])

        assert "INFY" in results
        assert "TCS" not in results

    @pytest.mark.asyncio
    async def test_stores_fetched_depth_in_redis(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        depth = _make_depth(symbol="RELIANCE")

        async def mock_fetch(symbol):
            return depth

        with patch.object(collector, "_fetch_order_book_depth", side_effect=mock_fetch):
            await collector.collect_order_book(symbols=["RELIANCE"])

        bus.redis_client.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        results = await collector.collect_order_book(symbols=[])

        assert results == {}

    @pytest.mark.asyncio
    async def test_handles_fetch_error_for_one_symbol(self):
        """Error fetching one symbol doesn't block others."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        depth_tcs = _make_depth(symbol="TCS")

        async def mock_fetch(symbol):
            if symbol == "RELIANCE":
                raise Exception("Feed error")
            return depth_tcs

        with patch.object(collector, "_fetch_order_book_depth", side_effect=mock_fetch):
            results = await collector.collect_order_book(symbols=["RELIANCE", "TCS"])

        assert "RELIANCE" not in results
        assert "TCS" in results

    @pytest.mark.asyncio
    async def test_returns_correct_depth_objects(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        depth_rel = _make_depth(symbol="RELIANCE", base_bid=2499.0)
        depth_tcs = _make_depth(symbol="TCS", base_bid=3499.0)

        async def mock_fetch(symbol):
            return {"RELIANCE": depth_rel, "TCS": depth_tcs}.get(symbol)

        with patch.object(collector, "_fetch_order_book_depth", side_effect=mock_fetch):
            results = await collector.collect_order_book(symbols=["RELIANCE", "TCS"])

        assert len(results) == 2
        assert results["RELIANCE"].bids[0].price == 2499.0
        assert results["TCS"].bids[0].price == 3499.0

    @pytest.mark.asyncio
    async def test_no_subscribed_symbols_returns_empty(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        results = await collector.collect_order_book()

        assert results == {}


# ---------------------------------------------------------------------------
# Tests: _fetch_order_book_depth default implementation
# ---------------------------------------------------------------------------

class TestFetchOrderBookDepth:
    @pytest.mark.asyncio
    async def test_default_returns_none(self):
        """Default implementation returns None (to be overridden in production)."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        result = await collector._fetch_order_book_depth("RELIANCE")

        assert result is None
