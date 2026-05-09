"""
Corporate Actions Collector for LOHI-TRADE.

Fetches corporate actions (dividends, splits, bonuses, rights, buybacks)
and exchange announcements (circuit breakers, trading halts, new listings)
from NSE/BSE. Stores action history, sends notifications for watchlist
securities, and updates stock universe with adjusted prices.

Fetches every 30 minutes during market hours and once at 7:00 PM IST
after market close.

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("CorporateActionsCollector")

# IST timezone offset: UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


class CorporateActionType(Enum):
    """Types of corporate actions tracked."""
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"


class AnnouncementType(Enum):
    """Types of exchange announcements tracked."""
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    TRADING_HALT = "TRADING_HALT"
    NEW_LISTING = "NEW_LISTING"



@dataclass
class CorporateAction:
    """
    A corporate action record.

    Requirement 27.4: Store action type, ex-date, record date, and details.
    """
    symbol: str
    action_type: CorporateActionType
    ex_date: Optional[date] = None
    record_date: Optional[date] = None
    details: Dict[str, Any] = field(default_factory=dict)
    source: str = "NSE"
    fetched_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for storage and event bus publishing."""
        return {
            "symbol": self.symbol,
            "action_type": self.action_type.value,
            "ex_date": self.ex_date.isoformat() if self.ex_date else None,
            "record_date": self.record_date.isoformat() if self.record_date else None,
            "details": self.details,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorporateAction":
        """Deserialize from dict."""
        ex_date = None
        if data.get("ex_date"):
            ex_date = date.fromisoformat(data["ex_date"]) if isinstance(data["ex_date"], str) else data["ex_date"]
        record_date = None
        if data.get("record_date"):
            record_date = date.fromisoformat(data["record_date"]) if isinstance(data["record_date"], str) else data["record_date"]
        fetched_at = None
        if data.get("fetched_at"):
            fetched_at = datetime.fromisoformat(data["fetched_at"]) if isinstance(data["fetched_at"], str) else data["fetched_at"]
        details = data.get("details", {})
        if isinstance(details, str):
            details = json.loads(details)
        return cls(
            symbol=data["symbol"],
            action_type=CorporateActionType(data["action_type"]),
            ex_date=ex_date,
            record_date=record_date,
            details=details,
            source=data.get("source", "NSE"),
            fetched_at=fetched_at,
        )


@dataclass
class ExchangeAnnouncement:
    """
    An exchange announcement record.

    Requirement 27.2: circuit breakers, trading halts, new listings.
    """
    symbol: str
    announcement_type: AnnouncementType
    details: Dict[str, Any] = field(default_factory=dict)
    source: str = "NSE"
    announced_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "symbol": self.symbol,
            "announcement_type": self.announcement_type.value,
            "details": self.details,
            "source": self.source,
            "announced_at": self.announced_at.isoformat() if self.announced_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeAnnouncement":
        """Deserialize from dict."""
        announced_at = None
        if data.get("announced_at"):
            announced_at = datetime.fromisoformat(data["announced_at"]) if isinstance(data["announced_at"], str) else data["announced_at"]
        details = data.get("details", {})
        if isinstance(details, str):
            details = json.loads(details)
        return cls(
            symbol=data["symbol"],
            announcement_type=AnnouncementType(data["announcement_type"]),
            details=details,
            source=data.get("source", "NSE"),
            announced_at=announced_at,
        )



class CorporateActionsCollector:
    """
    Collects corporate actions and exchange announcements from NSE/BSE.

    Fetches dividends, splits, bonuses, rights, buybacks (Req 27.1),
    exchange announcements (Req 27.2), sends notifications for watchlist
    securities (Req 27.3), stores action history (Req 27.4), updates
    stock universe with adjusted prices (Req 27.5), and runs on a
    schedule of every 30 minutes during market hours plus once at
    7:00 PM IST after close (Req 27.6).

    Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6
    """

    # Market hours: 9:15 - 15:30 IST
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MIN = 15
    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MIN = 30

    # Post-close fetch at 19:00 IST (Req 27.6)
    POST_CLOSE_FETCH_HOUR = 19
    POST_CLOSE_FETCH_MIN = 0

    # Fetch interval during market hours: 30 minutes (Req 27.6)
    FETCH_INTERVAL_MINUTES = 30

    # Stream / notification config
    CORPORATE_ACTIONS_STREAM = "stream:corporate_actions"
    ANNOUNCEMENTS_STREAM = "stream:announcements"
    NOTIFICATIONS_STREAM = "stream:notifications"
    STREAM_MAXLEN = 500

    def __init__(
        self,
        event_bus: EventBus,
        nse_api_url: str = "https://nse-api.example.com",
        bse_api_url: str = "https://bse-api.example.com",
        watchlist_symbols: Optional[List[str]] = None,
        stock_universe: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Initialize the corporate actions collector.

        Args:
            event_bus: EventBus instance for publishing notifications.
            nse_api_url: Base URL for NSE corporate actions API.
            bse_api_url: Base URL for BSE corporate actions API.
            watchlist_symbols: Symbols in user watchlists for notifications.
            stock_universe: Current stock universe mapping symbol -> metadata.
        """
        self.event_bus = event_bus
        self.nse_api_url = nse_api_url
        self.bse_api_url = bse_api_url
        self._watchlist_symbols: List[str] = watchlist_symbols or []
        self._stock_universe: Dict[str, Dict[str, Any]] = stock_universe or {}

        # Corporate action history (Req 27.4)
        self._action_history: List[CorporateAction] = []
        # Exchange announcement history (Req 27.2)
        self._announcement_history: List[ExchangeAnnouncement] = []

        # Scheduling state
        self._running = False
        self._last_fetch_time: Optional[datetime] = None

        # Stats
        self._total_actions_fetched: int = 0
        self._total_announcements_fetched: int = 0
        self._total_notifications_sent: int = 0
        self._total_price_adjustments: int = 0
        self._fetch_errors: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_corporate_actions(self) -> List[CorporateAction]:
        """
        Fetch corporate actions from NSE and BSE.

        Fetches dividends, splits, bonuses, rights, and buybacks.
        Stores in history, sends notifications for watchlist securities,
        and updates stock universe for splits/bonuses.

        Returns:
            List of newly fetched corporate actions.

        Requirements: 27.1, 27.3, 27.4, 27.5
        """
        logger.info("Fetching corporate actions from NSE/BSE")
        now = datetime.now(IST)
        all_actions: List[CorporateAction] = []

        try:
            # Fetch from NSE (Req 27.1)
            nse_actions = await self._fetch_from_nse()
            all_actions.extend(nse_actions)

            # Fetch from BSE (Req 27.1)
            bse_actions = await self._fetch_from_bse()
            all_actions.extend(bse_actions)

            # Deduplicate by (symbol, action_type, ex_date)
            all_actions = self._deduplicate_actions(all_actions)

            # Store in history (Req 27.4)
            for action in all_actions:
                action.fetched_at = now
                self._store_action(action)

            # Publish to event bus
            for action in all_actions:
                self._publish_action(action)

            # Send notifications for watchlist securities (Req 27.3)
            self._send_watchlist_notifications(all_actions)

            # Update stock universe for splits/bonuses (Req 27.5)
            self._apply_price_adjustments(all_actions)

            self._total_actions_fetched += len(all_actions)
            self._last_fetch_time = now

            logger.info(
                f"Fetched {len(all_actions)} corporate actions "
                f"(NSE: {len(nse_actions)}, BSE: {len(bse_actions)})"
            )

        except Exception as e:
            self._fetch_errors += 1
            logger.error(f"Error fetching corporate actions: {e}", exc_info=True)

        return all_actions

    async def fetch_exchange_announcements(self) -> List[ExchangeAnnouncement]:
        """
        Fetch exchange announcements: circuit breakers, trading halts, new listings.

        Returns:
            List of newly fetched announcements.

        Requirements: 27.2
        """
        logger.info("Fetching exchange announcements from NSE/BSE")
        now = datetime.now(IST)
        all_announcements: List[ExchangeAnnouncement] = []

        try:
            nse_announcements = await self._fetch_nse_announcements()
            all_announcements.extend(nse_announcements)

            bse_announcements = await self._fetch_bse_announcements()
            all_announcements.extend(bse_announcements)

            # Store and publish
            for ann in all_announcements:
                ann.announced_at = ann.announced_at or now
                self._store_announcement(ann)
                self._publish_announcement(ann)

            # Notify for watchlist securities
            self._send_announcement_notifications(all_announcements)

            self._total_announcements_fetched += len(all_announcements)

            logger.info(f"Fetched {len(all_announcements)} exchange announcements")

        except Exception as e:
            self._fetch_errors += 1
            logger.error(f"Error fetching announcements: {e}", exc_info=True)

        return all_announcements

    def update_watchlist(self, symbols: List[str]) -> None:
        """
        Update the watchlist symbols for notification filtering.

        Args:
            symbols: Current watchlist symbols.
        """
        self._watchlist_symbols = list(symbols)
        logger.info(f"Updated watchlist with {len(symbols)} symbols")

    def update_stock_universe(self, universe: Dict[str, Dict[str, Any]]) -> None:
        """
        Update the stock universe reference.

        Args:
            universe: Mapping of symbol -> metadata dict.
        """
        self._stock_universe = dict(universe)
        logger.info(f"Updated stock universe with {len(universe)} securities")

    def get_action_history(
        self,
        symbol: Optional[str] = None,
        action_type: Optional[CorporateActionType] = None,
    ) -> List[CorporateAction]:
        """
        Retrieve stored corporate action history with optional filters.

        Args:
            symbol: Filter by symbol.
            action_type: Filter by action type.

        Returns:
            Filtered list of corporate actions.
        """
        result = list(self._action_history)
        if symbol:
            result = [a for a in result if a.symbol == symbol]
        if action_type:
            result = [a for a in result if a.action_type == action_type]
        return result

    def get_announcement_history(
        self,
        symbol: Optional[str] = None,
        announcement_type: Optional[AnnouncementType] = None,
    ) -> List[ExchangeAnnouncement]:
        """
        Retrieve stored exchange announcement history with optional filters.

        Args:
            symbol: Filter by symbol.
            announcement_type: Filter by announcement type.

        Returns:
            Filtered list of announcements.
        """
        result = list(self._announcement_history)
        if symbol:
            result = [a for a in result if a.symbol == symbol]
        if announcement_type:
            result = [a for a in result if a.announcement_type == announcement_type]
        return result

    def should_fetch_now(self, now: Optional[datetime] = None) -> bool:
        """
        Determine if a fetch should be triggered based on the schedule.

        Fetches every 30 minutes during market hours (9:15-15:30 IST)
        and once at 7:00 PM IST after market close.

        Args:
            now: Current time (defaults to IST now).

        Returns:
            True if a fetch should be triggered.

        Requirements: 27.6
        """
        if now is None:
            now = datetime.now(IST)
        else:
            if now.tzinfo is None:
                now = now.replace(tzinfo=IST)
            else:
                now = now.astimezone(IST)

        t = now.hour * 60 + now.minute

        market_open = self.MARKET_OPEN_HOUR * 60 + self.MARKET_OPEN_MIN   # 9:15 = 555
        market_close = self.MARKET_CLOSE_HOUR * 60 + self.MARKET_CLOSE_MIN  # 15:30 = 930
        post_close = self.POST_CLOSE_FETCH_HOUR * 60 + self.POST_CLOSE_FETCH_MIN  # 19:00 = 1140

        is_market_hours = market_open <= t < market_close
        is_post_close_window = post_close <= t < post_close + 5  # 5-minute window

        if not is_market_hours and not is_post_close_window:
            return False

        # Check if enough time has passed since last fetch
        if self._last_fetch_time is not None:
            last_t = self._last_fetch_time.astimezone(IST)
            elapsed = (now - last_t).total_seconds() / 60
            if is_market_hours and elapsed < self.FETCH_INTERVAL_MINUTES:
                return False
            # For post-close, only fetch once
            if is_post_close_window:
                last_t_minutes = last_t.hour * 60 + last_t.minute
                if last_t_minutes >= post_close and last_t.date() == now.date():
                    return False

        return True

    async def run_scheduled_fetch(self, now: Optional[datetime] = None) -> Optional[List[CorporateAction]]:
        """
        Run a fetch if the schedule says it's time.

        Args:
            now: Current time for schedule check.

        Returns:
            List of actions if fetch was triggered, None otherwise.
        """
        if self.should_fetch_now(now):
            actions = await self.fetch_corporate_actions()
            await self.fetch_exchange_announcements()
            return actions
        return None

    async def start(self) -> None:
        """Start the scheduled fetch loop."""
        self._running = True
        logger.info("Corporate actions collector started")

    async def stop(self) -> None:
        """Stop the scheduled fetch loop."""
        self._running = False
        logger.info("Corporate actions collector stopped")

    @property
    def is_running(self) -> bool:
        """Whether the collector is actively running."""
        return self._running

    @property
    def last_fetch_time(self) -> Optional[datetime]:
        """Time of the last successful fetch."""
        return self._last_fetch_time

    @property
    def total_actions_fetched(self) -> int:
        return self._total_actions_fetched

    @property
    def total_announcements_fetched(self) -> int:
        return self._total_announcements_fetched

    @property
    def total_notifications_sent(self) -> int:
        return self._total_notifications_sent

    @property
    def total_price_adjustments(self) -> int:
        return self._total_price_adjustments

    @property
    def fetch_errors(self) -> int:
        return self._fetch_errors

    @property
    def action_history(self) -> List[CorporateAction]:
        return list(self._action_history)

    @property
    def announcement_history(self) -> List[ExchangeAnnouncement]:
        return list(self._announcement_history)

    @property
    def watchlist_symbols(self) -> List[str]:
        return list(self._watchlist_symbols)

    @property
    def stock_universe(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._stock_universe)

    # ------------------------------------------------------------------
    # Internal: Fetching from exchanges
    # ------------------------------------------------------------------

    async def _fetch_from_nse(self) -> List[CorporateAction]:
        """
        Fetch corporate actions from NSE API.

        In production, this would call the NSE corporate actions REST API.
        Returns empty list by default; override or inject for testing.

        Requirements: 27.1
        """
        # Production: HTTP GET to NSE corporate actions endpoint
        return []

    async def _fetch_from_bse(self) -> List[CorporateAction]:
        """
        Fetch corporate actions from BSE API.

        In production, this would call the BSE corporate actions REST API.
        Returns empty list by default; override or inject for testing.

        Requirements: 27.1
        """
        # Production: HTTP GET to BSE corporate actions endpoint
        return []

    async def _fetch_nse_announcements(self) -> List[ExchangeAnnouncement]:
        """
        Fetch exchange announcements from NSE.

        Requirements: 27.2
        """
        return []

    async def _fetch_bse_announcements(self) -> List[ExchangeAnnouncement]:
        """
        Fetch exchange announcements from BSE.

        Requirements: 27.2
        """
        return []

    # ------------------------------------------------------------------
    # Internal: Deduplication
    # ------------------------------------------------------------------

    def _deduplicate_actions(self, actions: List[CorporateAction]) -> List[CorporateAction]:
        """
        Deduplicate corporate actions by (symbol, action_type, ex_date).

        When the same action appears from both NSE and BSE, keep the NSE version.
        Also deduplicates against existing history.
        """
        seen = set()
        # Build set of existing history keys
        for existing in self._action_history:
            key = (existing.symbol, existing.action_type, existing.ex_date)
            seen.add(key)

        unique: List[CorporateAction] = []
        for action in actions:
            key = (action.symbol, action.action_type, action.ex_date)
            if key not in seen:
                seen.add(key)
                unique.append(action)
        return unique

    # ------------------------------------------------------------------
    # Internal: Storage (Req 27.4)
    # ------------------------------------------------------------------

    def _store_action(self, action: CorporateAction) -> None:
        """Store a corporate action in history."""
        self._action_history.append(action)
        logger.debug(
            f"Stored corporate action: {action.action_type.value} "
            f"for {action.symbol}"
        )

    def _store_announcement(self, announcement: ExchangeAnnouncement) -> None:
        """Store an exchange announcement in history."""
        self._announcement_history.append(announcement)
        logger.debug(
            f"Stored announcement: {announcement.announcement_type.value} "
            f"for {announcement.symbol}"
        )

    # ------------------------------------------------------------------
    # Internal: Event bus publishing
    # ------------------------------------------------------------------

    def _publish_action(self, action: CorporateAction) -> None:
        """Publish a corporate action to the event bus."""
        try:
            self.event_bus.publish(
                stream_name=self.CORPORATE_ACTIONS_STREAM,
                message=action.to_dict(),
                maxlen=self.STREAM_MAXLEN,
            )
        except Exception as e:
            logger.error(f"Failed to publish corporate action: {e}")

    def _publish_announcement(self, announcement: ExchangeAnnouncement) -> None:
        """Publish an exchange announcement to the event bus."""
        try:
            self.event_bus.publish(
                stream_name=self.ANNOUNCEMENTS_STREAM,
                message=announcement.to_dict(),
                maxlen=self.STREAM_MAXLEN,
            )
        except Exception as e:
            logger.error(f"Failed to publish announcement: {e}")

    # ------------------------------------------------------------------
    # Internal: Notifications (Req 27.3)
    # ------------------------------------------------------------------

    def _send_watchlist_notifications(self, actions: List[CorporateAction]) -> None:
        """
        Send notifications for corporate actions on watchlist securities.

        Requirements: 27.3
        """
        for action in actions:
            if action.symbol in self._watchlist_symbols:
                self._send_notification(
                    symbol=action.symbol,
                    title=f"Corporate Action: {action.action_type.value}",
                    message=(
                        f"{action.action_type.value} announced for {action.symbol}. "
                        f"Ex-date: {action.ex_date or 'TBD'}."
                    ),
                    data=action.to_dict(),
                )

    def _send_announcement_notifications(self, announcements: List[ExchangeAnnouncement]) -> None:
        """Send notifications for exchange announcements on watchlist securities."""
        for ann in announcements:
            if ann.symbol in self._watchlist_symbols:
                self._send_notification(
                    symbol=ann.symbol,
                    title=f"Exchange: {ann.announcement_type.value}",
                    message=(
                        f"{ann.announcement_type.value} for {ann.symbol}. "
                        f"Source: {ann.source}."
                    ),
                    data=ann.to_dict(),
                )

    def _send_notification(
        self,
        symbol: str,
        title: str,
        message: str,
        data: Dict[str, Any],
    ) -> None:
        """Publish a notification to the notifications stream."""
        try:
            self.event_bus.publish(
                stream_name=self.NOTIFICATIONS_STREAM,
                message={
                    "symbol": symbol,
                    "title": title,
                    "message": message,
                    "data": data,
                    "timestamp": datetime.now(IST).isoformat(),
                },
                maxlen=self.STREAM_MAXLEN,
            )
            self._total_notifications_sent += 1
            logger.info(f"Notification sent for {symbol}: {title}")
        except Exception as e:
            logger.error(f"Failed to send notification for {symbol}: {e}")

    # ------------------------------------------------------------------
    # Internal: Price adjustments (Req 27.5)
    # ------------------------------------------------------------------

    def _apply_price_adjustments(self, actions: List[CorporateAction]) -> None:
        """
        Update stock universe with adjusted prices after splits/bonuses.

        For SPLIT actions, divides the price by the split ratio.
        For BONUS actions, adjusts price based on the bonus ratio.

        Requirements: 27.5
        """
        for action in actions:
            if action.action_type == CorporateActionType.SPLIT:
                self._adjust_for_split(action)
            elif action.action_type == CorporateActionType.BONUS:
                self._adjust_for_bonus(action)

    def _adjust_for_split(self, action: CorporateAction) -> None:
        """
        Adjust stock universe price for a stock split.

        Expects details to contain 'ratio' as 'new:old' (e.g., '5:1'
        means 5 new shares for every 1 old share, price divides by 5).
        """
        symbol = action.symbol
        if symbol not in self._stock_universe:
            return

        ratio_str = action.details.get("ratio", "")
        if not ratio_str or ":" not in str(ratio_str):
            logger.warning(f"Invalid split ratio for {symbol}: {ratio_str}")
            return

        try:
            parts = str(ratio_str).split(":")
            new_shares = float(parts[0])
            old_shares = float(parts[1])
            if old_shares == 0:
                logger.warning(f"Zero denominator in split ratio for {symbol}")
                return
            split_factor = new_shares / old_shares
        except (ValueError, IndexError):
            logger.warning(f"Cannot parse split ratio for {symbol}: {ratio_str}")
            return

        current_price = self._stock_universe[symbol].get("price", 0)
        if current_price and split_factor > 0:
            adjusted_price = current_price / split_factor
            self._stock_universe[symbol]["price"] = adjusted_price
            self._stock_universe[symbol]["last_adjusted"] = datetime.now(IST).isoformat()
            self._stock_universe[symbol]["adjustment_reason"] = f"SPLIT {ratio_str}"
            self._total_price_adjustments += 1
            logger.info(
                f"Adjusted {symbol} price for split {ratio_str}: "
                f"{current_price:.2f} -> {adjusted_price:.2f}"
            )

    def _adjust_for_bonus(self, action: CorporateAction) -> None:
        """
        Adjust stock universe price for a bonus issue.

        Expects details to contain 'ratio' as 'bonus:existing'
        (e.g., '1:1' means 1 bonus share for every 1 existing,
        price adjusts by existing/(bonus+existing)).
        """
        symbol = action.symbol
        if symbol not in self._stock_universe:
            return

        ratio_str = action.details.get("ratio", "")
        if not ratio_str or ":" not in str(ratio_str):
            logger.warning(f"Invalid bonus ratio for {symbol}: {ratio_str}")
            return

        try:
            parts = str(ratio_str).split(":")
            bonus_shares = float(parts[0])
            existing_shares = float(parts[1])
            total = bonus_shares + existing_shares
            if total == 0:
                logger.warning(f"Zero total in bonus ratio for {symbol}")
                return
            adjustment_factor = existing_shares / total
        except (ValueError, IndexError):
            logger.warning(f"Cannot parse bonus ratio for {symbol}: {ratio_str}")
            return

        current_price = self._stock_universe[symbol].get("price", 0)
        if current_price and adjustment_factor > 0:
            adjusted_price = current_price * adjustment_factor
            self._stock_universe[symbol]["price"] = adjusted_price
            self._stock_universe[symbol]["last_adjusted"] = datetime.now(IST).isoformat()
            self._stock_universe[symbol]["adjustment_reason"] = f"BONUS {ratio_str}"
            self._total_price_adjustments += 1
            logger.info(
                f"Adjusted {symbol} price for bonus {ratio_str}: "
                f"{current_price:.2f} -> {adjusted_price:.2f}"
            )
