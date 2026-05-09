"""
Tests for the Indicator Engine.

Validates indicator calculation using pandas-ta, rolling window management,
insufficient data handling, symbol isolation, and error resilience.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.6
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from src.soldier.candle_builder import Candle
from src.soldier.indicator_engine import (
    MAX_ROLLING_WINDOW,
    MIN_CANDLES_REQUIRED,
    IndicatorEngine,
    IndicatorSet,
)


def _make_candle(
    symbol: str = "RELIANCE",
    timeframe: str = "1m",
    base_price: float = 1000.0,
    volume: int = 1000,
    offset_minutes: int = 0,
    price_delta: float = 0.0,
) -> Candle:
    """Helper to create a Candle with realistic OHLCV data."""
    price = base_price + price_delta
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open=price - 1.0,
        high=price + 2.0,
        low=price - 2.0,
        close=price,
        volume=volume,
        timestamp=datetime(2024, 1, 15, 9, 15) + timedelta(minutes=offset_minutes),
        is_complete=True,
    )


def _build_candle_series(
    n: int,
    symbol: str = "RELIANCE",
    timeframe: str = "1m",
    base_price: float = 1000.0,
    volume: int = 1000,
    trend: float = 0.5,
) -> list[Candle]:
    """Build a series of n candles with a slight upward trend and some noise."""
    candles = []
    np.random.seed(42)
    for i in range(n):
        noise = np.random.uniform(-2, 2)
        price = base_price + i * trend + noise
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open=price - abs(noise) * 0.5,
                high=price + abs(noise) + 1.0,
                low=price - abs(noise) - 1.0,
                close=price,
                volume=volume + int(np.random.uniform(-200, 200)),
                timestamp=datetime(2024, 1, 15, 9, 15) + timedelta(minutes=i),
                is_complete=True,
            )
        )
    return candles


class TestIndicatorEngineBasic:
    """Basic functionality tests for IndicatorEngine."""

    def test_insufficient_data_returns_none(self):
        """With fewer than MIN_CANDLES_REQUIRED candles, add_candle returns None."""
        engine = IndicatorEngine()
        candles = _build_candle_series(MIN_CANDLES_REQUIRED - 1)
        result = None
        for c in candles:
            result = engine.add_candle(c)
        assert result is None

    def test_sufficient_data_returns_indicator_set(self):
        """With enough candles, add_candle returns a valid IndicatorSet."""
        engine = IndicatorEngine()
        # Need enough candles for all indicators including BB(20) and MACD warm-up
        candles = _build_candle_series(50)
        result = None
        for c in candles:
            result = engine.add_candle(c)
        assert result is not None
        assert isinstance(result, IndicatorSet)

    def test_indicator_set_has_correct_symbol_and_timeframe(self):
        """IndicatorSet should carry the correct symbol and timeframe."""
        engine = IndicatorEngine()
        candles = _build_candle_series(50, symbol="TCS", timeframe="5m")
        result = None
        for c in candles:
            result = engine.add_candle(c)
        assert result is not None
        assert result.symbol == "TCS"
        assert result.timeframe == "5m"

    def test_indicator_set_timestamp_matches_last_candle(self):
        """IndicatorSet timestamp should match the last candle's timestamp."""
        engine = IndicatorEngine()
        candles = _build_candle_series(50)
        result = None
        for c in candles:
            result = engine.add_candle(c)
        assert result is not None
        assert result.timestamp == candles[-1].timestamp


class TestIndicatorValues:
    """Tests that indicator values are reasonable."""

    @pytest.fixture
    def indicators(self) -> IndicatorSet:
        engine = IndicatorEngine()
        candles = _build_candle_series(60, base_price=1000.0, trend=0.5)
        result = None
        for c in candles:
            result = engine.add_candle(c)
        assert result is not None
        return result

    def test_rsi_in_valid_range(self, indicators: IndicatorSet):
        """RSI should be between 0 and 100."""
        assert 0 <= indicators.rsi_14 <= 100

    def test_bollinger_band_ordering(self, indicators: IndicatorSet):
        """BB lower < BB middle < BB upper."""
        assert indicators.bb_lower < indicators.bb_middle < indicators.bb_upper

    def test_ema_values_are_positive(self, indicators: IndicatorSet):
        """EMA values should be positive for positive price data."""
        assert indicators.ema_9 > 0
        assert indicators.ema_21 > 0

    def test_atr_is_positive(self, indicators: IndicatorSet):
        """ATR should be positive."""
        assert indicators.atr_14 > 0

    def test_vwap_is_positive(self, indicators: IndicatorSet):
        """VWAP should be positive for positive price data."""
        assert indicators.vwap > 0

    def test_supertrend_direction_valid(self, indicators: IndicatorSet):
        """Supertrend direction should be 1 (bullish) or -1 (bearish)."""
        assert indicators.supertrend_direction in (1, -1)

    def test_supertrend_value_is_positive(self, indicators: IndicatorSet):
        """Supertrend value should be positive for positive price data."""
        assert indicators.supertrend > 0

    def test_volume_avg_is_positive(self, indicators: IndicatorSet):
        """Volume average should be positive."""
        assert indicators.volume_avg_20 > 0

    def test_macd_histogram_equals_macd_minus_signal(self, indicators: IndicatorSet):
        """MACD histogram should approximately equal MACD - signal."""
        expected = indicators.macd - indicators.macd_signal
        assert abs(indicators.macd_hist - expected) < 0.01


class TestRollingWindow:
    """Tests for rolling window management."""

    def test_rolling_window_capped_at_max(self):
        """Window should not exceed MAX_ROLLING_WINDOW candles."""
        engine = IndicatorEngine()
        candles = _build_candle_series(MAX_ROLLING_WINDOW + 20)
        for c in candles:
            engine.add_candle(c)
        assert engine.get_candle_count("RELIANCE", "1m") == MAX_ROLLING_WINDOW

    def test_candle_count_tracks_additions(self):
        """get_candle_count should reflect the number of candles added."""
        engine = IndicatorEngine()
        candles = _build_candle_series(10)
        for c in candles:
            engine.add_candle(c)
        assert engine.get_candle_count("RELIANCE", "1m") == 10

    def test_candle_count_zero_for_unknown_symbol(self):
        """get_candle_count returns 0 for a symbol with no data."""
        engine = IndicatorEngine()
        assert engine.get_candle_count("UNKNOWN", "1m") == 0


class TestGetLatestIndicators:
    """Tests for get_latest_indicators."""

    def test_returns_none_before_calculation(self):
        """Before any candles are added, get_latest_indicators returns None."""
        engine = IndicatorEngine()
        assert engine.get_latest_indicators("RELIANCE") is None

    def test_returns_latest_after_calculation(self):
        """After sufficient candles, get_latest_indicators returns the result."""
        engine = IndicatorEngine()
        candles = _build_candle_series(50)
        for c in candles:
            engine.add_candle(c)
        result = engine.get_latest_indicators("RELIANCE", "1m")
        assert result is not None
        assert isinstance(result, IndicatorSet)

    def test_updates_on_new_candle(self):
        """Adding a new candle should update the latest indicators."""
        engine = IndicatorEngine()
        candles = _build_candle_series(51)
        for c in candles[:50]:
            engine.add_candle(c)
        first = engine.get_latest_indicators("RELIANCE", "1m")

        engine.add_candle(candles[50])
        second = engine.get_latest_indicators("RELIANCE", "1m")

        assert first is not None and second is not None
        assert second.timestamp == candles[50].timestamp
        # Values should differ since we added a new candle
        assert first.timestamp != second.timestamp


class TestSymbolIsolation:
    """Tests that indicators are calculated independently per symbol."""

    def test_different_symbols_independent(self):
        """Indicators for one symbol should not affect another."""
        engine = IndicatorEngine()
        reliance_candles = _build_candle_series(50, symbol="RELIANCE", base_price=2500)
        tcs_candles = _build_candle_series(50, symbol="TCS", base_price=3500)

        for c in reliance_candles:
            engine.add_candle(c)
        for c in tcs_candles:
            engine.add_candle(c)

        rel = engine.get_latest_indicators("RELIANCE", "1m")
        tcs = engine.get_latest_indicators("TCS", "1m")

        assert rel is not None and tcs is not None
        assert rel.symbol == "RELIANCE"
        assert tcs.symbol == "TCS"
        # Prices are very different, so EMAs should differ significantly
        assert abs(rel.ema_21 - tcs.ema_21) > 500

    def test_different_timeframes_independent(self):
        """Indicators for different timeframes of the same symbol are independent."""
        engine = IndicatorEngine()
        candles_1m = _build_candle_series(50, timeframe="1m", base_price=1000)
        candles_5m = _build_candle_series(50, timeframe="5m", base_price=2000)

        for c in candles_1m:
            engine.add_candle(c)
        for c in candles_5m:
            engine.add_candle(c)

        ind_1m = engine.get_latest_indicators("RELIANCE", "1m")
        ind_5m = engine.get_latest_indicators("RELIANCE", "5m")

        assert ind_1m is not None and ind_5m is not None
        assert abs(ind_1m.ema_21 - ind_5m.ema_21) > 500


class TestReset:
    """Tests for the reset functionality."""

    def test_reset_specific_symbol(self):
        """Resetting a specific symbol/timeframe clears only that data."""
        engine = IndicatorEngine()
        candles_rel = _build_candle_series(50, symbol="RELIANCE")
        candles_tcs = _build_candle_series(50, symbol="TCS")

        for c in candles_rel:
            engine.add_candle(c)
        for c in candles_tcs:
            engine.add_candle(c)

        engine.reset(symbol="RELIANCE", timeframe="1m")

        assert engine.get_candle_count("RELIANCE", "1m") == 0
        assert engine.get_latest_indicators("RELIANCE", "1m") is None
        assert engine.get_candle_count("TCS", "1m") == 50

    def test_reset_all(self):
        """Resetting without arguments clears all data."""
        engine = IndicatorEngine()
        candles = _build_candle_series(50)
        for c in candles:
            engine.add_candle(c)

        engine.reset()

        assert engine.get_candle_count("RELIANCE", "1m") == 0
        assert engine.get_latest_indicators("RELIANCE", "1m") is None


class TestErrorHandling:
    """Tests for error handling in indicator calculation."""

    def test_zero_volume_candles_handled(self):
        """Candles with zero volume should not crash the engine."""
        engine = IndicatorEngine()
        candles = _build_candle_series(50, volume=0)
        result = None
        for c in candles:
            result = engine.add_candle(c)
        # Should either return a result or None, but not raise
        assert result is None or isinstance(result, IndicatorSet)

    def test_constant_price_candles(self):
        """Candles with constant price should not crash (ATR/BB may be 0)."""
        engine = IndicatorEngine()
        candles = []
        for i in range(50):
            candles.append(
                Candle(
                    symbol="FLAT",
                    timeframe="1m",
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    volume=1000,
                    timestamp=datetime(2024, 1, 15, 9, 15) + timedelta(minutes=i),
                    is_complete=True,
                )
            )
        result = None
        for c in candles:
            result = engine.add_candle(c)
        # Flat price: ATR=0, BB bands collapse. Should still return or return None gracefully.
        assert result is None or isinstance(result, IndicatorSet)
