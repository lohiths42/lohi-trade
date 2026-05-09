"""
Property-based tests for corporate action adjustments.

**Property 17: Corporate action round-trip** — applying adjustments then
reverting produces original raw data for all securities with corporate actions.

**Validates: Requirements 28.7**

Uses Hypothesis to generate random OHLCV bars and corporate actions (SPLIT
and BONUS with various ratios and ex-dates), then verifies the round-trip
property: adjust → revert recovers the original data within floating-point
tolerance.
"""

from datetime import date, timedelta

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.ingestion.corporate_actions_collector import (
    CorporateAction,
    CorporateActionType,
)
from src.ingestion.historical_data_service import (
    HistoricalDataService,
    OHLCV,
)


# ── Strategies ────────────────────────────────────────────────────

# Reasonable positive prices (avoid extremes that cause float issues)
price_st = st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)

volume_st = st.integers(min_value=0, max_value=10_000_000)

date_st = st.dates(min_value=date(2010, 1, 1), max_value=date(2025, 12, 31))

symbol_st = st.sampled_from([
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "WIPRO",
])


def ohlcv_bar_st(symbol=None, bar_date=None):
    """Strategy for a single OHLCV bar."""
    return st.builds(
        OHLCV,
        symbol=symbol if symbol is not None else symbol_st,
        date=bar_date if bar_date is not None else date_st,
        open=price_st,
        high=price_st,
        low=price_st,
        close=price_st,
        volume=volume_st,
    )


# Positive integers for ratio parts (avoid zero which makes factor None)
ratio_part_st = st.integers(min_value=1, max_value=100)

action_type_st = st.sampled_from([CorporateActionType.SPLIT, CorporateActionType.BONUS])


def corporate_action_st(symbol=None):
    """Strategy for a single corporate action (SPLIT or BONUS) with valid ratio."""
    return st.builds(
        lambda sym, atype, ex, left, right: CorporateAction(
            symbol=sym,
            action_type=atype,
            ex_date=ex,
            details={"ratio": f"{left}:{right}"},
        ),
        sym=symbol if symbol is not None else symbol_st,
        atype=action_type_st,
        ex=date_st,
        left=ratio_part_st,
        right=ratio_part_st,
    )


# Generate a list of bars for a single symbol with unique dates
def bars_for_symbol_st(symbol):
    """Strategy for a list of OHLCV bars for a given symbol with unique dates."""
    return st.lists(
        ohlcv_bar_st(symbol=st.just(symbol)),
        min_size=1,
        max_size=20,
    ).map(lambda bars: _deduplicate_bars_by_date(bars))


def _deduplicate_bars_by_date(bars):
    """Keep only one bar per date."""
    seen = set()
    result = []
    for b in bars:
        if b.date not in seen:
            seen.add(b.date)
            result.append(b)
    return result


# ── Property 17: Corporate action round-trip ──────────────────────

class TestCorporateActionRoundTrip:
    """
    **Property 17: Corporate action round-trip**

    Applying adjustments then reverting produces original raw data for all
    securities with corporate actions.

    **Validates: Requirements 28.7**
    """

    @given(
        bars=bars_for_symbol_st("RELIANCE"),
        actions=st.lists(
            corporate_action_st(symbol=st.just("RELIANCE")),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_adjust_then_revert_is_identity(self, bars, actions):
        """
        For any set of OHLCV bars and corporate actions, applying
        adjust_for_corporate_actions then revert_adjustments recovers
        the original prices within floating-point tolerance.

        **Validates: Requirements 28.7**
        """
        assume(len(bars) > 0)

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        reverted = HistoricalDataService.revert_adjustments(adjusted, actions)

        assert len(reverted) == len(bars)
        for orig, rev in zip(bars, reverted):
            assert rev.symbol == orig.symbol
            assert rev.date == orig.date
            assert rev.volume == orig.volume
            assert rev.open == pytest.approx(orig.open, rel=1e-6)
            assert rev.high == pytest.approx(orig.high, rel=1e-6)
            assert rev.low == pytest.approx(orig.low, rel=1e-6)
            assert rev.close == pytest.approx(orig.close, rel=1e-6)

    @given(
        symbol=symbol_st,
        bars_data=st.lists(
            st.tuples(date_st, price_st, price_st, price_st, price_st, volume_st),
            min_size=1,
            max_size=15,
        ),
        actions=st.lists(
            corporate_action_st(),
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_round_trip_various_symbols(self, symbol, bars_data, actions):
        """
        Round-trip holds for any symbol, including when actions list is empty
        (which should return a copy of the original data).

        **Validates: Requirements 28.7**
        """
        # Build bars with unique dates for the symbol
        seen_dates = set()
        bars = []
        for d, o, h, l, c, v in bars_data:
            if d not in seen_dates:
                seen_dates.add(d)
                bars.append(OHLCV(symbol=symbol, date=d, open=o, high=h, low=l, close=c, volume=v))
        assume(len(bars) > 0)

        # Make actions match the symbol
        matched_actions = [
            CorporateAction(
                symbol=symbol,
                action_type=a.action_type,
                ex_date=a.ex_date,
                details=a.details,
            )
            for a in actions
        ]

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, matched_actions)
        reverted = HistoricalDataService.revert_adjustments(adjusted, matched_actions)

        assert len(reverted) == len(bars)
        for orig, rev in zip(bars, reverted):
            assert rev.open == pytest.approx(orig.open, rel=1e-6)
            assert rev.high == pytest.approx(orig.high, rel=1e-6)
            assert rev.low == pytest.approx(orig.low, rel=1e-6)
            assert rev.close == pytest.approx(orig.close, rel=1e-6)

    @given(
        bars=bars_for_symbol_st("TCS"),
    )
    @settings(max_examples=25, deadline=None)
    def test_empty_actions_returns_copy(self, bars):
        """
        With no corporate actions, adjust and revert both return exact copies.

        **Validates: Requirements 28.7**
        """
        assume(len(bars) > 0)

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, [])
        reverted = HistoricalDataService.revert_adjustments(adjusted, [])

        assert len(reverted) == len(bars)
        for orig, rev in zip(bars, reverted):
            assert rev.open == orig.open
            assert rev.high == orig.high
            assert rev.low == orig.low
            assert rev.close == orig.close
            assert rev.volume == orig.volume
            # Must be a copy, not the same object
            assert rev is not orig
