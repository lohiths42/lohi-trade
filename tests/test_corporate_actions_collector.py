"""
Tests for the Corporate Actions Collector.

Covers: fetching corporate actions, exchange announcements, deduplication,
storage, notifications for watchlist securities, price adjustments for
splits/bonuses, scheduling logic, and serialization round-trips.

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.ingestion.corporate_actions_collector import (
    CorporateActionsCollector,
    CorporateAction,
    CorporateActionType,
    ExchangeAnnouncement,
    AnnouncementType,
    IST,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_bus() -> MagicMock:
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="msg-id-1")
    return bus


def _make_collector(
    watchlist: list = None,
    universe: dict = None,
) -> tuple:
    """Create a collector with mock event bus."""
    bus = _make_event_bus()
    collector = CorporateActionsCollector(
        event_bus=bus,
        watchlist_symbols=watchlist or [],
        stock_universe=universe or {},
    )
    return collector, bus


def _make_action(
    symbol: str = "RELIANCE",
    action_type: CorporateActionType = CorporateActionType.DIVIDEND,
    ex_date: date = None,
    record_date: date = None,
    details: dict = None,
    source: str = "NSE",
) -> CorporateAction:
    """Create a sample CorporateAction."""
    return CorporateAction(
        symbol=symbol,
        action_type=action_type,
        ex_date=ex_date or date(2024, 6, 15),
        record_date=record_date or date(2024, 6, 17),
        details=details or {"amount": 10.0},
        source=source,
    )


def _make_announcement(
    symbol: str = "RELIANCE",
    ann_type: AnnouncementType = AnnouncementType.CIRCUIT_BREAKER,
    details: dict = None,
    source: str = "NSE",
) -> ExchangeAnnouncement:
    """Create a sample ExchangeAnnouncement."""
    return ExchangeAnnouncement(
        symbol=symbol,
        announcement_type=ann_type,
        details=details or {"direction": "upper"},
        source=source,
        announced_at=datetime(2024, 6, 15, 10, 30, tzinfo=IST),
    )


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------

class TestCorporateActionsCollectorInit:
    def test_initial_state(self):
        collector, bus = _make_collector()

        assert collector.is_running is False
        assert collector.last_fetch_time is None
        assert collector.total_actions_fetched == 0
        assert collector.total_announcements_fetched == 0
        assert collector.total_notifications_sent == 0
        assert collector.total_price_adjustments == 0
        assert collector.fetch_errors == 0
        assert collector.action_history == []
        assert collector.announcement_history == []

    def test_init_with_watchlist(self):
        collector, _ = _make_collector(watchlist=["RELIANCE", "TCS"])
        assert collector.watchlist_symbols == ["RELIANCE", "TCS"]

    def test_init_with_stock_universe(self):
        universe = {"RELIANCE": {"price": 2500.0}, "TCS": {"price": 3500.0}}
        collector, _ = _make_collector(universe=universe)
        assert collector.stock_universe == universe

    def test_init_default_urls(self):
        bus = _make_event_bus()
        collector = CorporateActionsCollector(event_bus=bus)
        assert collector.nse_api_url == "https://nse-api.example.com"
        assert collector.bse_api_url == "https://bse-api.example.com"


# ---------------------------------------------------------------------------
# Tests: CorporateAction dataclass serialization
# ---------------------------------------------------------------------------

class TestCorporateActionSerialization:
    def test_to_dict(self):
        action = _make_action()
        d = action.to_dict()

        assert d["symbol"] == "RELIANCE"
        assert d["action_type"] == "DIVIDEND"
        assert d["ex_date"] == "2024-06-15"
        assert d["record_date"] == "2024-06-17"
        assert d["details"] == {"amount": 10.0}
        assert d["source"] == "NSE"

    def test_from_dict_round_trip(self):
        original = _make_action()
        original.fetched_at = datetime(2024, 6, 15, 12, 0, tzinfo=IST)
        d = original.to_dict()
        restored = CorporateAction.from_dict(d)

        assert restored.symbol == original.symbol
        assert restored.action_type == original.action_type
        assert restored.ex_date == original.ex_date
        assert restored.record_date == original.record_date
        assert restored.details == original.details
        assert restored.source == original.source

    def test_from_dict_with_none_dates(self):
        d = {
            "symbol": "TCS",
            "action_type": "SPLIT",
            "ex_date": None,
            "record_date": None,
            "details": {"ratio": "2:1"},
            "source": "BSE",
        }
        action = CorporateAction.from_dict(d)
        assert action.ex_date is None
        assert action.record_date is None

    def test_from_dict_with_string_details(self):
        d = {
            "symbol": "INFY",
            "action_type": "BONUS",
            "details": '{"ratio": "1:1"}',
        }
        action = CorporateAction.from_dict(d)
        assert action.details == {"ratio": "1:1"}


# ---------------------------------------------------------------------------
# Tests: ExchangeAnnouncement serialization
# ---------------------------------------------------------------------------

class TestAnnouncementSerialization:
    def test_to_dict(self):
        ann = _make_announcement()
        d = ann.to_dict()

        assert d["symbol"] == "RELIANCE"
        assert d["announcement_type"] == "CIRCUIT_BREAKER"
        assert d["source"] == "NSE"
        assert d["announced_at"] is not None

    def test_from_dict_round_trip(self):
        original = _make_announcement()
        d = original.to_dict()
        restored = ExchangeAnnouncement.from_dict(d)

        assert restored.symbol == original.symbol
        assert restored.announcement_type == original.announcement_type
        assert restored.details == original.details
        assert restored.source == original.source

    def test_from_dict_with_string_details(self):
        d = {
            "symbol": "TCS",
            "announcement_type": "TRADING_HALT",
            "details": '{"reason": "pending news"}',
        }
        ann = ExchangeAnnouncement.from_dict(d)
        assert ann.details == {"reason": "pending news"}


# ---------------------------------------------------------------------------
# Tests: Fetching corporate actions (Req 27.1)
# ---------------------------------------------------------------------------

class TestFetchCorporateActions:
    @pytest.mark.asyncio
    async def test_fetch_returns_combined_nse_bse(self):
        """Fetches from both NSE and BSE and combines results. (Req 27.1)"""
        collector, bus = _make_collector()

        nse_action = _make_action(symbol="RELIANCE", source="NSE")
        bse_action = _make_action(symbol="TCS", source="BSE")

        with patch.object(collector, "_fetch_from_nse", return_value=[nse_action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[bse_action]):
                actions = await collector.fetch_corporate_actions()

        assert len(actions) == 2
        symbols = {a.symbol for a in actions}
        assert symbols == {"RELIANCE", "TCS"}

    @pytest.mark.asyncio
    async def test_fetch_stores_in_history(self):
        """Fetched actions are stored in history. (Req 27.4)"""
        collector, bus = _make_collector()
        action = _make_action()

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                await collector.fetch_corporate_actions()

        assert len(collector.action_history) == 1
        assert collector.action_history[0].symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_fetch_publishes_to_event_bus(self):
        """Each action is published to the corporate actions stream."""
        collector, bus = _make_collector()
        action = _make_action()

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                await collector.fetch_corporate_actions()

        # At least one publish call for the action
        assert bus.publish.called
        call_args_list = bus.publish.call_args_list
        streams = [c.kwargs.get("stream_name") or c[1].get("stream_name", c[0][0] if c[0] else "")
                    for c in call_args_list]
        assert CorporateActionsCollector.CORPORATE_ACTIONS_STREAM in streams

    @pytest.mark.asyncio
    async def test_fetch_updates_stats(self):
        """Stats are updated after fetch."""
        collector, bus = _make_collector()
        action = _make_action()

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                await collector.fetch_corporate_actions()

        assert collector.total_actions_fetched == 1
        assert collector.last_fetch_time is not None

    @pytest.mark.asyncio
    async def test_fetch_handles_error_gracefully(self):
        """Errors during fetch increment error count but don't raise."""
        collector, bus = _make_collector()

        with patch.object(collector, "_fetch_from_nse", side_effect=Exception("API down")):
            actions = await collector.fetch_corporate_actions()

        assert actions == []
        assert collector.fetch_errors == 1

    @pytest.mark.asyncio
    async def test_fetch_sets_fetched_at(self):
        """Each action gets a fetched_at timestamp."""
        collector, bus = _make_collector()
        action = _make_action()
        assert action.fetched_at is None

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                result = await collector.fetch_corporate_actions()

        assert result[0].fetched_at is not None


# ---------------------------------------------------------------------------
# Tests: Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_dedup_same_action_from_nse_and_bse(self):
        """Same action from NSE and BSE is deduplicated."""
        collector, bus = _make_collector()

        action_nse = _make_action(symbol="RELIANCE", source="NSE")
        action_bse = _make_action(symbol="RELIANCE", source="BSE")

        with patch.object(collector, "_fetch_from_nse", return_value=[action_nse]):
            with patch.object(collector, "_fetch_from_bse", return_value=[action_bse]):
                actions = await collector.fetch_corporate_actions()

        assert len(actions) == 1

    @pytest.mark.asyncio
    async def test_dedup_against_existing_history(self):
        """Actions already in history are not re-added."""
        collector, bus = _make_collector()
        existing = _make_action(symbol="RELIANCE")
        existing.fetched_at = datetime.now(IST)
        collector._action_history.append(existing)

        new_action = _make_action(symbol="RELIANCE")  # same key

        with patch.object(collector, "_fetch_from_nse", return_value=[new_action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                actions = await collector.fetch_corporate_actions()

        assert len(actions) == 0
        assert len(collector.action_history) == 1

    def test_dedup_different_action_types_kept(self):
        """Different action types for same symbol are kept."""
        collector, _ = _make_collector()
        actions = [
            _make_action(symbol="RELIANCE", action_type=CorporateActionType.DIVIDEND),
            _make_action(symbol="RELIANCE", action_type=CorporateActionType.SPLIT),
        ]
        result = collector._deduplicate_actions(actions)
        assert len(result) == 2

    def test_dedup_different_dates_kept(self):
        """Same action type with different ex-dates are kept."""
        collector, _ = _make_collector()
        actions = [
            _make_action(symbol="RELIANCE", ex_date=date(2024, 6, 15)),
            _make_action(symbol="RELIANCE", ex_date=date(2024, 9, 15)),
        ]
        result = collector._deduplicate_actions(actions)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests: Exchange announcements (Req 27.2)
# ---------------------------------------------------------------------------

class TestFetchAnnouncements:
    @pytest.mark.asyncio
    async def test_fetch_announcements_combined(self):
        """Fetches from both NSE and BSE. (Req 27.2)"""
        collector, bus = _make_collector()

        nse_ann = _make_announcement(symbol="RELIANCE", source="NSE")
        bse_ann = _make_announcement(symbol="TCS", source="BSE")

        with patch.object(collector, "_fetch_nse_announcements", return_value=[nse_ann]):
            with patch.object(collector, "_fetch_bse_announcements", return_value=[bse_ann]):
                anns = await collector.fetch_exchange_announcements()

        assert len(anns) == 2
        assert collector.total_announcements_fetched == 2

    @pytest.mark.asyncio
    async def test_fetch_announcements_stores_in_history(self):
        """Announcements are stored in history."""
        collector, bus = _make_collector()
        ann = _make_announcement()

        with patch.object(collector, "_fetch_nse_announcements", return_value=[ann]):
            with patch.object(collector, "_fetch_bse_announcements", return_value=[]):
                await collector.fetch_exchange_announcements()

        assert len(collector.announcement_history) == 1

    @pytest.mark.asyncio
    async def test_fetch_announcements_publishes(self):
        """Announcements are published to event bus."""
        collector, bus = _make_collector()
        ann = _make_announcement()

        with patch.object(collector, "_fetch_nse_announcements", return_value=[ann]):
            with patch.object(collector, "_fetch_bse_announcements", return_value=[]):
                await collector.fetch_exchange_announcements()

        assert bus.publish.called

    @pytest.mark.asyncio
    async def test_fetch_announcements_handles_error(self):
        """Errors during announcement fetch are handled gracefully."""
        collector, bus = _make_collector()

        with patch.object(collector, "_fetch_nse_announcements", side_effect=Exception("fail")):
            anns = await collector.fetch_exchange_announcements()

        assert anns == []
        assert collector.fetch_errors == 1

    @pytest.mark.asyncio
    async def test_announcement_types_covered(self):
        """All announcement types can be fetched. (Req 27.2)"""
        collector, bus = _make_collector()
        anns = [
            _make_announcement(symbol="A", ann_type=AnnouncementType.CIRCUIT_BREAKER),
            _make_announcement(symbol="B", ann_type=AnnouncementType.TRADING_HALT),
            _make_announcement(symbol="C", ann_type=AnnouncementType.NEW_LISTING),
        ]

        with patch.object(collector, "_fetch_nse_announcements", return_value=anns):
            with patch.object(collector, "_fetch_bse_announcements", return_value=[]):
                result = await collector.fetch_exchange_announcements()

        types = {a.announcement_type for a in result}
        assert types == {
            AnnouncementType.CIRCUIT_BREAKER,
            AnnouncementType.TRADING_HALT,
            AnnouncementType.NEW_LISTING,
        }


# ---------------------------------------------------------------------------
# Tests: Notifications for watchlist securities (Req 27.3)
# ---------------------------------------------------------------------------

class TestWatchlistNotifications:
    @pytest.mark.asyncio
    async def test_notification_sent_for_watchlist_action(self):
        """Notification sent when action is for a watchlist security. (Req 27.3)"""
        collector, bus = _make_collector(watchlist=["RELIANCE"])
        action = _make_action(symbol="RELIANCE")

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                await collector.fetch_corporate_actions()

        assert collector.total_notifications_sent == 1
        # Check notification was published to notifications stream
        notification_calls = [
            c for c in bus.publish.call_args_list
            if (c.kwargs.get("stream_name") or (c[0][0] if c[0] else ""))
            == CorporateActionsCollector.NOTIFICATIONS_STREAM
        ]
        assert len(notification_calls) >= 1

    @pytest.mark.asyncio
    async def test_no_notification_for_non_watchlist(self):
        """No notification for securities not in watchlist."""
        collector, bus = _make_collector(watchlist=["TCS"])
        action = _make_action(symbol="RELIANCE")

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                await collector.fetch_corporate_actions()

        assert collector.total_notifications_sent == 0

    @pytest.mark.asyncio
    async def test_notification_for_announcement_on_watchlist(self):
        """Notification sent for announcement on watchlist security."""
        collector, bus = _make_collector(watchlist=["RELIANCE"])
        ann = _make_announcement(symbol="RELIANCE")

        with patch.object(collector, "_fetch_nse_announcements", return_value=[ann]):
            with patch.object(collector, "_fetch_bse_announcements", return_value=[]):
                await collector.fetch_exchange_announcements()

        assert collector.total_notifications_sent == 1

    def test_update_watchlist(self):
        """Watchlist can be updated dynamically."""
        collector, _ = _make_collector()
        collector.update_watchlist(["INFY", "HDFC"])
        assert collector.watchlist_symbols == ["INFY", "HDFC"]

    @pytest.mark.asyncio
    async def test_notification_publish_failure_handled(self):
        """Notification publish failure doesn't crash the collector."""
        collector, bus = _make_collector(watchlist=["RELIANCE"])
        # Make publish fail only for notifications stream
        original_publish = bus.publish

        def selective_fail(**kwargs):
            if kwargs.get("stream_name") == CorporateActionsCollector.NOTIFICATIONS_STREAM:
                raise Exception("Redis down")
            return original_publish(**kwargs)

        bus.publish = MagicMock(side_effect=selective_fail)
        action = _make_action(symbol="RELIANCE")

        with patch.object(collector, "_fetch_from_nse", return_value=[action]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                # Should not raise
                await collector.fetch_corporate_actions()

        # Notification count stays 0 since publish failed
        assert collector.total_notifications_sent == 0


# ---------------------------------------------------------------------------
# Tests: Corporate action history storage (Req 27.4)
# ---------------------------------------------------------------------------

class TestActionHistory:
    def test_store_action(self):
        """Actions are stored with all fields. (Req 27.4)"""
        collector, _ = _make_collector()
        action = _make_action()
        collector._store_action(action)

        assert len(collector.action_history) == 1
        stored = collector.action_history[0]
        assert stored.action_type == CorporateActionType.DIVIDEND
        assert stored.ex_date == date(2024, 6, 15)
        assert stored.record_date == date(2024, 6, 17)

    def test_get_history_filter_by_symbol(self):
        """History can be filtered by symbol."""
        collector, _ = _make_collector()
        collector._store_action(_make_action(symbol="RELIANCE"))
        collector._store_action(_make_action(symbol="TCS"))

        result = collector.get_action_history(symbol="RELIANCE")
        assert len(result) == 1
        assert result[0].symbol == "RELIANCE"

    def test_get_history_filter_by_type(self):
        """History can be filtered by action type."""
        collector, _ = _make_collector()
        collector._store_action(_make_action(action_type=CorporateActionType.DIVIDEND))
        collector._store_action(_make_action(
            symbol="TCS",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2024, 7, 1),
        ))

        result = collector.get_action_history(action_type=CorporateActionType.SPLIT)
        assert len(result) == 1
        assert result[0].action_type == CorporateActionType.SPLIT

    def test_get_history_no_filter_returns_all(self):
        """No filter returns all history."""
        collector, _ = _make_collector()
        collector._store_action(_make_action(symbol="A"))
        collector._store_action(_make_action(symbol="B", ex_date=date(2024, 7, 1)))

        result = collector.get_action_history()
        assert len(result) == 2

    def test_all_action_types_stored(self):
        """All corporate action types can be stored. (Req 27.1)"""
        collector, _ = _make_collector()
        for at in CorporateActionType:
            collector._store_action(_make_action(
                symbol=f"SYM_{at.value}",
                action_type=at,
                ex_date=date(2024, 6, 15 + list(CorporateActionType).index(at)),
            ))

        assert len(collector.action_history) == 5
        stored_types = {a.action_type for a in collector.action_history}
        assert stored_types == set(CorporateActionType)


# ---------------------------------------------------------------------------
# Tests: Announcement history
# ---------------------------------------------------------------------------

class TestAnnouncementHistory:
    def test_store_announcement(self):
        collector, _ = _make_collector()
        ann = _make_announcement()
        collector._store_announcement(ann)

        assert len(collector.announcement_history) == 1

    def test_get_announcement_history_filter_by_symbol(self):
        collector, _ = _make_collector()
        collector._store_announcement(_make_announcement(symbol="RELIANCE"))
        collector._store_announcement(_make_announcement(symbol="TCS"))

        result = collector.get_announcement_history(symbol="TCS")
        assert len(result) == 1

    def test_get_announcement_history_filter_by_type(self):
        collector, _ = _make_collector()
        collector._store_announcement(
            _make_announcement(ann_type=AnnouncementType.CIRCUIT_BREAKER)
        )
        collector._store_announcement(
            _make_announcement(symbol="TCS", ann_type=AnnouncementType.NEW_LISTING)
        )

        result = collector.get_announcement_history(
            announcement_type=AnnouncementType.NEW_LISTING
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: Price adjustments for splits/bonuses (Req 27.5)
# ---------------------------------------------------------------------------

class TestPriceAdjustments:
    def test_split_adjusts_price(self):
        """Stock split divides price by split ratio. (Req 27.5)"""
        universe = {"RELIANCE": {"price": 2500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            details={"ratio": "5:1"},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["RELIANCE"]["price"] == pytest.approx(500.0)
        assert collector.total_price_adjustments == 1
        assert "SPLIT 5:1" in collector.stock_universe["RELIANCE"]["adjustment_reason"]

    def test_split_2_to_1(self):
        """2:1 split halves the price."""
        universe = {"TCS": {"price": 4000.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="TCS",
            action_type=CorporateActionType.SPLIT,
            details={"ratio": "2:1"},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["TCS"]["price"] == pytest.approx(2000.0)

    def test_bonus_adjusts_price(self):
        """Bonus issue adjusts price by existing/(bonus+existing). (Req 27.5)"""
        universe = {"INFY": {"price": 1500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="INFY",
            action_type=CorporateActionType.BONUS,
            details={"ratio": "1:1"},
        )
        collector._apply_price_adjustments([action])

        # 1:1 bonus -> price * 1/(1+1) = 750
        assert collector.stock_universe["INFY"]["price"] == pytest.approx(750.0)
        assert collector.total_price_adjustments == 1

    def test_bonus_2_to_3(self):
        """2:3 bonus adjusts price by 3/(2+3) = 3/5."""
        universe = {"HDFC": {"price": 1000.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="HDFC",
            action_type=CorporateActionType.BONUS,
            details={"ratio": "2:3"},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["HDFC"]["price"] == pytest.approx(600.0)

    def test_split_unknown_symbol_ignored(self):
        """Split for symbol not in universe is ignored."""
        collector, _ = _make_collector(universe={})

        action = _make_action(
            symbol="UNKNOWN",
            action_type=CorporateActionType.SPLIT,
            details={"ratio": "2:1"},
        )
        collector._apply_price_adjustments([action])

        assert collector.total_price_adjustments == 0

    def test_split_invalid_ratio_ignored(self):
        """Invalid split ratio is handled gracefully."""
        universe = {"RELIANCE": {"price": 2500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            details={"ratio": "invalid"},
        )
        collector._apply_price_adjustments([action])

        # Price unchanged
        assert collector.stock_universe["RELIANCE"]["price"] == 2500.0
        assert collector.total_price_adjustments == 0

    def test_split_missing_ratio_ignored(self):
        """Missing ratio in details is handled gracefully."""
        universe = {"RELIANCE": {"price": 2500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            details={},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["RELIANCE"]["price"] == 2500.0

    def test_split_zero_denominator_ignored(self):
        """Zero denominator in split ratio is handled."""
        universe = {"RELIANCE": {"price": 2500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            details={"ratio": "2:0"},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["RELIANCE"]["price"] == 2500.0

    def test_dividend_does_not_adjust_price(self):
        """Dividend actions don't trigger price adjustment."""
        universe = {"RELIANCE": {"price": 2500.0}}
        collector, _ = _make_collector(universe=universe)

        action = _make_action(
            symbol="RELIANCE",
            action_type=CorporateActionType.DIVIDEND,
            details={"amount": 10.0},
        )
        collector._apply_price_adjustments([action])

        assert collector.stock_universe["RELIANCE"]["price"] == 2500.0
        assert collector.total_price_adjustments == 0

    def test_multiple_adjustments_applied(self):
        """Multiple splits/bonuses are applied sequentially."""
        universe = {
            "A": {"price": 1000.0},
            "B": {"price": 2000.0},
        }
        collector, _ = _make_collector(universe=universe)

        actions = [
            _make_action(symbol="A", action_type=CorporateActionType.SPLIT,
                         details={"ratio": "2:1"}, ex_date=date(2024, 6, 15)),
            _make_action(symbol="B", action_type=CorporateActionType.BONUS,
                         details={"ratio": "1:2"}, ex_date=date(2024, 6, 16)),
        ]
        collector._apply_price_adjustments(actions)

        assert collector.stock_universe["A"]["price"] == pytest.approx(500.0)
        # B: 2000 * 2/(1+2) = 2000 * 2/3 ≈ 1333.33
        assert collector.stock_universe["B"]["price"] == pytest.approx(2000.0 * 2 / 3)
        assert collector.total_price_adjustments == 2

    def test_update_stock_universe(self):
        """Stock universe can be updated dynamically."""
        collector, _ = _make_collector()
        collector.update_stock_universe({"NEW": {"price": 100.0}})
        assert "NEW" in collector.stock_universe


# ---------------------------------------------------------------------------
# Tests: Scheduling logic (Req 27.6)
# ---------------------------------------------------------------------------

class TestScheduling:
    def test_should_fetch_during_market_hours(self):
        """Returns True during market hours with no recent fetch. (Req 27.6)"""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 10, 0, tzinfo=IST)  # 10:00 AM IST
        assert collector.should_fetch_now(now) is True

    def test_should_not_fetch_before_market(self):
        """Returns False before market opens."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 8, 0, tzinfo=IST)  # 8:00 AM IST
        assert collector.should_fetch_now(now) is False

    def test_should_not_fetch_between_close_and_post(self):
        """Returns False between market close and post-close window."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 16, 0, tzinfo=IST)  # 4:00 PM IST
        assert collector.should_fetch_now(now) is False

    def test_should_fetch_at_post_close(self):
        """Returns True at 7:00 PM IST post-close window. (Req 27.6)"""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 19, 0, tzinfo=IST)  # 7:00 PM IST
        assert collector.should_fetch_now(now) is True

    def test_should_not_fetch_after_post_close_window(self):
        """Returns False after the 5-minute post-close window."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 19, 10, tzinfo=IST)  # 7:10 PM IST
        assert collector.should_fetch_now(now) is False

    def test_should_not_fetch_too_soon_during_market(self):
        """Returns False if last fetch was less than 30 minutes ago. (Req 27.6)"""
        collector, _ = _make_collector()
        collector._last_fetch_time = datetime(2024, 6, 15, 10, 0, tzinfo=IST)
        now = datetime(2024, 6, 15, 10, 20, tzinfo=IST)  # 20 min later
        assert collector.should_fetch_now(now) is False

    def test_should_fetch_after_30_minutes(self):
        """Returns True if 30+ minutes since last fetch. (Req 27.6)"""
        collector, _ = _make_collector()
        collector._last_fetch_time = datetime(2024, 6, 15, 10, 0, tzinfo=IST)
        now = datetime(2024, 6, 15, 10, 31, tzinfo=IST)  # 31 min later
        assert collector.should_fetch_now(now) is True

    def test_post_close_only_once_per_day(self):
        """Post-close fetch only happens once per day."""
        collector, _ = _make_collector()
        collector._last_fetch_time = datetime(2024, 6, 15, 19, 0, tzinfo=IST)
        now = datetime(2024, 6, 15, 19, 3, tzinfo=IST)  # same day, same window
        assert collector.should_fetch_now(now) is False

    def test_should_not_fetch_late_night(self):
        """Returns False late at night."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 23, 0, tzinfo=IST)
        assert collector.should_fetch_now(now) is False

    def test_naive_datetime_treated_as_ist(self):
        """Naive datetime is treated as IST."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 12, 0)  # naive, during market hours
        assert collector.should_fetch_now(now) is True

    def test_market_open_boundary(self):
        """Exactly at market open (9:15) should trigger fetch."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 9, 15, tzinfo=IST)
        assert collector.should_fetch_now(now) is True

    def test_market_close_boundary(self):
        """Exactly at market close (15:30) should NOT trigger fetch."""
        collector, _ = _make_collector()
        now = datetime(2024, 6, 15, 15, 30, tzinfo=IST)
        assert collector.should_fetch_now(now) is False


# ---------------------------------------------------------------------------
# Tests: Scheduled fetch integration
# ---------------------------------------------------------------------------

class TestScheduledFetch:
    @pytest.mark.asyncio
    async def test_run_scheduled_fetch_triggers(self):
        """run_scheduled_fetch triggers when schedule says yes."""
        collector, bus = _make_collector()
        now = datetime(2024, 6, 15, 10, 0, tzinfo=IST)

        with patch.object(collector, "_fetch_from_nse", return_value=[]):
            with patch.object(collector, "_fetch_from_bse", return_value=[]):
                with patch.object(collector, "_fetch_nse_announcements", return_value=[]):
                    with patch.object(collector, "_fetch_bse_announcements", return_value=[]):
                        result = await collector.run_scheduled_fetch(now)

        assert result is not None  # fetch was triggered

    @pytest.mark.asyncio
    async def test_run_scheduled_fetch_skips(self):
        """run_scheduled_fetch returns None when not time."""
        collector, bus = _make_collector()
        now = datetime(2024, 6, 15, 8, 0, tzinfo=IST)  # before market

        result = await collector.run_scheduled_fetch(now)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: Start/stop lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        collector, _ = _make_collector()
        await collector.start()
        assert collector.is_running is True

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        collector, _ = _make_collector()
        await collector.start()
        await collector.stop()
        assert collector.is_running is False


# ---------------------------------------------------------------------------
# Tests: Event bus publishing
# ---------------------------------------------------------------------------

class TestEventBusPublishing:
    def test_publish_action(self):
        """Corporate action is published to correct stream."""
        collector, bus = _make_collector()
        action = _make_action()
        collector._publish_action(action)

        bus.publish.assert_called_once()
        kwargs = bus.publish.call_args.kwargs
        assert kwargs["stream_name"] == CorporateActionsCollector.CORPORATE_ACTIONS_STREAM
        assert kwargs["maxlen"] == CorporateActionsCollector.STREAM_MAXLEN

    def test_publish_announcement(self):
        """Announcement is published to correct stream."""
        collector, bus = _make_collector()
        ann = _make_announcement()
        collector._publish_announcement(ann)

        bus.publish.assert_called_once()
        kwargs = bus.publish.call_args.kwargs
        assert kwargs["stream_name"] == CorporateActionsCollector.ANNOUNCEMENTS_STREAM

    def test_publish_action_failure_handled(self):
        """Publish failure for action doesn't raise."""
        collector, bus = _make_collector()
        bus.publish.side_effect = Exception("Redis down")
        action = _make_action()

        # Should not raise
        collector._publish_action(action)

    def test_publish_announcement_failure_handled(self):
        """Publish failure for announcement doesn't raise."""
        collector, bus = _make_collector()
        bus.publish.side_effect = Exception("Redis down")
        ann = _make_announcement()

        # Should not raise
        collector._publish_announcement(ann)


# ---------------------------------------------------------------------------
# Tests: Enum coverage
# ---------------------------------------------------------------------------

class TestEnums:
    def test_corporate_action_types(self):
        """All required corporate action types exist. (Req 27.1)"""
        assert CorporateActionType.DIVIDEND.value == "DIVIDEND"
        assert CorporateActionType.SPLIT.value == "SPLIT"
        assert CorporateActionType.BONUS.value == "BONUS"
        assert CorporateActionType.RIGHTS.value == "RIGHTS"
        assert CorporateActionType.BUYBACK.value == "BUYBACK"

    def test_announcement_types(self):
        """All required announcement types exist. (Req 27.2)"""
        assert AnnouncementType.CIRCUIT_BREAKER.value == "CIRCUIT_BREAKER"
        assert AnnouncementType.TRADING_HALT.value == "TRADING_HALT"
        assert AnnouncementType.NEW_LISTING.value == "NEW_LISTING"
