"""Property-based tests for Bias Classification Thresholds.

Verifies that the BiasCalculator classifies aggregated bias as
BULLISH (score > 0.2), BEARISH (score < -0.2), or NEUTRAL
(-0.2 ≤ score ≤ 0.2).

**Property 26: Bias Classification Thresholds**
**Validates: Requirements 8.3**

Properties tested:
  1. Any score > 0.2 is classified as BULLISH
  2. Any score < -0.2 is classified as BEARISH
  3. Any score in [-0.2, 0.2] is classified as NEUTRAL
  4. Classification is exhaustive (every score maps to exactly one category)
  5. Boundary values: score == 0.2 is NEUTRAL, score == -0.2 is NEUTRAL
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.bias_calculator import BiasCalculator

VALID_BIASES = {"BULLISH", "BEARISH", "NEUTRAL"}

# Strategies for score ranges
_bullish_score = st.floats(
    min_value=0.2, max_value=1.0,
    allow_nan=False, allow_infinity=False,
    exclude_min=True,
)
_bearish_score = st.floats(
    min_value=-1.0, max_value=-0.2,
    allow_nan=False, allow_infinity=False,
    exclude_max=True,
)
_neutral_score = st.floats(
    min_value=-0.2, max_value=0.2,
    allow_nan=False, allow_infinity=False,
)
_any_score = st.floats(
    min_value=-1.0, max_value=1.0,
    allow_nan=False, allow_infinity=False,
)


class TestBiasClassificationProperties:
    """**Property 26: Bias Classification Thresholds**
    **Validates: Requirements 8.3**
    """

    @given(score=_bullish_score)
    @settings(max_examples=25)
    def test_score_above_threshold_is_bullish(self, score):
        """Any score > 0.2 is classified as BULLISH.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        result = calc._classify(score)
        assert result == "BULLISH", (
            f"Score {score} > 0.2 should be BULLISH, got {result}"
        )

    @given(score=_bearish_score)
    @settings(max_examples=25)
    def test_score_below_threshold_is_bearish(self, score):
        """Any score < -0.2 is classified as BEARISH.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        result = calc._classify(score)
        assert result == "BEARISH", (
            f"Score {score} < -0.2 should be BEARISH, got {result}"
        )

    @given(score=_neutral_score)
    @settings(max_examples=25)
    def test_score_in_neutral_range_is_neutral(self, score):
        """Any score in [-0.2, 0.2] is classified as NEUTRAL.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        result = calc._classify(score)
        assert result == "NEUTRAL", (
            f"Score {score} in [-0.2, 0.2] should be NEUTRAL, got {result}"
        )

    @given(score=_any_score)
    @settings(max_examples=25)
    def test_classification_is_exhaustive(self, score):
        """Every score in [-1.0, 1.0] maps to exactly one of BULLISH,
        BEARISH, or NEUTRAL.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        result = calc._classify(score)
        assert result in VALID_BIASES, (
            f"Score {score} classified as '{result}', expected one of {VALID_BIASES}"
        )

    def test_boundary_upper_is_neutral(self):
        """Boundary: score == 0.2 is classified as NEUTRAL.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        assert calc._classify(0.2) == "NEUTRAL", (
            "Score 0.2 should be NEUTRAL (boundary inclusive)"
        )

    def test_boundary_lower_is_neutral(self):
        """Boundary: score == -0.2 is classified as NEUTRAL.

        **Validates: Requirements 8.3**
        """
        calc = BiasCalculator()
        assert calc._classify(-0.2) == "NEUTRAL", (
            "Score -0.2 should be NEUTRAL (boundary inclusive)"
        )
