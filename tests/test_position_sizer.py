"""Unit tests for the Position Sizer.

Tests position size calculation, max risk/position capping, rounding,
and rejection when quantity < 1.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.7
"""

from datetime import datetime
from unittest.mock import MagicMock

from src.execution.position_sizer import PositionSizer, PositionSizeResult
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal
from src.utils.config import CapitalConfig, Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_indicator_set(symbol: str = "RELIANCE") -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 30),
        rsi_14=45.0,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=2600.0,
        bb_middle=2500.0,
        bb_lower=2400.0,
        vwap=2500.0,
        ema_9=2510.0,
        ema_21=2490.0,
        supertrend=2480.0,
        supertrend_direction=1,
        atr_14=30.0,
        volume_avg_20=100000.0,
    )


def _make_signal(
    symbol: str = "RELIANCE",
    side: str = "BUY",
    entry_price: float = 1000.0,
    stop_loss: float = 980.0,
) -> Signal:
    return Signal(
        signal_id="test-signal-001",
        symbol=symbol,
        strategy="MeanReversion",
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=entry_price + 60.0,
        quantity=0,
        timestamp=datetime(2024, 1, 15, 10, 30),
        indicators=_make_indicator_set(symbol),
    )


def _make_config(
    capital: float = 200_000.0,
    risk_pct: float = 1.0,
    max_pos_pct: float = 20.0,
) -> Config:
    """Build a minimal Config with only the fields PositionSizer needs."""
    config = MagicMock(spec=Config)
    config.capital = CapitalConfig(
        total=capital,
        risk_per_trade_pct=risk_pct,
        max_position_size_pct=max_pos_pct,
        max_daily_loss_pct=2.0,
    )
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPositionSizerNormalCalculation:
    """Test the basic position sizing formula."""

    def test_design_example(self):
        """Verify the exact example from the design doc.

        Capital ₹2,00,000, risk 1% = ₹2,000
        Entry ₹1,000, stop ₹980, risk/share ₹20
        Raw qty = 2000/20 = 100
        Max position 20% = ₹40,000 → 40 shares
        Final: 40 shares
        """
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=1000.0, stop_loss=980.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == 40
        assert result.position_value == 40_000.0
        assert result.risk_amount == 40 * 20.0  # 800
        assert result.rejection_reason is None

    def test_risk_limited_not_position_limited(self):
        """When risk formula gives fewer shares than position cap allows."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 100, stop 80 → risk/share = 20, max_risk = 2000
        # Raw qty = 2000/20 = 100
        # Max position = 40000/100 = 400
        # Final: 100 (risk-limited)
        signal = _make_signal(entry_price=100.0, stop_loss=80.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == 100
        assert result.position_value == 10_000.0
        assert result.risk_amount == 100 * 20.0

    def test_result_fields_populated(self):
        """All result fields should be correctly populated."""
        config = _make_config()
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=500.0, stop_loss=490.0)

        result = sizer.calculate_quantity(signal)

        assert isinstance(result, PositionSizeResult)
        assert isinstance(result.quantity, int)
        assert result.risk_amount > 0
        assert result.position_value > 0


class TestMaxPositionSizeCapping:
    """Test that position value is capped at max_position_size_pct of capital."""

    def test_capped_by_position_size(self):
        """Position value should not exceed 20% of capital."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 1000, stop 980 → risk/share=20, raw qty=100
        # Position value 100*1000=100000 > 40000 → capped to 40
        signal = _make_signal(entry_price=1000.0, stop_loss=980.0)

        result = sizer.calculate_quantity(signal)

        assert result.position_value <= 200_000 * 0.20

    def test_not_capped_when_within_limit(self):
        """When position value is within limit, no capping occurs."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 50, stop 30 → risk/share=20, raw qty=100
        # Position value 100*50=5000 < 40000 → not capped
        signal = _make_signal(entry_price=50.0, stop_loss=30.0)

        result = sizer.calculate_quantity(signal)

        assert result.quantity == 100
        assert result.position_value == 5_000.0


class TestQuantityRounding:
    """Test that quantity is rounded to nearest integer."""

    def test_rounds_down_below_half(self):
        """Quantity 10.3 should round to 10."""
        # Need: max_risk / risk_per_share = 10.3 (approx)
        # capital=200000, risk=1% → max_risk=2000
        # risk_per_share = 2000/10.3 ≈ 194.17
        # entry - stop = 194.17 → entry=1000, stop=805.83
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=100.0)
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=1000.0, stop_loss=1000.0 - 194.17)

        result = sizer.calculate_quantity(signal)

        assert result.quantity == 10

    def test_rounds_up_above_half(self):
        """Quantity 10.7 should round to 11."""
        # max_risk=2000, risk_per_share = 2000/10.7 ≈ 186.92
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=100.0)
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=1000.0, stop_loss=1000.0 - 186.92)

        result = sizer.calculate_quantity(signal)

        assert result.quantity == 11


class TestMinimumQuantityRejection:
    """Test rejection when calculated quantity < 1."""

    def test_reject_when_quantity_below_one(self):
        """Very expensive stock with tight stop should be rejected."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 50000, stop 47000 → risk/share=3000, raw qty=2000/3000=0.67
        # Max position = 40000/50000 = 0.8
        # min(0.67, 0.8) = 0.67 → round = 1 ... still valid
        # Need even more extreme: entry 100000, stop 97000
        # raw qty = 2000/3000 = 0.67, max pos = 40000/100000 = 0.4
        # min(0.67, 0.4) = 0.4 → round = 0 → rejected
        signal = _make_signal(entry_price=100_000.0, stop_loss=97_000.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is False
        assert result.quantity == 0
        assert result.rejection_reason == "Insufficient capital for minimum quantity"
        assert result.risk_amount == 0.0
        assert result.position_value == 0.0

    def test_reject_with_small_capital(self):
        """Small capital with moderate stock price should be rejected."""
        config = _make_config(capital=1_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # max_risk = 10, risk/share = 20, raw qty = 0.5
        # max pos = 200/1000 = 0.2
        # min(0.5, 0.2) = 0.2 → round = 0 → rejected
        signal = _make_signal(entry_price=1000.0, stop_loss=980.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is False
        assert result.quantity == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_entry_equals_stop_loss(self):
        """Zero risk per share should be rejected."""
        config = _make_config()
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=1000.0, stop_loss=1000.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is False
        assert result.quantity == 0
        assert "zero" in result.rejection_reason.lower()

    def test_very_tight_stop_loss(self):
        """Very tight stop loss → large quantity, capped by position size."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 1000, stop 999.50 → risk/share=0.50
        # raw qty = 2000/0.50 = 4000
        # max pos = 40000/1000 = 40
        # Final: 40 (position-capped)
        signal = _make_signal(entry_price=1000.0, stop_loss=999.50)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == 40
        assert result.position_value <= 200_000 * 0.20

    def test_very_wide_stop_loss(self):
        """Wide stop loss → small quantity."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # Entry 1000, stop 500 → risk/share=500
        # raw qty = 2000/500 = 4
        # max pos = 40000/1000 = 40
        # Final: 4 (risk-limited)
        signal = _make_signal(entry_price=1000.0, stop_loss=500.0)

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == 4
        assert result.risk_amount == 4 * 500.0

    def test_sell_signal_uses_abs_risk(self):
        """SELL signal where stop_loss > entry_price should still work."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        # SELL: entry 1000, stop 1020 → risk/share = |1000-1020| = 20
        signal = _make_signal(
            side="SELL", entry_price=1000.0, stop_loss=1020.0,
        )

        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == 40  # same as BUY example

    def test_max_risk_not_exceeded(self):
        """Actual risk should never exceed 1% of capital."""
        config = _make_config(capital=200_000, risk_pct=1.0, max_pos_pct=20.0)
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=1000.0, stop_loss=980.0)

        result = sizer.calculate_quantity(signal)

        max_risk = 200_000 * 0.01
        assert result.risk_amount <= max_risk

    def test_quantity_is_integer(self):
        """Quantity must always be an integer."""
        config = _make_config()
        sizer = PositionSizer(config)
        signal = _make_signal(entry_price=333.0, stop_loss=320.0)

        result = sizer.calculate_quantity(signal)

        assert isinstance(result.quantity, int)
