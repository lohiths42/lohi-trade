"""Tests for the OpeningRangeBreakoutStrategy.

Validates:
- BUY signal when price breaks above range with volume
- SELL signal when price breaks below range with volume
- No signal when price within range
- No signal when volume insufficient
- No signal outside trade window
- No signal when no opening range set
- Stop loss and target calculations for both BUY and SELL
- Disabled strategy returns None
- Empty candles returns None
- Boundary conditions

Requirements: 4.4
"""

from datetime import datetime

import pandas as pd
import pytest

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import OpeningRangeBreakoutStrategy
from src.utils.config import OpeningRangeBreakoutStrategy as ORBConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_config(enabled: bool = True) -> ORBConfig:
    return ORBConfig(
        enabled=enabled,
        range_start="09:15",
        range_end="09:30",
        trade_window_start="09:30",
        trade_window_end="10:30",
        volume_multiplier=2.0,
        target_multiplier=1.5,
    )


def _make_indicators(
    symbol: str = "RELIANCE",
    volume_avg_20: float = 50000.0,
    atr_14: float = 3.0,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=50.0,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=110.0,
        bb_middle=105.0,
        bb_lower=100.0,
        vwap=102.0,
        ema_9=103.0,
        ema_21=101.0,
        supertrend=95.0,
        supertrend_direction=1,
        atr_14=atr_14,
        volume_avg_20=volume_avg_20,
    )


def _make_candles(
    close: float = 110.0,
    volume: float = 120000.0,
    timestamp: datetime | None = None,
) -> pd.DataFrame:
    """Create a minimal candles DataFrame with one row."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 10, 0, 0)  # Within trade window
    return pd.DataFrame(
        {
            "open": [105.0],
            "high": [111.0],
            "low": [104.0],
            "close": [close],
            "volume": [volume],
            "timestamp": [timestamp],
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestORBProperties:
    def test_name(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        assert strat.name == "OpeningRangeBreakout"

    def test_enabled_true(self):
        strat = OpeningRangeBreakoutStrategy(_default_config(enabled=True))
        assert strat.enabled is True

    def test_enabled_false(self):
        strat = OpeningRangeBreakoutStrategy(_default_config(enabled=False))
        assert strat.enabled is False


class TestORBOpeningRangeManagement:
    def test_set_and_get_opening_range(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        assert strat.get_opening_range("RELIANCE") == (108.0, 102.0)

    def test_get_opening_range_not_set(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        assert strat.get_opening_range("RELIANCE") is None

    def test_clear_opening_ranges(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        strat.set_opening_range("TCS", 200.0, 195.0)
        strat.clear_opening_ranges()
        assert strat.get_opening_range("RELIANCE") is None
        assert strat.get_opening_range("TCS") is None


class TestORBBuySignal:
    """BUY breakout: close > range_high AND volume > 2x volume_avg_20."""

    def test_generates_buy_signal_on_upward_breakout(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators(volume_avg_20=50000.0)
        # close=110 > range_high=108, volume=120000 > 2*50000=100000
        candles = _make_candles(close=110.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.side == "BUY"
        assert signal.strategy == "OpeningRangeBreakout"
        assert signal.symbol == "RELIANCE"

    def test_buy_entry_price_is_last_candle_close(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.entry_price == 110.0

    def test_buy_stop_loss_is_range_low(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss == pytest.approx(102.0)

    def test_buy_target_calculation(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # target = 110.0 + (1.5 * (108.0 - 102.0)) = 110.0 + 9.0 = 119.0
        assert signal.target == pytest.approx(119.0)

    def test_buy_signal_includes_indicators_snapshot(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.indicators is indicators


class TestORBSellSignal:
    """SELL breakout: close < range_low AND volume > 2x volume_avg_20."""

    def test_generates_sell_signal_on_downward_breakout(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators(volume_avg_20=50000.0)
        # close=100 < range_low=102, volume=120000 > 2*50000=100000
        candles = _make_candles(close=100.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.side == "SELL"
        assert signal.strategy == "OpeningRangeBreakout"
        assert signal.symbol == "RELIANCE"

    def test_sell_stop_loss_is_range_high(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=100.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        assert signal.stop_loss == pytest.approx(108.0)

    def test_sell_target_calculation(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=100.0, volume=120000.0)

        signal = strat.generate_signal(indicators, candles)

        assert signal is not None
        # target = 100.0 - (1.5 * (108.0 - 102.0)) = 100.0 - 9.0 = 91.0
        assert signal.target == pytest.approx(91.0)


class TestORBNoSignal:
    """Cases where no signal should be generated."""

    def test_no_signal_when_price_within_range(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        # close=105 is between range_low=102 and range_high=108
        candles = _make_candles(close=105.0, volume=120000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_volume_insufficient(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators(volume_avg_20=50000.0)
        # close=110 > range_high, but volume=90000 <= 2*50000=100000
        candles = _make_candles(close=110.0, volume=90000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_outside_trade_window_too_early(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        # 9:20 AM is before trade window start (9:30)
        candles = _make_candles(
            close=110.0,
            volume=120000.0,
            timestamp=datetime(2024, 1, 15, 9, 20, 0),
        )

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_outside_trade_window_too_late(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        # 11:00 AM is after trade window end (10:30)
        candles = _make_candles(
            close=110.0,
            volume=120000.0,
            timestamp=datetime(2024, 1, 15, 11, 0, 0),
        )

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_no_opening_range_set(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        # No opening range set for RELIANCE
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_disabled(self):
        strat = OpeningRangeBreakoutStrategy(_default_config(enabled=False))
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=110.0, volume=120000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_when_candles_empty(self):
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = pd.DataFrame()

        assert strat.generate_signal(indicators, candles) is None


class TestORBBoundaryConditions:
    """Boundary conditions for breakout and volume checks."""

    def test_no_signal_at_range_high_boundary(self):
        """Price exactly at range_high should NOT trigger BUY (strict >)."""
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=108.0, volume=120000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_range_low_boundary(self):
        """Price exactly at range_low should NOT trigger SELL (strict <)."""
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(close=102.0, volume=120000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_no_signal_at_volume_boundary(self):
        """Volume exactly at threshold should NOT trigger (strict >)."""
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators(volume_avg_20=50000.0)
        # volume=100000 == 2*50000=100000, not strictly greater
        candles = _make_candles(close=110.0, volume=100000.0)

        assert strat.generate_signal(indicators, candles) is None

    def test_signal_at_trade_window_start(self):
        """Candle at exactly 9:30 should be within trade window."""
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(
            close=110.0,
            volume=120000.0,
            timestamp=datetime(2024, 1, 15, 9, 30, 0),
        )

        signal = strat.generate_signal(indicators, candles)
        assert signal is not None
        assert signal.side == "BUY"

    def test_signal_at_trade_window_end(self):
        """Candle at exactly 10:30 should be within trade window."""
        strat = OpeningRangeBreakoutStrategy(_default_config())
        strat.set_opening_range("RELIANCE", 108.0, 102.0)
        indicators = _make_indicators()
        candles = _make_candles(
            close=110.0,
            volume=120000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
        )

        signal = strat.generate_signal(indicators, candles)
        assert signal is not None
        assert signal.side == "BUY"
