"""
Property-based test for Symbol Isolation in Indicator Calculation.

Property 10: Symbol Isolation in Indicator Calculation
For any two different symbols, indicator calculations for one symbol
should not affect indicator values for the other symbol.

Validates: Requirements 3.4
"""

import math
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.candle_builder import Candle
from src.soldier.indicator_engine import IndicatorEngine, IndicatorSet


# ---------------------------------------------------------------------------
# Composite strategy: generate a candle series with configurable symbol and
# base_price so we can create two distinct series at different price levels.
# ---------------------------------------------------------------------------

@st.composite
def candle_series_for_symbol(draw, symbol: str, base_price: float):
    """
    Generate a series of 50 candles for a given symbol starting around
    *base_price* using a random walk.

    High >= max(open, close), Low <= min(open, close), volume > 0,
    timestamps increment by 1 minute.
    """
    num_candles = 50
    candles: list[Candle] = []
    price = base_price
    base_time = datetime(2024, 1, 15, 9, 15, 0)

    for i in range(num_candles):
        step = draw(
            st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False)
        )
        price = max(1.0, price + step)

        open_delta = draw(
            st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        )
        open_price = max(0.5, price + open_delta)
        close_price = max(0.5, price)

        high_extra = draw(
            st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)
        )
        low_extra = draw(
            st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)
        )
        high_price = max(open_price, close_price) + high_extra
        low_price = max(0.01, min(open_price, close_price) - low_extra)

        volume = draw(st.integers(min_value=100, max_value=500_000))

        candles.append(
            Candle(
                symbol=symbol,
                timeframe="1m",
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                timestamp=base_time + timedelta(minutes=i),
                is_complete=True,
            )
        )

    return candles


def _indicators_match(a: IndicatorSet, b: IndicatorSet, tol: float = 1e-10) -> list[str]:
    """
    Compare all float fields of two IndicatorSets within *tol*.

    Returns a list of mismatch descriptions (empty means they match).
    """
    mismatches: list[str] = []
    float_fields = [
        "rsi_14", "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_middle", "bb_lower",
        "vwap", "ema_9", "ema_21",
        "supertrend", "atr_14", "volume_avg_20",
    ]
    for field in float_fields:
        val_a = getattr(a, field)
        val_b = getattr(b, field)
        if not math.isfinite(val_a) or not math.isfinite(val_b):
            mismatches.append(f"{field}: a={val_a}, b={val_b} (non-finite)")
        elif abs(val_a - val_b) >= tol:
            mismatches.append(f"{field}: a={val_a}, b={val_b}, diff={abs(val_a - val_b)}")

    # Integer field
    if a.supertrend_direction != b.supertrend_direction:
        mismatches.append(
            f"supertrend_direction: a={a.supertrend_direction}, b={b.supertrend_direction}"
        )

    return mismatches


@st.composite
def two_symbol_candle_series(draw):
    """
    Generate two candle series for different symbols at different price levels.

    Symbol A trades around 500, symbol B trades around 3000 — far enough
    apart that any cross-contamination would be obvious.
    """
    candles_a = draw(candle_series_for_symbol(symbol="RELIANCE", base_price=500.0))
    candles_b = draw(candle_series_for_symbol(symbol="TCS", base_price=3000.0))
    return candles_a, candles_b


@given(data=two_symbol_candle_series())
@settings(max_examples=25, deadline=None)
def test_property_symbol_isolation_in_indicator_calculation(data):
    """
    Property 10: Symbol Isolation in Indicator Calculation

    For any two different symbols, indicator calculations for one symbol
    should not affect indicator values for the other symbol.

    Validates: Requirements 3.4

    Feature: lohi-trade, Property 10: Symbol Isolation in Indicator Calculation
    """
    candles_a, candles_b = data

    # --- Isolated engines: one per symbol ---
    engine_isolated_a = IndicatorEngine()
    engine_isolated_b = IndicatorEngine()

    # --- Shared engine: both symbols fed into the same instance ---
    engine_shared = IndicatorEngine()

    # Feed symbol A candles to isolated-A and shared engines
    isolated_result_a = None
    shared_result_a = None
    for candle in candles_a:
        isolated_result_a = engine_isolated_a.add_candle(candle)
        shared_result_a = engine_shared.add_candle(candle)

    # Feed symbol B candles to isolated-B and shared engines
    isolated_result_b = None
    shared_result_b = None
    for candle in candles_b:
        isolated_result_b = engine_isolated_b.add_candle(candle)
        shared_result_b = engine_shared.add_candle(candle)

    # Both isolated engines should have produced indicators (50 candles > 26 min)
    assert isolated_result_a is not None, "Isolated engine A should produce indicators"
    assert isolated_result_b is not None, "Isolated engine B should produce indicators"
    assert shared_result_a is not None, "Shared engine should produce indicators for symbol A"
    assert shared_result_b is not None, "Shared engine should produce indicators for symbol B"

    # --- Core assertion: shared engine results must match isolated results ---

    mismatches_a = _indicators_match(shared_result_a, isolated_result_a)
    assert not mismatches_a, (
        f"Symbol A indicators differ between shared and isolated engines:\n"
        + "\n".join(mismatches_a)
    )

    mismatches_b = _indicators_match(shared_result_b, isolated_result_b)
    assert not mismatches_b, (
        f"Symbol B indicators differ between shared and isolated engines:\n"
        + "\n".join(mismatches_b)
    )
