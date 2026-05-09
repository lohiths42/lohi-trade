"""
Tests for the MeanReversionStrategy.

Validates:
- Signal generation when all 4 entry conditions are met
- No signal when any single condition fails
- Correct stop loss and target calculation
- Disabled strategy returns None
- Empty candles returns None
- Signal fields are populated correctly

Requirements: 4.2
"""

from datetime import datetime
from typing import Optional

import pandas as pd
import pytest

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import MeanReversionStrategy, Signal
from src.utils.config import MeanReversionStrategy as MeanReversionConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(enabled: bool = True) -> MeanReversionConfig:
    return MeanReversionConfig(
        enabled=enabled,
        rsi_oversold=30,
        rsi_overbought=65,
        volume_multiplier=1.5,
        stop_loss_atr_multiplier=1.5,
    )


def _make_indicators(
    symbol: str = "RELIANCE",
    rsi_14: float = 25.0,
    bb_lower: float = 95.0,
    bb_middle: float = 100.0,
    bb_upper: float = 105.0,
    vwap: float = 90.0,
    atr_14: float = 3.0,
    volume_avg_20: float = 50000.0,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=rsi_14,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        vwap=vwap,
        ema_9=101.0,
        ema_21=100.0,
        supertrend=95.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )


def _make_candles(close: float = 93.0, volume: float = 80000.0) -> pd.DataFrame:
    """Create a minimal candles DataFrame with one row."""
    return pd.DataFrame(
        {
            "open": [92.0],
            "high": [94.0],
            "low": [91.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [datetime(2024, 1, 15, 10, 0, 0)],
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMeanReversionProperties:
    def test_name(self):
        strat = MeanReversionStrategy(_default_config())
        assert strat.name == "MeanReversion"

    def test_enabled_true(self):
        strat = MeanReversionStrategy(_default_config(enabled=True))
        assert strat.enabled is True

    def test_enabled_false(self):
        strat = MeanReversionStrategy(_default_config(enabled=False))
        assert strat.enabled is False


class TestMeanReversionSignalGeneration:
    """All 4 conditions met: RSI<30, price<BB_lower, volume>1.5x avg, price>VWAP."""

    def test_generates_buy_signal_when_all_conditions_met(self):
        strat = MeanReversionStrategy(_default_config())
        # close=93 < bb_lower=95, rsi=25 < 30, volume=80000 > 1.5*50000=75000, close=93 > vwap=90
        indicators = _make_indicators()
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.side == "BUY"
        assert signal.strategy == "MeanReversion"
        assert signal.symbol == "RELIANCE"

    def test_entry_price_is_last_candle_close(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators()
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.entry_price == 93.0

    def test_stop_loss_calculation(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(atr_14=3.0)
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # stop_loss = 93.0 - (1.5 * 3.0) = 93.0 - 4.5 = 88.5
        assert signal.stop_loss == pytest.approx(88.5)

    def test_target_is_bb_middle(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(bb_middle=100.0)
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.target == 100.0

    def test_signal_includes_indicators_snapshot(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators()
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.indicators is indicators


class TestMeanReversionNoSignal:
    """Each condition failing individually should prevent signal generation."""

    def test_no_signal_when_rsi_too_high(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(rsi_14=35.0)  # >= 30
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_price_above_bb_lower(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(bb_lower=90.0)  # close=93 > 90
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_volume_too_low(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(volume_avg_20=60000.0)  # 70000 < 1.5*60000=90000
        candles = _make_candles(close=93.0, volume=70000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_price_below_vwap(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(vwap=95.0)  # close=93 < vwap=95
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_disabled(self):
        strat = MeanReversionStrategy(_default_config(enabled=False))
        indicators = _make_indicators()
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_candles_empty(self):
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators()
        candles = pd.DataFrame()

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_rsi_boundary(self):
        """RSI exactly at threshold (30) should NOT trigger (condition is strict <)."""
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(rsi_14=30.0)
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_bb_lower_boundary(self):
        """Price exactly at BB lower should NOT trigger (condition is strict <)."""
        strat = MeanReversionStrategy(_default_config())
        indicators = _make_indicators(bb_lower=93.0)  # close == bb_lower
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None


class TestMeanReversionWithCustomConfig:
    def test_custom_rsi_threshold(self):
        config = MeanReversionConfig(
            enabled=True,
            rsi_oversold=25,
            rsi_overbought=65,
            volume_multiplier=1.5,
            stop_loss_atr_multiplier=1.5,
        )
        strat = MeanReversionStrategy(config)
        # RSI=27 is above custom threshold of 25
        indicators = _make_indicators(rsi_14=27.0)
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_custom_volume_multiplier(self):
        config = MeanReversionConfig(
            enabled=True,
            rsi_oversold=30,
            rsi_overbought=65,
            volume_multiplier=2.0,
            stop_loss_atr_multiplier=1.5,
        )
        strat = MeanReversionStrategy(config)
        # volume=80000 < 2.0 * 50000 = 100000
        indicators = _make_indicators()
        candles = _make_candles(close=93.0, volume=80000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_custom_atr_multiplier_in_stop_loss(self):
        config = MeanReversionConfig(
            enabled=True,
            rsi_oversold=30,
            rsi_overbought=65,
            volume_multiplier=1.5,
            stop_loss_atr_multiplier=2.0,
        )
        strat = MeanReversionStrategy(config)
        indicators = _make_indicators(atr_14=3.0)
        candles = _make_candles(close=93.0, volume=80000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # stop_loss = 93.0 - (2.0 * 3.0) = 87.0
        assert signal.stop_loss == pytest.approx(87.0)
