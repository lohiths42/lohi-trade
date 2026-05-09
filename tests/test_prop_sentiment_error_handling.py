"""
Property-based tests for Sentiment Error Handling.

Validates that the SentimentAnalyzer gracefully handles inference failures
by defaulting to NEUTRAL sentiment with confidence 0.0, and that errors
are logged with article details.

**Property 24: Sentiment Error Handling**
**Validates: Requirements 7.7**

Properties tested:
  1. Any exception during inference results in NEUTRAL fallback
  2. Fallback always has confidence 0.0 and raw_score 0.0
  3. Article ID and ticker are preserved in fallback result
  4. Tokenizer failure produces NEUTRAL fallback
  5. ONNX session failure produces NEUTRAL fallback
"""

import uuid
from typing import Dict, Optional

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.sentiment_analyzer import SentimentAnalyzer, SentimentResult


# ---------------------------------------------------------------------------
# Mocks that simulate failures
# ---------------------------------------------------------------------------


class ExplodingTokenizer:
    """Tokenizer that always raises an exception."""

    def __call__(self, text, **kwargs):
        raise RuntimeError("Tokenizer exploded")


class ExplodingOnnxSession:
    """ONNX session that always raises an exception."""

    def run(self, output_names, inputs):
        raise RuntimeError("ONNX inference exploded")

    def get_providers(self):
        return ["CPUExecutionProvider"]


class GoodTokenizer:
    """Tokenizer that works normally."""

    def __call__(self, text, **kwargs):
        seq_len = kwargs.get("max_length", 512)
        return {
            "input_ids": np.ones((1, seq_len), dtype=np.int64),
            "attention_mask": np.ones((1, seq_len), dtype=np.int64),
        }


class NaNOnnxSession:
    """ONNX session that returns NaN logits."""

    def run(self, output_names, inputs):
        return [np.array([[float("nan"), float("nan"), float("nan")]], dtype=np.float32)]

    def get_providers(self):
        return ["CPUExecutionProvider"]


def _build_broken_analyzer(
    tokenizer=None,
    session=None,
    model_loaded=True,
) -> SentimentAnalyzer:
    """Build analyzer with specified (possibly broken) components."""
    analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
    analyzer._tokenizer = tokenizer
    analyzer._session = session
    analyzer._model_loaded = model_loaded
    analyzer._keywords = {"positive": {}, "negative": {}}
    analyzer._event_bus = None
    analyzer._db_manager = None
    analyzer._model_path = "fake"
    analyzer._tokenizer_path = "fake"
    return analyzer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_text = st.text(min_size=1, max_size=200, alphabet=st.characters(categories=("L", "N", "P", "Z")))
_article_id = st.text(min_size=1, max_size=36, alphabet=st.characters(categories=("L", "N")))
_ticker = st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"])


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSentimentErrorHandlingProperties:
    """
    **Property 24: Sentiment Error Handling**
    **Validates: Requirements 7.7**
    """

    @given(text=_text, article_id=_article_id, ticker=_ticker)
    @settings(max_examples=25)
    def test_model_not_loaded_returns_neutral(self, text, article_id, ticker):
        """When model is not loaded, returns NEUTRAL with zero scores."""
        analyzer = _build_broken_analyzer(model_loaded=False)
        result = analyzer.analyze(text, article_id=article_id, ticker=ticker)

        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0
        assert result.raw_score == 0.0
        assert result.boosted_score == 0.0

    @given(text=_text, article_id=_article_id, ticker=_ticker)
    @settings(max_examples=25)
    def test_tokenizer_failure_returns_neutral(self, text, article_id, ticker):
        """Tokenizer exception produces NEUTRAL fallback."""
        analyzer = _build_broken_analyzer(
            tokenizer=ExplodingTokenizer(),
            session=ExplodingOnnxSession(),
            model_loaded=True,
        )
        result = analyzer.analyze(text, article_id=article_id, ticker=ticker)

        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0

    @given(text=_text, article_id=_article_id, ticker=_ticker)
    @settings(max_examples=25)
    def test_onnx_session_failure_returns_neutral(self, text, article_id, ticker):
        """ONNX session exception produces NEUTRAL fallback."""
        analyzer = _build_broken_analyzer(
            tokenizer=GoodTokenizer(),
            session=ExplodingOnnxSession(),
            model_loaded=True,
        )
        result = analyzer.analyze(text, article_id=article_id, ticker=ticker)

        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0

    @given(text=_text, article_id=_article_id, ticker=_ticker)
    @settings(max_examples=25)
    def test_fallback_preserves_article_id_and_ticker(self, text, article_id, ticker):
        """Fallback result preserves the article_id and ticker."""
        analyzer = _build_broken_analyzer(model_loaded=False)
        result = analyzer.analyze(text, article_id=article_id, ticker=ticker)

        assert result.article_id == article_id
        assert result.ticker == ticker

    @given(text=_text, article_id=_article_id, ticker=_ticker)
    @settings(max_examples=25)
    def test_nan_logits_returns_neutral(self, text, article_id, ticker):
        """NaN logits from ONNX session produce NEUTRAL fallback."""
        analyzer = _build_broken_analyzer(
            tokenizer=GoodTokenizer(),
            session=NaNOnnxSession(),
            model_loaded=True,
        )
        result = analyzer.analyze(text, article_id=article_id, ticker=ticker)

        # NaN in softmax will cause math errors, should fall back to NEUTRAL
        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0
