"""
Unit tests for IndicatorPublisher.

Validates that calculated indicators are published to the correct Redis Stream
with the expected message format and maxlen.

Requirements: 3.3, 3.5
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.soldier.candle_builder import Candle, CandleBuilder
from src.soldier.indicator_engine import IndicatorEngine, IndicatorSet
from src.soldier.indicator_publisher import (
    IndicatorPublisher,
    INDICATOR_STREAM_MAXLEN,
)


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


def _make_indicator_set(**overrides) -> IndicatorSet:
    defaults = dict(
        symbol="RELIANCE",
        timeframe="1m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=45.0,
        macd=1.5,
        macd_signal=1.2,
        macd_hist=0.3,
        bb_upper=2520.0,
        bb_middle=2505.0,
        bb_lower=2490.0,
        vwap=2503.0,
        ema_9=2504.0,
        ema_21=2502.0,
        supertrend=2480.0,
        supertrend_direction=1,
        atr_14=15.0,
        volume_avg_20=950.0,
    )
    defaults.update(overrides)
    return IndicatorSet(**defaults)


class TestIndicatorPublisher:
    """Unit tests for IndicatorPublisher."""

    def test_publishes_to_correct_stream_when_indicators_available(self):
        """When indicators are calculated, they should be published to stream:indicators:{symbol}."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        indicator_set = _make_indicator_set(symbol="TCS")
        engine.add_candle.return_value = indicator_set

        publisher = IndicatorPublisher(event_bus, engine)
        candle = _make_candle(symbol="TCS")
        result = publisher.process_candle(candle)

        assert result is indicator_set
        event_bus.publish.assert_called_once()
        stream_name = event_bus.publish.call_args[0][0]
        assert stream_name == "stream:indicators:TCS"

    def test_does_not_publish_when_insufficient_data(self):
        """When IndicatorEngine returns None (insufficient data), nothing should be published."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        engine.add_candle.return_value = None

        publisher = IndicatorPublisher(event_bus, engine)
        candle = _make_candle()
        result = publisher.process_candle(candle)

        assert result is None
        event_bus.publish.assert_not_called()

    def test_publishes_with_correct_maxlen(self):
        """Publish should use maxlen=100."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        engine.add_candle.return_value = _make_indicator_set()

        publisher = IndicatorPublisher(event_bus, engine)
        publisher.process_candle(_make_candle())

        call_kwargs = event_bus.publish.call_args
        assert call_kwargs[1]["maxlen"] == INDICATOR_STREAM_MAXLEN
        assert INDICATOR_STREAM_MAXLEN == 100

    def test_serialized_message_contains_all_indicator_fields(self):
        """Published message should contain all indicator fields from IndicatorSet."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        ts = datetime(2024, 1, 15, 10, 0, 0)
        indicator_set = _make_indicator_set(
            symbol="INFY",
            timeframe="5m",
            timestamp=ts,
            rsi_14=55.0,
            macd=2.0,
            macd_signal=1.8,
            macd_hist=0.2,
            bb_upper=1530.0,
            bb_middle=1510.0,
            bb_lower=1490.0,
            vwap=1505.0,
            ema_9=1508.0,
            ema_21=1503.0,
            supertrend=1480.0,
            supertrend_direction=-1,
            atr_14=20.0,
            volume_avg_20=3000.0,
        )
        engine.add_candle.return_value = indicator_set

        publisher = IndicatorPublisher(event_bus, engine)
        publisher.process_candle(_make_candle(symbol="INFY", timeframe="5m"))

        message = event_bus.publish.call_args[0][1]
        assert message["symbol"] == "INFY"
        assert message["timeframe"] == "5m"
        assert message["timestamp"] == ts.isoformat()
        assert message["rsi_14"] == 55.0
        assert message["macd"] == 2.0
        assert message["macd_signal"] == 1.8
        assert message["macd_hist"] == 0.2
        assert message["bb_upper"] == 1530.0
        assert message["bb_middle"] == 1510.0
        assert message["bb_lower"] == 1490.0
        assert message["vwap"] == 1505.0
        assert message["ema_9"] == 1508.0
        assert message["ema_21"] == 1503.0
        assert message["supertrend"] == 1480.0
        assert message["supertrend_direction"] == -1
        assert message["atr_14"] == 20.0
        assert message["volume_avg_20"] == 3000.0

    def test_register_on_candle_builder(self):
        """register_on_candle_builder should hook process_candle into the CandleBuilder."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        builder = CandleBuilder(timeframes=["1m"])

        assert len(builder._on_complete_callbacks) == 0

        publisher = IndicatorPublisher(event_bus, engine)
        publisher.register_on_candle_builder(builder)

        assert len(builder._on_complete_callbacks) == 1
        assert builder._on_complete_callbacks[0] == publisher.process_candle

    def test_handles_publish_failure_gracefully(self):
        """If EventBus.publish raises, the publisher should log the error and not crash."""
        event_bus = MagicMock()
        event_bus.publish.side_effect = ConnectionError("Redis down")
        engine = MagicMock(spec=IndicatorEngine)
        engine.add_candle.return_value = _make_indicator_set()

        publisher = IndicatorPublisher(event_bus, engine)
        # Should not raise; returns the indicator set even if publish fails
        result = publisher.process_candle(_make_candle())
        assert result is not None

    def test_returns_none_when_engine_returns_none(self):
        """process_candle should return None when the engine returns None."""
        event_bus = MagicMock()
        engine = MagicMock(spec=IndicatorEngine)
        engine.add_candle.return_value = None

        publisher = IndicatorPublisher(event_bus, engine)
        result = publisher.process_candle(_make_candle())
        assert result is None
