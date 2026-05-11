"""Unit tests for CandlePublisher.

Validates that completed candles are published to the correct Redis Stream
with the expected message format and maxlen.

Requirements: 2.2
"""

from datetime import datetime
from unittest.mock import MagicMock

from src.soldier.candle_builder import Candle, CandleBuilder
from src.soldier.candle_publisher import CANDLE_STREAM_MAXLEN, CandlePublisher


def _make_candle(**overrides) -> Candle:
    defaults = dict(
        symbol="RELIANCE",
        timeframe="1m",
        open=2500.0,
        high=2510.0,
        low=2495.0,
        close=2505.0,
        volume=1000,
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        is_complete=True,
    )
    defaults.update(overrides)
    return Candle(**defaults)


class TestCandlePublisher:
    """Unit tests for CandlePublisher."""

    def test_registers_callback_on_candle_builder(self):
        """CandlePublisher should register itself as a callback on the CandleBuilder."""
        event_bus = MagicMock()
        builder = CandleBuilder(timeframes=["1m"])

        assert len(builder._on_complete_callbacks) == 0
        CandlePublisher(event_bus, builder)
        assert len(builder._on_complete_callbacks) == 1

    def test_publishes_to_correct_stream(self):
        """Published stream name should be stream:candles:{symbol}:{timeframe}."""
        event_bus = MagicMock()
        builder = CandleBuilder(timeframes=["1m"])
        publisher = CandlePublisher(event_bus, builder)

        candle = _make_candle(symbol="TCS", timeframe="5m")
        publisher._on_candle_complete(candle)

        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "stream:candles:TCS:5m"

    def test_publishes_with_correct_maxlen(self):
        """Publish should use maxlen=500."""
        event_bus = MagicMock()
        builder = CandleBuilder(timeframes=["1m"])
        publisher = CandlePublisher(event_bus, builder)

        candle = _make_candle()
        publisher._on_candle_complete(candle)

        call_kwargs = event_bus.publish.call_args
        assert call_kwargs[1]["maxlen"] == CANDLE_STREAM_MAXLEN

    def test_serializes_candle_fields(self):
        """Published message should contain all required candle fields."""
        event_bus = MagicMock()
        builder = CandleBuilder(timeframes=["1m"])
        publisher = CandlePublisher(event_bus, builder)

        ts = datetime(2024, 1, 15, 10, 0, 0)
        candle = _make_candle(
            symbol="INFY",
            timeframe="15m",
            open=1500.0,
            high=1520.0,
            low=1490.0,
            close=1510.0,
            volume=5000,
            timestamp=ts,
            is_complete=True,
        )
        publisher._on_candle_complete(candle)

        message = event_bus.publish.call_args[0][1]
        assert message["symbol"] == "INFY"
        assert message["timeframe"] == "15m"
        assert message["open"] == 1500.0
        assert message["high"] == 1520.0
        assert message["low"] == 1490.0
        assert message["close"] == 1510.0
        assert message["volume"] == 5000
        assert message["timestamp"] == ts.isoformat()
        assert message["is_complete"] is True

    def test_handles_publish_failure_gracefully(self):
        """If EventBus.publish raises, the publisher should log the error and not crash."""
        event_bus = MagicMock()
        event_bus.publish.side_effect = ConnectionError("Redis down")
        builder = CandleBuilder(timeframes=["1m"])
        publisher = CandlePublisher(event_bus, builder)

        candle = _make_candle()
        # Should not raise
        publisher._on_candle_complete(candle)

    def test_callback_fires_on_candle_complete(self):
        """When CandleBuilder completes a candle, the publisher should publish it."""
        event_bus = MagicMock()
        builder = CandleBuilder(timeframes=["1m"])
        CandlePublisher(event_bus, builder)

        from src.ingestion.broker_interface import Tick

        # Process ticks in two different 1m buckets to trigger candle completion
        t1 = Tick(symbol="RELIANCE", token=2885, ltp=2500.0, volume=100,
                   timestamp=datetime(2024, 1, 15, 10, 0, 30), exchange="NSE")
        t2 = Tick(symbol="RELIANCE", token=2885, ltp=2510.0, volume=200,
                   timestamp=datetime(2024, 1, 15, 10, 1, 0), exchange="NSE")

        builder.process_tick(t1)
        assert event_bus.publish.call_count == 0

        builder.process_tick(t2)
        assert event_bus.publish.call_count == 1

        stream_name = event_bus.publish.call_args[0][0]
        assert stream_name == "stream:candles:RELIANCE:1m"
