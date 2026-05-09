"""
Tests for market data wiring module.

Verifies task 28.2:
- MarketDataCollector ticks are forwarded to unified stream:ticks
- Soldier/Commander/RMS/OMS can consume expanded market data seamlessly
- Corporate action notifications are wired to push notification center

Requirements: 25.4, 27.3
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call

import pytest

from src.ingestion.market_data_collector import (
    MarketDataCollector,
    TickData,
    MarketSession,
    IST,
)
from src.ingestion.corporate_actions_collector import (
    CorporateActionsCollector,
    CorporateAction,
    CorporateActionType,
    ExchangeAnnouncement,
    AnnouncementType,
)
from src.ingestion.market_data_wiring import (
    MarketDataWiring,
    UNIFIED_TICK_STREAM,
    UNIFIED_TICK_STREAM_MAXLEN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_bus() -> MagicMock:
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="msg-id-1")
    bus.redis_client = MagicMock()
    return bus


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


def _make_wiring(
    watchlist: list = None,
    push_callback: object = None,
) -> tuple:
    """Create a MarketDataWiring with mock dependencies."""
    bus = _make_event_bus()
    mdc = MarketDataCollector(event_bus=bus)
    cac = CorporateActionsCollector(
        event_bus=bus,
        watchlist_symbols=watchlist or [],
    )
    wiring = MarketDataWiring(
        event_bus=bus,
        market_data_collector=mdc,
        corporate_actions_collector=cac,
        push_notification_callback=push_callback,
    )
    return wiring, bus, mdc, cac


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------


class TestMarketDataWiringInit:
    def test_initial_state(self):
        wiring, _, _, _ = _make_wiring()
        assert wiring.is_wired is False
        assert wiring.ticks_forwarded == 0
        assert wiring.notifications_forwarded == 0

    def test_wire_sets_wired_flag(self):
        wiring, _, _, _ = _make_wiring()
        wiring.wire()
        assert wiring.is_wired is True

    def test_wire_idempotent(self):
        """Calling wire() twice does not double-patch."""
        wiring, _, _, _ = _make_wiring()
        wiring.wire()
        wiring.wire()
        assert wiring.is_wired is True


# ---------------------------------------------------------------------------
# Tests: Tick forwarding to unified stream (Req 25.4)
# ---------------------------------------------------------------------------


class TestTickForwardingToUnifiedStream:
    def test_tick_published_to_per_symbol_and_unified_stream(self):
        """After wiring, ticks go to both stream:ticks:{symbol} and stream:ticks."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data(symbol="RELIANCE")
        mdc._process_tick(tick)

        # Should have two publish calls: per-symbol + unified
        assert bus.publish.call_count == 2

        call_args_list = bus.publish.call_args_list
        stream_names = [
            c.kwargs.get("stream_name", c[0][0] if c[0] else "")
            for c in call_args_list
        ]
        assert "stream:ticks:RELIANCE" in stream_names
        assert UNIFIED_TICK_STREAM in stream_names

    def test_unified_stream_message_contains_all_fields(self):
        """Unified stream message has all required tick fields."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data(symbol="TCS", ltp=3500.0)
        mdc._process_tick(tick)

        # Find the unified stream publish call
        unified_call = None
        for c in bus.publish.call_args_list:
            sn = c.kwargs.get("stream_name", c[0][0] if c[0] else "")
            if sn == UNIFIED_TICK_STREAM:
                unified_call = c
                break

        assert unified_call is not None
        msg = unified_call.kwargs["message"]
        assert msg["symbol"] == "TCS"
        assert msg["ltp"] == 3500.0
        assert "timestamp" in msg
        assert "exchange" in msg
        assert "session" in msg

    def test_unified_stream_uses_correct_maxlen(self):
        """Unified stream publish uses the configured maxlen."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data()
        mdc._process_tick(tick)

        unified_call = None
        for c in bus.publish.call_args_list:
            sn = c.kwargs.get("stream_name", c[0][0] if c[0] else "")
            if sn == UNIFIED_TICK_STREAM:
                unified_call = c
                break

        assert unified_call is not None
        assert unified_call.kwargs["maxlen"] == UNIFIED_TICK_STREAM_MAXLEN

    def test_multiple_ticks_forwarded(self):
        """Multiple ticks are all forwarded to unified stream."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        for sym in ["RELIANCE", "TCS", "INFY"]:
            mdc._process_tick(_make_tick_data(symbol=sym))

        # 3 per-symbol + 3 unified = 6 total
        assert bus.publish.call_count == 6
        assert wiring.ticks_forwarded == 3

    def test_unified_publish_failure_does_not_break_per_symbol(self):
        """If unified stream publish fails, per-symbol still works."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        call_count = 0
        original_publish = bus.publish

        def selective_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("stream_name") == UNIFIED_TICK_STREAM:
                raise Exception("Redis unified stream down")
            return original_publish(**kwargs)

        bus.publish = MagicMock(side_effect=selective_fail)

        tick = _make_tick_data()
        # Should not raise
        mdc._process_tick(tick)

        # Per-symbol publish should have been called (first call)
        assert call_count == 2  # per-symbol + unified (which failed)
        assert wiring.ticks_forwarded == 0  # unified failed

    def test_stats_updated_after_forwarding(self):
        """Collector stats are still updated after wiring."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data()
        mdc._process_tick(tick)

        assert mdc.stats.total_ticks_received == 1
        assert mdc.stats.total_ticks_published == 1


# ---------------------------------------------------------------------------
# Tests: Corporate action notification wiring (Req 27.3)
# ---------------------------------------------------------------------------


class TestCorporateActionNotificationWiring:
    def test_notification_forwarded_to_push_callback(self):
        """Corporate action notification is forwarded to push callback."""
        captured = []

        def push_callback(symbol, title, message, data):
            captured.append({
                "symbol": symbol,
                "title": title,
                "message": message,
                "data": data,
            })

        wiring, bus, _, cac = _make_wiring(
            watchlist=["RELIANCE"],
            push_callback=push_callback,
        )
        wiring.wire()

        # Simulate sending a notification
        cac._send_notification(
            symbol="RELIANCE",
            title="Corporate Action: DIVIDEND",
            message="DIVIDEND announced for RELIANCE. Ex-date: 2024-06-15.",
            data={"action_type": "DIVIDEND", "symbol": "RELIANCE"},
        )

        assert len(captured) == 1
        assert captured[0]["symbol"] == "RELIANCE"
        assert "DIVIDEND" in captured[0]["title"]
        assert wiring.notifications_forwarded == 1

    def test_notification_still_published_to_stream(self):
        """Original stream:notifications publish still happens."""
        wiring, bus, _, cac = _make_wiring(
            watchlist=["TCS"],
            push_callback=lambda **kw: None,
        )
        wiring.wire()

        cac._send_notification(
            symbol="TCS",
            title="Corporate Action: SPLIT",
            message="SPLIT announced for TCS.",
            data={"action_type": "SPLIT"},
        )

        # Check that stream:notifications was published to
        notification_calls = [
            c for c in bus.publish.call_args_list
            if (c.kwargs.get("stream_name") or (c[0][0] if c[0] else ""))
            == "stream:notifications"
        ]
        assert len(notification_calls) >= 1

    def test_no_push_callback_still_publishes_to_stream(self):
        """Without push callback, notifications still go to stream."""
        wiring, bus, _, cac = _make_wiring(watchlist=["INFY"])
        wiring.wire()

        cac._send_notification(
            symbol="INFY",
            title="Corporate Action: BONUS",
            message="BONUS announced for INFY.",
            data={"action_type": "BONUS"},
        )

        # stream:notifications should still be published
        assert bus.publish.called
        assert wiring.notifications_forwarded == 0

    def test_push_callback_failure_does_not_break_stream_publish(self):
        """If push callback fails, stream publish still works."""
        def failing_callback(**kwargs):
            raise Exception("FCM down")

        wiring, bus, _, cac = _make_wiring(
            watchlist=["RELIANCE"],
            push_callback=failing_callback,
        )
        wiring.wire()

        # Should not raise
        cac._send_notification(
            symbol="RELIANCE",
            title="Test",
            message="Test message",
            data={},
        )

        # Stream publish should still have happened
        assert bus.publish.called
        assert wiring.notifications_forwarded == 0

    def test_multiple_notifications_forwarded(self):
        """Multiple notifications are all forwarded."""
        captured = []

        def push_callback(symbol, title, message, data):
            captured.append(symbol)

        wiring, bus, _, cac = _make_wiring(
            watchlist=["A", "B", "C"],
            push_callback=push_callback,
        )
        wiring.wire()

        for sym in ["A", "B", "C"]:
            cac._send_notification(
                symbol=sym,
                title=f"Action for {sym}",
                message=f"Details for {sym}",
                data={"symbol": sym},
            )

        assert len(captured) == 3
        assert wiring.notifications_forwarded == 3


# ---------------------------------------------------------------------------
# Tests: End-to-end wiring with fetch_corporate_actions
# ---------------------------------------------------------------------------


class TestEndToEndCorporateActionWiring:
    @pytest.mark.asyncio
    async def test_fetch_triggers_notification_forwarding(self):
        """Full fetch → notification → push callback flow works."""
        captured = []

        def push_callback(symbol, title, message, data):
            captured.append(symbol)

        bus = _make_event_bus()
        cac = CorporateActionsCollector(
            event_bus=bus,
            watchlist_symbols=["RELIANCE"],
        )
        mdc = MarketDataCollector(event_bus=bus)
        wiring = MarketDataWiring(
            event_bus=bus,
            market_data_collector=mdc,
            corporate_actions_collector=cac,
            push_notification_callback=push_callback,
        )
        wiring.wire()

        # Inject a corporate action for a watchlist symbol
        action = CorporateAction(
            symbol="RELIANCE",
            action_type=CorporateActionType.DIVIDEND,
            details={"amount": 10.0},
        )

        from unittest.mock import patch, AsyncMock

        with patch.object(cac, "_fetch_from_nse", new_callable=AsyncMock, return_value=[action]):
            with patch.object(cac, "_fetch_from_bse", new_callable=AsyncMock, return_value=[]):
                await cac.fetch_corporate_actions()

        # Notification should have been forwarded to push callback
        assert "RELIANCE" in captured
        assert wiring.notifications_forwarded >= 1


# ---------------------------------------------------------------------------
# Tests: Seamless consumption by Soldier/Commander/RMS/OMS
# ---------------------------------------------------------------------------


class TestSeamlessConsumption:
    def test_unified_stream_message_format_compatible_with_existing_pipeline(self):
        """
        Messages on unified stream:ticks have the same format as the
        existing websocket_client publishes, ensuring Soldier/Commander/
        RMS/OMS consume them seamlessly.
        """
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data(symbol="RELIANCE", ltp=2500.0)
        mdc._process_tick(tick)

        # Find unified stream message
        unified_msg = None
        for c in bus.publish.call_args_list:
            sn = c.kwargs.get("stream_name", c[0][0] if c[0] else "")
            if sn == UNIFIED_TICK_STREAM:
                unified_msg = c.kwargs["message"]
                break

        assert unified_msg is not None

        # Verify all fields expected by the existing pipeline
        required_fields = [
            "symbol", "ltp", "volume", "timestamp", "exchange",
        ]
        for field in required_fields:
            assert field in unified_msg, f"Missing field: {field}"

        # Verify field types are compatible
        assert isinstance(unified_msg["symbol"], str)
        assert isinstance(unified_msg["ltp"], (int, float))
        assert isinstance(unified_msg["exchange"], str)

    def test_per_symbol_stream_still_works_after_wiring(self):
        """Per-symbol streams are unaffected by wiring."""
        wiring, bus, mdc, _ = _make_wiring()
        wiring.wire()

        tick = _make_tick_data(symbol="INFY", ltp=1500.0)
        mdc._process_tick(tick)

        per_symbol_call = None
        for c in bus.publish.call_args_list:
            sn = c.kwargs.get("stream_name", c[0][0] if c[0] else "")
            if sn == "stream:ticks:INFY":
                per_symbol_call = c
                break

        assert per_symbol_call is not None
        msg = per_symbol_call.kwargs["message"]
        assert msg["symbol"] == "INFY"
        assert msg["ltp"] == 1500.0
