"""Market data wiring module for LOHI-TRADE.

Connects MarketDataCollector and CorporateActionsCollector outputs to the
existing Redis Streams event bus so that Soldier/Commander/RMS/OMS consume
expanded market data seamlessly. Also wires corporate action notifications
to the push notification center for watchlist securities.

Task 28.2 — Requirements: 25.4, 27.3
"""

import logging
from collections.abc import Callable
from typing import Any

from src.ingestion.corporate_actions_collector import (
    CorporateActionsCollector,
)
from src.ingestion.market_data_collector import (
    MarketDataCollector,
    TickData,
)
from src.state.event_bus import EventBus

logger = logging.getLogger(__name__)

# Unified tick stream consumed by the existing pipeline
UNIFIED_TICK_STREAM = "stream:ticks"
UNIFIED_TICK_STREAM_MAXLEN = 5000

# Notification stream for corporate actions → push notification center
CORPORATE_ACTION_NOTIFICATION_STREAM = "stream:notifications"
NOTIFICATION_STREAM_MAXLEN = 500


class MarketDataWiring:
    """Wires MarketDataCollector and CorporateActionsCollector to the existing
    Redis Streams event bus.

    Responsibilities:
    - Publishes MarketDataCollector ticks to the unified ``stream:ticks``
      stream so Soldier/Commander/RMS/OMS consume expanded data seamlessly.
    - Wires corporate action notifications to the notification center
      (push notifications for watchlist securities).

    Requirements: 25.4, 27.3
    """

    def __init__(
        self,
        event_bus: EventBus,
        market_data_collector: MarketDataCollector,
        corporate_actions_collector: CorporateActionsCollector,
        push_notification_callback: Callable | None = None,
    ):
        """Initialize wiring between collectors and event bus.

        Args:
            event_bus: The Redis Streams event bus.
            market_data_collector: The NSE/BSE market data collector.
            corporate_actions_collector: The corporate actions collector.
            push_notification_callback: Optional async callback for sending
                push notifications. Signature:
                ``async def callback(user_id, symbol, title, message, data)``

        """
        self.event_bus = event_bus
        self.market_data_collector = market_data_collector
        self.corporate_actions_collector = corporate_actions_collector
        self._push_notification_callback = push_notification_callback
        self._wired = False
        self._ticks_forwarded = 0
        self._notifications_forwarded = 0

    def wire(self) -> None:
        """Wire all connections between collectors and the event bus.

        This patches the MarketDataCollector's ``_process_tick`` to also
        publish to the unified ``stream:ticks`` stream, and hooks into
        the CorporateActionsCollector's notification path.
        """
        if self._wired:
            logger.warning("MarketDataWiring already wired, skipping")
            return

        self._wire_market_data_to_unified_stream()
        self._wire_corporate_action_notifications()
        self._wired = True
        logger.info("MarketDataWiring: all connections established")

    def _wire_market_data_to_unified_stream(self) -> None:
        """Patch MarketDataCollector to also publish ticks to the unified
        ``stream:ticks`` stream.

        The collector already publishes to per-symbol streams
        (``stream:ticks:{symbol}``). This adds a secondary publish to
        the unified stream so that any consumer listening on
        ``stream:ticks`` (e.g., the existing candle builder pipeline)
        receives the expanded market data seamlessly.

        Requirement: 25.4
        """
        original_process_tick = self.market_data_collector._process_tick

        def enhanced_process_tick(tick_data: TickData) -> None:
            # Call original per-symbol publish
            original_process_tick(tick_data)

            # Also publish to unified stream:ticks
            try:
                message = MarketDataCollector._tick_to_message(tick_data)
                self.event_bus.publish(
                    stream_name=UNIFIED_TICK_STREAM,
                    message=message,
                    maxlen=UNIFIED_TICK_STREAM_MAXLEN,
                )
                self._ticks_forwarded += 1
            except Exception as e:
                logger.error(
                    f"Failed to forward tick to unified stream: {e}",
                    extra={"symbol": tick_data.symbol},
                )

        self.market_data_collector._process_tick = enhanced_process_tick
        logger.info(
            "Wired MarketDataCollector → unified stream:ticks",
        )

    def _wire_corporate_action_notifications(self) -> None:
        """Patch CorporateActionsCollector to forward watchlist notifications
        to the push notification center.

        The collector already publishes to ``stream:notifications`` via
        the event bus. This adds a hook so that each notification is also
        forwarded to the push notification callback (e.g., FCM) for
        mobile/web push delivery.

        Requirement: 27.3
        """
        original_send_notification = self.corporate_actions_collector._send_notification

        def enhanced_send_notification(
            symbol: str,
            title: str,
            message: str,
            data: dict[str, Any],
        ) -> None:
            # Call original (publishes to stream:notifications)
            original_send_notification(
                symbol=symbol,
                title=title,
                message=message,
                data=data,
            )

            # Forward to push notification callback
            if self._push_notification_callback is not None:
                try:
                    self._push_notification_callback(
                        symbol=symbol,
                        title=title,
                        message=message,
                        data=data,
                    )
                    self._notifications_forwarded += 1
                    logger.info(
                        f"Forwarded corporate action notification for {symbol} "
                        "to push notification center",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to forward notification to push center: {e}",
                        extra={"symbol": symbol},
                    )

        self.corporate_actions_collector._send_notification = enhanced_send_notification
        logger.info(
            "Wired CorporateActionsCollector → push notification center",
        )

    @property
    def is_wired(self) -> bool:
        """Whether wiring has been established."""
        return self._wired

    @property
    def ticks_forwarded(self) -> int:
        """Number of ticks forwarded to the unified stream."""
        return self._ticks_forwarded

    @property
    def notifications_forwarded(self) -> int:
        """Number of corporate action notifications forwarded to push center."""
        return self._notifications_forwarded
