"""
Property-based tests for TrendFollowingStrategy.

Uses hypothesis to verify that the Trend Following strategy behaves correctly
across a wide range of randomly generated indicator values.

**Validates: Requirements 4.3**

Properties tested:
  1. When all 6 conditions are met, a BUY signal is always generated
  2. When any condition fails, no signal is generated
  3. Stop loss is always below entry price
  4. Target is always above entry price
  5. Stop loss formula: stop_loss == entry_price - (stop_loss_atr_multiplier × atr_14)
  6. Target formula: target == entry_price + (target_atr_multiplier × atr_14)
"""

from datetime import datetime

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import TrendFollowingStrategy
from src.utils.config import TrendFollowingStrategy as TrendFollowingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(
    stop_loss_atr_multiplier: float = 2.0,
    target_atr_multiplier: float = 3.0,
) -> TrendFollowingConfig:
    return TrendFollowingConfig(
        enabled=True,
        ema_fast=9,
        ema_slow=21,
        stop_loss_atr_multiplier=stop_loss_atr_multiplier,
        target_atr_multiplier=target_atr_multiplier,
    )


# ---------------------------------------------------------------------------
# Strategies (hypothesis generators)
# ---------------------------------------------------------------------------

_price = st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)


@st.composite
def valid_trend_following_inputs(draw):
    """
    Generate indicator values where ALL 6 Trend Following conditions are met:
      1. EMA(9) > EMA(21)
      2. MACD > 0
      3. MACD histogram > 0
      4. close > VWAP
      5. supertrend_direction == 1
      6. volume > volume_avg_20
    """
    # EMA crossover: ema_9 > ema_21
    ema_21 = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    ema_9 = draw(st.floats(min_value=ema_21 + 0.01, max_value=ema_21 + 10_000.0, allow_nan=False, allow_infinity=False))

    # MACD positive and rising
    macd = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))
    macd_hist = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))

    # Price above VWAP
    vwap = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=vwap + 0.01, max_value=vwap + 10_000.0, allow_nan=False, allow_infinity=False))

    # Volume above average
    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=volume_avg_20 + 1.0,
        max_value=volume_avg_20 + 1e8,
        allow_nan=False, allow_infinity=False,
    ))

    atr_14 = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=50.0,
        macd=macd,
        macd_signal=0.0,
        macd_hist=macd_hist,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
        vwap=vwap,
        ema_9=ema_9,
        ema_21=ema_21,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0],
        "high": [close + 1.0],
        "low": [close - 2.0],
        "close": [close],
        "volume": [volume],
        "timestamp": [datetime(2024, 1, 15, 10, 0, 0)],
    })

    return indicators, candles, atr_14, close


@st.composite
def invalid_trend_following_inputs(draw):
    """
    Generate indicator values where AT LEAST ONE of the 6 conditions fails.

    We first generate a valid set, then deliberately break one condition.
    """
    # Start with valid values
    ema_21 = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    ema_9 = ema_21 + 1.0
    macd = 1.0
    macd_hist = 1.0
    vwap = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = vwap + 1.0
    supertrend_direction = 1
    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False))
    volume = volume_avg_20 + 1.0
    atr_14 = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))

    # Pick which condition to break (0-5)
    condition_to_break = draw(st.integers(min_value=0, max_value=5))

    if condition_to_break == 0:
        # Break EMA crossover: ema_9 <= ema_21
        ema_9 = draw(st.floats(min_value=0.1, max_value=ema_21, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 1:
        # Break MACD positive: macd <= 0
        macd = draw(st.floats(min_value=-1000.0, max_value=0.0, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 2:
        # Break MACD rising: macd_hist <= 0
        macd_hist = draw(st.floats(min_value=-1000.0, max_value=0.0, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 3:
        # Break price > VWAP: close <= vwap
        close = draw(st.floats(min_value=0.1, max_value=vwap, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 4:
        # Break supertrend bullish: direction != 1
        supertrend_direction = -1
    else:
        # Break volume above avg: volume <= volume_avg_20
        volume = draw(st.floats(
            min_value=0.0,
            max_value=volume_avg_20,
            allow_nan=False, allow_infinity=False,
        ))

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=50.0,
        macd=macd,
        macd_signal=0.0,
        macd_hist=macd_hist,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
        vwap=vwap,
        ema_9=ema_9,
        ema_21=ema_21,
        supertrend=0.0,
        supertrend_direction=supertrend_direction,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame({
        "open": [close - 1.0],
        "high": [close + 1.0],
        "low": [close - 2.0],
        "close": [close],
        "volume": [volume],
        "timestamp": [datetime(2024, 1, 15, 10, 0, 0)],
    })

    return indicators, candles


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

class TestTrendFollowingProperties:
    """
    **Validates: Requirements 4.3**

    Property 12: Trend Following Signal Conditions
    """

    @given(data=valid_trend_following_inputs())
    @settings(max_examples=100)
    def test_all_conditions_met_generates_buy_signal(self, data):
        """
        Property: When all 6 conditions are met, a BUY signal is always generated.

        **Validates: Requirements 4.3**
        """
        indicators, candles, _, _ = data
        strategy = TrendFollowingStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None, "Expected a BUY signal when all 6 conditions are met"
        assert signal.side == "BUY"
        assert signal.strategy == "TrendFollowing"

    @given(data=invalid_trend_following_inputs())
    @settings(max_examples=100)
    def test_any_condition_fails_no_signal(self, data):
        """
        Property: When any single condition fails, no signal is generated.

        **Validates: Requirements 4.3**
        """
        indicators, candles = data
        strategy = TrendFollowingStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is None, "Expected no signal when at least one condition fails"

    @given(data=valid_trend_following_inputs())
    @settings(max_examples=100)
    def test_stop_loss_below_entry_price(self, data):
        """
        Property: For any generated signal, stop_loss < entry_price.

        **Validates: Requirements 4.3**
        """
        indicators, candles, _, _ = data
        strategy = TrendFollowingStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss < signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be below entry_price ({signal.entry_price})"
        )

    @given(data=valid_trend_following_inputs())
    @settings(max_examples=100)
    def test_target_above_entry_price(self, data):
        """
        Property: For any generated signal, target > entry_price.

        **Validates: Requirements 4.3**
        """
        indicators, candles, _, _ = data
        strategy = TrendFollowingStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.target > signal.entry_price, (
            f"target ({signal.target}) must be above entry_price ({signal.entry_price})"
        )

    @given(data=valid_trend_following_inputs())
    @settings(max_examples=100)
    def test_stop_loss_formula_correctness(self, data):
        """
        Property: stop_loss == entry_price - (stop_loss_atr_multiplier × atr_14).

        **Validates: Requirements 4.3**
        """
        indicators, candles, atr_14, close = data
        atr_multiplier = 2.0
        strategy = TrendFollowingStrategy(_default_config(stop_loss_atr_multiplier=atr_multiplier))

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        expected_stop_loss = close - (atr_multiplier * atr_14)
        assert signal.stop_loss == pytest.approx(expected_stop_loss), (
            f"stop_loss ({signal.stop_loss}) must equal "
            f"entry_price - (atr_multiplier × atr_14) = {expected_stop_loss}"
        )

    @given(data=valid_trend_following_inputs())
    @settings(max_examples=100)
    def test_target_formula_correctness(self, data):
        """
        Property: target == entry_price + (target_atr_multiplier × atr_14).

        **Validates: Requirements 4.3**
        """
        indicators, candles, atr_14, close = data
        target_multiplier = 3.0
        strategy = TrendFollowingStrategy(_default_config(target_atr_multiplier=target_multiplier))

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        expected_target = close + (target_multiplier * atr_14)
        assert signal.target == pytest.approx(expected_target), (
            f"target ({signal.target}) must equal "
            f"entry_price + (target_multiplier × atr_14) = {expected_target}"
        )
