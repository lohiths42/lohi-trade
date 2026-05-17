"""Property-based tests for numeric accuracy validation.

**Validates: Requirements 21.4**

Property 20: Numeric accuracy — all numeric values in validated responses
    match source DB values within 0.01 tolerance.
"""

from app.services.chatbot_service import ChatbotService
from hypothesis import given, settings
from hypothesis import strategies as st

# ── Strategies ───────────────────────────────────────────────────────────────

# Finite floats for DB source values
finite_floats = st.floats(
    min_value=-1e9,
    max_value=1e9,
    allow_nan=False,
    allow_infinity=False,
)

# Keys that look like real trading data fields
numeric_keys = st.sampled_from(
    [
        "pnl",
        "price",
        "entry_price",
        "exit_price",
        "quantity",
        "win_rate",
        "sharpe_ratio",
        "total_pnl",
        "avg_profit",
        "best_trade_pnl",
        "worst_trade_pnl",
        "volume",
        "change_pct",
    ]
)

# Dict of numeric key-value pairs representing DB source values
numeric_dict_strategy = st.dictionaries(
    keys=numeric_keys,
    values=finite_floats,
    min_size=1,
    max_size=8,
)

# Small perturbation within default tolerance (±0.01).
# Use ±0.009 to avoid floating-point arithmetic edge cases where
# val + 0.01 produces a result with abs difference slightly > 0.01.
within_tolerance_delta = st.floats(
    min_value=-0.009,
    max_value=0.009,
    allow_nan=False,
    allow_infinity=False,
)

# Perturbation that exceeds default tolerance (> 0.01 in absolute value)
exceeding_tolerance_delta = st.one_of(
    st.floats(min_value=0.02, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1e6, max_value=-0.02, allow_nan=False, allow_infinity=False),
)


# ── Property 20: Numeric accuracy ───────────────────────────────────────────


class TestNumericAccuracyProperty:
    """**Validates: Requirements 21.4**

    Property 20: Numeric accuracy — all numeric values in validated responses
    match source DB values within 0.01 tolerance.
    """

    @given(db_values=numeric_dict_strategy)
    @settings(max_examples=100)
    def test_exact_copies_always_validate_true(self, db_values: dict):
        """Exact copies of DB values always pass numeric accuracy validation."""
        llm_values = dict(db_values)
        assert ChatbotService.validate_numeric_accuracy(llm_values, db_values) is True

    @given(
        db_values=numeric_dict_strategy,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_perturbations_within_tolerance_validate_true(self, db_values: dict, data):
        """For any dict of numeric values, adding perturbations within ±0.01
        to each value causes validate_numeric_accuracy to return True."""
        llm_values = {}
        for key, val in db_values.items():
            delta = data.draw(within_tolerance_delta, label=f"delta_{key}")
            llm_values[key] = val + delta
        assert ChatbotService.validate_numeric_accuracy(llm_values, db_values) is True

    @given(
        db_values=numeric_dict_strategy,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_perturbation_exceeding_tolerance_validates_false(self, db_values: dict, data):
        """For any dict of numeric values, if at least one value has a
        perturbation exceeding tolerance, validate_numeric_accuracy returns False."""
        # Pick one key to perturb beyond tolerance
        target_key = data.draw(st.sampled_from(sorted(db_values.keys())))
        llm_values = dict(db_values)
        delta = data.draw(exceeding_tolerance_delta, label="bad_delta")
        llm_values[target_key] = db_values[target_key] + delta
        assert ChatbotService.validate_numeric_accuracy(llm_values, db_values) is False

    @given(db_values=numeric_dict_strategy)
    @settings(max_examples=100)
    def test_detailed_returns_empty_when_all_match(self, db_values: dict):
        """The detailed version returns an empty list when all values
        are exact copies (within tolerance)."""
        llm_values = dict(db_values)
        result = ChatbotService.validate_numeric_accuracy_detailed(llm_values, db_values)
        assert result == []

    @given(
        db_values=numeric_dict_strategy,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_detailed_returns_discrepancies_when_exceeding(self, db_values: dict, data):
        """The detailed version returns a non-empty list with correct
        discrepancy info when at least one value exceeds tolerance."""
        target_key = data.draw(st.sampled_from(sorted(db_values.keys())))
        llm_values = dict(db_values)
        delta = data.draw(exceeding_tolerance_delta, label="bad_delta")
        llm_values[target_key] = db_values[target_key] + delta

        result = ChatbotService.validate_numeric_accuracy_detailed(llm_values, db_values)
        assert len(result) >= 1

        # The target key must appear in discrepancies
        reported_keys = [d["key"] for d in result]
        assert target_key in reported_keys

        # Each discrepancy has the correct structure
        for disc in result:
            assert "key" in disc
            assert "llm_value" in disc
            assert "db_value" in disc
            assert "difference" in disc
            assert disc["difference"] > 0.01
