"""Property-based tests for the CandleBuilder OHLCV calculation.

Property 6: OHLCV Calculation Correctness
For any sequence of ticks within a candle period, the calculated Open should equal
the first tick price, High should equal the maximum tick price, Low should equal
the minimum tick price, Close should equal the last tick price, and Volume should
equal the sum of all tick volumes.

Validates: Requirements 2.3
"""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from src.ingestion.broker_interface import Tick
from src.soldier.candle_builder import CandleBuilder

# Strategy: generate a list of (price, volume) pairs for ticks within a single 1-minute bucket
tick_data_strategy = st.lists(
    st.tuples(
        st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        st.integers(min_value=1, max_value=1_000_000),
    ),
    min_size=1,
    max_size=50,
)


@given(tick_data=tick_data_strategy)
@settings(max_examples=50, deadline=None)
def test_property_ohlcv_calculation_correctness(tick_data):
    """Property 6: OHLCV Calculation Correctness

    For any sequence of ticks within a candle period, the calculated Open should
    equal the first tick price, High should equal the maximum tick price, Low should
    equal the minimum tick price, Close should equal the last tick price, and Volume
    should equal the sum of all tick volumes.

    Validates: Requirements 2.3

    Feature: lohi-trade, Property 6: OHLCV Calculation Correctness
    """
    # Use only 1m timeframe for simplicity — all ticks in the same bucket
    builder = CandleBuilder(timeframes=["1m"])

    # Fixed timestamp within a single 1-minute bucket (e.g., 10:00:00 to 10:00:59)
    base_time = datetime(2024, 1, 15, 10, 0, 0)

    prices = [p for p, _ in tick_data]
    volumes = [v for _, v in tick_data]

    for i, (price, volume) in enumerate(tick_data):
        tick = Tick(
            symbol="RELIANCE",
            token=2885,
            ltp=price,
            volume=volume,
            timestamp=base_time.replace(second=min(i, 59)),
            exchange="NSE",
        )
        builder.process_tick(tick)

    candle = builder.get_current_candle("RELIANCE", "1m")
    assert candle is not None, "Candle should exist after processing ticks"

    # Open = first tick's price
    assert (
        candle.open == prices[0]
    ), f"Open should be first tick price: expected {prices[0]}, got {candle.open}"

    # High = max of all tick prices
    assert candle.high == max(
        prices
    ), f"High should be max price: expected {max(prices)}, got {candle.high}"

    # Low = min of all tick prices
    assert candle.low == min(
        prices
    ), f"Low should be min price: expected {min(prices)}, got {candle.low}"

    # Close = last tick's price
    assert (
        candle.close == prices[-1]
    ), f"Close should be last tick price: expected {prices[-1]}, got {candle.close}"

    # Volume = sum of all tick volumes
    assert candle.volume == sum(
        volumes
    ), f"Volume should be sum of volumes: expected {sum(volumes)}, got {candle.volume}"


# Strategy: generate a random price for the initial tick that establishes last known price
price_strategy = st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False)


@given(last_price=price_strategy)
@settings(max_examples=50, deadline=None)
def test_property_market_gap_handling(last_price):
    """Property 7: Market Gap Handling

    For any candle period with no ticks received, the candle should use the
    last known price from the previous period for all OHLCV values.

    **Validates: Requirements 2.4**

    Feature: lohi-trade, Property 7: Market Gap Handling
    """
    builder = CandleBuilder(timeframes=["1m"])

    # Process an initial tick to establish a last known price
    initial_time = datetime(2024, 1, 15, 10, 0, 30)  # 10:00:30 — inside the 10:00 bucket
    tick = Tick(
        symbol="RELIANCE",
        token=2885,
        ltp=last_price,
        volume=100,
        timestamp=initial_time,
        exchange="NSE",
    )
    builder.process_tick(tick)

    # Call fill_gap with a timestamp in a later time bucket (10:01 bucket)
    gap_time = datetime(2024, 1, 15, 10, 1, 15)  # 10:01:15 — next 1m bucket
    builder.fill_gap("RELIANCE", gap_time)

    # Retrieve the gap candle (it should now be the current candle for the 10:01 bucket)
    gap_candle = builder.get_current_candle("RELIANCE", "1m")
    assert gap_candle is not None, "Gap candle should exist after fill_gap"

    # The gap candle's bucket should be the 10:01 bucket
    expected_bucket = datetime(2024, 1, 15, 10, 1, 0)
    assert (
        gap_candle.timestamp == expected_bucket
    ), f"Gap candle timestamp should be {expected_bucket}, got {gap_candle.timestamp}"

    # All OHLCV price fields should equal the last known price
    assert (
        gap_candle.open == last_price
    ), f"Gap candle open should be last known price {last_price}, got {gap_candle.open}"
    assert (
        gap_candle.high == last_price
    ), f"Gap candle high should be last known price {last_price}, got {gap_candle.high}"
    assert (
        gap_candle.low == last_price
    ), f"Gap candle low should be last known price {last_price}, got {gap_candle.low}"
    assert (
        gap_candle.close == last_price
    ), f"Gap candle close should be last known price {last_price}, got {gap_candle.close}"

    # Volume should be zero for a gap candle
    assert gap_candle.volume == 0, f"Gap candle volume should be 0, got {gap_candle.volume}"

    # Gap candle should be marked as complete
    assert (
        gap_candle.is_complete is True
    ), f"Gap candle should be complete, got is_complete={gap_candle.is_complete}"


# Strategy: generate tick data that spans multiple 1-minute buckets
# Each tick has (price, volume, minute_offset) where minute_offset is 0..N
multi_timeframe_tick_strategy = st.lists(
    st.tuples(
        st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        st.integers(min_value=1, max_value=1_000_000),
    ),
    min_size=2,
    max_size=30,
)


@given(tick_data=multi_timeframe_tick_strategy)
@settings(max_examples=50, deadline=None)
def test_property_multi_timeframe_candle_building(tick_data):
    """Property 5: Multi-Timeframe Candle Building

    For any sequence of ticks, candles should be built and published for all
    configured timeframes (1m, 5m, 15m). When ticks span multiple 1-minute
    buckets, completed candles are produced for each timeframe.

    **Validates: Requirements 2.1, 2.2**

    Feature: lohi-trade, Property 5: Multi-Timeframe Candle Building
    """
    all_timeframes = ["1m", "5m", "15m"]
    builder = CandleBuilder(timeframes=all_timeframes)

    completed_candles: list = []
    builder.on_candle_complete(lambda c: completed_candles.append(c))

    # Distribute ticks across at least 2 different 1-minute buckets.
    # First half goes into minute 0 (10:00), second half into minute 1 (10:01).
    base_time = datetime(2024, 1, 15, 10, 0, 0)
    half = len(tick_data) // 2

    for i, (price, volume) in enumerate(tick_data):
        if i < half:
            ts = base_time.replace(second=min(i, 59))
        else:
            ts = base_time.replace(minute=1, second=min(i - half, 59))

        tick = Tick(
            symbol="RELIANCE",
            token=2885,
            ltp=price,
            volume=volume,
            timestamp=ts,
            exchange="NSE",
        )
        builder.process_tick(tick)

    # --- Assertions ---

    # 1) At least one completed 1m candle should exist (the 10:00 bucket completes
    #    when the first tick in the 10:01 bucket arrives).
    completed_1m = [c for c in completed_candles if c.timeframe == "1m"]
    assert (
        len(completed_1m) >= 1
    ), f"Expected at least 1 completed 1m candle, got {len(completed_1m)}"

    # 2) All completed candles must be marked complete
    for c in completed_candles:
        assert (
            c.is_complete is True
        ), f"Completed candle {c.symbol} {c.timeframe} should have is_complete=True"

    # 3) In-progress candles should exist for ALL 3 timeframes after processing
    for tf in all_timeframes:
        candle = builder.get_current_candle("RELIANCE", tf)
        assert candle is not None, f"Expected in-progress candle for timeframe {tf}, got None"

    # 4) All completed candles should have valid OHLCV data
    for c in completed_candles:
        assert c.open > 0, f"Open should be positive, got {c.open}"
        assert c.high >= c.low, f"High ({c.high}) should be >= Low ({c.low})"
        assert c.high >= c.open, f"High ({c.high}) should be >= Open ({c.open})"
        assert c.high >= c.close, f"High ({c.high}) should be >= Close ({c.close})"
        assert c.low <= c.open, f"Low ({c.low}) should be <= Open ({c.open})"
        assert c.low <= c.close, f"Low ({c.low}) should be <= Close ({c.close})"
        assert c.volume > 0, f"Volume should be positive, got {c.volume}"
