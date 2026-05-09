"""
Publishes calculated indicators to Redis Streams via the Event Bus.

Receives completed candles, feeds them to the IndicatorEngine for calculation,
and publishes the resulting IndicatorSet to stream:indicators:{symbol}.

Requirements: 3.3, 3.5
"""

import time
from dataclasses import asdict
from typing import Optional

from src.soldier.candle_builder import Candle, CandleBuilder
from src.soldier.indicator_engine import IndicatorEngine, IndicatorSet
from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("IndicatorPublisher")

INDICATOR_STREAM_MAXLEN = 100

# Latency threshold in milliseconds (Requirement 3.5)
LATENCY_THRESHOLD_MS = 50


class IndicatorPublisher:
    """
    Publishes indicator calculations from IndicatorEngine to Redis Streams.

    Processes completed candles through the IndicatorEngine and publishes
    resulting IndicatorSet to stream:indicators:{symbol} with maxlen=100.
    Measures and logs latency, warning if it exceeds 50ms.

    Requirements: 3.3, 3.5
    """

    def __init__(self, event_bus: EventBus, indicator_engine: IndicatorEngine) -> None:
        self._event_bus = event_bus
        self._indicator_engine = indicator_engine
        logger.info("IndicatorPublisher initialized")

    def process_candle(self, candle: Candle) -> Optional[IndicatorSet]:
        """
        Process a completed candle through the indicator engine and publish results.

        Calls IndicatorEngine.add_candle to calculate indicators. If sufficient
        historical data exists and calculation succeeds, publishes the IndicatorSet
        to stream:indicators:{symbol}.

        Args:
            candle: A completed Candle object.

        Returns:
            IndicatorSet if indicators were calculated and published, None otherwise.

        Requirements: 3.3, 3.5
        """
        start = time.monotonic()

        result = self._indicator_engine.add_candle(candle)

        if result is None:
            return None

        stream_name = f"stream:indicators:{candle.symbol}"
        message = self._serialize_indicators(result)

        try:
            self._event_bus.publish(stream_name, message, maxlen=INDICATOR_STREAM_MAXLEN)
        except Exception as e:
            logger.error(
                f"Failed to publish indicators to {stream_name}: {e}",
                extra={"symbol": candle.symbol, "timeframe": candle.timeframe},
            )
            return result

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"Published indicators to {stream_name} in {elapsed_ms:.2f}ms",
            extra={
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "latency_ms": round(elapsed_ms, 2),
            },
        )

        if elapsed_ms > LATENCY_THRESHOLD_MS:
            logger.warning(
                f"Indicator publish latency {elapsed_ms:.2f}ms exceeds {LATENCY_THRESHOLD_MS}ms threshold",
                extra={
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )

        return result

    def register_on_candle_builder(self, candle_builder: CandleBuilder) -> None:
        """
        Register process_candle as a callback on the CandleBuilder.

        Args:
            candle_builder: The CandleBuilder to register on.
        """
        candle_builder.on_candle_complete(self.process_candle)
        logger.info("IndicatorPublisher registered on CandleBuilder")

    @staticmethod
    def _serialize_indicators(indicator_set: IndicatorSet) -> dict:
        """
        Convert an IndicatorSet to a dict suitable for Redis Stream publishing.

        Args:
            indicator_set: The IndicatorSet to serialize.

        Returns:
            Dictionary with all indicator fields, timestamp as ISO string.
        """
        data = asdict(indicator_set)
        data["timestamp"] = indicator_set.timestamp.isoformat()
        return data
