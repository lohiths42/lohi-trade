"""Property-based tests for price discrepancy detection between NSE and BSE.

**Property 18: Price discrepancy detection** — dual-listed securities with
>0.5% price difference between NSE and BSE are always flagged.

**Validates: Requirements 26.5**

Uses Hypothesis to generate random price pairs and verify:
- Prices with >0.5% difference are always flagged (True)
- Prices with <=0.5% difference are never flagged (False)
- Zero or negative prices always return False
"""

from unittest.mock import MagicMock

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.ingestion.market_data_collector import MarketDataCollector

# ── Helpers ───────────────────────────────────────────────────────

THRESHOLD = 0.005  # 0.5%

# Small margin to stay clear of floating-point boundary ambiguity
_MARGIN = 1e-9

NSE_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "WIPRO",
]

symbol_strategy = st.sampled_from(NSE_SYMBOLS)

base_price = st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False)


def _make_collector() -> MarketDataCollector:
    """Create a MarketDataCollector with a mock EventBus."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="1234567890-0")
    return MarketDataCollector(event_bus=bus)


# ── Strategies ────────────────────────────────────────────────────
# The discrepancy formula is: abs(nse - bse) / nse
# So we generate bse as nse * (1 + offset) or nse * (1 - offset)
# to directly control the percentage difference relative to nse.


@st.composite
def large_discrepancy_prices(draw):
    """Generate (nse_price, bse_price) where abs(nse-bse)/nse > 0.5%."""
    nse = draw(base_price)
    # offset > THRESHOLD guarantees discrepancy > 0.5%
    offset = draw(st.floats(
        min_value=THRESHOLD + _MARGIN,
        max_value=2.0,
        allow_nan=False,
        allow_infinity=False,
    ))
    above = draw(st.booleans())
    bse = nse * (1.0 + offset) if above else nse * (1.0 - offset)
    assume(bse > 0)
    # Verify the property holds (guards against FP surprises)
    assume(abs(nse - bse) / nse > THRESHOLD)
    return (nse, bse)


@st.composite
def small_discrepancy_prices(draw):
    """Generate (nse_price, bse_price) where abs(nse-bse)/nse <= 0.5%."""
    nse = draw(base_price)
    # offset in [0, THRESHOLD - margin] keeps difference within threshold
    offset = draw(st.floats(
        min_value=0.0,
        max_value=THRESHOLD - _MARGIN,
        allow_nan=False,
        allow_infinity=False,
    ))
    above = draw(st.booleans())
    bse = nse * (1.0 + offset) if above else nse * (1.0 - offset)
    assume(bse > 0)
    # Verify the property holds (guards against FP surprises)
    assume(abs(nse - bse) / nse <= THRESHOLD)
    return (nse, bse)


# ── Property 18: Price discrepancy detection ──────────────────────


@given(
    symbol=symbol_strategy,
    prices=large_discrepancy_prices(),
)
@settings(max_examples=25)
def test_large_discrepancy_always_flagged(symbol, prices):
    """Prices with >0.5% difference are always flagged as discrepant.

    **Validates: Requirements 26.5**
    """
    nse_price, bse_price = prices
    collector = _make_collector()
    result = collector.detect_price_discrepancy(symbol, nse_price, bse_price)

    assert result is True, (
        f"Expected True for {symbol}: NSE={nse_price}, BSE={bse_price}, "
        f"diff={abs(nse_price - bse_price) / nse_price * 100:.4f}%"
    )


@given(
    symbol=symbol_strategy,
    prices=small_discrepancy_prices(),
)
@settings(max_examples=25)
def test_small_discrepancy_never_flagged(symbol, prices):
    """Prices with <=0.5% difference are never flagged.

    **Validates: Requirements 26.5**
    """
    nse_price, bse_price = prices
    collector = _make_collector()
    result = collector.detect_price_discrepancy(symbol, nse_price, bse_price)

    assert result is False, (
        f"Expected False for {symbol}: NSE={nse_price}, BSE={bse_price}, "
        f"diff={abs(nse_price - bse_price) / nse_price * 100:.4f}%"
    )


@given(
    symbol=symbol_strategy,
    nse_price=st.floats(min_value=-10_000.0, max_value=0.0, allow_nan=False, allow_infinity=False),
    bse_price=st.floats(min_value=0.01, max_value=50_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=25)
def test_zero_or_negative_nse_price_returns_false(symbol, nse_price, bse_price):
    """Zero or negative NSE price always returns False.

    **Validates: Requirements 26.5**
    """
    collector = _make_collector()
    result = collector.detect_price_discrepancy(symbol, nse_price, bse_price)

    assert result is False, (
        f"Expected False for non-positive NSE price: {nse_price}"
    )


@given(
    symbol=symbol_strategy,
    nse_price=st.floats(min_value=0.01, max_value=50_000.0, allow_nan=False, allow_infinity=False),
    bse_price=st.floats(min_value=-10_000.0, max_value=0.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=25)
def test_zero_or_negative_bse_price_returns_false(symbol, nse_price, bse_price):
    """Zero or negative BSE price always returns False.

    **Validates: Requirements 26.5**
    """
    collector = _make_collector()
    result = collector.detect_price_discrepancy(symbol, nse_price, bse_price)

    assert result is False, (
        f"Expected False for non-positive BSE price: {bse_price}"
    )
