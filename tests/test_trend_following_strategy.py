"""
Tests for the TrendFollowingStrategy.

Validates:
- Signal generation when all 6 entry conditions are met
- No signal when any single condition fails
- Correct stop loss and target calculation
- Disabled strategy returns None
- Empty candles returns None
- Signal fields are populated correctly
- Boundary conditions for each entry condition

Requirements: 4.3
"""

from datetime import datetime

import pandas as pd
import pytest

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import TrendFollowingStrategy, Signal
from src.utils.config import TrendFollowingStrategy as TrendFollowingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(enabled: bool = True) -> TrendFollowingConfig:
    return TrendFollowingConfig(
        enabled=enabled,
        ema_fast=9,
        ema_slow=21,
        stop_loss_atr_multiplier=2.0,
        target_atr_multiplier=3.0,
    )


def _make_indicators(
    symbol: str = "RELIANCE",
    ema_9: float = 105.0,
    ema_21: float = 100.0,
    macd: float = 1.5,
    macd_hist: float = 0.5,
    vwap: float = 98.0,
    supertrend_direction: int = 1,
    atr_14: float = 3.0,
    volume_avg_20: float = 50000.0,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=50.0,
        macd=macd,
        macd_signal=0.3,
        macd_hist=macd_hist,
        bb_upper=110.0,
        bb_middle=105.0,
        bb_lower=100.0,
        vwap=vwap,
        ema_9=ema_9,
        ema_21=ema_21,
        supertrend=95.0,
        supertrend_direction=supertrend_direction,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )


def _make_candles(close: float = 103.0, volume: float = 60000.0) -> pd.DataFrame:
    """Create a minimal candles DataFrame with one row."""
    return pd.DataFrame(
        {
            "open": [101.0],
            "high": [104.0],
            "low": [100.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [datetime(2024, 1, 15, 10, 0, 0)],
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTrendFollowingProperties:
    def test_name(self):
        strat = TrendFollowingStrategy(_default_config())
        assert strat.name == "TrendFollowing"

    def test_enabled_true(self):
        strat = TrendFollowingStrategy(_default_config(enabled=True))
        assert strat.enabled is True

    def test_enabled_false(self):
        strat = TrendFollowingStrategy(_default_config(enabled=False))
        assert strat.enabled is False


class TestTrendFollowingSignalGeneration:
    """All 6 conditions met: EMA9>EMA21, MACD>0, MACD_hist>0, price>VWAP, supertrend==1, volume>avg."""

    def test_generates_buy_signal_when_all_conditions_met(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators()
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.side == "BUY"
        assert signal.strategy == "TrendFollowing"
        assert signal.symbol == "RELIANCE"

    def test_entry_price_is_last_candle_close(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators()
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.entry_price == 103.0

    def test_stop_loss_calculation(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(atr_14=3.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # stop_loss = 103.0 - (2.0 * 3.0) = 103.0 - 6.0 = 97.0
        assert signal.stop_loss == pytest.approx(97.0)

    def test_target_calculation(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(atr_14=3.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # target = 103.0 + (3.0 * 3.0) = 103.0 + 9.0 = 112.0
        assert signal.target == pytest.approx(112.0)

    def test_signal_includes_indicators_snapshot(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators()
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.indicators is indicators


class TestTrendFollowingNoSignal:
    """Each condition failing individually should prevent signal generation."""

    def test_no_signal_when_ema9_below_ema21(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(ema_9=99.0, ema_21=100.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_macd_negative(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(macd=-0.5)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_macd_hist_negative(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(macd_hist=-0.3)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_price_below_vwap(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(vwap=110.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_supertrend_bearish(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(supertrend_direction=-1)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_volume_below_avg(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(volume_avg_20=70000.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_disabled(self):
        strat = TrendFollowingStrategy(_default_config(enabled=False))
        indicators = _make_indicators()
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_candles_empty(self):
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators()
        candles = pd.DataFrame()

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_ema_boundary(self):
        """EMA9 exactly equal to EMA21 should NOT trigger (condition is strict >)."""
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(ema_9=100.0, ema_21=100.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_macd_zero(self):
        """MACD exactly at 0 should NOT trigger (condition is strict >)."""
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(macd=0.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_macd_hist_zero(self):
        """MACD histogram exactly at 0 should NOT trigger (condition is strict >)."""
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(macd_hist=0.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_vwap_boundary(self):
        """Price exactly at VWAP should NOT trigger (condition is strict >)."""
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(vwap=103.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_volume_boundary(self):
        """Volume exactly at avg should NOT trigger (condition is strict >)."""
        strat = TrendFollowingStrategy(_default_config())
        indicators = _make_indicators(volume_avg_20=60000.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        assert strat.generate_signal(indicators, candles) is None


class TestTrendFollowingWithCustomConfig:
    def test_custom_atr_multiplier_in_stop_loss(self):
        config = TrendFollowingConfig(
            enabled=True,
            ema_fast=9,
            ema_slow=21,
            stop_loss_atr_multiplier=1.5,
            target_atr_multiplier=3.0,
        )
        strat = TrendFollowingStrategy(config)
        indicators = _make_indicators(atr_14=4.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # stop_loss = 103.0 - (1.5 * 4.0) = 103.0 - 6.0 = 97.0
        assert signal.stop_loss == pytest.approx(97.0)

    def test_custom_target_multiplier(self):
        config = TrendFollowingConfig(
            enabled=True,
            ema_fast=9,
            ema_slow=21,
            stop_loss_atr_multiplier=2.0,
            target_atr_multiplier=4.0,
        )
        strat = TrendFollowingStrategy(config)
        indicators = _make_indicators(atr_14=3.0)
        candles = _make_candles(close=103.0, volume=60000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # target = 103.0 + (4.0 * 3.0) = 103.0 + 12.0 = 115.0
        assert signal.target == pytest.approx(115.0)
