"""Property-based test for Indicator Calculation Completeness.

Property 8: Indicator Calculation Completeness
For any completed candle with sufficient historical data (100+ prior candles),
all configured indicators (RSI, MACD, Bollinger Bands, VWAP, EMA, Supertrend, ATR)
should be calculated and published.

Validates: Requirements 3.1
"""

import math
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.candle_builder import Candle
from src.soldier.indicator_engine import IndicatorEngine

# ---------------------------------------------------------------------------
# Composite strategy: generate a list of realistic candles via random walk
# ---------------------------------------------------------------------------

@st.composite
def candle_series_strategy(draw):
    """Generate a series of 50+ candles with realistic OHLCV data.

    Uses a random-walk approach: start from a base price and apply small
    incremental steps so that prices stay positive and vary realistically.
    High >= max(open, close), Low <= min(open, close), volume > 0,
    timestamps increment by 1 minute.
    """
    num_candles = draw(st.integers(min_value=50, max_value=100))
    base_price = draw(st.floats(min_value=50.0, max_value=5000.0, allow_nan=False, allow_infinity=False))

    candles: list[Candle] = []
    price = base_price
    base_time = datetime(2024, 1, 15, 9, 15, 0)

    for i in range(num_candles):
        # Small random step for the close price
        step = draw(st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False))
        price = max(1.0, price + step)  # keep price positive

        # Open deviates slightly from previous close
        open_delta = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        open_price = max(0.5, price + open_delta)
        close_price = max(0.5, price)

        # High >= max(open, close), Low <= min(open, close)
        high_extra = draw(st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False))
        low_extra = draw(st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False))
        high_price = max(open_price, close_price) + high_extra
        low_price = min(open_price, close_price) - low_extra
        low_price = max(0.01, low_price)  # keep low positive

        volume = draw(st.integers(min_value=100, max_value=500_000))

        candles.append(
            Candle(
                symbol="RELIANCE",
                timeframe="1m",
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                timestamp=base_time + timedelta(minutes=i),
                is_complete=True,
            ),
        )

    return candles


@given(candles=candle_series_strategy())
@settings(max_examples=25, deadline=None)
def test_property_indicator_calculation_completeness(candles):
    """Property 8: Indicator Calculation Completeness

    For any completed candle with sufficient historical data (100+ prior candles),
    all configured indicators should be calculated and published.

    Validates: Requirements 3.1

    Feature: lohi-trade, Property 8: Indicator Calculation Completeness
    """
    engine = IndicatorEngine()

    # Feed all candles into the engine
    result = None
    for candle in candles:
        result = engine.add_candle(candle)

    # With 50+ candles (well above MIN_CANDLES_REQUIRED=26), the last
    # add_candle call should produce a non-None IndicatorSet.
    assert result is not None, (
        f"Expected indicators after {len(candles)} candles "
        f"(min required: 26), got None"
    )

    # --- All indicator fields must be finite (not NaN, not inf) ---

    # RSI should be in [0, 100]
    assert 0 <= result.rsi_14 <= 100, (
        f"RSI should be in [0, 100], got {result.rsi_14}"
    )

    # MACD, MACD signal, MACD histogram should be finite
    assert math.isfinite(result.macd), f"MACD should be finite, got {result.macd}"
    assert math.isfinite(result.macd_signal), f"MACD signal should be finite, got {result.macd_signal}"
    assert math.isfinite(result.macd_hist), f"MACD histogram should be finite, got {result.macd_hist}"

    # Bollinger Bands: lower < middle < upper
    assert math.isfinite(result.bb_lower), f"BB lower should be finite, got {result.bb_lower}"
    assert math.isfinite(result.bb_middle), f"BB middle should be finite, got {result.bb_middle}"
    assert math.isfinite(result.bb_upper), f"BB upper should be finite, got {result.bb_upper}"
    assert result.bb_lower <= result.bb_middle <= result.bb_upper, (
        f"Expected bb_lower <= bb_middle <= bb_upper, "
        f"got {result.bb_lower} <= {result.bb_middle} <= {result.bb_upper}"
    )

    # VWAP should be positive
    assert result.vwap > 0, f"VWAP should be > 0, got {result.vwap}"

    # EMAs should be positive
    assert result.ema_9 > 0, f"EMA(9) should be > 0, got {result.ema_9}"
    assert result.ema_21 > 0, f"EMA(21) should be > 0, got {result.ema_21}"

    # Supertrend should be positive
    assert result.supertrend > 0, f"Supertrend should be > 0, got {result.supertrend}"

    # Supertrend direction should be 1 (bullish) or -1 (bearish)
    assert result.supertrend_direction in (1, -1), (
        f"Supertrend direction should be 1 or -1, got {result.supertrend_direction}"
    )

    # ATR should be non-negative
    assert result.atr_14 >= 0, f"ATR should be >= 0, got {result.atr_14}"

    # Volume average should be positive
    assert result.volume_avg_20 > 0, f"Volume avg (20) should be > 0, got {result.volume_avg_20}"
