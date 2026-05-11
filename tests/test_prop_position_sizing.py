"""Property-based tests for Position Sizer.

Uses hypothesis to verify position sizing properties across a wide range
of randomly generated inputs: capital, entry prices, stop losses, and
risk/position-size percentages.

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.7**
"""

from datetime import datetime
from unittest.mock import MagicMock

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.execution.position_sizer import PositionSizer
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
    entry_price: float,
    stop_loss: float,
    side: str = "BUY",
    symbol: str = "RELIANCE",
) -> Signal:
    return Signal(
        signal_id="prop-test-signal",
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
    capital: float,
    risk_pct: float,
    max_pos_pct: float,
) -> Config:
    config = MagicMock(spec=Config)
    config.capital = CapitalConfig(
        total=capital,
        risk_per_trade_pct=risk_pct,
        max_position_size_pct=max_pos_pct,
        max_daily_loss_pct=2.0,
    )
    return config


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating random inputs
# ---------------------------------------------------------------------------

capitals = st.floats(min_value=10_000, max_value=1_000_000, allow_nan=False, allow_infinity=False)
entry_prices = st.floats(min_value=10, max_value=10_000, allow_nan=False, allow_infinity=False)
risk_pcts = st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)
max_pos_pcts = st.floats(min_value=10, max_value=50, allow_nan=False, allow_infinity=False)
# Stop loss offset: positive value subtracted from entry to get stop loss
stop_offsets = st.floats(min_value=0.01, max_value=5000, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 39: Position Size Calculation Formula
# ---------------------------------------------------------------------------

class TestProperty39PositionSizeCalculationFormula:
    """**Validates: Requirements 10.1**

    For any valid signal, quantity = round(min(
        max_risk / risk_per_share,
        max_pos_value / entry_price
    ))
    """

    @given(
        capital=capitals,
        entry_price=entry_prices,
        stop_offset=stop_offsets,
        risk_pct=risk_pcts,
        max_pos_pct=max_pos_pcts,
    )
    @settings(max_examples=100)
    def test_formula_matches_expected(
        self, capital, entry_price, stop_offset, risk_pct, max_pos_pct,
    ):
        stop_loss = entry_price - stop_offset
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        max_risk = capital * risk_pct / 100.0
        max_pos_value = capital * max_pos_pct / 100.0

        raw_qty = max_risk / risk_per_share
        max_qty_by_pos = max_pos_value / entry_price
        expected_qty = round(min(raw_qty, max_qty_by_pos))

        # Skip cases where quantity rounds to 0 (tested by Property 44)
        assume(expected_qty >= 1)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        assert result.is_valid is True
        assert result.quantity == expected_qty


# ---------------------------------------------------------------------------
# Property 40: Maximum Risk Per Trade
# ---------------------------------------------------------------------------

class TestProperty40MaximumRiskPerTrade:
    """**Validates: Requirements 10.2**

    For any valid result, risk_amount <= 1% of capital.
    (More generally, risk_amount <= risk_pct% of capital, but the system
    enforces max 1% via configuration. We test with the configured pct.)
    """

    @given(
        capital=capitals,
        entry_price=entry_prices,
        stop_offset=stop_offsets,
        risk_pct=risk_pcts,
        max_pos_pct=max_pos_pcts,
    )
    @settings(max_examples=100)
    def test_risk_does_not_exceed_limit(
        self, capital, entry_price, stop_offset, risk_pct, max_pos_pct,
    ):
        stop_loss = entry_price - stop_offset
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        if result.is_valid:
            max_risk = capital * risk_pct / 100.0
            # Allow small floating-point tolerance due to rounding
            assert result.risk_amount <= max_risk + risk_per_share, (
                f"risk_amount {result.risk_amount} exceeds max_risk {max_risk} "
                f"(+1 share tolerance {risk_per_share})"
            )


# ---------------------------------------------------------------------------
# Property 41: Maximum Position Size
# ---------------------------------------------------------------------------

class TestProperty41MaximumPositionSize:
    """**Validates: Requirements 10.3**

    For any valid result, position_value <= max_position_size_pct% of capital.
    """

    @given(
        capital=capitals,
        entry_price=entry_prices,
        stop_offset=stop_offsets,
        risk_pct=risk_pcts,
        max_pos_pct=max_pos_pcts,
    )
    @settings(max_examples=100)
    def test_position_value_within_limit(
        self, capital, entry_price, stop_offset, risk_pct, max_pos_pct,
    ):
        stop_loss = entry_price - stop_offset
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        if result.is_valid:
            max_pos_value = capital * max_pos_pct / 100.0
            # Allow tolerance of one share worth due to rounding
            assert result.position_value <= max_pos_value + entry_price, (
                f"position_value {result.position_value} exceeds "
                f"max_pos_value {max_pos_value} (+1 share tolerance {entry_price})"
            )


# ---------------------------------------------------------------------------
# Property 42: Quantity Capping
# ---------------------------------------------------------------------------

class TestProperty42QuantityCapping:
    """**Validates: Requirements 10.4**

    For any valid result, quantity * entry_price <= max_position_value.
    (With rounding tolerance of one share.)
    """

    @given(
        capital=capitals,
        entry_price=entry_prices,
        stop_offset=stop_offsets,
        risk_pct=risk_pcts,
        max_pos_pct=max_pos_pcts,
    )
    @settings(max_examples=100)
    def test_quantity_capped_by_position_value(
        self, capital, entry_price, stop_offset, risk_pct, max_pos_pct,
    ):
        stop_loss = entry_price - stop_offset
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        if result.is_valid:
            max_pos_value = capital * max_pos_pct / 100.0
            # Rounding can push position_value slightly above the cap
            assert result.quantity * entry_price <= max_pos_value + entry_price


# ---------------------------------------------------------------------------
# Property 43: Quantity Rounding
# ---------------------------------------------------------------------------

class TestProperty43QuantityRounding:
    """**Validates: Requirements 10.5**

    For any valid result, quantity is an integer (no fractional shares).
    """

    @given(
        capital=capitals,
        entry_price=entry_prices,
        stop_offset=stop_offsets,
        risk_pct=risk_pcts,
        max_pos_pct=max_pos_pcts,
    )
    @settings(max_examples=100)
    def test_quantity_is_integer(
        self, capital, entry_price, stop_offset, risk_pct, max_pos_pct,
    ):
        stop_loss = entry_price - stop_offset
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        assert isinstance(result.quantity, int), (
            f"quantity should be int, got {type(result.quantity)}"
        )


# ---------------------------------------------------------------------------
# Property 44: Minimum Quantity Rejection
# ---------------------------------------------------------------------------

class TestProperty44MinimumQuantityRejection:
    """**Validates: Requirements 10.7**

    When calculated quantity rounds to 0, result.is_valid is False.
    """

    @given(
        capital=st.floats(min_value=10_000, max_value=50_000, allow_nan=False, allow_infinity=False),
        entry_price=st.floats(min_value=5_000, max_value=10_000, allow_nan=False, allow_infinity=False),
        risk_pct=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False),
        max_pos_pct=st.floats(min_value=10, max_value=20, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_rejected_when_quantity_rounds_to_zero(
        self, capital, entry_price, risk_pct, max_pos_pct,
    ):
        # Use a very wide stop loss so risk_per_share is large, making quantity tiny
        # risk_per_share > max_risk ensures quantity < 1
        max_risk = capital * risk_pct / 100.0
        # Make risk_per_share at least 2x max_risk so raw_qty < 0.5 → rounds to 0
        stop_loss = entry_price - (max_risk * 3)
        risk_per_share = abs(entry_price - stop_loss)
        assume(risk_per_share > 0)

        # Also check position cap doesn't save us
        max_pos_value = capital * max_pos_pct / 100.0
        max_qty_by_pos = max_pos_value / entry_price
        raw_qty = max_risk / risk_per_share
        capped = min(raw_qty, max_qty_by_pos)
        assume(round(capped) < 1)

        signal = _make_signal(entry_price=entry_price, stop_loss=stop_loss)
        sizer = PositionSizer(_make_config(capital, risk_pct, max_pos_pct))
        result = sizer.calculate_quantity(signal)

        assert result.is_valid is False
        assert result.quantity == 0
        assert result.rejection_reason is not None
