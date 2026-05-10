"""Signal Generation Pipeline for LOHI-TRADE.

Consumes indicators, runs enabled strategies, checks for duplicate positions,
and publishes valid signals to the Event Bus. Optionally filters signals
through the ML quality model when enabled.

Requirements: 4.5, 4.6, 4.7, 4.8
"""

from dataclasses import asdict

import pandas as pd

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal, Strategy
from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("SignalPipeline")

SIGNAL_STREAM = "stream:signals"
SIGNAL_STREAM_MAXLEN = 1000


class SignalPipeline:
    """Orchestrates signal generation from indicators through strategies.

    Runs all enabled strategies against incoming indicators, checks trading
    hours and duplicate positions, optionally filters through ML model,
    then publishes valid signals to the Event Bus.

    Requirements: 4.5, 4.6, 4.7, 4.8
    """

    def __init__(
        self,
        event_bus: EventBus,
        strategies: list[Strategy],
        trading_start: str,
        trading_end: str,
        ml_strategy=None,
    ) -> None:
        self._event_bus = event_bus
        self._strategies = strategies
        self._ml_strategy = ml_strategy
        self._open_positions: set[str] = set()

        # Parse trading hours into hour/minute integers
        start_parts = trading_start.split(":")
        self._trading_start_hour = int(start_parts[0])
        self._trading_start_minute = int(start_parts[1])

        end_parts = trading_end.split(":")
        self._trading_end_hour = int(end_parts[0])
        self._trading_end_minute = int(end_parts[1])

        logger.info(
            f"SignalPipeline initialized with {len(strategies)} strategies, "
            f"trading hours {trading_start}-{trading_end}",
        )

    def _is_within_trading_hours(self, timestamp) -> bool:
        """Check if the given timestamp is within trading hours."""
        current_minutes = timestamp.hour * 60 + timestamp.minute
        start_minutes = self._trading_start_hour * 60 + self._trading_start_minute
        end_minutes = self._trading_end_hour * 60 + self._trading_end_minute
        return start_minutes <= current_minutes <= end_minutes

    def process_indicators(
        self, indicators: IndicatorSet, candles: pd.DataFrame,
    ) -> Signal | None:
        """Process indicators through all enabled strategies and publish valid signals.

        Checks trading hours, runs strategies (or ML-enhanced strategy),
        prevents duplicate positions, and publishes the first valid signal
        to the Event Bus.

        Args:
            indicators: The latest calculated IndicatorSet for a symbol.
            candles: Recent candle DataFrame for the symbol.

        Returns:
            The first valid Signal if one is generated, otherwise None.

        Requirements: 4.5, 4.6, 4.7, 4.8

        """
        # Check trading hours using indicator timestamp
        if not self._is_within_trading_hours(indicators.timestamp):
            logger.debug(
                f"Signal rejected for {indicators.symbol}: outside trading hours "
                f"(timestamp={indicators.timestamp})",
            )
            return None

        # Use ML strategy if available, otherwise run base strategies directly
        if self._ml_strategy is not None and self._ml_strategy.enabled:
            signal = self._ml_strategy.generate_signal(indicators, candles)
            if signal is not None:
                if signal.symbol in self._open_positions:
                    logger.info(
                        f"Signal rejected for {signal.symbol}: duplicate position exists "
                        f"(strategy={signal.strategy})",
                    )
                    return None

                message = self._serialize_signal(signal)
                self._event_bus.publish(
                    SIGNAL_STREAM, message, maxlen=SIGNAL_STREAM_MAXLEN,
                )
                self._open_positions.add(signal.symbol)
                logger.info(
                    f"ML-filtered signal published: symbol={signal.symbol} "
                    f"strategy={signal.strategy} side={signal.side} "
                    f"entry={signal.entry_price:.2f}",
                )
                return signal
            return None

        for strategy in self._strategies:
            if not strategy.enabled:
                continue

            signal = strategy.generate_signal(indicators, candles)
            if signal is None:
                continue

            # Check for duplicate position
            if signal.symbol in self._open_positions:
                logger.info(
                    f"Signal rejected for {signal.symbol}: duplicate position exists "
                    f"(strategy={signal.strategy})",
                )
                continue

            # Publish to Event Bus
            message = self._serialize_signal(signal)
            self._event_bus.publish(
                SIGNAL_STREAM, message, maxlen=SIGNAL_STREAM_MAXLEN,
            )

            # Track open position
            self._open_positions.add(signal.symbol)

            logger.info(
                f"Signal published: symbol={signal.symbol} strategy={signal.strategy} "
                f"side={signal.side} entry={signal.entry_price:.2f}",
            )

            return signal

        return None

    def add_open_position(self, symbol: str) -> None:
        """Add a symbol to the open positions set."""
        self._open_positions.add(symbol)

    def remove_open_position(self, symbol: str) -> None:
        """Remove a symbol from the open positions set."""
        self._open_positions.discard(symbol)

    def clear_open_positions(self) -> None:
        """Clear all open positions (daily reset)."""
        self._open_positions.clear()

    def get_open_positions(self) -> set[str]:
        """Return the current set of open positions."""
        return set(self._open_positions)

    def record_trade_outcome(
        self,
        signal_id: str,
        entry_price: float,
        exit_price: float,
        side: str,
        atr: float,
    ) -> bool:
        """Record a completed trade outcome for ML model training.

        Delegates to the ML strategy's feedback loop if available.

        Returns True if the model was retrained.
        """
        if self._ml_strategy is not None:
            return self._ml_strategy.record_outcome(
                signal_id, entry_price, exit_price, side, atr,
            )
        return False

    @staticmethod
    def _serialize_signal(signal: Signal) -> dict:
        """Convert a Signal to a dict suitable for Redis Stream publishing.

        Args:
            signal: The Signal to serialize.

        Returns:
            Dictionary with all signal fields, timestamp and indicators serialized.

        """
        data = asdict(signal)
        data["timestamp"] = signal.timestamp.isoformat()
        data["indicators"] = asdict(signal.indicators)
        # Serialize nested indicator timestamp too
        data["indicators"]["timestamp"] = signal.indicators.timestamp.isoformat()
        return data
