"""
Tests for the Strategy Engine interface and Signal dataclass.

Validates:
- Signal dataclass creation and field correctness
- create_signal factory function
- Strategy ABC cannot be instantiated directly
- Concrete strategy subclass must implement all abstract methods
"""

import uuid
from datetime import datetime
from typing import Optional

import pandas as pd
import pytest

from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal, Strategy, create_signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_indicator_set(symbol: str = "RELIANCE") -> IndicatorSet:
    """Create a minimal IndicatorSet for testing."""
    return IndicatorSet(
        symbol=symbol,
        timeframe="5m",
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        rsi_14=35.0,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=110.0,
        bb_middle=100.0,
        bb_lower=90.0,
        vwap=99.0,
        ema_9=101.0,
        ema_21=100.0,
        supertrend=95.0,
        supertrend_direction=1,
        atr_14=3.0,
        volume_avg_20=50000.0,
    )


class _DummyStrategy(Strategy):
    """Concrete strategy for testing the ABC contract."""

    def __init__(self, is_enabled: bool = True) -> None:
        self._enabled = is_enabled

    @property
    def name(self) -> str:
        return "DummyStrategy"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def generate_signal(
        self, indicators: IndicatorSet, candles: pd.DataFrame
    ) -> Optional[Signal]:
        # Always returns None — just proves the interface works
        return None


class _IncompleteStrategy(Strategy):
    """Strategy that only implements 'name' — should fail to instantiate."""

    @property
    def name(self) -> str:
        return "Incomplete"


# ---------------------------------------------------------------------------
# Signal dataclass tests
# ---------------------------------------------------------------------------

class TestSignal:
    def test_signal_fields(self):
        ind = _make_indicator_set()
        ts = datetime(2024, 1, 15, 10, 5, 0)
        sig = Signal(
            signal_id="abc-123",
            symbol="RELIANCE",
            strategy="MeanReversion",
            side="BUY",
            entry_price=100.0,
            stop_loss=95.5,
            target=105.0,
            quantity=40,
            timestamp=ts,
            indicators=ind,
        )

        assert sig.signal_id == "abc-123"
        assert sig.symbol == "RELIANCE"
        assert sig.strategy == "MeanReversion"
        assert sig.side == "BUY"
        assert sig.entry_price == 100.0
        assert sig.stop_loss == 95.5
        assert sig.target == 105.0
        assert sig.quantity == 40
        assert sig.timestamp == ts
        assert sig.indicators is ind

    def test_signal_sell_side(self):
        ind = _make_indicator_set()
        sig = Signal(
            signal_id="def-456",
            symbol="TCS",
            strategy="TrendFollowing",
            side="SELL",
            entry_price=3500.0,
            stop_loss=3550.0,
            target=3400.0,
            quantity=10,
            timestamp=datetime.now(),
            indicators=ind,
        )
        assert sig.side == "SELL"
        assert sig.stop_loss > sig.entry_price  # stop above entry for SELL


# ---------------------------------------------------------------------------
# create_signal factory tests
# ---------------------------------------------------------------------------

class TestCreateSignal:
    def test_creates_valid_signal(self):
        ind = _make_indicator_set()
        sig = create_signal(
            symbol="INFY",
            strategy="ORB",
            side="BUY",
            entry_price=1500.0,
            stop_loss=1480.0,
            target=1530.0,
            indicators=ind,
        )

        assert sig.symbol == "INFY"
        assert sig.strategy == "ORB"
        assert sig.side == "BUY"
        assert sig.entry_price == 1500.0
        assert sig.stop_loss == 1480.0
        assert sig.target == 1530.0
        assert sig.quantity == 0  # default, set by Position Sizer later
        # UUID format check
        uuid.UUID(sig.signal_id)  # raises if invalid

    def test_auto_generates_uuid(self):
        ind = _make_indicator_set()
        sig1 = create_signal("A", "S", "BUY", 100, 95, 110, ind)
        sig2 = create_signal("A", "S", "BUY", 100, 95, 110, ind)
        assert sig1.signal_id != sig2.signal_id

    def test_custom_timestamp(self):
        ind = _make_indicator_set()
        ts = datetime(2024, 6, 1, 12, 0, 0)
        sig = create_signal("X", "S", "SELL", 200, 210, 180, ind, timestamp=ts)
        assert sig.timestamp == ts

    def test_default_timestamp_is_recent(self):
        ind = _make_indicator_set()
        before = datetime.now()
        sig = create_signal("X", "S", "BUY", 100, 95, 110, ind)
        after = datetime.now()
        assert before <= sig.timestamp <= after

    def test_invalid_side_raises(self):
        ind = _make_indicator_set()
        with pytest.raises(ValueError, match="Invalid side"):
            create_signal("X", "S", "HOLD", 100, 95, 110, ind)


# ---------------------------------------------------------------------------
# Strategy ABC tests
# ---------------------------------------------------------------------------

class TestStrategyABC:
    def test_cannot_instantiate_abc_directly(self):
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_concrete_strategy_works(self):
        strat = _DummyStrategy()
        assert strat.name == "DummyStrategy"
        assert strat.enabled is True

        ind = _make_indicator_set()
        df = pd.DataFrame({"close": [100.0]})
        result = strat.generate_signal(ind, df)
        assert result is None

    def test_enabled_flag(self):
        strat = _DummyStrategy(is_enabled=False)
        assert strat.enabled is False

    def test_incomplete_strategy_cannot_instantiate(self):
        with pytest.raises(TypeError):
            _IncompleteStrategy()  # type: ignore[abstract]
