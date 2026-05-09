"""
Property-based tests for Sentiment Classification.

Validates that the SentimentAnalyzer produces valid sentiment labels,
confidence scores, and raw scores for arbitrary text inputs, including
when the ONNX model is unavailable (fallback behaviour).

**Property 22: Sentiment Classification**
**Validates: Requirements 7.3**

Properties tested:
  1. Sentiment label is always one of POSITIVE, NEGATIVE, NEUTRAL
  2. Confidence is in [0.0, 1.0]
  3. Raw score is in [-1.0, 1.0]
  4. Boosted score is in [-1.0, 1.0]
  5. When model is unavailable, fallback returns NEUTRAL with confidence 0.0
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.commander.sentiment_analyzer import (
    FINBERT_LABELS,
    SentimentAnalyzer,
    SentimentResult,
    _softmax,
    load_keywords,
)


# ---------------------------------------------------------------------------
# Helpers / Mocks
# ---------------------------------------------------------------------------

VALID_LABELS = {"POSITIVE", "NEGATIVE", "NEUTRAL"}


def _make_fake_logits(pos: float, neg: float, neu: float) -> List[float]:
    """Build a logits vector [positive, negative, neutral]."""
    return [pos, neg, neu]


class FakeTokenizer:
    """Minimal tokenizer mock that returns numpy-like dicts."""

    def __call__(self, text, **kwargs):
        import numpy as np

        seq_len = kwargs.get("max_length", 512)
        return {
            "input_ids": np.ones((1, seq_len), dtype=np.int64),
            "attention_mask": np.ones((1, seq_len), dtype=np.int64),
        }


class FakeOnnxSession:
    """ONNX session mock that returns configurable logits."""

    def __init__(self, logits: Optional[List[float]] = None):
        import numpy as np

        self._logits = logits or [0.5, -0.3, 0.1]
        self._logits_np = np.array([self._logits], dtype=np.float32)

    def run(self, output_names, inputs):
        return [self._logits_np]

    def get_providers(self):
        return ["CPUExecutionProvider"]


def _build_analyzer(
    logits: Optional[List[float]] = None,
    keywords: Optional[Dict[str, Dict[str, float]]] = None,
) -> SentimentAnalyzer:
    """Build a SentimentAnalyzer with mocked model and tokenizer."""
    analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
    analyzer._tokenizer = FakeTokenizer()
    analyzer._session = FakeOnnxSession(logits)
    analyzer._model_loaded = True
    analyzer._keywords = keywords or {"positive": {}, "negative": {}}
    analyzer._event_bus = None
    analyzer._db_manager = None
    analyzer._model_path = "fake"
    analyzer._tokenizer_path = "fake"
    return analyzer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_text = st.text(min_size=1, max_size=300, alphabet=st.characters(categories=("L", "N", "P", "Z")))

# Logits: three floats that aren't all identical (to avoid degenerate softmax)
_logits = st.tuples(
    st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSentimentClassificationProperties:
    """
    **Property 22: Sentiment Classification**
    **Validates: Requirements 7.3**
    """

    @given(logits=_logits, text=_text)
    @settings(max_examples=25)
    def test_label_is_valid(self, logits, text):
        """Sentiment label is always one of POSITIVE, NEGATIVE, NEUTRAL."""
        analyzer = _build_analyzer(logits=list(logits))
        result = analyzer.analyze(text)
        assert result.sentiment in VALID_LABELS, (
            f"Invalid sentiment label: {result.sentiment}"
        )

    @given(logits=_logits, text=_text)
    @settings(max_examples=25)
    def test_confidence_in_range(self, logits, text):
        """Confidence is in [0.0, 1.0]."""
        analyzer = _build_analyzer(logits=list(logits))
        result = analyzer.analyze(text)
        assert 0.0 <= result.confidence <= 1.0, (
            f"Confidence out of range: {result.confidence}"
        )

    @given(logits=_logits, text=_text)
    @settings(max_examples=25)
    def test_raw_score_in_range(self, logits, text):
        """Raw score (positive_prob - negative_prob) is in [-1.0, 1.0]."""
        analyzer = _build_analyzer(logits=list(logits))
        result = analyzer.analyze(text)
        assert -1.0 <= result.raw_score <= 1.0, (
            f"Raw score out of range: {result.raw_score}"
        )

    @given(logits=_logits, text=_text)
    @settings(max_examples=25)
    def test_boosted_score_in_range(self, logits, text):
        """Boosted score is clamped to [-1.0, 1.0]."""
        analyzer = _build_analyzer(logits=list(logits))
        result = analyzer.analyze(text)
        assert -1.0 <= result.boosted_score <= 1.0, (
            f"Boosted score out of range: {result.boosted_score}"
        )

    @given(text=_text)
    @settings(max_examples=25)
    def test_fallback_on_model_unavailable(self, text):
        """When model is not loaded, returns NEUTRAL with confidence 0.0."""
        analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
        analyzer._tokenizer = None
        analyzer._session = None
        analyzer._model_loaded = False
        analyzer._keywords = {"positive": {}, "negative": {}}
        analyzer._event_bus = None
        analyzer._db_manager = None
        analyzer._model_path = "fake"
        analyzer._tokenizer_path = "fake"

        result = analyzer.analyze(text, article_id="test-id", ticker="TEST")
        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0
        assert result.raw_score == 0.0
        assert result.boosted_score == 0.0


class TestSoftmaxProperties:
    """Verify softmax helper produces valid probability distributions."""

    @given(logits=_logits)
    @settings(max_examples=25)
    def test_softmax_sums_to_one(self, logits):
        """Softmax output sums to ~1.0."""
        probs = _softmax(list(logits))
        assert abs(sum(probs) - 1.0) < 1e-6, f"Softmax sum: {sum(probs)}"

    @given(logits=_logits)
    @settings(max_examples=25)
    def test_softmax_all_positive(self, logits):
        """All softmax probabilities are positive."""
        probs = _softmax(list(logits))
        assert all(p >= 0 for p in probs), f"Negative probability in {probs}"
