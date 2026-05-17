"""Unit tests for the SignalPipeline.

Tests signal generation, trading hours filtering, duplicate position
prevention, strategy execution, event bus publishing, open position
management, and signal serialization.

Requirements: 4.5, 4.6, 4.7, 4.8
"""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.signal_pipeline import SIGNAL_STREAM, SIGNAL_STREAM_MAXLEN, SignalPipeline
from src.soldier.strategy_engine import (
    MeanReversionStrategy,
    create_signal,
)
from src.utils.config import (
    MeanReversionStrategy as MeanReversionConfig,
)
from src.utils.config import (
    TrendFollowingStrategy as TrendFollowingConfig,
)

# --- Fixtures ---


def _make_indicators(
    symbol: str = "RELIANCE",
    timestamp: datetime | None = None,
    rsi_14: float = 25.0,
    bb_lower: float = 990.0,
    bb_middle: float = 1010.0,
    bb_upper: float = 1030.0,
    vwap: float = 995.0,
    ema_9: float = 1005.0,
    ema_21: float = 1000.0,
    macd: float = 1.5,
    macd_signal: float = 1.0,
    macd_hist: float = 0.5,
    supertrend: float = 990.0,
    supertrend_direction: int = 1,
    atr_14: float = 10.0,
    volume_avg_20: float = 50000.0,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        timeframe="1m",
        timestamp=timestamp or datetime(2024, 1, 15, 10, 30, 0),
        rsi_14=rsi_14,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        vwap=vwap,
        ema_9=ema_9,
        ema_21=ema_21,
        supertrend=supertrend,
        supertrend_direction=supertrend_direction,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )


def _make_candles(close: float = 985.0, volume: float = 100000.0) -> pd.DataFrame:
    """Create a minimal candle DataFrame for strategy evaluation."""
    return pd.DataFrame(
        [
            {
                "open": close - 5,
                "high": close + 5,
                "low": close - 10,
                "close": close,
                "volume": volume,
                "timestamp": datetime(2024, 1, 15, 10, 30, 0),
            },
        ],
    )


def _mean_reversion_config(enabled: bool = True) -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=enabled,
        rsi_oversold=30,
        rsi_overbought=65,
        volume_multiplier=1.5,
        stop_loss_atr_multiplier=1.5,
    )


def _trend_following_config(enabled: bool = True) -> TrendFollowingConfig:
    return TrendFollowingConfig(
        enabled=enabled,
        ema_fast=9,
        ema_slow=21,
        stop_loss_atr_multiplier=2.0,
        target_atr_multiplier=3.0,
    )


@pytest.fixture
def mock_event_bus() -> MagicMock:
    return MagicMock()


# --- Tests ---


class TestSignalGenerationWithinTradingHours:
    """Test that signals are generated when conditions are met during trading hours."""

    def test_mean_reversion_signal_generated(self, mock_event_bus: MagicMock):
        """A valid mean reversion setup within trading hours should produce a signal."""
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        # Indicators that satisfy mean reversion: RSI < 30, price < bb_lower, vol > 1.5x avg, price > vwap
        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            bb_middle=1010.0,
            vwap=980.0,
            atr_14=10.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is not None
        assert signal.symbol == "RELIANCE"
        assert signal.strategy == "MeanReversion"
        assert signal.side == "BUY"
        assert signal.entry_price == 985.0
        assert signal.stop_loss == 985.0 - (1.5 * 10.0)
        assert signal.target == 1010.0


class TestNoSignalOutsideTradingHours:
    """Test that no signals are generated outside trading hours (Req 4.7)."""

    @pytest.mark.parametrize(
        "hour,minute",
        [
            (9, 0),  # Before trading start
            (9, 29),  # Just before 9:30
            (15, 11),  # Just after 15:10
            (16, 0),  # Well after trading end
            (6, 0),  # Early morning
        ],
    )
    def test_no_signal_outside_hours(self, mock_event_bus: MagicMock, hour: int, minute: int):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, hour, minute, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is None
        mock_event_bus.publish.assert_not_called()

    def test_signal_at_trading_start_boundary(self, mock_event_bus: MagicMock):
        """Signal at exactly 09:30 should be allowed."""
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 9, 30, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)
        assert signal is not None

    def test_signal_at_trading_end_boundary(self, mock_event_bus: MagicMock):
        """Signal at exactly 15:10 should be allowed."""
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 15, 10, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)
        assert signal is not None


class TestDuplicatePositionPrevention:
    """Test that duplicate positions are prevented (Req 4.8)."""

    def test_second_signal_for_same_symbol_rejected(self, mock_event_bus: MagicMock):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        # First signal should succeed
        signal1 = pipeline.process_indicators(indicators, candles)
        assert signal1 is not None

        # Second signal for same symbol should be rejected
        signal2 = pipeline.process_indicators(indicators, candles)
        assert signal2 is None

    def test_pre_added_open_position_blocks_signal(self, mock_event_bus: MagicMock):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        pipeline.add_open_position("RELIANCE")

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)
        assert signal is None

    def test_different_symbols_allowed(self, mock_event_bus: MagicMock):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        candles = _make_candles(close=985.0, volume=100000.0)

        ind1 = _make_indicators(
            symbol="RELIANCE",
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        ind2 = _make_indicators(
            symbol="TCS",
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )

        signal1 = pipeline.process_indicators(ind1, candles)
        signal2 = pipeline.process_indicators(ind2, candles)

        assert signal1 is not None
        assert signal2 is not None
        assert signal1.symbol == "RELIANCE"
        assert signal2.symbol == "TCS"


class TestMultipleStrategiesRun:
    """Test that all enabled strategies are evaluated."""

    def test_first_matching_strategy_wins(self, mock_event_bus: MagicMock):
        """When multiple strategies could fire, the first one in the list wins."""
        mock_strategy_1 = MagicMock(spec=["name", "enabled", "generate_signal"])
        mock_strategy_1.enabled = True
        mock_strategy_1.name = "Strategy1"
        mock_strategy_1.generate_signal.return_value = None

        mock_strategy_2 = MagicMock(spec=["name", "enabled", "generate_signal"])
        mock_strategy_2.enabled = True
        mock_strategy_2.name = "Strategy2"
        signal = create_signal(
            symbol="RELIANCE",
            strategy="Strategy2",
            side="BUY",
            entry_price=1000.0,
            stop_loss=990.0,
            target=1020.0,
            indicators=_make_indicators(),
        )
        mock_strategy_2.generate_signal.return_value = signal

        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[mock_strategy_1, mock_strategy_2],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 10, 0, 0))
        candles = _make_candles()

        result = pipeline.process_indicators(indicators, candles)

        assert result is not None
        assert result.strategy == "Strategy2"
        mock_strategy_1.generate_signal.assert_called_once()
        mock_strategy_2.generate_signal.assert_called_once()


class TestDisabledStrategiesSkipped:
    """Test that disabled strategies are not executed."""

    def test_disabled_strategy_not_called(self, mock_event_bus: MagicMock):
        mock_strategy = MagicMock(spec=["name", "enabled", "generate_signal"])
        mock_strategy.enabled = False
        mock_strategy.name = "DisabledStrategy"

        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[mock_strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 10, 0, 0))
        candles = _make_candles()

        result = pipeline.process_indicators(indicators, candles)

        assert result is None
        mock_strategy.generate_signal.assert_not_called()


class TestSignalPublishedToEventBus:
    """Test that valid signals are published to the event bus (Req 4.6)."""

    def test_publish_called_with_correct_stream(self, mock_event_bus: MagicMock):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is not None
        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == SIGNAL_STREAM
        assert call_args[1]["maxlen"] == SIGNAL_STREAM_MAXLEN

    def test_no_publish_when_no_signal(self, mock_event_bus: MagicMock):
        """When no strategy generates a signal, nothing is published."""
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        # RSI too high for mean reversion
        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=50.0,
        )
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is None
        mock_event_bus.publish.assert_not_called()


class TestOpenPositionManagement:
    """Test open position tracking methods."""

    def test_add_and_get(self):
        pipeline = SignalPipeline(
            event_bus=MagicMock(),
            strategies=[],
            trading_start="09:30",
            trading_end="15:10",
        )

        pipeline.add_open_position("RELIANCE")
        pipeline.add_open_position("TCS")

        positions = pipeline.get_open_positions()
        assert positions == {"RELIANCE", "TCS"}

    def test_remove(self):
        pipeline = SignalPipeline(
            event_bus=MagicMock(),
            strategies=[],
            trading_start="09:30",
            trading_end="15:10",
        )

        pipeline.add_open_position("RELIANCE")
        pipeline.add_open_position("TCS")
        pipeline.remove_open_position("RELIANCE")

        assert pipeline.get_open_positions() == {"TCS"}

    def test_remove_nonexistent_is_safe(self):
        pipeline = SignalPipeline(
            event_bus=MagicMock(),
            strategies=[],
            trading_start="09:30",
            trading_end="15:10",
        )

        # Should not raise
        pipeline.remove_open_position("NONEXISTENT")
        assert pipeline.get_open_positions() == set()

    def test_clear(self):
        pipeline = SignalPipeline(
            event_bus=MagicMock(),
            strategies=[],
            trading_start="09:30",
            trading_end="15:10",
        )

        pipeline.add_open_position("RELIANCE")
        pipeline.add_open_position("TCS")
        pipeline.clear_open_positions()

        assert pipeline.get_open_positions() == set()

    def test_get_returns_copy(self):
        """get_open_positions should return a copy, not the internal set."""
        pipeline = SignalPipeline(
            event_bus=MagicMock(),
            strategies=[],
            trading_start="09:30",
            trading_end="15:10",
        )

        pipeline.add_open_position("RELIANCE")
        positions = pipeline.get_open_positions()
        positions.add("HACKED")

        assert "HACKED" not in pipeline.get_open_positions()


class TestSignalSerialization:
    """Test that signals are correctly serialized for Redis."""

    def test_serialized_signal_has_all_fields(self, mock_event_bus: MagicMock):
        strategy = MeanReversionStrategy(_mean_reversion_config())
        pipeline = SignalPipeline(
            event_bus=mock_event_bus,
            strategies=[strategy],
            trading_start="09:30",
            trading_end="15:10",
        )

        indicators = _make_indicators(
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            rsi_14=25.0,
            bb_lower=990.0,
            vwap=980.0,
            volume_avg_20=50000.0,
        )
        candles = _make_candles(close=985.0, volume=100000.0)

        pipeline.process_indicators(indicators, candles)

        published_message = mock_event_bus.publish.call_args[0][1]

        # Check all required signal fields
        assert "signal_id" in published_message
        assert "symbol" in published_message
        assert "strategy" in published_message
        assert "side" in published_message
        assert "entry_price" in published_message
        assert "stop_loss" in published_message
        assert "target" in published_message
        assert "timestamp" in published_message
        assert "indicators" in published_message

        # Timestamp should be ISO string
        assert isinstance(published_message["timestamp"], str)
        assert "T" in published_message["timestamp"]

        # Indicators should be a dict with its own ISO timestamp
        assert isinstance(published_message["indicators"], dict)
        assert isinstance(published_message["indicators"]["timestamp"], str)
