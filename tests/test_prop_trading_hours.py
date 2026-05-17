"""Property-based tests for Trading Hours Signal Filter.

Uses hypothesis to verify that the SignalPipeline correctly filters signals
based on trading hours (9:30 AM - 3:10 PM IST).

**Validates: Requirements 4.7**

Properties tested:
  1. Signals within trading hours (9:30-15:10) are allowed
  2. Signals before trading start (0:00-9:29) are rejected
  3. Signals after trading end (15:11-23:59) are rejected
  4. Boundary: signal at exactly 9:30 AM is allowed
  5. Boundary: signal at exactly 3:10 PM is allowed
  6. Boundary: signal at 9:29 AM is rejected
  7. Boundary: signal at 3:11 PM is rejected
"""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.signal_pipeline import SignalPipeline
from src.soldier.strategy_engine import MeanReversionStrategy
from src.utils.config import MeanReversionStrategy as MeanReversionConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean_reversion_config() -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=True,
        rsi_oversold=30,
        rsi_overbought=65,
        volume_multiplier=1.5,
        stop_loss_atr_multiplier=1.5,
    )


def _make_indicators(timestamp: datetime) -> IndicatorSet:
    """Create indicators that satisfy MeanReversion conditions."""
    return IndicatorSet(
        symbol="RELIANCE",
        timeframe="1m",
        timestamp=timestamp,
        rsi_14=25.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=1030.0,
        bb_middle=1010.0,
        bb_lower=990.0,
        vwap=980.0,
        ema_9=0.0,
        ema_21=0.0,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=10.0,
        volume_avg_20=50000.0,
    )


def _make_candles() -> pd.DataFrame:
    """Create candles that satisfy MeanReversion conditions (close=985 < bb_lower=990, volume=100000 > 1.5*50000)."""
    return pd.DataFrame(
        [
            {
                "open": 980.0,
                "high": 990.0,
                "low": 975.0,
                "close": 985.0,
                "volume": 100000.0,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0),
            },
        ],
    )


def _make_pipeline() -> SignalPipeline:
    strategy = MeanReversionStrategy(_mean_reversion_config())
    return SignalPipeline(
        event_bus=MagicMock(),
        strategies=[strategy],
        trading_start="09:30",
        trading_end="15:10",
    )


# ---------------------------------------------------------------------------
# Timestamp generators
# ---------------------------------------------------------------------------


@st.composite
def within_trading_hours(draw):
    """Generate timestamps between 9:30 and 15:10 (inclusive, minute resolution)."""
    total_minutes = draw(st.integers(min_value=9 * 60 + 30, max_value=15 * 60 + 10))
    hour = total_minutes // 60
    minute = total_minutes % 60
    return datetime(2024, 1, 15, hour, minute, 0)


@st.composite
def before_trading_hours(draw):
    """Generate timestamps between 0:00 and 9:29 (inclusive, minute resolution)."""
    total_minutes = draw(st.integers(min_value=0, max_value=9 * 60 + 29))
    hour = total_minutes // 60
    minute = total_minutes % 60
    return datetime(2024, 1, 15, hour, minute, 0)


@st.composite
def after_trading_hours(draw):
    """Generate timestamps between 15:11 and 23:59 (inclusive, minute resolution)."""
    total_minutes = draw(st.integers(min_value=15 * 60 + 11, max_value=23 * 60 + 59))
    hour = total_minutes // 60
    minute = total_minutes % 60
    return datetime(2024, 1, 15, hour, minute, 0)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestTradingHoursFilterProperties:
    """**Validates: Requirements 4.7**

    Property 15: Trading Hours Signal Filter
    """

    @given(ts=within_trading_hours())
    @settings(max_examples=25)
    def test_signals_within_trading_hours_are_allowed(self, ts: datetime):
        """Property: For any timestamp between 9:30 AM and 3:10 PM (inclusive),
        a signal should be generated when MeanReversion conditions are met.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=ts)
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert (
            signal is not None
        ), f"Expected signal at {ts.strftime('%H:%M')} (within trading hours)"
        assert signal.side == "BUY"
        assert signal.strategy == "MeanReversion"

    @given(ts=before_trading_hours())
    @settings(max_examples=25)
    def test_signals_before_trading_start_are_rejected(self, ts: datetime):
        """Property: For any timestamp before 9:30 AM, no signal should be
        generated even with valid MeanReversion conditions.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=ts)
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert (
            signal is None
        ), f"Expected no signal at {ts.strftime('%H:%M')} (before trading hours)"

    @given(ts=after_trading_hours())
    @settings(max_examples=25)
    def test_signals_after_trading_end_are_rejected(self, ts: datetime):
        """Property: For any timestamp after 3:10 PM, no signal should be
        generated even with valid MeanReversion conditions.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=ts)
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is None, f"Expected no signal at {ts.strftime('%H:%M')} (after trading hours)"

    def test_boundary_signal_at_exactly_0930_is_allowed(self):
        """Boundary: Signal at exactly 9:30 AM should be allowed.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 9, 30, 0))
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is not None, "Expected signal at exactly 09:30 (trading start)"
        assert signal.side == "BUY"

    def test_boundary_signal_at_exactly_1510_is_allowed(self):
        """Boundary: Signal at exactly 3:10 PM should be allowed.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 15, 10, 0))
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is not None, "Expected signal at exactly 15:10 (trading end)"
        assert signal.side == "BUY"

    def test_boundary_signal_at_0929_is_rejected(self):
        """Boundary: Signal at 9:29 AM should be rejected.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 9, 29, 0))
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is None, "Expected no signal at 09:29 (before trading start)"

    def test_boundary_signal_at_1511_is_rejected(self):
        """Boundary: Signal at 3:11 PM should be rejected.

        **Validates: Requirements 4.7**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(timestamp=datetime(2024, 1, 15, 15, 11, 0))
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is None, "Expected no signal at 15:11 (after trading end)"
