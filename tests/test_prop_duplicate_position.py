"""Property-based tests for Duplicate Position Prevention.

Uses hypothesis to verify that the SignalPipeline correctly prevents
duplicate signals for symbols that already have open positions.

**Validates: Requirements 4.8**

Properties tested:
  1. First signal for a symbol is always accepted
  2. Second signal for same symbol is always rejected
  3. Signals for different symbols are independent
  4. Pre-added open position blocks signal
  5. Removing open position allows new signal
  6. Clear open positions allows all symbols
"""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.signal_pipeline import SignalPipeline
from src.soldier.strategy_engine import MeanReversionStrategy
from src.utils.config import MeanReversionStrategy as MeanReversionConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_symbols = st.text(
    alphabet=st.characters(whitelist_categories=("Lu",)),
    min_size=2,
    max_size=10,
)


def _mean_reversion_config() -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=True,
        rsi_oversold=30,
        rsi_overbought=65,
        volume_multiplier=1.5,
        stop_loss_atr_multiplier=1.5,
    )


def _make_indicators(symbol: str) -> IndicatorSet:
    """Create indicators that satisfy MeanReversion conditions for a given symbol."""
    return IndicatorSet(
        symbol=symbol,
        timeframe="1m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=25.0,
        macd=0.0,
        macd_signal=0.0,
        macd_hist=0.0,
        bb_upper=1030.0,
        bb_middle=1010.0,
        bb_lower=990.0,
        vwap=980.0,
        ema_9=0.0,
        ema_21=0.0,
        supertrend=0.0,
        supertrend_direction=1,
        atr_14=10.0,
        volume_avg_20=50000.0,
    )


def _make_candles() -> pd.DataFrame:
    """Create candles that satisfy MeanReversion conditions (close=985 < bb_lower=990, volume=100000 > 1.5*50000)."""
    return pd.DataFrame(
        [
            {
                "open": 980.0,
                "high": 990.0,
                "low": 975.0,
                "close": 985.0,
                "volume": 100000.0,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0),
            },
        ],
    )


def _make_pipeline() -> SignalPipeline:
    strategy = MeanReversionStrategy(_mean_reversion_config())
    return SignalPipeline(
        event_bus=MagicMock(),
        strategies=[strategy],
        trading_start="09:30",
        trading_end="15:10",
    )


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestDuplicatePositionPreventionProperties:
    """**Validates: Requirements 4.8**

    Property 16: Duplicate Position Prevention
    """

    @given(symbol=_symbols)
    @settings(max_examples=25)
    def test_first_signal_for_symbol_is_always_accepted(self, symbol: str):
        """Property: For any random symbol with valid conditions, the first
        signal should always be generated.

        **Validates: Requirements 4.8**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(symbol)
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)

        assert signal is not None, f"Expected first signal for '{symbol}' to be accepted"
        assert signal.symbol == symbol

    @given(symbol=_symbols)
    @settings(max_examples=25)
    def test_second_signal_for_same_symbol_is_always_rejected(self, symbol: str):
        """Property: After a signal is generated for a symbol, any subsequent
        signal for the same symbol should be rejected.

        **Validates: Requirements 4.8**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(symbol)
        candles = _make_candles()

        # First signal should be accepted
        first = pipeline.process_indicators(indicators, candles)
        assert first is not None

        # Second signal for same symbol should be rejected
        second = pipeline.process_indicators(indicators, candles)
        assert (
            second is None
        ), f"Expected second signal for '{symbol}' to be rejected (duplicate position)"

    @given(
        symbol_a=_symbols,
        symbol_b=_symbols,
    )
    @settings(max_examples=25)
    def test_signals_for_different_symbols_are_independent(
        self,
        symbol_a: str,
        symbol_b: str,
    ):
        """Property: Generating a signal for symbol A should not prevent
        generating a signal for symbol B.

        **Validates: Requirements 4.8**
        """
        from hypothesis import assume

        assume(symbol_a != symbol_b)

        pipeline = _make_pipeline()
        candles = _make_candles()

        # Generate signal for symbol A
        signal_a = pipeline.process_indicators(
            _make_indicators(symbol_a),
            candles,
        )
        assert signal_a is not None

        # Signal for symbol B should still be accepted
        signal_b = pipeline.process_indicators(
            _make_indicators(symbol_b),
            candles,
        )
        assert (
            signal_b is not None
        ), f"Signal for '{symbol_b}' should not be blocked by open position in '{symbol_a}'"
        assert signal_b.symbol == symbol_b

    @given(symbol=_symbols)
    @settings(max_examples=25)
    def test_pre_added_open_position_blocks_signal(self, symbol: str):
        """Property: If a symbol is added to open positions before processing,
        no signal should be generated for that symbol.

        **Validates: Requirements 4.8**
        """
        pipeline = _make_pipeline()
        pipeline.add_open_position(symbol)

        indicators = _make_indicators(symbol)
        candles = _make_candles()

        signal = pipeline.process_indicators(indicators, candles)
        assert (
            signal is None
        ), f"Expected signal for '{symbol}' to be blocked by pre-added open position"

    @given(symbol=_symbols)
    @settings(max_examples=25)
    def test_removing_open_position_allows_new_signal(self, symbol: str):
        """Property: After removing a symbol from open positions, a new signal
        for that symbol should be accepted.

        **Validates: Requirements 4.8**
        """
        pipeline = _make_pipeline()
        indicators = _make_indicators(symbol)
        candles = _make_candles()

        # Generate first signal (adds to open positions)
        first = pipeline.process_indicators(indicators, candles)
        assert first is not None

        # Remove from open positions
        pipeline.remove_open_position(symbol)

        # New signal should be accepted
        second = pipeline.process_indicators(indicators, candles)
        assert (
            second is not None
        ), f"Expected signal for '{symbol}' to be accepted after removing open position"

    @given(data=st.data())
    @settings(max_examples=25)
    def test_clear_open_positions_allows_all_symbols(self, data):
        """Property: After clearing all open positions, signals for any
        previously blocked symbol should be accepted.

        **Validates: Requirements 4.8**
        """
        # Generate 2-5 distinct symbols
        symbols = data.draw(
            st.lists(_symbols, min_size=2, max_size=5, unique=True),
        )

        pipeline = _make_pipeline()
        candles = _make_candles()

        # Generate signals for all symbols (adds them to open positions)
        for sym in symbols:
            signal = pipeline.process_indicators(
                _make_indicators(sym),
                candles,
            )
            assert signal is not None

        # Verify all are now blocked
        for sym in symbols:
            signal = pipeline.process_indicators(
                _make_indicators(sym),
                candles,
            )
            assert signal is None

        # Clear all open positions
        pipeline.clear_open_positions()

        # All symbols should now be accepted again
        for sym in symbols:
            signal = pipeline.process_indicators(
                _make_indicators(sym),
                candles,
            )
            assert (
                signal is not None
            ), f"Expected signal for '{sym}' to be accepted after clearing open positions"
