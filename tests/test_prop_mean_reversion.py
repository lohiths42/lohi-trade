"""
Property-based tests for MeanReversionStrategy.

Uses hypothesis to verify that the Mean Reversion strategy behaves correctly
across a wide range of randomly generated indicator values.

**Validates: Requirements 4.2**

Properties tested:
  1. When all 4 conditions are met, a BUY signal is always generated
  2. When any condition fails, no signal is generated
  3. Stop loss is always below entry price
  4. Target equals BB middle
  5. Stop loss formula: stop_loss == entry_price - (atr_multiplier × atr_14)
"""

from datetime import datetime

import pandas as pd
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import MeanReversionStrategy
from src.utils.config import MeanReversionStrategy as MeanReversionConfig


# ---------------------------------------------------------------------------
# Strategies (hypothesis generators)
# ---------------------------------------------------------------------------

# Reusable float strategies for indicator values
_positive_float = st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False)
_price = st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)
_volume = st.floats(min_value=1.0, max_value=1e9, allow_nan=False, allow_infinity=False)
_rsi = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


def _default_config(
    rsi_oversold: int = 30,
    volume_multiplier: float = 1.5,
    stop_loss_atr_multiplier: float = 1.5,
) -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=True,
        rsi_oversold=rsi_oversold,
        rsi_overbought=65,
        volume_multiplier=volume_multiplier,
        stop_loss_atr_multiplier=stop_loss_atr_multiplier,
    )


@st.composite
def valid_mean_reversion_inputs(draw):
    """
    Generate indicator values where ALL 4 Mean Reversion conditions are met:
      1. RSI < 30
      2. close < bb_lower
      3. volume > 1.5 × volume_avg_20
      4. close > vwap

    We pick vwap first, then close > vwap but close < bb_lower,
    so bb_lower must be > close > vwap.
    """
    rsi_oversold = 30
    volume_multiplier = 1.5

    # RSI strictly below threshold
    rsi_14 = draw(st.floats(min_value=0.1, max_value=29.99, allow_nan=False, allow_infinity=False))

    # Pick vwap, then close above vwap, then bb_lower above close
    vwap = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=vwap + 0.01, max_value=vwap + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_lower = draw(st.floats(min_value=close + 0.01, max_value=close + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_middle = draw(st.floats(min_value=bb_lower + 0.01, max_value=bb_lower + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_upper = draw(st.floats(min_value=bb_middle + 0.01, max_value=bb_middle + 10_000.0, allow_nan=False, allow_infinity=False))

    # Volume spike: volume > volume_multiplier × volume_avg_20
    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False))
    volume = draw(st.floats(
        min_value=volume_multiplier * volume_avg_20 + 1.0,
        max_value=volume_multiplier * volume_avg_20 + 1e8,
        allow_nan=False, allow_infinity=False,
    ))

    atr_14 = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=rsi_14,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        vwap=vwap,
        ema_9=0.0,
        ema_21=0.0,
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

    return indicators, candles, atr_14, bb_middle, close


@st.composite
def invalid_mean_reversion_inputs(draw):
    """
    Generate indicator values where AT LEAST ONE condition fails.

    We first generate a valid set, then deliberately break one condition.
    """
    rsi_oversold = 30
    volume_multiplier = 1.5

    # Start with valid values
    vwap = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=vwap + 0.01, max_value=vwap + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_lower = draw(st.floats(min_value=close + 0.01, max_value=close + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_middle = draw(st.floats(min_value=bb_lower + 0.01, max_value=bb_lower + 10_000.0, allow_nan=False, allow_infinity=False))
    bb_upper = draw(st.floats(min_value=bb_middle + 0.01, max_value=bb_middle + 10_000.0, allow_nan=False, allow_infinity=False))
    rsi_14 = draw(st.floats(min_value=0.1, max_value=29.99, allow_nan=False, allow_infinity=False))
    volume_avg_20 = draw(st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False))
    volume = volume_multiplier * volume_avg_20 + 1.0
    atr_14 = draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))

    # Pick which condition to break (0-3)
    condition_to_break = draw(st.integers(min_value=0, max_value=3))

    if condition_to_break == 0:
        # Break RSI: make RSI >= 30
        rsi_14 = draw(st.floats(min_value=30.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 1:
        # Break price < bb_lower: make close >= bb_lower
        close = draw(st.floats(min_value=bb_lower, max_value=bb_lower + 10_000.0, allow_nan=False, allow_infinity=False))
        # Ensure close still > vwap for isolation (only one condition broken)
        vwap = close - draw(st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False))
    elif condition_to_break == 2:
        # Break volume: make volume <= volume_multiplier × volume_avg_20
        volume = draw(st.floats(
            min_value=0.0,
            max_value=volume_multiplier * volume_avg_20,
            allow_nan=False, allow_infinity=False,
        ))
    else:
        # Break price > vwap: make close <= vwap
        vwap = close + draw(st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False))
        # Ensure close still < bb_lower
        bb_lower = max(bb_lower, close + 0.01)

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=rsi_14,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        vwap=vwap,
        ema_9=0.0,
        ema_21=0.0,
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

    return indicators, candles


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

class TestMeanReversionProperties:
    """
    **Validates: Requirements 4.2**

    Property 11: Mean Reversion Signal Conditions
    """

    @given(data=valid_mean_reversion_inputs())
    @settings(max_examples=25)
    def test_all_conditions_met_generates_buy_signal(self, data):
        """
        Property: When all 4 conditions are met, a BUY signal is always generated.

        **Validates: Requirements 4.2**
        """
        indicators, candles, _, _, _ = data
        strategy = MeanReversionStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None, "Expected a BUY signal when all conditions are met"
        assert signal.side == "BUY"
        assert signal.strategy == "MeanReversion"

    @given(data=invalid_mean_reversion_inputs())
    @settings(max_examples=25)
    def test_any_condition_fails_no_signal(self, data):
        """
        Property: When any single condition fails, no signal is generated.

        **Validates: Requirements 4.2**
        """
        indicators, candles = data
        strategy = MeanReversionStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is None, "Expected no signal when at least one condition fails"

    @given(data=valid_mean_reversion_inputs())
    @settings(max_examples=25)
    def test_stop_loss_below_entry_price(self, data):
        """
        Property: For any generated signal, stop_loss < entry_price.

        **Validates: Requirements 4.2**
        """
        indicators, candles, atr_14, _, close = data
        strategy = MeanReversionStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss < signal.entry_price, (
            f"stop_loss ({signal.stop_loss}) must be below entry_price ({signal.entry_price})"
        )

    @given(data=valid_mean_reversion_inputs())
    @settings(max_examples=25)
    def test_target_equals_bb_middle(self, data):
        """
        Property: For any generated signal, target == bb_middle.

        **Validates: Requirements 4.2**
        """
        indicators, candles, _, bb_middle, _ = data
        strategy = MeanReversionStrategy(_default_config())

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.target == pytest.approx(bb_middle), (
            f"target ({signal.target}) must equal bb_middle ({bb_middle})"
        )

    @given(data=valid_mean_reversion_inputs())
    @settings(max_examples=25)
    def test_stop_loss_formula_correctness(self, data):
        """
        Property: stop_loss == entry_price - (stop_loss_atr_multiplier × atr_14).

        **Validates: Requirements 4.2**
        """
        indicators, candles, atr_14, _, close = data
        atr_multiplier = 1.5
        strategy = MeanReversionStrategy(_default_config(stop_loss_atr_multiplier=atr_multiplier))

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        expected_stop_loss = close - (atr_multiplier * atr_14)
        assert signal.stop_loss == pytest.approx(expected_stop_loss), (
            f"stop_loss ({signal.stop_loss}) must equal "
            f"entry_price - (atr_multiplier × atr_14) = {expected_stop_loss}"
        )
