"""Tests for the NSE Market Data Collector.

Covers: connection, tick processing & publishing, reconnection with
exponential backoff, broker fallback, pre/post-market sessions,
message parsing, and subscription management.

Requirements: 25.1, 25.2, 25.4, 25.5, 25.6, 25.7
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.broker_interface import Tick
from src.ingestion.market_data_collector import (
    IST,
    ConnectionStats,
    FeedSource,
    MarketDataCollector,
    MarketSession,
    TickData,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_bus() -> MagicMock:
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="1234567890-0")
    return bus


def _make_fallback_broker() -> MagicMock:
    """Create a mock fallback broker."""
    broker = MagicMock()
    broker.subscribe = MagicMock(return_value=True)
    broker.unsubscribe = MagicMock(return_value=True)
    broker.is_connected = MagicMock(return_value=True)
    return broker


def _make_tick_data(
    symbol: str = "RELIANCE",
    ltp: float = 2500.0,
    timestamp: datetime = None,
) -> TickData:
    """Create a sample TickData."""
    if timestamp is None:
        timestamp = datetime.now(IST)
    return TickData(
        symbol=symbol,
        token=12345,
        ltp=ltp,
        last_traded_qty=100,
        total_volume=500000,
        best_bid_price=2499.50,
        best_bid_qty=200,
        best_ask_price=2500.50,
        best_ask_qty=150,
        open=2480.0,
        high=2510.0,
        low=2475.0,
        close=2505.0,
        previous_close=2490.0,
        timestamp=timestamp,
        exchange="NSE",
    )


def _make_nse_json(symbol: str = "RELIANCE", ltp: float = 2500.0) -> str:
    """Create a raw NSE JSON message string."""
    return json.dumps(
        {
            "symbol": symbol,
            "token": 12345,
            "ltp": ltp,
            "last_traded_qty": 100,
            "total_volume": 500000,
            "best_bid_price": 2499.50,
            "best_bid_qty": 200,
            "best_ask_price": 2500.50,
            "best_ask_qty": 150,
            "open": 2480.0,
            "high": 2510.0,
            "low": 2475.0,
            "close": 2505.0,
            "previous_close": 2490.0,
            "timestamp": datetime.now(IST).isoformat(),
            "exchange": "NSE",
        }
    )


# ---------------------------------------------------------------------------
# Tests: Initialisation & basic state
# ---------------------------------------------------------------------------


class TestMarketDataCollectorInit:
    def test_initial_state(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        assert collector.is_connected is False
        assert collector.feed_source == FeedSource.DISCONNECTED
        assert collector.subscribed_symbols == []
        assert collector.stats.total_ticks_received == 0

    def test_init_with_symbols(self):
        bus = _make_event_bus()
        symbols = ["RELIANCE", "TCS", "INFY"]
        collector = MarketDataCollector(event_bus=bus, subscribed_symbols=symbols)

        assert collector.subscribed_symbols == symbols

    def test_init_with_fallback_broker(self):
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(event_bus=bus, fallback_broker=broker)

        assert collector.fallback_broker is broker


# ---------------------------------------------------------------------------
# Tests: Subscription management
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_adds_symbols(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        collector.subscribe(["RELIANCE", "TCS"])
        assert "RELIANCE" in collector.subscribed_symbols
        assert "TCS" in collector.subscribed_symbols

    def test_subscribe_no_duplicates(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus, subscribed_symbols=["RELIANCE"])

        collector.subscribe(["RELIANCE", "TCS"])
        assert collector.subscribed_symbols.count("RELIANCE") == 1
        assert len(collector.subscribed_symbols) == 2

    def test_unsubscribe_removes_symbols(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            subscribed_symbols=["RELIANCE", "TCS", "INFY"],
        )

        collector.unsubscribe(["TCS"])
        assert "TCS" not in collector.subscribed_symbols
        assert len(collector.subscribed_symbols) == 2


# ---------------------------------------------------------------------------
# Tests: Tick processing & publishing (Requirement 25.2, 25.4)
# ---------------------------------------------------------------------------


class TestTickProcessing:
    def test_process_tick_publishes_to_event_bus(self):
        """Tick data is published to the correct Redis stream."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        tick = _make_tick_data()

        collector._process_tick(tick)

        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args.kwargs["stream_name"] == "stream:ticks:RELIANCE"
        assert call_args.kwargs["maxlen"] == 1000

    def test_process_tick_message_contains_all_fields(self):
        """Published message includes all required fields per 25.2."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        tick = _make_tick_data()

        collector._process_tick(tick)

        msg = bus.publish.call_args.kwargs["message"]
        assert msg["symbol"] == "RELIANCE"
        assert msg["ltp"] == 2500.0
        assert msg["last_traded_qty"] == 100
        assert msg["volume"] == 500000
        assert msg["bid"] == 2499.50
        assert msg["bid_qty"] == 200
        assert msg["ask"] == 2500.50
        assert msg["ask_qty"] == 150
        assert msg["open"] == 2480.0
        assert msg["high"] == 2510.0
        assert msg["low"] == 2475.0
        assert msg["close"] == 2505.0
        assert msg["previous_close"] == 2490.0
        assert msg["exchange"] == "NSE"
        assert "timestamp" in msg
        assert "session" in msg

    def test_process_tick_updates_stats(self):
        """Stats are updated after processing a tick."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        tick = _make_tick_data()

        collector._process_tick(tick)

        assert collector.stats.total_ticks_received == 1
        assert collector.stats.total_ticks_published == 1
        assert collector.stats.last_tick_time is not None

    def test_process_tick_tracks_latency(self):
        """Publish latency is tracked in stats."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        tick = _make_tick_data()

        collector._process_tick(tick)

        assert collector.stats.publish_count_for_latency == 1
        assert collector.stats.avg_publish_latency_ms >= 0

    def test_process_tick_handles_publish_failure(self):
        """Publish failure is logged but does not raise."""
        bus = _make_event_bus()
        bus.publish.side_effect = Exception("Redis down")
        collector = MarketDataCollector(event_bus=bus)
        tick = _make_tick_data()

        # Should not raise
        collector._process_tick(tick)

        assert collector.stats.total_ticks_received == 1
        assert collector.stats.total_ticks_published == 0


# ---------------------------------------------------------------------------
# Tests: NSE message parsing (Requirement 25.2)
# ---------------------------------------------------------------------------


class TestNSEMessageParsing:
    def test_parse_valid_message(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = _make_nse_json()

        tick = collector.parse_nse_message(raw)

        assert tick is not None
        assert tick.symbol == "RELIANCE"
        assert tick.ltp == 2500.0
        assert tick.exchange == "NSE"

    def test_parse_invalid_json(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        tick = collector.parse_nse_message("not json")
        assert tick is None

    def test_parse_missing_required_field(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = json.dumps({"ltp": 100.0})  # missing symbol, token, timestamp

        tick = collector.parse_nse_message(raw)
        assert tick is None

    def test_parse_optional_fields_default(self):
        """Optional fields default to 0 when missing."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = json.dumps(
            {
                "symbol": "TCS",
                "token": 999,
                "ltp": 3500.0,
                "timestamp": datetime.now(IST).isoformat(),
            }
        )

        tick = collector.parse_nse_message(raw)

        assert tick is not None
        assert tick.last_traded_qty == 0
        assert tick.best_bid_price == 0.0


# ---------------------------------------------------------------------------
# Tests: Market session detection (Requirements 25.6, 25.7)
# ---------------------------------------------------------------------------


class TestMarketSession:
    def test_pre_market_session(self):
        """9:00 - 9:15 IST is pre-market."""
        dt = datetime(2024, 1, 15, 9, 10, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.PRE_MARKET

    def test_pre_market_start_boundary(self):
        dt = datetime(2024, 1, 15, 9, 0, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.PRE_MARKET

    def test_normal_session(self):
        """9:15 - 15:30 IST is normal trading."""
        dt = datetime(2024, 1, 15, 12, 0, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.NORMAL

    def test_normal_session_start_boundary(self):
        dt = datetime(2024, 1, 15, 9, 15, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.NORMAL

    def test_post_market_session(self):
        """15:30 - 16:00 IST is post-market."""
        dt = datetime(2024, 1, 15, 15, 45, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.POST_MARKET

    def test_post_market_start_boundary(self):
        dt = datetime(2024, 1, 15, 15, 30, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.POST_MARKET

    def test_closed_session_before_market(self):
        dt = datetime(2024, 1, 15, 8, 0, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.CLOSED

    def test_closed_session_after_market(self):
        dt = datetime(2024, 1, 15, 16, 0, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.CLOSED

    def test_closed_session_late_night(self):
        dt = datetime(2024, 1, 15, 22, 0, tzinfo=IST)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.CLOSED

    def test_naive_datetime_treated_as_ist(self):
        """Naive datetime is treated as IST."""
        dt = datetime(2024, 1, 15, 12, 0)
        assert MarketDataCollector.get_current_session(dt) == MarketSession.NORMAL


# ---------------------------------------------------------------------------
# Tests: Pre-market and post-market data collection (25.6, 25.7)
# ---------------------------------------------------------------------------


class TestSessionDataCollection:
    def test_collect_pre_market_data(self):
        """Pre-market data includes indicative opening price."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        ts = datetime(2024, 1, 15, 9, 5, tzinfo=IST)
        tick = _make_tick_data(ltp=2480.0, timestamp=ts)

        result = collector.collect_pre_market_data(tick)

        assert result["session"] == "PRE_MARKET"
        assert result["indicative_open"] == 2480.0
        # Tick should be published during pre-market
        assert bus.publish.called

    def test_collect_post_market_data(self):
        """Post-market data includes closing price."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        ts = datetime(2024, 1, 15, 15, 45, tzinfo=IST)
        tick = _make_tick_data(ltp=2510.0, timestamp=ts)

        result = collector.collect_post_market_data(tick)

        assert result["session"] == "POST_MARKET"
        assert result["closing_price"] == 2510.0
        assert bus.publish.called

    def test_pre_market_outside_session_no_publish(self):
        """Calling collect_pre_market_data outside pre-market doesn't publish."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        ts = datetime(2024, 1, 15, 12, 0, tzinfo=IST)  # Normal session
        tick = _make_tick_data(timestamp=ts)

        result = collector.collect_pre_market_data(tick)

        assert result["indicative_open"] == tick.ltp
        assert not bus.publish.called


# ---------------------------------------------------------------------------
# Tests: Connection lifecycle (Requirement 25.1)
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect_nse_feed(self):
        """connect_nse_feed sets connected state and feed source."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        await collector.connect_nse_feed()

        assert collector.is_connected is True
        assert collector.feed_source == FeedSource.NSE
        assert collector.stats.connected_at is not None

        await collector.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Disconnect clears state."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        await collector.connect_nse_feed()

        await collector.disconnect()

        assert collector.is_connected is False
        assert collector.feed_source == FeedSource.DISCONNECTED
        assert collector.stats.disconnected_at is not None


# ---------------------------------------------------------------------------
# Tests: Reconnection with exponential backoff (Requirement 25.5)
# ---------------------------------------------------------------------------


class TestReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_success(self):
        """Successful reconnection resets state."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        success = await collector._reconnect()

        assert success is True
        assert collector.is_connected is True
        assert collector.feed_source == FeedSource.NSE

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff_capped_at_5s(self):
        """Backoff delay never exceeds 5 seconds."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        # Simulate many failed attempts
        collector._reconnect_attempts = 8
        max_delay = min(
            collector.RECONNECT_BASE_DELAY * (2**8),
            collector.RECONNECT_MAX_DELAY,
        )
        assert max_delay == 5.0

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts_exceeded(self):
        """Returns False after max attempts."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        collector._reconnect_attempts = collector.MAX_RECONNECT_ATTEMPTS

        success = await collector._reconnect()

        assert success is False

    @pytest.mark.asyncio
    async def test_reconnect_increments_stats(self):
        """Each reconnection attempt increments stats."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        await collector._reconnect()

        assert collector.stats.reconnection_attempts == 1


# ---------------------------------------------------------------------------
# Tests: Broker fallback (Requirement 25.5)
# ---------------------------------------------------------------------------


class TestBrokerFallback:
    @pytest.mark.asyncio
    async def test_activate_fallback(self):
        """Fallback activates and subscribes via broker."""
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(
            event_bus=bus,
            fallback_broker=broker,
            subscribed_symbols=["RELIANCE"],
        )

        await collector._activate_fallback()

        assert collector.feed_source == FeedSource.BROKER_FALLBACK
        broker.subscribe.assert_called_once()
        assert collector.stats.fallback_activations == 1

    @pytest.mark.asyncio
    async def test_activate_fallback_no_broker(self):
        """No-op when no fallback broker is configured."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        await collector._activate_fallback()

        assert collector.feed_source != FeedSource.BROKER_FALLBACK

    @pytest.mark.asyncio
    async def test_activate_fallback_idempotent(self):
        """Activating fallback twice doesn't double-subscribe."""
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(
            event_bus=bus,
            fallback_broker=broker,
            subscribed_symbols=["TCS"],
        )

        await collector._activate_fallback()
        await collector._activate_fallback()

        assert broker.subscribe.call_count == 1

    def test_deactivate_fallback(self):
        """Deactivating fallback unsubscribes from broker."""
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(
            event_bus=bus,
            fallback_broker=broker,
            subscribed_symbols=["INFY"],
        )
        collector._fallback_active = True

        collector._deactivate_fallback()

        assert collector._fallback_active is False
        broker.unsubscribe.assert_called_once()

    def test_fallback_tick_published(self):
        """Ticks from fallback broker are published to event bus."""
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(event_bus=bus, fallback_broker=broker)

        tick = Tick(
            symbol="RELIANCE",
            token=12345,
            ltp=2500.0,
            volume=500000,
            timestamp=datetime.now(IST),
            exchange="NSE",
            bid=2499.50,
            ask=2500.50,
            open=2480.0,
            high=2510.0,
            low=2475.0,
            close=2505.0,
        )

        collector._on_fallback_tick(tick)

        bus.publish.assert_called_once()
        msg = bus.publish.call_args.kwargs["message"]
        assert msg["symbol"] == "RELIANCE"
        assert msg["ltp"] == 2500.0


# ---------------------------------------------------------------------------
# Tests: handle_feed_disconnect (Requirement 25.5)
# ---------------------------------------------------------------------------


class TestHandleFeedDisconnect:
    @pytest.mark.asyncio
    async def test_feed_disconnect_activates_fallback_and_reconnects(self):
        """On disconnect, fallback is activated and reconnection succeeds."""
        bus = _make_event_bus()
        broker = _make_fallback_broker()
        collector = MarketDataCollector(
            event_bus=bus,
            fallback_broker=broker,
            subscribed_symbols=["RELIANCE"],
        )
        collector._running = True

        await collector.handle_feed_disconnect()

        # Should have reconnected
        assert collector.is_connected is True
        assert collector.feed_source == FeedSource.NSE
        # Fallback should have been activated then deactivated
        assert collector.stats.fallback_activations >= 1


# ---------------------------------------------------------------------------
# Tests: tick_to_message static method
# ---------------------------------------------------------------------------


class TestTickToMessage:
    def test_all_fields_present(self):
        tick = _make_tick_data()
        msg = MarketDataCollector._tick_to_message(tick)

        expected_keys = {
            "symbol",
            "token",
            "ltp",
            "last_traded_qty",
            "volume",
            "bid",
            "bid_qty",
            "ask",
            "ask_qty",
            "open",
            "high",
            "low",
            "close",
            "previous_close",
            "timestamp",
            "exchange",
            "session",
        }
        assert set(msg.keys()) == expected_keys

    def test_session_field_matches_timestamp(self):
        ts = datetime(2024, 1, 15, 9, 5, tzinfo=IST)
        tick = _make_tick_data(timestamp=ts)
        msg = MarketDataCollector._tick_to_message(tick)

        assert msg["session"] == "PRE_MARKET"


# ---------------------------------------------------------------------------
# Tests: ConnectionStats
# ---------------------------------------------------------------------------


class TestConnectionStats:
    def test_avg_latency_zero_when_no_data(self):
        stats = ConnectionStats()
        assert stats.avg_publish_latency_ms == 0.0

    def test_avg_latency_calculation(self):
        stats = ConnectionStats()
        stats.total_publish_latency_ms = 100.0
        stats.publish_count_for_latency = 10
        assert stats.avg_publish_latency_ms == 10.0


# ===========================================================================
# BSE Market Data Collector Tests
# Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6
# ===========================================================================


def _make_bse_tick_data(
    symbol: str = "RELIANCE",
    ltp: float = 2502.0,
    timestamp: datetime = None,
) -> TickData:
    """Create a sample BSE TickData."""
    if timestamp is None:
        timestamp = datetime.now(IST)
    return TickData(
        symbol=symbol,
        token=54321,
        ltp=ltp,
        last_traded_qty=80,
        total_volume=300000,
        best_bid_price=2501.50,
        best_bid_qty=180,
        best_ask_price=2502.50,
        best_ask_qty=120,
        open=2478.0,
        high=2512.0,
        low=2470.0,
        close=2508.0,
        previous_close=2488.0,
        timestamp=timestamp,
        exchange="BSE",
    )


def _make_bse_json(symbol: str = "RELIANCE", ltp: float = 2502.0) -> str:
    """Create a raw BSE JSON message string."""
    return json.dumps(
        {
            "symbol": symbol,
            "token": 54321,
            "ltp": ltp,
            "last_traded_qty": 80,
            "total_volume": 300000,
            "best_bid_price": 2501.50,
            "best_bid_qty": 180,
            "best_ask_price": 2502.50,
            "best_ask_qty": 120,
            "open": 2478.0,
            "high": 2512.0,
            "low": 2470.0,
            "close": 2508.0,
            "previous_close": 2488.0,
            "timestamp": datetime.now(IST).isoformat(),
            "exchange": "BSE",
        }
    )


# ---------------------------------------------------------------------------
# Tests: BSE Initialisation & state (Requirement 26.1)
# ---------------------------------------------------------------------------


class TestBSEInit:
    def test_bse_initial_state(self):
        """BSE feed starts disconnected."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        assert collector.is_bse_connected is False
        assert collector.dual_listed_symbols == []
        assert collector.bse_only_symbols == []

    def test_init_with_dual_listed_symbols(self):
        bus = _make_event_bus()
        dual = ["RELIANCE", "TCS", "INFY"]
        collector = MarketDataCollector(
            event_bus=bus,
            dual_listed_symbols=dual,
        )
        assert collector.dual_listed_symbols == dual

    def test_init_with_bse_only_symbols(self):
        bus = _make_event_bus()
        bse_only = ["BSELTD", "BSESTOCK"]
        collector = MarketDataCollector(
            event_bus=bus,
            bse_only_symbols=bse_only,
        )
        assert collector.bse_only_symbols == bse_only

    def test_init_with_custom_bse_feed_url(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            bse_feed_url="wss://custom-bse.example.com/ws",
        )
        assert collector.bse_feed_url == "wss://custom-bse.example.com/ws"


# ---------------------------------------------------------------------------
# Tests: BSE Connection lifecycle (Requirement 26.1, 26.6)
# ---------------------------------------------------------------------------


class TestBSEConnection:
    @pytest.mark.asyncio
    async def test_connect_bse_feed(self):
        """connect_bse_feed sets BSE connected state. (Req 26.1)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        await collector.connect_bse_feed()

        assert collector.is_bse_connected is True
        assert collector.stats.bse_connected_at is not None

    @pytest.mark.asyncio
    async def test_disconnect_bse(self):
        """disconnect_bse clears BSE state."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        await collector.connect_bse_feed()

        await collector.disconnect_bse()

        assert collector.is_bse_connected is False
        assert collector.stats.bse_disconnected_at is not None

    @pytest.mark.asyncio
    async def test_full_disconnect_clears_bse(self):
        """Full disconnect also clears BSE state."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        await collector.connect_nse_feed()
        await collector.connect_bse_feed()

        await collector.disconnect()

        assert collector.is_connected is False
        assert collector.is_bse_connected is False

    @pytest.mark.asyncio
    async def test_bse_connect_failure_continues_with_nse(self):
        """If BSE connection fails, continues with NSE only. (Req 26.6)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        await collector.connect_nse_feed()

        # Simulate BSE connection failure
        with patch.object(
            collector,
            "_establish_bse_connection",
            side_effect=Exception("BSE down"),
        ):
            await collector.connect_bse_feed()

        # NSE should still be connected, BSE should not
        assert collector.is_connected is True
        assert collector.is_bse_connected is False


# ---------------------------------------------------------------------------
# Tests: BSE message parsing (Requirement 26.2)
# ---------------------------------------------------------------------------


class TestBSEMessageParsing:
    def test_parse_valid_bse_message(self):
        """BSE messages are parsed with same fields as NSE. (Req 26.2)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = _make_bse_json(symbol="RELIANCE", ltp=2502.0)

        tick = collector.parse_bse_message(raw)

        assert tick is not None
        assert tick.symbol == "RELIANCE"
        assert tick.ltp == 2502.0
        assert tick.exchange == "BSE"

    def test_parse_bse_message_has_all_fields(self):
        """BSE tick has same data fields as NSE. (Req 26.2)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = _make_bse_json()

        tick = collector.parse_bse_message(raw)

        assert tick.last_traded_qty == 80
        assert tick.total_volume == 300000
        assert tick.best_bid_price == 2501.50
        assert tick.best_bid_qty == 180
        assert tick.best_ask_price == 2502.50
        assert tick.best_ask_qty == 120
        assert tick.open == 2478.0
        assert tick.high == 2512.0
        assert tick.low == 2470.0
        assert tick.close == 2508.0
        assert tick.previous_close == 2488.0

    def test_parse_invalid_bse_json(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        tick = collector.parse_bse_message("not json")
        assert tick is None

    def test_parse_bse_missing_required_field(self):
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = json.dumps({"ltp": 100.0})

        tick = collector.parse_bse_message(raw)
        assert tick is None

    def test_parse_bse_optional_fields_default(self):
        """Optional fields default to 0 when missing."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        raw = json.dumps(
            {
                "symbol": "BSELTD",
                "token": 999,
                "ltp": 150.0,
                "timestamp": datetime.now(IST).isoformat(),
            }
        )

        tick = collector.parse_bse_message(raw)

        assert tick is not None
        assert tick.exchange == "BSE"
        assert tick.last_traded_qty == 0
        assert tick.best_bid_price == 0.0


# ---------------------------------------------------------------------------
# Tests: Dual-listed handling — NSE primary (Requirement 26.3)
# ---------------------------------------------------------------------------


class TestDualListedHandling:
    def test_dual_listed_nse_primary_no_publish(self):
        """For dual-listed, BSE tick does NOT publish to event bus (NSE is primary). (Req 26.3)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            dual_listed_symbols=["RELIANCE"],
        )
        # Seed NSE price
        collector._nse_latest_prices["RELIANCE"] = 2500.0

        bse_tick = _make_bse_tick_data(symbol="RELIANCE", ltp=2501.0)
        collector._process_bse_tick(bse_tick)

        # Should NOT publish to event bus (NSE is primary)
        bus.publish.assert_not_called()

    def test_dual_listed_triggers_discrepancy_check(self):
        """For dual-listed, BSE tick triggers discrepancy detection. (Req 26.3, 26.5)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            dual_listed_symbols=["RELIANCE"],
        )
        # Seed NSE price
        collector._nse_latest_prices["RELIANCE"] = 2500.0

        # BSE price with >0.5% discrepancy
        bse_tick = _make_bse_tick_data(symbol="RELIANCE", ltp=2520.0)
        collector._process_bse_tick(bse_tick)

        assert collector.stats.price_discrepancies_detected == 1

    def test_dual_listed_no_discrepancy_when_close(self):
        """No discrepancy logged when prices are within 0.5%. (Req 26.5)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            dual_listed_symbols=["RELIANCE"],
        )
        collector._nse_latest_prices["RELIANCE"] = 2500.0

        # BSE price within 0.5% (2500 * 0.005 = 12.5, so 2510 is within)
        bse_tick = _make_bse_tick_data(symbol="RELIANCE", ltp=2510.0)
        collector._process_bse_tick(bse_tick)

        assert collector.stats.price_discrepancies_detected == 0

    def test_dual_listed_no_nse_price_yet(self):
        """If no NSE price yet, no discrepancy check for dual-listed."""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            dual_listed_symbols=["RELIANCE"],
        )
        # No NSE price seeded

        bse_tick = _make_bse_tick_data(symbol="RELIANCE", ltp=2500.0)
        collector._process_bse_tick(bse_tick)

        assert collector.stats.price_discrepancies_detected == 0
        bus.publish.assert_not_called()

    def test_nse_tick_tracks_price_for_discrepancy(self):
        """NSE ticks update the latest price cache for discrepancy detection."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        nse_tick = _make_tick_data(symbol="RELIANCE", ltp=2500.0)
        collector._process_tick(nse_tick)

        assert collector._nse_latest_prices["RELIANCE"] == 2500.0


# ---------------------------------------------------------------------------
# Tests: BSE-only securities (Requirement 26.4)
# ---------------------------------------------------------------------------


class TestBSEOnlySecurities:
    def test_bse_only_publishes_to_event_bus(self):
        """BSE-only securities are published as sole source. (Req 26.4)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            bse_only_symbols=["BSELTD"],
        )

        bse_tick = _make_bse_tick_data(symbol="BSELTD", ltp=150.0)
        collector._process_bse_tick(bse_tick)

        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args.kwargs["stream_name"] == "stream:ticks:BSELTD"

    def test_bse_only_message_contains_all_fields(self):
        """BSE-only tick message has all required fields. (Req 26.2)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            bse_only_symbols=["BSELTD"],
        )

        bse_tick = _make_bse_tick_data(symbol="BSELTD", ltp=150.0)
        collector._process_bse_tick(bse_tick)

        msg = bus.publish.call_args.kwargs["message"]
        assert msg["symbol"] == "BSELTD"
        assert msg["ltp"] == 150.0
        assert msg["exchange"] == "BSE"
        assert "volume" in msg
        assert "bid" in msg
        assert "ask" in msg

    def test_bse_only_updates_stats(self):
        """BSE-only tick updates both general and BSE stats."""
        bus = _make_event_bus()
        collector = MarketDataCollector(
            event_bus=bus,
            bse_only_symbols=["BSELTD"],
        )

        bse_tick = _make_bse_tick_data(symbol="BSELTD", ltp=150.0)
        collector._process_bse_tick(bse_tick)

        assert collector.stats.bse_ticks_received == 1
        assert collector.stats.bse_ticks_published == 1
        # Also updates general stats via _process_tick
        assert collector.stats.total_ticks_received == 1
        assert collector.stats.total_ticks_published == 1


# ---------------------------------------------------------------------------
# Tests: Price discrepancy detection (Requirement 26.5)
# ---------------------------------------------------------------------------


class TestPriceDiscrepancy:
    def test_discrepancy_above_threshold(self):
        """Detects discrepancy when diff > 0.5%. (Req 26.5)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        # 2500 * 0.005 = 12.5, so 2515 is 0.6% diff
        result = collector.detect_price_discrepancy("RELIANCE", 2500.0, 2515.0)

        assert result is True
        assert collector.stats.price_discrepancies_detected == 1

    def test_no_discrepancy_below_threshold(self):
        """No discrepancy when diff <= 0.5%. (Req 26.5)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        # 2500 * 0.005 = 12.5, so 2510 is 0.4% diff
        result = collector.detect_price_discrepancy("RELIANCE", 2500.0, 2510.0)

        assert result is False
        assert collector.stats.price_discrepancies_detected == 0

    def test_discrepancy_exact_threshold(self):
        """At exactly 0.5%, no discrepancy (must be >0.5%). (Req 26.5)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        # Exactly 0.5%: 2500 * 0.005 = 12.5 → BSE = 2512.5
        result = collector.detect_price_discrepancy("RELIANCE", 2500.0, 2512.5)

        assert result is False

    def test_discrepancy_bse_lower_than_nse(self):
        """Detects discrepancy when BSE price is lower than NSE."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        result = collector.detect_price_discrepancy("RELIANCE", 2500.0, 2480.0)

        assert result is True  # 0.8% diff

    def test_discrepancy_zero_nse_price(self):
        """Returns False for zero NSE price (avoid division by zero)."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        result = collector.detect_price_discrepancy("RELIANCE", 0.0, 2500.0)

        assert result is False

    def test_discrepancy_zero_bse_price(self):
        """Returns False for zero BSE price."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        result = collector.detect_price_discrepancy("RELIANCE", 2500.0, 0.0)

        assert result is False

    def test_discrepancy_negative_prices(self):
        """Returns False for negative prices."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        result = collector.detect_price_discrepancy("RELIANCE", -100.0, 2500.0)
        assert result is False

    def test_multiple_discrepancies_increment_stats(self):
        """Multiple discrepancies increment the counter."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        collector.detect_price_discrepancy("RELIANCE", 2500.0, 2520.0)
        collector.detect_price_discrepancy("TCS", 3500.0, 3540.0)

        assert collector.stats.price_discrepancies_detected == 2


# ---------------------------------------------------------------------------
# Tests: BSE feed unavailability — continue with NSE (Requirement 26.6)
# ---------------------------------------------------------------------------


class TestBSEFeedUnavailability:
    @pytest.mark.asyncio
    async def test_nse_continues_when_bse_unavailable(self):
        """NSE feed continues operating when BSE is unavailable. (Req 26.6)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        # Connect NSE successfully
        await collector.connect_nse_feed()
        assert collector.is_connected is True

        # BSE fails to connect
        with patch.object(
            collector,
            "_establish_bse_connection",
            side_effect=Exception("BSE down"),
        ):
            await collector.connect_bse_feed()

        # NSE still works
        assert collector.is_connected is True
        assert collector.is_bse_connected is False

        # Can still process NSE ticks
        tick = _make_tick_data()
        collector._process_tick(tick)
        assert collector.stats.total_ticks_published == 1

        await collector.disconnect()

    @pytest.mark.asyncio
    async def test_handle_bse_feed_disconnect(self):
        """BSE disconnect handler logs and attempts reconnection. (Req 26.6)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        collector._running = True

        await collector.handle_bse_feed_disconnect()

        # Should have reconnected
        assert collector.is_bse_connected is True
        assert collector.stats.bse_reconnection_attempts >= 1

    @pytest.mark.asyncio
    async def test_bse_reconnect_max_attempts(self):
        """BSE reconnection gives up after max attempts. (Req 26.6)"""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)
        collector._bse_reconnect_attempts = collector.MAX_RECONNECT_ATTEMPTS

        success = await collector._reconnect_bse()

        assert success is False
        assert collector.is_bse_connected is False

    @pytest.mark.asyncio
    async def test_bse_reconnect_success(self):
        """BSE reconnection succeeds and restores state."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        success = await collector._reconnect_bse()

        assert success is True
        assert collector.is_bse_connected is True


# ---------------------------------------------------------------------------
# Tests: BSE ConnectionStats
# ---------------------------------------------------------------------------


class TestBSEConnectionStats:
    def test_bse_stats_initial_values(self):
        stats = ConnectionStats()
        assert stats.bse_connected_at is None
        assert stats.bse_disconnected_at is None
        assert stats.bse_ticks_received == 0
        assert stats.bse_ticks_published == 0
        assert stats.bse_reconnection_attempts == 0
        assert stats.price_discrepancies_detected == 0

    def test_unknown_symbol_bse_tick_publishes(self):
        """Unknown symbols (not in dual or bse-only lists) are published."""
        bus = _make_event_bus()
        collector = MarketDataCollector(event_bus=bus)

        bse_tick = _make_bse_tick_data(symbol="UNKNOWN", ltp=100.0)
        collector._process_bse_tick(bse_tick)

        bus.publish.assert_called_once()
        assert collector.stats.bse_ticks_received == 1
        assert collector.stats.bse_ticks_published == 1
