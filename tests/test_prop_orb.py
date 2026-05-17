"""Property-based tests for OpeningRangeBreakoutStrategy.

Uses hypothesis to verify that the ORB strategy behaves correctly
across a wide range of randomly generated indicator values.

**Validates: Requirements 4.4**

Properties tested:
  1. BUY breakout always generates BUY signal
  2. SELL breakout always generates SELL signal
  3. Price within range never generates signal
  4. BUY stop loss equals range_low
  5. SELL stop loss equals range_high
  6. BUY target formula: target == entry_price + (target_multiplier × range_size)
  7. SELL target formula: target == entry_price - (target_multiplier × range_size)
"""

from datetime import datetime

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import OpeningRangeBreakoutStrategy
from src.utils.config import OpeningRangeBreakoutStrategy as ORBConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_config(
    volume_multiplier: float = 2.0,
    target_multiplier: float = 1.5,
) -> ORBConfig:
    return ORBConfig(
        enabled=True,
        range_start="09:15",
        range_end="09:30",
        trade_window_start="09:30",
        trade_window_end="10:30",
        volume_multiplier=volume_multiplier,
        target_multiplier=target_multiplier,
    )


# ---------------------------------------------------------------------------
# Composite strategies (hypothesis generators)
# ---------------------------------------------------------------------------


@st.composite
def valid_buy_breakout_inputs(draw):
    """Generate inputs where BUY breakout conditions are met:
    - close > range_high
    - volume > volume_multiplier × volume_avg_20
    - candle timestamp within trade window (9:30-10:30 AM)
    """
    volume_multiplier = 2.0

    # Opening range: range_low < range_high
    range_low = draw(
        st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False)
    )
    range_high = draw(
        st.floats(
            min_value=range_low + 0.01,
            max_value=range_low + 10_000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    # Close strictly above range_high
    close = draw(
        st.floats(
            min_value=range_high + 0.01,
            max_value=range_high + 10_000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    # Volume spike: volume > volume_multiplier × volume_avg_20
    volume_avg_20 = draw(
        st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False)
    )
    volume = draw(
        st.floats(
            min_value=volume_multiplier * volume_avg_20 + 1.0,
            max_value=volume_multiplier * volume_avg_20 + 1e8,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    atr_14 = draw(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )

    # Generate a time within trade window (9:30-10:30)
    hour = draw(st.sampled_from([9, 10]))
    if hour == 9:
        minute = draw(st.integers(min_value=30, max_value=59))
    elif hour == 10:
        minute = draw(st.integers(min_value=0, max_value=30))
    candle_time = datetime(2024, 1, 15, hour, minute, 0)

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=candle_time,
        rsi_14=50.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
        vwap=0.0,
        ema_9=0.0,
        ema_21=0.0,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame(
        {
            "open": [close - 1.0],
            "high": [close + 1.0],
            "low": [close - 2.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [candle_time],
        }
    )

    return indicators, candles, range_high, range_low, close


@st.composite
def valid_sell_breakout_inputs(draw):
    """Generate inputs where SELL breakout conditions are met:
    - close < range_low
    - volume > volume_multiplier × volume_avg_20
    - candle timestamp within trade window (9:30-10:30 AM)
    """
    volume_multiplier = 2.0

    # Opening range: range_low < range_high
    range_low = draw(
        st.floats(min_value=10.0, max_value=50_000.0, allow_nan=False, allow_infinity=False)
    )
    range_high = draw(
        st.floats(
            min_value=range_low + 0.01,
            max_value=range_low + 10_000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    # Close strictly below range_low
    close = draw(
        st.floats(min_value=0.01, max_value=range_low - 0.01, allow_nan=False, allow_infinity=False)
    )

    # Volume spike: volume > volume_multiplier × volume_avg_20
    volume_avg_20 = draw(
        st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False)
    )
    volume = draw(
        st.floats(
            min_value=volume_multiplier * volume_avg_20 + 1.0,
            max_value=volume_multiplier * volume_avg_20 + 1e8,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    atr_14 = draw(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )

    # Generate a time within trade window (9:30-10:30)
    hour = draw(st.sampled_from([9, 10]))
    if hour == 9:
        minute = draw(st.integers(min_value=30, max_value=59))
    elif hour == 10:
        minute = draw(st.integers(min_value=0, max_value=30))
    candle_time = datetime(2024, 1, 15, hour, minute, 0)

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=candle_time,
        rsi_14=50.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
        vwap=0.0,
        ema_9=0.0,
        ema_21=0.0,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame(
        {
            "open": [close - 1.0],
            "high": [close + 1.0],
            "low": [close - 2.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [candle_time],
        }
    )

    return indicators, candles, range_high, range_low, close


@st.composite
def price_within_range_inputs(draw):
    """Generate inputs where price is within the opening range:
      - range_low <= close <= range_high
    Volume and time are valid so only the price condition prevents a signal.
    """
    volume_multiplier = 2.0

    # Opening range
    range_low = draw(
        st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False)
    )
    range_high = draw(
        st.floats(
            min_value=range_low + 0.01,
            max_value=range_low + 10_000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    # Close within range (inclusive)
    close = draw(
        st.floats(min_value=range_low, max_value=range_high, allow_nan=False, allow_infinity=False)
    )

    # Volume spike (sufficient)
    volume_avg_20 = draw(
        st.floats(min_value=100.0, max_value=1e8, allow_nan=False, allow_infinity=False)
    )
    volume = draw(
        st.floats(
            min_value=volume_multiplier * volume_avg_20 + 1.0,
            max_value=volume_multiplier * volume_avg_20 + 1e8,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    atr_14 = draw(
        st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )

    # Generate a time within trade window (9:30-10:30)
    hour = draw(st.sampled_from([9, 10]))
    if hour == 9:
        minute = draw(st.integers(min_value=30, max_value=59))
    elif hour == 10:
        minute = draw(st.integers(min_value=0, max_value=30))
    candle_time = datetime(2024, 1, 15, hour, minute, 0)

    indicators = IndicatorSet(
        symbol="TEST",
        timeframe="5m",
        timestamp=candle_time,
        rsi_14=50.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=0.0,
        bb_middle=0.0,
        bb_lower=0.0,
        vwap=0.0,
        ema_9=0.0,
        ema_21=0.0,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )

    candles = pd.DataFrame(
        {
            "open": [close - 1.0],
            "high": [close + 1.0],
            "low": [close - 2.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [candle_time],
        }
    )

    return indicators, candles, range_high, range_low


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestORBProperties:
    """**Validates: Requirements 4.4**

    Property 13: Opening Range Breakout Signal Conditions
    """

    @given(data=valid_buy_breakout_inputs())
    @settings(max_examples=25)
    def test_buy_breakout_generates_buy_signal(self, data):
        """Property: When close > range_high with sufficient volume within trade
        window, a BUY signal is always generated.

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, _ = data
        strategy = OpeningRangeBreakoutStrategy(_default_config())
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None, "Expected a BUY signal on upward breakout"
        assert signal.side == "BUY"
        assert signal.strategy == "OpeningRangeBreakout"

    @given(data=valid_sell_breakout_inputs())
    @settings(max_examples=25)
    def test_sell_breakout_generates_sell_signal(self, data):
        """Property: When close < range_low with sufficient volume within trade
        window, a SELL signal is always generated.

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, _ = data
        strategy = OpeningRangeBreakoutStrategy(_default_config())
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None, "Expected a SELL signal on downward breakout"
        assert signal.side == "SELL"
        assert signal.strategy == "OpeningRangeBreakout"

    @given(data=price_within_range_inputs())
    @settings(max_examples=25)
    def test_price_within_range_no_signal(self, data):
        """Property: When range_low <= close <= range_high, no signal is generated
        regardless of volume or time.

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low = data
        strategy = OpeningRangeBreakoutStrategy(_default_config())
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is None, "Expected no signal when price is within opening range"

    @given(data=valid_buy_breakout_inputs())
    @settings(max_examples=25)
    def test_buy_stop_loss_equals_range_low(self, data):
        """Property: For any BUY signal, stop_loss == range_low.

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, _ = data
        strategy = OpeningRangeBreakoutStrategy(_default_config())
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss == pytest.approx(
            range_low
        ), f"BUY stop_loss ({signal.stop_loss}) must equal range_low ({range_low})"

    @given(data=valid_sell_breakout_inputs())
    @settings(max_examples=25)
    def test_sell_stop_loss_equals_range_high(self, data):
        """Property: For any SELL signal, stop_loss == range_high.

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, _ = data
        strategy = OpeningRangeBreakoutStrategy(_default_config())
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss == pytest.approx(
            range_high
        ), f"SELL stop_loss ({signal.stop_loss}) must equal range_high ({range_high})"

    @given(data=valid_buy_breakout_inputs())
    @settings(max_examples=25)
    def test_buy_target_formula(self, data):
        """Property: For any BUY signal,
        target == entry_price + (target_multiplier × (range_high - range_low)).

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, close = data
        target_multiplier = 1.5
        strategy = OpeningRangeBreakoutStrategy(
            _default_config(target_multiplier=target_multiplier)
        )
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        range_size = range_high - range_low
        expected_target = close + (target_multiplier * range_size)
        assert signal.target == pytest.approx(expected_target), (
            f"BUY target ({signal.target}) must equal "
            f"entry_price + (target_multiplier × range_size) = {expected_target}"
        )

    @given(data=valid_sell_breakout_inputs())
    @settings(max_examples=25)
    def test_sell_target_formula(self, data):
        """Property: For any SELL signal,
        target == entry_price - (target_multiplier × (range_high - range_low)).

        **Validates: Requirements 4.4**
        """
        indicators, candles, range_high, range_low, close = data
        target_multiplier = 1.5
        strategy = OpeningRangeBreakoutStrategy(
            _default_config(target_multiplier=target_multiplier)
        )
        strategy.set_opening_range("TEST", range_high, range_low)

        signal = strategy.generate_signal(indicators, candles)

        assert signal is not None
        range_size = range_high - range_low
        expected_target = close - (target_multiplier * range_size)
        assert signal.target == pytest.approx(expected_target), (
            f"SELL target ({signal.target}) must equal "
            f"entry_price - (target_multiplier × range_size) = {expected_target}"
        )
