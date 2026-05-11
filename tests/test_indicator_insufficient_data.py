"""Property-based test for Indicator Calculation with Insufficient Data.

Property 9: Indicator Calculation with Insufficient Data
For any symbol with fewer candles than the maximum indicator period required,
no indicators should be calculated or published.

Validates: Requirements 3.3
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.candle_builder import Candle
from src.soldier.indicator_engine import MIN_CANDLES_REQUIRED, IndicatorEngine


@st.composite
def insufficient_candle_series(draw):
    """Generate a series of 1 to MIN_CANDLES_REQUIRED-1 candles with realistic
    OHLCV data using a random walk approach.

    High >= max(open, close), Low <= min(open, close), volume > 0,
    timestamps increment by 1 minute.
    """
    num_candles = draw(st.integers(min_value=1, max_value=MIN_CANDLES_REQUIRED - 1))
    base_price = draw(
        st.floats(min_value=50.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
    )

    candles: list[Candle] = []
    price = base_price
    base_time = datetime(2024, 1, 15, 9, 15, 0)

    for i in range(num_candles):
        step = draw(
            st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
        )
        price = max(1.0, price + step)

        open_delta = draw(
            st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        )
        open_price = max(0.5, price + open_delta)
        close_price = max(0.5, price)

        high_extra = draw(
            st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        )
        low_extra = draw(
            st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        )
        high_price = max(open_price, close_price) + high_extra
        low_price = max(0.01, min(open_price, close_price) - low_extra)

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


@given(candles=insufficient_candle_series())
@settings(max_examples=50, deadline=None)
def test_property_indicator_insufficient_data(candles):
    """Property 9: Indicator Calculation with Insufficient Data

    For any symbol with fewer candles than the maximum indicator period required,
    no indicators should be calculated or published.

    Validates: Requirements 3.3

    Feature: lohi-trade, Property 9: Indicator Calculation with Insufficient Data
    """
    engine = IndicatorEngine()

    # Feed all candles and assert every call returns None
    for candle in candles:
        result = engine.add_candle(candle)
        assert result is None, (
            f"Expected None with {engine.get_candle_count(candle.symbol, candle.timeframe)} "
            f"candles (min required: {MIN_CANDLES_REQUIRED}), got IndicatorSet"
        )

    # After all candles, get_latest_indicators should also return None
    assert engine.get_latest_indicators("RELIANCE", "1m") is None, (
        f"get_latest_indicators should return None with only {len(candles)} candles "
        f"(min required: {MIN_CANDLES_REQUIRED})"
    )
