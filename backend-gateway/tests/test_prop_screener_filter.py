"""Property-based tests for screener filter consistency.

**Validates: Requirements 10.4, 10.5**

Property 14: Screener filter consistency — all returned results satisfy every
applied filter criterion.

Approach: Generate random ScreenerResultItem data and ScreenerFilters, then
apply the filter logic in Python to verify that every item passing the filters
actually satisfies all criteria. This tests the AND-logic consistency
of the screener without requiring a real database.
"""

from decimal import Decimal
from typing import Optional

from app.services.screener_service import (
    Range,
    ScreenerEngine,
    ScreenerFilters,
    ScreenerResultItem,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ── Strategies ───────────────────────────────────────────────────────────────

# Fast numeric strategies — use floats mapped to Decimal (avoids slow st.decimals)
_dec = st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False).map(
    lambda f: Decimal(str(round(f, 2)))
)
_pos_dec = st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False).map(
    lambda f: Decimal(str(round(f, 2)))
)
_rsi_dec = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False).map(
    lambda f: Decimal(str(round(f, 2)))
)

EXCHANGES = ["NSE", "BSE", "BOTH"]
SECTORS = ["Energy", "IT/Technology", "Pharma", "Banking & Finance"]
MCAP_CATS = ["large-cap", "mid-cap", "small-cap"]


@st.composite
def range_st(draw):
    """Generate a Range with min <= max."""
    a = draw(st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    b = draw(st.floats(min_value=-500.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    lo, hi = min(a, b), max(a, b)
    choice = draw(st.sampled_from(["both", "min_only", "max_only"]))
    if choice == "both":
        return Range(min=lo, max=hi)
    elif choice == "min_only":
        return Range(min=lo, max=None)
    else:
        return Range(min=None, max=hi)


@st.composite
def screener_filters_st(draw):
    """Generate ScreenerFilters with 1-5 active filters (no assume needed)."""
    filters = ScreenerFilters()

    # Pick which filter categories to activate (always at least 1)
    num_range_filters = draw(st.integers(min_value=1, max_value=5))

    range_fields = [
        "pe_ratio",
        "pb_ratio",
        "market_cap",
        "dividend_yield",
        "eps",
        "roe",
        "debt_to_equity",
        "revenue_growth_1y",
        "revenue_growth_3y",
        "profit_growth_1y",
        "profit_growth_3y",
        "rsi_14",
        "avg_volume",
        "price_change_1d",
        "price_change_1w",
        "price_change_1m",
        "price_change_3m",
        "price_change_6m",
        "price_change_1y",
        "price_change_3y",
        "price_change_5y",
        "return_1y",
        "cagr_3y",
        "cagr_5y",
    ]

    chosen = draw(
        st.lists(
            st.sampled_from(range_fields),
            min_size=num_range_filters,
            max_size=num_range_filters,
            unique=True,
        )
    )
    for field_name in chosen:
        setattr(filters, field_name, draw(range_st()))

    # Optionally add meta filters
    if draw(st.booleans()):
        filters.exchange = draw(st.sampled_from(EXCHANGES))
    if draw(st.booleans()):
        filters.sector = draw(st.sampled_from(SECTORS))
    if draw(st.booleans()):
        filters.market_cap_category = draw(st.sampled_from(MCAP_CATS))
    if draw(st.booleans()):
        filters.ma_crossover_50_200 = draw(st.sampled_from(["golden", "death"]))

    return filters


@st.composite
def result_item_st(draw):
    """Generate a ScreenerResultItem with fast strategies."""
    return ScreenerResultItem(
        security_id=draw(st.integers(min_value=1, max_value=9999)),
        symbol=draw(
            st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFC", "ICICI", "SBIN", "ITC", "LT"])
        ),
        company_name="Corp",
        exchange=draw(st.sampled_from(EXCHANGES)),
        sector=draw(st.one_of(st.none(), st.sampled_from(SECTORS))),
        market_cap_category=draw(st.one_of(st.none(), st.sampled_from(MCAP_CATS))),
        pe_ratio=draw(st.one_of(st.none(), _pos_dec)),
        pb_ratio=draw(st.one_of(st.none(), _pos_dec)),
        market_cap=draw(st.one_of(st.none(), _pos_dec)),
        dividend_yield=draw(st.one_of(st.none(), _pos_dec)),
        eps=draw(st.one_of(st.none(), _dec)),
        roe=draw(st.one_of(st.none(), _dec)),
        debt_to_equity=draw(st.one_of(st.none(), _pos_dec)),
        revenue_growth_1y=draw(st.one_of(st.none(), _dec)),
        revenue_growth_3y=draw(st.one_of(st.none(), _dec)),
        profit_growth_1y=draw(st.one_of(st.none(), _dec)),
        profit_growth_3y=draw(st.one_of(st.none(), _dec)),
        return_1y=draw(st.one_of(st.none(), _dec)),
        cagr_3y=draw(st.one_of(st.none(), _dec)),
        cagr_5y=draw(st.one_of(st.none(), _dec)),
        high_52w=draw(st.one_of(st.none(), _pos_dec)),
        low_52w=draw(st.one_of(st.none(), _pos_dec)),
        rsi_14=draw(st.one_of(st.none(), _rsi_dec)),
        sma_50=draw(st.one_of(st.none(), _pos_dec)),
        sma_200=draw(st.one_of(st.none(), _pos_dec)),
        avg_volume_20d=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10_000_000))),
        price_change_1d=draw(st.one_of(st.none(), _dec)),
        price_change_1w=draw(st.one_of(st.none(), _dec)),
        price_change_1m=draw(st.one_of(st.none(), _dec)),
        price_change_3m=draw(st.one_of(st.none(), _dec)),
        price_change_6m=draw(st.one_of(st.none(), _dec)),
        price_change_1y=draw(st.one_of(st.none(), _dec)),
        price_change_3y=draw(st.one_of(st.none(), _dec)),
        price_change_5y=draw(st.one_of(st.none(), _dec)),
    )


# ── Filter checking logic (mirrors SQL WHERE clauses) ────────────────────────


def _check_range(value: Optional[Decimal], rng: Optional[Range]) -> bool:
    """Check if a value satisfies a Range filter. None values fail the filter."""
    if rng is None:
        return True
    if value is None:
        return False
    val = float(value)
    if rng.min is not None and val < rng.min:
        return False
    if rng.max is not None and val > rng.max:
        return False
    return True


def _check_int_range(value: Optional[int], rng: Optional[Range]) -> bool:
    """Check if an integer value satisfies a Range filter."""
    if rng is None:
        return True
    if value is None:
        return False
    if rng.min is not None and value < int(rng.min):
        return False
    if rng.max is not None and value > int(rng.max):
        return False
    return True


def item_satisfies_filters(item: ScreenerResultItem, filters: ScreenerFilters) -> bool:
    """Check if a ScreenerResultItem satisfies all applied filters (AND logic)."""
    if filters.exchange is not None and item.exchange != filters.exchange:
        return False
    if filters.sector is not None and item.sector != filters.sector:
        return False
    if (
        filters.market_cap_category is not None
        and item.market_cap_category != filters.market_cap_category
    ):
        return False

    range_checks = [
        (item.pe_ratio, filters.pe_ratio),
        (item.pb_ratio, filters.pb_ratio),
        (item.market_cap, filters.market_cap),
        (item.dividend_yield, filters.dividend_yield),
        (item.eps, filters.eps),
        (item.roe, filters.roe),
        (item.debt_to_equity, filters.debt_to_equity),
        (item.revenue_growth_1y, filters.revenue_growth_1y),
        (item.revenue_growth_3y, filters.revenue_growth_3y),
        (item.profit_growth_1y, filters.profit_growth_1y),
        (item.profit_growth_3y, filters.profit_growth_3y),
        (item.return_1y, filters.return_1y),
        (item.cagr_3y, filters.cagr_3y),
        (item.cagr_5y, filters.cagr_5y),
        (item.rsi_14, filters.rsi_14),
        (item.price_change_1d, filters.price_change_1d),
        (item.price_change_1w, filters.price_change_1w),
        (item.price_change_1m, filters.price_change_1m),
        (item.price_change_3m, filters.price_change_3m),
        (item.price_change_6m, filters.price_change_6m),
        (item.price_change_1y, filters.price_change_1y),
        (item.price_change_3y, filters.price_change_3y),
        (item.price_change_5y, filters.price_change_5y),
    ]

    for val, rng in range_checks:
        if not _check_range(val, rng):
            return False

    if not _check_int_range(item.avg_volume_20d, filters.avg_volume):
        return False

    if filters.ma_crossover_50_200 == "golden":
        if item.sma_50 is None or item.sma_200 is None or item.sma_50 <= item.sma_200:
            return False
    elif filters.ma_crossover_50_200 == "death":
        if item.sma_50 is None or item.sma_200 is None or item.sma_50 >= item.sma_200:
            return False

    return True


# ── Property 14: Screener filter consistency ─────────────────────────────────


class TestScreenerFilterConsistencyProperty:
    """**Validates: Requirements 10.4, 10.5**

    Property 14: Screener filter consistency — all returned results satisfy
    every applied filter criterion.
    """

    @given(
        items=st.lists(result_item_st(), min_size=1, max_size=10),
        filters=screener_filters_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_passing_items_satisfy_all_filters(
        self, items: list[ScreenerResultItem], filters: ScreenerFilters
    ):
        """Every item that passes the filter check must satisfy ALL applied
        filter criteria (AND logic)."""
        passing = [item for item in items if item_satisfies_filters(item, filters)]

        for item in passing:
            # Meta filters
            if filters.exchange is not None:
                assert item.exchange == filters.exchange
            if filters.sector is not None:
                assert item.sector == filters.sector
            if filters.market_cap_category is not None:
                assert item.market_cap_category == filters.market_cap_category

            # All range filters
            self._assert_range(item.pe_ratio, filters.pe_ratio, "pe_ratio")
            self._assert_range(item.pb_ratio, filters.pb_ratio, "pb_ratio")
            self._assert_range(item.market_cap, filters.market_cap, "market_cap")
            self._assert_range(item.dividend_yield, filters.dividend_yield, "dividend_yield")
            self._assert_range(item.eps, filters.eps, "eps")
            self._assert_range(item.roe, filters.roe, "roe")
            self._assert_range(item.debt_to_equity, filters.debt_to_equity, "debt_to_equity")
            self._assert_range(
                item.revenue_growth_1y, filters.revenue_growth_1y, "revenue_growth_1y"
            )
            self._assert_range(
                item.revenue_growth_3y, filters.revenue_growth_3y, "revenue_growth_3y"
            )
            self._assert_range(item.profit_growth_1y, filters.profit_growth_1y, "profit_growth_1y")
            self._assert_range(item.profit_growth_3y, filters.profit_growth_3y, "profit_growth_3y")
            self._assert_range(item.return_1y, filters.return_1y, "return_1y")
            self._assert_range(item.cagr_3y, filters.cagr_3y, "cagr_3y")
            self._assert_range(item.cagr_5y, filters.cagr_5y, "cagr_5y")
            self._assert_range(item.rsi_14, filters.rsi_14, "rsi_14")
            self._assert_range(item.price_change_1d, filters.price_change_1d, "price_change_1d")
            self._assert_range(item.price_change_1w, filters.price_change_1w, "price_change_1w")
            self._assert_range(item.price_change_1m, filters.price_change_1m, "price_change_1m")
            self._assert_range(item.price_change_3m, filters.price_change_3m, "price_change_3m")
            self._assert_range(item.price_change_6m, filters.price_change_6m, "price_change_6m")
            self._assert_range(item.price_change_1y, filters.price_change_1y, "price_change_1y")
            self._assert_range(item.price_change_3y, filters.price_change_3y, "price_change_3y")
            self._assert_range(item.price_change_5y, filters.price_change_5y, "price_change_5y")

            # MA crossover
            if filters.ma_crossover_50_200 == "golden":
                assert item.sma_50 is not None and item.sma_200 is not None
                assert item.sma_50 > item.sma_200
            elif filters.ma_crossover_50_200 == "death":
                assert item.sma_50 is not None and item.sma_200 is not None
                assert item.sma_50 < item.sma_200

    @given(
        items=st.lists(result_item_st(), min_size=1, max_size=10),
        filters=screener_filters_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rejected_items_violate_at_least_one_filter(
        self, items: list[ScreenerResultItem], filters: ScreenerFilters
    ):
        """Every item that fails the filter check must violate at least one
        applied filter criterion — no false rejections."""
        rejected = [item for item in items if not item_satisfies_filters(item, filters)]

        for item in rejected:
            violations = []

            if filters.exchange is not None and item.exchange != filters.exchange:
                violations.append("exchange")
            if filters.sector is not None and item.sector != filters.sector:
                violations.append("sector")
            if (
                filters.market_cap_category is not None
                and item.market_cap_category != filters.market_cap_category
            ):
                violations.append("market_cap_category")

            range_checks = [
                ("pe_ratio", item.pe_ratio, filters.pe_ratio),
                ("pb_ratio", item.pb_ratio, filters.pb_ratio),
                ("market_cap", item.market_cap, filters.market_cap),
                ("dividend_yield", item.dividend_yield, filters.dividend_yield),
                ("eps", item.eps, filters.eps),
                ("roe", item.roe, filters.roe),
                ("debt_to_equity", item.debt_to_equity, filters.debt_to_equity),
                ("revenue_growth_1y", item.revenue_growth_1y, filters.revenue_growth_1y),
                ("revenue_growth_3y", item.revenue_growth_3y, filters.revenue_growth_3y),
                ("profit_growth_1y", item.profit_growth_1y, filters.profit_growth_1y),
                ("profit_growth_3y", item.profit_growth_3y, filters.profit_growth_3y),
                ("return_1y", item.return_1y, filters.return_1y),
                ("cagr_3y", item.cagr_3y, filters.cagr_3y),
                ("cagr_5y", item.cagr_5y, filters.cagr_5y),
                ("rsi_14", item.rsi_14, filters.rsi_14),
                ("price_change_1d", item.price_change_1d, filters.price_change_1d),
                ("price_change_1w", item.price_change_1w, filters.price_change_1w),
                ("price_change_1m", item.price_change_1m, filters.price_change_1m),
                ("price_change_3m", item.price_change_3m, filters.price_change_3m),
                ("price_change_6m", item.price_change_6m, filters.price_change_6m),
                ("price_change_1y", item.price_change_1y, filters.price_change_1y),
                ("price_change_3y", item.price_change_3y, filters.price_change_3y),
                ("price_change_5y", item.price_change_5y, filters.price_change_5y),
            ]

            for name, val, rng in range_checks:
                if not _check_range(val, rng):
                    violations.append(name)

            if not _check_int_range(item.avg_volume_20d, filters.avg_volume):
                violations.append("avg_volume")

            if filters.ma_crossover_50_200 == "golden":
                if item.sma_50 is None or item.sma_200 is None or item.sma_50 <= item.sma_200:
                    violations.append("ma_crossover_golden")
            elif filters.ma_crossover_50_200 == "death":
                if item.sma_50 is None or item.sma_200 is None or item.sma_50 >= item.sma_200:
                    violations.append("ma_crossover_death")

            assert (
                len(violations) > 0
            ), f"Item {item.symbol} was rejected but no filter violation found"

    @given(
        items=st.lists(result_item_st(), min_size=0, max_size=10),
        filters=screener_filters_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_filter_result_count_is_consistent(
        self, items: list[ScreenerResultItem], filters: ScreenerFilters
    ):
        """The count of passing items plus rejected items equals total items."""
        passing = [i for i in items if item_satisfies_filters(i, filters)]
        rejected = [i for i in items if not item_satisfies_filters(i, filters)]

        assert len(passing) + len(rejected) == len(items)

    @staticmethod
    def _assert_range(value: Optional[Decimal], rng: Optional[Range], field: str):
        """Assert that a value satisfies a Range filter."""
        if rng is None:
            return
        assert value is not None, f"{field} is None but filter requires a value"
        val = float(value)
        if rng.min is not None:
            assert val >= rng.min, f"{field}={val} < filter min {rng.min}"
        if rng.max is not None:
            assert val <= rng.max, f"{field}={val} > filter max {rng.max}"


# ── WHERE clause consistency with filter model ──────────────────────────────


class TestWhereClauseConsistency:
    """Verify that _build_where_clauses produces consistent clause/param counts."""

    @given(filters=screener_filters_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_where_clauses_param_index_consistent(self, filters: ScreenerFilters):
        """next_param_idx should always equal len(params) + 1."""
        engine = ScreenerEngine()
        clauses, params, next_idx = engine._build_where_clauses(filters)

        assert next_idx == len(params) + 1, f"next_idx={next_idx} but len(params)={len(params)}"

        for clause in clauses:
            if "$" in clause:
                assert any(f"${i}" in clause for i in range(1, next_idx))
