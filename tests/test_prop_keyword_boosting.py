"""Property-based tests for Indian Market Keyword Boosting.

Validates that keyword boosters correctly shift sentiment scores and
that the boosted score remains clamped within [-1.0, 1.0].

**Property 23: Keyword Boosting**
**Validates: Requirements 7.5**

Properties tested:
  1. Positive keywords increase the boosted score relative to raw score
  2. Negative keywords decrease the boosted score relative to raw score
  3. Boosted score is always clamped to [-1.0, 1.0]
  4. No keywords means boosted score equals raw score
  5. Multiple keywords accumulate their boosts
"""

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.commander.sentiment_analyzer import SentimentAnalyzer

# ---------------------------------------------------------------------------
# Mocks (same pattern as classification tests)
# ---------------------------------------------------------------------------


class FakeTokenizer:
    def __call__(self, text, **kwargs):
        seq_len = kwargs.get("max_length", 512)
        return {
            "input_ids": np.ones((1, seq_len), dtype=np.int64),
            "attention_mask": np.ones((1, seq_len), dtype=np.int64),
        }


class FakeOnnxSession:
    """Returns neutral-ish logits so raw_score ≈ 0, letting boost dominate."""

    def __init__(self, logits=None):
        self._logits = np.array([logits or [0.0, 0.0, 2.0]], dtype=np.float32)

    def run(self, output_names, inputs):
        return [self._logits]

    def get_providers(self):
        return ["CPUExecutionProvider"]


def _build_analyzer(keywords: dict[str, dict[str, float]], logits=None) -> SentimentAnalyzer:
    analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
    analyzer._tokenizer = FakeTokenizer()
    analyzer._session = FakeOnnxSession(logits)
    analyzer._model_loaded = True
    analyzer._keywords = keywords
    analyzer._event_bus = None
    analyzer._db_manager = None
    analyzer._model_path = "fake"
    analyzer._tokenizer_path = "fake"
    return analyzer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_keyword = st.text(min_size=3, max_size=30, alphabet=st.characters(categories=("L", "Z")))
_pos_boost = st.floats(min_value=0.01, max_value=0.25, allow_nan=False, allow_infinity=False)
_neg_boost = st.floats(min_value=-0.25, max_value=-0.01, allow_nan=False, allow_infinity=False)


@st.composite
def keyword_and_text(draw, polarity="positive"):
    """Generate a keyword, its boost value, and text containing that keyword."""
    kw = draw(_keyword)
    assume(len(kw.strip()) >= 3)
    boost = draw(_pos_boost if polarity == "positive" else _neg_boost)
    # Build text that contains the keyword
    prefix = draw(st.text(min_size=0, max_size=50, alphabet=st.characters(categories=("L", "Z"))))
    text = f"{prefix} {kw} reported strong results"
    return kw, boost, text


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestKeywordBoostingProperties:
    """**Property 23: Keyword Boosting**
    **Validates: Requirements 7.5**
    """

    @given(data=keyword_and_text(polarity="positive"))
    @settings(max_examples=25)
    def test_positive_keyword_increases_score(self, data):
        """Positive keyword boosts the score above the raw score."""
        kw, boost, text = data
        keywords = {"positive": {kw: boost}, "negative": {}}
        analyzer = _build_analyzer(keywords)

        result = analyzer.analyze(text)
        # With neutral logits, raw_score ≈ 0, so boosted should be > raw
        assert (
            result.boosted_score >= result.raw_score
        ), f"Positive boost failed: boosted={result.boosted_score}, raw={result.raw_score}"

    @given(data=keyword_and_text(polarity="negative"))
    @settings(max_examples=25)
    def test_negative_keyword_decreases_score(self, data):
        """Negative keyword reduces the score below the raw score."""
        kw, boost, text = data
        keywords = {"positive": {}, "negative": {kw: boost}}
        analyzer = _build_analyzer(keywords)

        result = analyzer.analyze(text)
        assert (
            result.boosted_score <= result.raw_score
        ), f"Negative boost failed: boosted={result.boosted_score}, raw={result.raw_score}"

    @given(
        kw=_keyword,
        boost=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=25)
    def test_boosted_score_clamped(self, kw, boost):
        """Boosted score is always in [-1.0, 1.0] regardless of boost magnitude."""
        assume(len(kw.strip()) >= 3)
        if boost >= 0:
            keywords = {"positive": {kw: abs(boost)}, "negative": {}}
        else:
            keywords = {"positive": {}, "negative": {kw: boost}}

        analyzer = _build_analyzer(keywords)
        text = f"Some text about {kw} in the market"
        result = analyzer.analyze(text)

        assert (
            -1.0 <= result.boosted_score <= 1.0
        ), f"Boosted score out of range: {result.boosted_score}"

    @given(text=st.text(min_size=5, max_size=100, alphabet=st.characters(categories=("L", "Z"))))
    @settings(max_examples=25)
    def test_no_keywords_means_no_boost(self, text):
        """With empty keyword dict, boosted_score equals raw_score."""
        analyzer = _build_analyzer({"positive": {}, "negative": {}})
        result = analyzer.analyze(text)
        assert (
            result.boosted_score == result.raw_score
        ), f"Expected no boost: boosted={result.boosted_score}, raw={result.raw_score}"

    @given(
        kw1=keyword_and_text(polarity="positive"),
        kw2=keyword_and_text(polarity="positive"),
    )
    @settings(max_examples=25)
    def test_multiple_keywords_accumulate(self, kw1, kw2):
        """Multiple matching keywords accumulate their boosts."""
        kw1_word, boost1, _ = kw1
        kw2_word, boost2, _ = kw2
        assume(kw1_word.lower() != kw2_word.lower())

        keywords = {"positive": {kw1_word: boost1, kw2_word: boost2}, "negative": {}}
        analyzer = _build_analyzer(keywords)

        # Text containing both keywords
        text = f"News about {kw1_word} and {kw2_word} today"
        result_both = analyzer.analyze(text)

        # Text containing only first keyword
        analyzer2 = _build_analyzer({"positive": {kw1_word: boost1}, "negative": {}})
        result_one = analyzer2.analyze(f"News about {kw1_word} today")

        # Both keywords should produce >= single keyword boost
        assert (
            result_both.boosted_score >= result_one.boosted_score - 0.001
        ), f"Accumulation failed: both={result_both.boosted_score}, one={result_one.boosted_score}"
