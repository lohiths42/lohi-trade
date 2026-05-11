"""Publishes completed candles to Redis Streams via the Event Bus.

Registers as a callback on CandleBuilder.on_candle_complete and publishes
each completed candle to stream:candles:{symbol}:{timeframe} with maxlen=500.

Requirements: 2.2
"""

import time

from src.soldier.candle_builder import Candle, CandleBuilder
from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("CandlePublisher")

CANDLE_STREAM_MAXLEN = 500


class CandlePublisher:
    """Publishes completed candles from CandleBuilder to Redis Streams.

    Automatically registers itself as a callback on the provided CandleBuilder.
    Measures and logs latency from candle completion to publish.
    """

    def __init__(self, event_bus: EventBus, candle_builder: CandleBuilder) -> None:
        self._event_bus = event_bus
        candle_builder.on_candle_complete(self._on_candle_complete)
        logger.info("CandlePublisher initialized and registered on CandleBuilder")

    def _on_candle_complete(self, candle: Candle) -> None:
        """Callback invoked when a candle completes. Publishes to Redis Stream."""
        start = time.monotonic()

        stream_name = f"stream:candles:{candle.symbol}:{candle.timeframe}"
        message = self._serialize_candle(candle)

        try:
            self._event_bus.publish(stream_name, message, maxlen=CANDLE_STREAM_MAXLEN)
        except Exception as e:
            logger.error(
                f"Failed to publish candle to {stream_name}: {e}",
                extra={"symbol": candle.symbol, "timeframe": candle.timeframe},
            )
            return

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"Published candle to {stream_name} in {elapsed_ms:.2f}ms",
            extra={
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "latency_ms": round(elapsed_ms, 2),
            },
        )

        if elapsed_ms > 100:
            logger.warning(
                f"Candle publish latency {elapsed_ms:.2f}ms exceeds 100ms threshold",
                extra={
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )

    @staticmethod
    def _serialize_candle(candle: Candle) -> dict:
        """Convert a Candle to a dict suitable for Redis Stream publishing."""
        return {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "timestamp": candle.timestamp.isoformat(),
            "is_complete": candle.is_complete,
        }
