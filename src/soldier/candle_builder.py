"""Candle Builder for LOHI-TRADE.

Aggregates real-time ticks into OHLCV candles for multiple timeframes (1m, 5m, 15m).
Uses time-based bucketing to align candles to standard market intervals.

Requirements: 2.1, 2.3, 2.4, 2.5
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.ingestion.broker_interface import Tick
from src.utils.logger import get_logger

logger = get_logger("candle_builder")

# Timeframe durations in seconds
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}


@dataclass
class Candle:
    """OHLCV candle for a specific symbol and timeframe.

    Attributes:
        symbol: Trading symbol (e.g., "RELIANCE")
        timeframe: Candle timeframe (e.g., "1m", "5m", "15m")
        open: First tick price in the period
        high: Maximum tick price in the period
        low: Minimum tick price in the period
        close: Last tick price in the period
        volume: Sum of tick volumes in the period
        timestamp: Start time of the candle period (bucket start)
        is_complete: Whether the candle period has ended

    """

    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime
    is_complete: bool


def _get_bucket_start(timestamp: datetime, timeframe_seconds: int) -> datetime:
    """Calculate the start of the time bucket for a given timestamp.

    Aligns to standard market intervals:
    - 1m candles start at :00 seconds of each minute
    - 5m candles start at :00, :05, :10, :15, ... minutes
    - 15m candles start at :00, :15, :30, :45 minutes

    Args:
        timestamp: The tick timestamp.
        timeframe_seconds: Duration of the timeframe in seconds.

    Returns:
        The datetime representing the start of the bucket.

    """
    # Calculate seconds since midnight for alignment
    midnight = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (timestamp - midnight).total_seconds()
    bucket_index = int(seconds_since_midnight) // timeframe_seconds
    bucket_start = midnight + timedelta(seconds=bucket_index * timeframe_seconds)
    return bucket_start


class CandleBuilder:
    """Builds OHLCV candles from ticks for multiple timeframes.

    Maintains in-memory state for current (in-progress) candles per symbol
    and timeframe. Fires a callback when a candle period completes.

    Usage:
        builder = CandleBuilder(timeframes=["1m", "5m", "15m"])
        builder.on_candle_complete(my_callback)
        builder.process_tick(tick)
    """

    def __init__(self, timeframes: list[str] | None = None) -> None:
        """Initialize the CandleBuilder.

        Args:
            timeframes: List of timeframe strings to build candles for.
                        Defaults to ["1m", "5m", "15m"].

        """
        if timeframes is None:
            timeframes = ["1m", "5m", "15m"]

        # Validate timeframes
        for tf in timeframes:
            if tf not in TIMEFRAME_SECONDS:
                raise ValueError(
                    f"Unsupported timeframe '{tf}'. Supported: {list(TIMEFRAME_SECONDS.keys())}",
                )

        self._timeframes = timeframes

        # Current in-progress candles: (symbol, timeframe) -> Candle
        self._current_candles: dict[tuple[str, str], Candle] = {}

        # Last known price per symbol — used for market gap handling (Req 2.4)
        self._last_known_price: dict[str, float] = {}

        # Callbacks to invoke when a candle completes
        self._on_complete_callbacks: list[Callable[[Candle], None]] = []

        logger.info(f"CandleBuilder initialized with timeframes: {timeframes}")

    @property
    def timeframes(self) -> list[str]:
        """Return the configured timeframes."""
        return list(self._timeframes)

    def on_candle_complete(self, callback: Callable[[Candle], None]) -> None:
        """Register a callback to be invoked when a candle completes.

        Args:
            callback: Function that receives the completed Candle.

        """
        self._on_complete_callbacks.append(callback)

    def process_tick(self, tick: Tick) -> None:
        """Process a single tick and update candle state for all timeframes.

        If the tick falls into a new time bucket, the previous candle is
        completed and the callback is fired. A new candle is then started.

        Args:
            tick: The incoming Tick to process.

        """
        # Update last known price for this symbol
        self._last_known_price[tick.symbol] = tick.ltp

        for tf in self._timeframes:
            tf_seconds = TIMEFRAME_SECONDS[tf]
            bucket_start = _get_bucket_start(tick.timestamp, tf_seconds)
            key = (tick.symbol, tf)

            current = self._current_candles.get(key)

            if current is None:
                # First tick for this symbol/timeframe — start a new candle
                self._current_candles[key] = Candle(
                    symbol=tick.symbol,
                    timeframe=tf,
                    open=tick.ltp,
                    high=tick.ltp,
                    low=tick.ltp,
                    close=tick.ltp,
                    volume=tick.volume,
                    timestamp=bucket_start,
                    is_complete=False,
                )
            elif bucket_start > current.timestamp:
                # New bucket — complete the old candle and start a new one
                self._complete_candle(current)

                self._current_candles[key] = Candle(
                    symbol=tick.symbol,
                    timeframe=tf,
                    open=tick.ltp,
                    high=tick.ltp,
                    low=tick.ltp,
                    close=tick.ltp,
                    volume=tick.volume,
                    timestamp=bucket_start,
                    is_complete=False,
                )
            else:
                # Same bucket — update OHLCV
                current.high = max(current.high, tick.ltp)
                current.low = min(current.low, tick.ltp)
                current.close = tick.ltp
                current.volume += tick.volume

    def get_current_candle(self, symbol: str, timeframe: str) -> Candle | None:
        """Get the current in-progress candle for a symbol and timeframe.

        Args:
            symbol: Trading symbol.
            timeframe: Candle timeframe (e.g., "1m").

        Returns:
            The current Candle if one exists, otherwise None.

        """
        return self._current_candles.get((symbol, timeframe))

    def fill_gap(self, symbol: str, timestamp: datetime) -> None:
        """Handle a market gap by carrying forward the last known price.

        When no ticks arrive for a candle period, this method creates a
        candle using the last known price for all OHLCV values and zero
        volume, then completes it. This satisfies Requirement 2.4.

        Args:
            symbol: Trading symbol that experienced the gap.
            timestamp: The timestamp within the gap period.

        """
        last_price = self._last_known_price.get(symbol)
        if last_price is None:
            logger.warning(
                f"Cannot fill gap for {symbol}: no last known price available",
            )
            return

        for tf in self._timeframes:
            tf_seconds = TIMEFRAME_SECONDS[tf]
            bucket_start = _get_bucket_start(timestamp, tf_seconds)
            key = (symbol, tf)

            current = self._current_candles.get(key)

            # Only fill if there's no candle for this bucket yet,
            # or the current candle is from a previous bucket
            if current is None or bucket_start > current.timestamp:
                if current is not None and bucket_start > current.timestamp:
                    # Complete the previous candle first
                    self._complete_candle(current)

                gap_candle = Candle(
                    symbol=symbol,
                    timeframe=tf,
                    open=last_price,
                    high=last_price,
                    low=last_price,
                    close=last_price,
                    volume=0,
                    timestamp=bucket_start,
                    is_complete=True,
                )
                self._current_candles[key] = gap_candle
                self._fire_callbacks(gap_candle)
                logger.debug(
                    f"Filled market gap for {symbol} {tf} at {bucket_start} "
                    f"with last price {last_price}",
                )

    def flush(self) -> list[Candle]:
        """Complete and return all current in-progress candles.

        Useful at end-of-day to finalize any remaining open candles.

        Returns:
            List of completed Candle objects.

        """
        completed = []
        for key in list(self._current_candles.keys()):
            candle = self._current_candles.pop(key)
            candle.is_complete = True
            self._fire_callbacks(candle)
            completed.append(candle)
        return completed

    def reset(self) -> None:
        """Reset all in-memory state. Called at the start of each trading day
        to satisfy Requirement 2.5 (maintain candle state for current day only).
        """
        self._current_candles.clear()
        self._last_known_price.clear()
        logger.info("CandleBuilder state reset for new trading day")

    def _complete_candle(self, candle: Candle) -> None:
        """Mark a candle as complete and fire callbacks."""
        candle.is_complete = True
        self._fire_callbacks(candle)
        logger.debug(
            f"Candle complete: {candle.symbol} {candle.timeframe} "
            f"O={candle.open} H={candle.high} L={candle.low} C={candle.close} "
            f"V={candle.volume} @ {candle.timestamp}",
        )

    def _fire_callbacks(self, candle: Candle) -> None:
        """Invoke all registered on_candle_complete callbacks."""
        for cb in self._on_complete_callbacks:
            try:
                cb(candle)
            except Exception as e:
                logger.error(f"Error in candle complete callback: {e}")
