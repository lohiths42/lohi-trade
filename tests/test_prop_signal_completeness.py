"""
Property-based tests for Signal Completeness.

Uses hypothesis to verify that every signal produced by the SignalPipeline
contains all required fields: entry_price, stop_loss, target (all finite
positive numbers), a valid UUID signal_id, a valid strategy name, a valid
side, and an IndicatorSet snapshot.

**Validates: Requirements 4.5**

Properties tested:
  1. Every signal has a non-empty signal_id (valid UUID)
  2. Every signal has entry_price, stop_loss, and target as finite positive numbers
  3. For BUY signals, stop_loss < entry_price < target
  4. For SELL signals (ORB), stop_loss > entry_price > target
  5. Every signal has a valid strategy name
  6. Every signal has a valid side
  7. Every signal includes an indicators snapshot (IndicatorSet)
"""

import math
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.signal_pipeline import SignalPipeline
from src.soldier.strategy_engine import (
    MeanReversionStrategy,
    OpeningRangeBreakoutStrategy,
    Signal,
    TrendFollowingStrategy,
)
from src.utils.config import MeanReversionStrategy as MeanReversionConfig
from src.utils.config import OpeningRangeBreakoutStrategy as ORBConfig
from src.utils.config import TrendFollowingStrategy as TrendFollowingConfig


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

VALID_STRATEGIES = {"MeanReversion", "TrendFollowing", "OpeningRangeBreakout"}
VALID_SIDES = {"BUY", "SELL"}


def _mr_config() -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=True,
        rsi_oversold=30,
        rsi_overbought=65,
        volume_multiplier=1.5,
        stop_loss_atr_multiplier=1.5,
    )


def _tf_config() -> TrendFollowingConfig:
    return TrendFollowingConfig(
        enabled=True,
        ema_fast=9,
        ema_slow=21,
        stop_loss_atr_multiplier=2.0,
        target_atr_multiplier=3.0,
    )


def _orb_config() -> ORBConfig:
    return ORBConfig(
        enabled=True,
        range_start="09:15",
        range_end="09:30",
        trade_window_start="09:30",
        trade_window_end="10:30",
        volume_multiplier=2.0,
        target_multiplier=1.5,
    )


def _make_pipeline(strategies):
    """Create a SignalPipeline with a mocked EventBus."""
    event_bus = MagicMock()
    return SignalPipeline(
        event_bus=event_bus,
        strategies=strategies,
        trading_start="09:30",
        trading_end="15:10",
    )


# ---------------------------------------------------------------------------
# Composite strategies (hypothesis generators)
# ---------------------------------------------------------------------------

@st.composite
def mean_reversion_signal_inputs(draw):
    """Generate valid MeanReversion indicator inputs that trigger a BUY signal.

    Constrains ATR so that stop_loss = close - 1.5*ATR > 0.
    """
    vwap = draw(st.floats(min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=vwap + 0.01, max_value=vwap + 5_000.0, allow_nan=False, allow_infinity=False))
    bb_lower = draw(st.floats(min_value=close + 0.01, max_value=close + 5_000.0, allow_nan=False, allow_infinity=False))
    bb_middle = draw(st.floats(min_value=bb_lower + 0.01, max_value=bb_lower + 5_000.0, allow_nan=False, allow_infinity=False))
    bb_upper = draw(st.floats(min_value=bb_middle + 0.01, max_value=bb_middle + 5_000.0, allow_nan=False, allow_infinity=False))

    rsi_14 = draw(st.floats(min_value=0.1, max_value=29.99, allow_nan=False, allow_infinity=False))

    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e7, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=1.5 * volume_avg_20 + 1.0,
        max_value=1.5 * volume_avg_20 + 1e7,
        allow_nan=False, allow_infinity=False,
    ))

    # ATR must be small enough that stop_loss = close - 1.5*ATR > 0
    max_atr = (close - 0.01) / 1.5
    atr_14 = draw(st.floats(min_value=0.01, max_value=max(0.01, max_atr), allow_nan=False, allow_infinity=False))

    ts = datetime(2024, 1, 15, 10, 0, 0)

    indicators = IndicatorSet(
        symbol="TEST", timeframe="5m", timestamp=ts,
        rsi_14=rsi_14, macd=0.0, macd_signal=0.0, macd_hist=0.0,
        bb_upper=bb_upper, bb_middle=bb_middle, bb_lower=bb_lower,
        vwap=vwap, ema_9=0.0, ema_21=0.0,
        supertrend=0.0, supertrend_direction=1,
        atr_14=atr_14, volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0], "high": [close + 1.0],
        "low": [close - 2.0], "close": [close],
        "volume": [volume], "timestamp": [ts],
    })

    return indicators, candles


@st.composite
def trend_following_signal_inputs(draw):
    """Generate valid TrendFollowing indicator inputs that trigger a BUY signal.

    Constrains ATR so that stop_loss = close - 2.0*ATR > 0.
    """
    vwap = draw(st.floats(min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=vwap + 0.01, max_value=vwap + 5_000.0, allow_nan=False, allow_infinity=False))

    ema_21 = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    ema_9 = draw(st.floats(min_value=ema_21 + 0.01, max_value=ema_21 + 5_000.0, allow_nan=False, allow_infinity=False))

    macd = draw(st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False))
    macd_hist = draw(st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False))

    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e7, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=volume_avg_20 + 1.0,
        max_value=volume_avg_20 + 1e7,
        allow_nan=False, allow_infinity=False,
    ))

    # ATR must be small enough that stop_loss = close - 2.0*ATR > 0
    max_atr = (close - 0.01) / 2.0
    atr_14 = draw(st.floats(min_value=0.01, max_value=max(0.01, max_atr), allow_nan=False, allow_infinity=False))

    ts = datetime(2024, 1, 15, 10, 0, 0)

    indicators = IndicatorSet(
        symbol="TEST", timeframe="5m", timestamp=ts,
        rsi_14=50.0, macd=macd, macd_signal=0.0, macd_hist=macd_hist,
        bb_upper=0.0, bb_middle=0.0, bb_lower=0.0,
        vwap=vwap, ema_9=ema_9, ema_21=ema_21,
        supertrend=0.0, supertrend_direction=1,
        atr_14=atr_14, volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0], "high": [close + 1.0],
        "low": [close - 2.0], "close": [close],
        "volume": [volume], "timestamp": [ts],
    })

    return indicators, candles


@st.composite
def orb_buy_signal_inputs(draw):
    """Generate valid ORB BUY breakout inputs."""
    range_low = draw(st.floats(min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    range_high = draw(st.floats(min_value=range_low + 0.01, max_value=range_low + 5_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=range_high + 0.01, max_value=range_high + 5_000.0, allow_nan=False, allow_infinity=False))

    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e7, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=2.0 * volume_avg_20 + 1.0,
        max_value=2.0 * volume_avg_20 + 1e7,
        allow_nan=False, allow_infinity=False,
    ))

    atr_14 = draw(st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False))

    hour = draw(st.sampled_from([9, 10]))
    minute = draw(st.integers(min_value=30, max_value=59)) if hour == 9 else draw(st.integers(min_value=0, max_value=30))
    ts = datetime(2024, 1, 15, hour, minute, 0)

    indicators = IndicatorSet(
        symbol="TEST", timeframe="5m", timestamp=ts,
        rsi_14=50.0, macd=0.0, macd_signal=0.0, macd_hist=0.0,
        bb_upper=0.0, bb_middle=0.0, bb_lower=0.0,
        vwap=0.0, ema_9=0.0, ema_21=0.0,
        supertrend=0.0, supertrend_direction=1,
        atr_14=atr_14, volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0], "high": [close + 1.0],
        "low": [close - 2.0], "close": [close],
        "volume": [volume], "timestamp": [ts],
    })

    return indicators, candles, range_high, range_low


@st.composite
def orb_sell_signal_inputs(draw):
    """Generate valid ORB SELL breakout inputs.

    Constrains so that target = close - 1.5*(range_high - range_low) > 0
    and close < range_low.
    """
    # Pick close first, then derive range so target stays positive.
    close = draw(st.floats(min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    # range_high - range_low must be < close / 1.5 so target > 0
    max_range_size = (close - 0.01) / 1.5
    range_size = draw(st.floats(min_value=0.1, max_value=max(0.1, max_range_size), allow_nan=False, allow_infinity=False))
    # range_low must be > close (so close < range_low triggers SELL)
    range_low = draw(st.floats(min_value=close + 0.01, max_value=close + 5_000.0, allow_nan=False, allow_infinity=False))
    range_high = range_low + range_size

    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e7, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=2.0 * volume_avg_20 + 1.0,
        max_value=2.0 * volume_avg_20 + 1e7,
        allow_nan=False, allow_infinity=False,
    ))

    atr_14 = draw(st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False))

    hour = draw(st.sampled_from([9, 10]))
    minute = draw(st.integers(min_value=30, max_value=59)) if hour == 9 else draw(st.integers(min_value=0, max_value=30))
    ts = datetime(2024, 1, 15, hour, minute, 0)

    indicators = IndicatorSet(
        symbol="TEST", timeframe="5m", timestamp=ts,
        rsi_14=50.0, macd=0.0, macd_signal=0.0, macd_hist=0.0,
        bb_upper=0.0, bb_middle=0.0, bb_lower=0.0,
        vwap=0.0, ema_9=0.0, ema_21=0.0,
        supertrend=0.0, supertrend_direction=1,
        atr_14=atr_14, volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0], "high": [close + 1.0],
        "low": [close - 2.0], "close": [close],
        "volume": [volume], "timestamp": [ts],
    })

    return indicators, candles, range_high, range_low


# ---------------------------------------------------------------------------
# Helper: generate signal through the pipeline
# ---------------------------------------------------------------------------

def _signal_via_mr_pipeline(indicators, candles) -> Signal:
    """Run MeanReversion through the pipeline and return the signal."""
    strategy = MeanReversionStrategy(_mr_config())
    pipeline = _make_pipeline([strategy])
    signal = pipeline.process_indicators(indicators, candles)
    assert signal is not None, "Expected MeanReversion signal"
    return signal


def _signal_via_tf_pipeline(indicators, candles) -> Signal:
    """Run TrendFollowing through the pipeline and return the signal."""
    strategy = TrendFollowingStrategy(_tf_config())
    pipeline = _make_pipeline([strategy])
    signal = pipeline.process_indicators(indicators, candles)
    assert signal is not None, "Expected TrendFollowing signal"
    return signal


def _signal_via_orb_pipeline(indicators, candles, range_high, range_low) -> Signal:
    """Run ORB through the pipeline and return the signal."""
    strategy = OpeningRangeBreakoutStrategy(_orb_config())
    strategy.set_opening_range("TEST", range_high, range_low)
    pipeline = _make_pipeline([strategy])
    signal = pipeline.process_indicators(indicators, candles)
    assert signal is not None, "Expected ORB signal"
    return signal


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

class TestSignalCompletenessProperties:
    """
    **Validates: Requirements 4.5**

    Property 14: Signal Completeness
    """

    # --- Property 1: signal_id is a valid UUID ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_signal_has_valid_uuid(self, data):
        """
        Property: Every MeanReversion signal has a non-empty, valid UUID signal_id.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        assert isinstance(signal.signal_id, str) and len(signal.signal_id) > 0
        uuid.UUID(signal.signal_id)  # raises ValueError if invalid

    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_signal_has_valid_uuid(self, data):
        """
        Property: Every TrendFollowing signal has a non-empty, valid UUID signal_id.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        assert isinstance(signal.signal_id, str) and len(signal.signal_id) > 0
        uuid.UUID(signal.signal_id)


    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_buy_signal_has_valid_uuid(self, data):
        """
        Property: Every ORB BUY signal has a non-empty, valid UUID signal_id.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert isinstance(signal.signal_id, str) and len(signal.signal_id) > 0
        uuid.UUID(signal.signal_id)

    @given(data=orb_sell_signal_inputs())
    @settings(max_examples=25)
    def test_orb_sell_signal_has_valid_uuid(self, data):
        """
        Property: Every ORB SELL signal has a non-empty, valid UUID signal_id.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert isinstance(signal.signal_id, str) and len(signal.signal_id) > 0
        uuid.UUID(signal.signal_id)

    # --- Property 2: entry_price, stop_loss, target are finite positive ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_signal_prices_finite_positive(self, data):
        """
        Property: Every MeanReversion signal has finite positive entry_price,
        stop_loss, and target.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        for field_name in ("entry_price", "stop_loss", "target"):
            val = getattr(signal, field_name)
            assert math.isfinite(val), f"{field_name} must be finite, got {val}"
            assert val > 0, f"{field_name} must be positive, got {val}"


    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_signal_prices_finite_positive(self, data):
        """
        Property: Every TrendFollowing signal has finite positive entry_price,
        stop_loss, and target.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        for field_name in ("entry_price", "stop_loss", "target"):
            val = getattr(signal, field_name)
            assert math.isfinite(val), f"{field_name} must be finite, got {val}"
            assert val > 0, f"{field_name} must be positive, got {val}"

    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_buy_signal_prices_finite_positive(self, data):
        """
        Property: Every ORB BUY signal has finite positive entry_price,
        stop_loss, and target.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        for field_name in ("entry_price", "stop_loss", "target"):
            val = getattr(signal, field_name)
            assert math.isfinite(val), f"{field_name} must be finite, got {val}"
            assert val > 0, f"{field_name} must be positive, got {val}"

    @given(data=orb_sell_signal_inputs())
    @settings(max_examples=25)
    def test_orb_sell_signal_prices_finite_positive(self, data):
        """
        Property: Every ORB SELL signal has finite positive entry_price,
        stop_loss, and target.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        for field_name in ("entry_price", "stop_loss", "target"):
            val = getattr(signal, field_name)
            assert math.isfinite(val), f"{field_name} must be finite, got {val}"
            assert val > 0, f"{field_name} must be positive, got {val}"


    # --- Property 3: BUY signals have stop_loss < entry_price < target ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_buy_price_ordering(self, data):
        """
        Property: For MeanReversion BUY signals, stop_loss < entry_price < target.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        assert signal.side == "BUY"
        assert signal.stop_loss < signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be < entry_price ({signal.entry_price})"
        )
        assert signal.entry_price < signal.target, (
            f"entry_price ({signal.entry_price}) must be < target ({signal.target})"
        )

    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_buy_price_ordering(self, data):
        """
        Property: For TrendFollowing BUY signals, stop_loss < entry_price < target.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        assert signal.side == "BUY"
        assert signal.stop_loss < signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be < entry_price ({signal.entry_price})"
        )
        assert signal.entry_price < signal.target, (
            f"entry_price ({signal.entry_price}) must be < target ({signal.target})"
        )

    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_buy_price_ordering(self, data):
        """
        Property: For ORB BUY signals, stop_loss < entry_price < target.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.side == "BUY"
        assert signal.stop_loss < signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be < entry_price ({signal.entry_price})"
        )
        assert signal.entry_price < signal.target, (
            f"entry_price ({signal.entry_price}) must be < target ({signal.target})"
        )


    # --- Property 4: SELL signals (ORB) have stop_loss > entry_price > target ---

    @given(data=orb_sell_signal_inputs())
    @settings(max_examples=25)
    def test_orb_sell_price_ordering(self, data):
        """
        Property: For ORB SELL signals, stop_loss > entry_price > target.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.side == "SELL"
        assert signal.stop_loss > signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be > entry_price ({signal.entry_price})"
        )
        assert signal.entry_price > signal.target, (
            f"entry_price ({signal.entry_price}) must be > target ({signal.target})"
        )

    # --- Property 5: valid strategy name ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_signal_valid_strategy(self, data):
        """
        Property: Every MeanReversion signal has strategy in VALID_STRATEGIES.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        assert signal.strategy in VALID_STRATEGIES

    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_signal_valid_strategy(self, data):
        """
        Property: Every TrendFollowing signal has strategy in VALID_STRATEGIES.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        assert signal.strategy in VALID_STRATEGIES

    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_signal_valid_strategy(self, data):
        """
        Property: Every ORB signal has strategy in VALID_STRATEGIES.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.strategy in VALID_STRATEGIES


    # --- Property 6: valid side ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_signal_valid_side(self, data):
        """
        Property: Every MeanReversion signal has side in VALID_SIDES.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        assert signal.side in VALID_SIDES

    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_signal_valid_side(self, data):
        """
        Property: Every TrendFollowing signal has side in VALID_SIDES.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        assert signal.side in VALID_SIDES

    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_buy_signal_valid_side(self, data):
        """
        Property: Every ORB BUY signal has side in VALID_SIDES.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.side in VALID_SIDES

    @given(data=orb_sell_signal_inputs())
    @settings(max_examples=25)
    def test_orb_sell_signal_valid_side(self, data):
        """
        Property: Every ORB SELL signal has side in VALID_SIDES.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.side in VALID_SIDES


    # --- Property 7: indicators snapshot is an IndicatorSet ---

    @given(data=mean_reversion_signal_inputs())
    @settings(max_examples=25)
    def test_mr_signal_has_indicator_snapshot(self, data):
        """
        Property: Every MeanReversion signal includes a non-None IndicatorSet.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_mr_pipeline(indicators, candles)
        assert signal.indicators is not None
        assert isinstance(signal.indicators, IndicatorSet)

    @given(data=trend_following_signal_inputs())
    @settings(max_examples=25)
    def test_tf_signal_has_indicator_snapshot(self, data):
        """
        Property: Every TrendFollowing signal includes a non-None IndicatorSet.

        **Validates: Requirements 4.5**
        """
        indicators, candles = data
        signal = _signal_via_tf_pipeline(indicators, candles)
        assert signal.indicators is not None
        assert isinstance(signal.indicators, IndicatorSet)

    @given(data=orb_buy_signal_inputs())
    @settings(max_examples=25)
    def test_orb_buy_signal_has_indicator_snapshot(self, data):
        """
        Property: Every ORB BUY signal includes a non-None IndicatorSet.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.indicators is not None
        assert isinstance(signal.indicators, IndicatorSet)

    @given(data=orb_sell_signal_inputs())
    @settings(max_examples=25)
    def test_orb_sell_signal_has_indicator_snapshot(self, data):
        """
        Property: Every ORB SELL signal includes a non-None IndicatorSet.

        **Validates: Requirements 4.5**
        """
        indicators, candles, rh, rl = data
        signal = _signal_via_orb_pipeline(indicators, candles, rh, rl)
        assert signal.indicators is not None
        assert isinstance(signal.indicators, IndicatorSet)
