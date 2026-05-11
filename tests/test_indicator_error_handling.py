"""Property-based test for Indicator Calculation Error Handling.

Property: Indicator calculation error handling

When indicator calculation fails for one symbol, the engine should log
the error and continue processing other symbols without crashing.

Validates: Requirements 3.6

Feature: lohi-trade, Property: Indicator Calculation Error Handling
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.candle_builder import Candle
from src.soldier.indicator_engine import MIN_CANDLES_REQUIRED, IndicatorEngine

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@st.composite
def valid_candle_series(draw, symbol: str = "RELIANCE", num_candles: int = 50):
    """Generate a series of candles with normal, well-behaved prices for a symbol.
    Prices walk around a base price with small increments.
    """
    base_price = draw(st.floats(min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False))
    candles: list[Candle] = []
    price = base_price
    base_time = datetime(2024, 1, 15, 9, 15, 0)

    for i in range(num_candles):
        step = draw(st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False))
        price = max(1.0, price + step)

        open_price = max(0.5, price + draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)))
        close_price = max(0.5, price)
        high_price = max(open_price, close_price) + draw(st.floats(min_value=0.0, max_value=3.0, allow_nan=False, allow_infinity=False))
        low_price = max(0.01, min(open_price, close_price) - draw(st.floats(min_value=0.0, max_value=3.0, allow_nan=False, allow_infinity=False)))
        volume = draw(st.integers(min_value=100, max_value=500_000))

        candles.append(Candle(
            symbol=symbol,
            timeframe="1m",
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            timestamp=base_time + timedelta(minutes=i),
            is_complete=True,
        ))

    return candles


@st.composite
def bad_candle_series(draw, symbol: str = "BADSTOCK", num_candles: int = 50):
    """Generate a series of candles with extreme/edge-case values that might
    stress indicator calculations: very small prices near zero, zero volumes,
    identical OHLC values, etc.
    """
    candles: list[Candle] = []
    base_time = datetime(2024, 1, 15, 9, 15, 0)

    for i in range(num_candles):
        # Mix of extreme scenarios
        scenario = draw(st.sampled_from(["near_zero", "zero_volume", "constant", "tiny_range"]))

        if scenario == "near_zero":
            price = draw(st.floats(min_value=0.01, max_value=0.1, allow_nan=False, allow_infinity=False))
            open_p = price
            high_p = price + 0.001
            low_p = max(0.001, price - 0.001)
            close_p = price
            vol = draw(st.integers(min_value=0, max_value=10))
        elif scenario == "zero_volume":
            price = draw(st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False))
            open_p = price
            high_p = price + 1.0
            low_p = price - 1.0
            close_p = price
            vol = 0
        elif scenario == "constant":
            price = draw(st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False))
            open_p = price
            high_p = price
            low_p = price
            close_p = price
            vol = draw(st.integers(min_value=1, max_value=100))
        else:  # tiny_range
            price = draw(st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False))
            open_p = price
            high_p = price + 0.0001
            low_p = max(0.001, price - 0.0001)
            close_p = price
            vol = draw(st.integers(min_value=1, max_value=1000))

        candles.append(Candle(
            symbol=symbol,
            timeframe="1m",
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol,
            timestamp=base_time + timedelta(minutes=i),
            is_complete=True,
        ))

    return candles


# ---------------------------------------------------------------------------
# Property test: error isolation between symbols
# ---------------------------------------------------------------------------

@given(
    good_candles=valid_candle_series(symbol="RELIANCE"),
    bad_candles=bad_candle_series(symbol="BADSTOCK"),
)
@settings(max_examples=25, deadline=None)
def test_property_indicator_error_handling_continues_other_symbols(good_candles, bad_candles):
    """Property: Indicator calculation error handling

    When indicator calculation fails for one symbol, the engine should log
    the error and continue processing other symbols without crashing.

    Validates: Requirements 3.6

    Feature: lohi-trade, Property: Indicator Calculation Error Handling
    """
    engine = IndicatorEngine()

    # Interleave good and bad candles into the same engine.
    # Feed them alternately to simulate concurrent processing.
    max_len = max(len(good_candles), len(bad_candles))

    for i in range(max_len):
        # Feed bad candle first (if available) — should never raise
        if i < len(bad_candles):
            try:
                engine.add_candle(bad_candles[i])
            except Exception as exc:
                raise AssertionError(
                    f"Engine raised exception on bad candle #{i} for BADSTOCK: {exc}",
                ) from exc

        # Feed good candle (if available) — should never raise
        if i < len(good_candles):
            try:
                result = engine.add_candle(good_candles[i])
            except Exception as exc:
                raise AssertionError(
                    f"Engine raised exception on good candle #{i} for RELIANCE: {exc}",
                ) from exc

    # After feeding all candles, the good symbol should have valid indicators
    # (50 candles > MIN_CANDLES_REQUIRED = 26)
    good_indicators = engine.get_latest_indicators("RELIANCE", "1m")
    assert good_indicators is not None, (
        "Good symbol (RELIANCE) should produce valid indicators even when "
        "bad symbol data is processed in the same engine"
    )
    assert good_indicators.symbol == "RELIANCE"
    assert good_indicators.timeframe == "1m"

    # The engine should still be functional — candle counts should be correct
    assert engine.get_candle_count("RELIANCE", "1m") == len(good_candles)
    assert engine.get_candle_count("BADSTOCK", "1m") == len(bad_candles)


# ---------------------------------------------------------------------------
# Property test: monkey-patched calculate_indicators is handled gracefully
# ---------------------------------------------------------------------------

@given(good_candles=valid_candle_series(symbol="SYMBOL_A", num_candles=50))
@settings(max_examples=25, deadline=None)
def test_property_indicator_error_handling_monkey_patched_recovery(good_candles):
    """Property: Indicator calculation error handling (monkey-patch recovery)

    When calculate_indicators is monkey-patched to raise an exception,
    add_candle should return None (not raise). After restoring the original
    method, the engine should continue to work for other symbols.

    Validates: Requirements 3.6

    Feature: lohi-trade, Property: Indicator Calculation Error Handling
    """
    engine = IndicatorEngine()

    # Step 1: Feed enough candles for SYMBOL_A to get valid indicators
    for candle in good_candles:
        engine.add_candle(candle)

    result_a = engine.get_latest_indicators("SYMBOL_A", "1m")
    assert result_a is not None, "SYMBOL_A should have valid indicators after 50 candles"

    # Step 2: Monkey-patch calculate_indicators to raise an exception
    original_method = engine.calculate_indicators

    def broken_calculate(*args, **kwargs):
        raise RuntimeError("Simulated indicator calculation failure")

    engine.calculate_indicators = broken_calculate

    # Step 3: Feed a new candle for SYMBOL_B — should return None, NOT raise
    new_candle = Candle(
        symbol="SYMBOL_B",
        timeframe="1m",
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=1000,
        timestamp=datetime(2024, 1, 15, 10, 30, 0),
        is_complete=True,
    )
    # Feed enough candles for SYMBOL_B to pass the minimum threshold
    base_time = datetime(2024, 1, 15, 9, 15, 0)
    for i in range(MIN_CANDLES_REQUIRED):
        filler = Candle(
            symbol="SYMBOL_B",
            timeframe="1m",
            open=100.0 + i * 0.1,
            high=105.0 + i * 0.1,
            low=95.0 + i * 0.1,
            close=102.0 + i * 0.1,
            volume=1000,
            timestamp=base_time + timedelta(minutes=i),
            is_complete=True,
        )
        try:
            result_b = engine.add_candle(filler)
        except Exception as exc:
            raise AssertionError(
                f"Engine raised exception with broken calculate_indicators: {exc}",
            ) from exc

    # The result should be None because calculate_indicators is broken
    assert result_b is None, (
        "add_candle should return None when calculate_indicators raises, not propagate the error"
    )

    # Step 4: Restore the original method
    engine.calculate_indicators = original_method

    # Step 5: Feed another candle for SYMBOL_A — should still work
    extra_candle = Candle(
        symbol="SYMBOL_A",
        timeframe="1m",
        open=good_candles[-1].close,
        high=good_candles[-1].close + 3.0,
        low=good_candles[-1].close - 3.0,
        close=good_candles[-1].close + 1.0,
        volume=2000,
        timestamp=good_candles[-1].timestamp + timedelta(minutes=1),
        is_complete=True,
    )
    try:
        result_a_after = engine.add_candle(extra_candle)
    except Exception as exc:
        raise AssertionError(
            f"Engine raised exception after restoring calculate_indicators: {exc}",
        ) from exc

    assert result_a_after is not None, (
        "SYMBOL_A should still produce valid indicators after restoring "
        "calculate_indicators from a broken state"
    )
    assert result_a_after.symbol == "SYMBOL_A"
