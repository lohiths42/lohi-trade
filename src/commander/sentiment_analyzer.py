"""Sentiment Analyzer for The Commander.

Classifies news sentiment using FinBERT (ONNX Runtime) with Indian market
keyword boosters. Publishes results to stream:sentiment and stores in
the sentiment_log SQLite table.

Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus

logger = logging.getLogger(__name__)

# FinBERT label mapping: index -> label
FINBERT_LABELS = {0: "POSITIVE", 1: "NEGATIVE", 2: "NEUTRAL"}

SENTIMENT_STREAM_NAME = "stream:sentiment"
SENTIMENT_STREAM_MAXLEN = 10000

INSERT_SENTIMENT_SQL = """
    INSERT INTO sentiment_log
        (article_id, ticker, sentiment, confidence, raw_score, boosted_score,
         news_title, news_source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

# Default paths
DEFAULT_ONNX_MODEL_PATH = "data/models/finbert.onnx"
DEFAULT_TOKENIZER_PATH = "data/models/finbert_tokenizer"
DEFAULT_KEYWORDS_PATH = "config/keywords.json"


def _softmax(logits: list[float]) -> list[float]:
    """Compute softmax probabilities from raw logits."""
    import math

    max_val = max(logits)
    exps = [math.exp(x - max_val) for x in logits]
    total = sum(exps)
    return [e / total for e in exps]


def load_keywords(path: str = DEFAULT_KEYWORDS_PATH) -> dict[str, dict[str, float]]:
    """Load Indian market keyword boosters from JSON file.

    Args:
        path: Path to keywords.json.

    Returns:
        Dict with 'positive' and 'negative' keyword mappings.

    Requirements: 7.5

    """
    try:
        with open(path) as f:
            data = json.load(f)
        logger.info(
            f"Loaded {len(data.get('positive', {}))} positive and "
            f"{len(data.get('negative', {}))} negative keyword boosters",
        )
        return data
    except FileNotFoundError:
        logger.warning(f"Keywords file not found: {path}, using empty boosters")
        return {"positive": {}, "negative": {}}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid keywords JSON at {path}: {e}")
        return {"positive": {}, "negative": {}}


@dataclass
class SentimentResult:
    """Result of sentiment analysis for a news article/ticker pair.

    Attributes:
        article_id: UUID of the source article.
        ticker: NSE ticker symbol.
        sentiment: POSITIVE, NEGATIVE, or NEUTRAL.
        confidence: Probability of the predicted class (0.0-1.0).
        raw_score: Signed score before keyword boosting (-1.0 to 1.0).
        boosted_score: Score after applying keyword boosters.
        timestamp: When the analysis was performed.

    """

    article_id: str = ""
    ticker: str = ""
    sentiment: str = "NEUTRAL"
    confidence: float = 0.0
    raw_score: float = 0.0
    boosted_score: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class SentimentAnalyzer:
    """Classifies news sentiment using FinBERT via ONNX Runtime.

    Supports:
    - ONNX model loading with CoreML execution provider (Apple Neural Engine)
    - Indian market keyword boosters
    - Error handling with NEUTRAL fallback
    - Publishing to Redis Stream and SQLite persistence

    Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7
    """

    def __init__(
        self,
        model_path: str = DEFAULT_ONNX_MODEL_PATH,
        tokenizer_path: str = DEFAULT_TOKENIZER_PATH,
        keywords_path: str = DEFAULT_KEYWORDS_PATH,
        event_bus: EventBus | None = None,
        db_manager: DatabaseConnectionManager | None = None,
    ) -> None:
        self._model_path = model_path
        self._tokenizer_path = tokenizer_path
        self._event_bus = event_bus
        self._db_manager = db_manager
        self._session = None
        self._tokenizer = None
        self._keywords = load_keywords(keywords_path)
        self._model_loaded = False

        self._load_model()

    def _load_model(self) -> None:
        """Load ONNX model and tokenizer. Gracefully degrade on failure."""
        # Load tokenizer
        try:
            from transformers import AutoTokenizer

            if Path(self._tokenizer_path).exists():
                self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_path)
                logger.info(f"Loaded tokenizer from {self._tokenizer_path}")
            else:
                self._tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
                logger.info("Loaded tokenizer from HuggingFace (ProsusAI/finbert)")
        except Exception as e:
            logger.warning(f"Failed to load tokenizer: {e}")
            self._tokenizer = None

        # Load ONNX model
        try:
            import onnxruntime as ort

            if not Path(self._model_path).exists():
                logger.warning(
                    f"ONNX model not found at {self._model_path}. "
                    "Run: python scripts/convert_finbert_onnx.py",
                )
                return

            # Prefer CoreML (Apple Neural Engine), fall back to CPU
            providers = []
            available = ort.get_available_providers()
            if "CoreMLExecutionProvider" in available:
                providers.append("CoreMLExecutionProvider")
            providers.append("CPUExecutionProvider")

            self._session = ort.InferenceSession(
                self._model_path, providers=providers,
            )
            self._model_loaded = True
            logger.info(
                f"ONNX model loaded from {self._model_path} "
                f"(providers: {self._session.get_providers()})",
            )
        except Exception as e:
            logger.warning(f"Failed to load ONNX model: {e}")
            self._session = None

    @property
    def is_model_loaded(self) -> bool:
        """Whether the ONNX model and tokenizer are ready."""
        return self._model_loaded and self._tokenizer is not None

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        text: str,
        article_id: str = "",
        ticker: str = "",
        news_title: str = "",
        news_source: str = "",
    ) -> SentimentResult:
        """Classify sentiment of a text using FinBERT.

        On inference failure, defaults to NEUTRAL with confidence 0.0.

        Args:
            text: Text to analyze (title + content).
            article_id: UUID of the source article.
            ticker: NSE ticker symbol.
            news_title: Article title for persistence.
            news_source: Article source for persistence.

        Returns:
            SentimentResult with classification and scores.

        Requirements: 7.3, 7.5, 7.7

        """
        try:
            raw_label, raw_confidence, raw_score = self._run_inference(text)
        except Exception as e:
            logger.error(
                f"Sentiment inference failed for article '{article_id}': {e}",
                extra={"article_id": article_id, "ticker": ticker},
            )
            return self._neutral_fallback(article_id, ticker)

        # Apply keyword boosters
        boost = self._calculate_boost(text)
        boosted_score = max(-1.0, min(1.0, raw_score + boost))

        # Re-classify based on boosted score
        if boosted_score > 0.05:
            sentiment = "POSITIVE"
        elif boosted_score < -0.05:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        # If boost didn't change the label, keep original confidence;
        # otherwise reduce confidence slightly to reflect the override.
        if sentiment == raw_label:
            confidence = raw_confidence
        else:
            confidence = max(0.0, raw_confidence - abs(boost))

        result = SentimentResult(
            article_id=article_id,
            ticker=ticker,
            sentiment=sentiment,
            confidence=round(confidence, 4),
            raw_score=round(raw_score, 4),
            boosted_score=round(boosted_score, 4),
            timestamp=datetime.now(UTC),
        )

        logger.info(
            f"Sentiment for {ticker}: {sentiment} "
            f"(raw={raw_score:.3f}, boost={boost:+.3f}, final={boosted_score:.3f})",
            extra={
                "article_id": article_id,
                "ticker": ticker,
                "sentiment": sentiment,
            },
        )

        return result

    def analyze_and_publish(
        self,
        text: str,
        article_id: str,
        ticker: str,
        news_title: str = "",
        news_source: str = "",
    ) -> SentimentResult:
        """Analyze sentiment, publish to Redis Stream, and store in SQLite.

        Args:
            text: Text to analyze.
            article_id: UUID of the source article.
            ticker: NSE ticker symbol.
            news_title: Article title for persistence.
            news_source: Article source for persistence.

        Returns:
            SentimentResult.

        Requirements: 7.6

        """
        result = self.analyze(text, article_id, ticker, news_title, news_source)

        if self._event_bus is not None:
            self._publish_to_stream(result)

        if self._db_manager is not None:
            self._store_in_sqlite(result, news_title, news_source)

        return result

    # ------------------------------------------------------------------
    # Inference internals
    # ------------------------------------------------------------------

    def _run_inference(self, text: str) -> tuple[str, float, float]:
        """Run FinBERT inference via ONNX Runtime.

        Returns:
            (label, confidence, signed_score) where signed_score is in [-1, 1].

        Raises:
            RuntimeError: If model or tokenizer is not loaded.

        """
        if not self.is_model_loaded:
            raise RuntimeError("ONNX model or tokenizer not loaded")

        import numpy as np

        inputs = self._tokenizer(
            text,
            return_tensors="np",
            max_length=512,
            truncation=True,
            padding="max_length",
        )

        ort_inputs = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
        }

        logits = self._session.run(["logits"], ort_inputs)[0][0]
        logits_list = logits.tolist()

        # Guard against NaN / Inf logits
        import math

        if any(math.isnan(v) or math.isinf(v) for v in logits_list):
            raise RuntimeError("ONNX model returned NaN/Inf logits")

        probs = _softmax(logits_list)

        # FinBERT labels: 0=positive, 1=negative, 2=neutral
        pred_idx = int(np.argmax(probs))
        label = FINBERT_LABELS[pred_idx]
        confidence = probs[pred_idx]

        # Signed score: positive_prob - negative_prob
        raw_score = probs[0] - probs[1]

        return label, confidence, raw_score

    # ------------------------------------------------------------------
    # Keyword boosting
    # ------------------------------------------------------------------

    def _calculate_boost(self, text: str) -> float:
        """Calculate keyword boost for a text.

        Scans text for positive and negative keywords and sums their
        boost values.

        Requirements: 7.5
        """
        text_lower = text.lower()
        boost = 0.0

        for keyword, value in self._keywords.get("positive", {}).items():
            if keyword.lower() in text_lower:
                boost += value

        for keyword, value in self._keywords.get("negative", {}).items():
            if keyword.lower() in text_lower:
                boost += value  # value is already negative

        return boost

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _neutral_fallback(
        self, article_id: str = "", ticker: str = "",
    ) -> SentimentResult:
        """Return NEUTRAL sentiment as fallback on inference failure.

        Requirements: 7.7
        """
        logger.warning(
            f"Defaulting to NEUTRAL sentiment for article '{article_id}' / ticker '{ticker}'",
            extra={"article_id": article_id, "ticker": ticker},
        )
        return SentimentResult(
            article_id=article_id,
            ticker=ticker,
            sentiment="NEUTRAL",
            confidence=0.0,
            raw_score=0.0,
            boosted_score=0.0,
            timestamp=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Publishing and persistence
    # ------------------------------------------------------------------

    def _publish_to_stream(self, result: SentimentResult) -> str:
        """Publish sentiment result to stream:sentiment. Requirements: 7.6"""
        message = {
            "article_id": result.article_id,
            "ticker": result.ticker,
            "sentiment": result.sentiment,
            "confidence": str(result.confidence),
            "raw_score": str(result.raw_score),
            "boosted_score": str(result.boosted_score),
            "timestamp": result.timestamp.isoformat(),
        }
        msg_id = self._event_bus.publish(
            SENTIMENT_STREAM_NAME, message, maxlen=SENTIMENT_STREAM_MAXLEN,
        )
        logger.debug(
            f"Published sentiment to {SENTIMENT_STREAM_NAME}: {msg_id}",
            extra={"article_id": result.article_id, "ticker": result.ticker},
        )
        return msg_id

    def _store_in_sqlite(
        self, result: SentimentResult, news_title: str, news_source: str,
    ) -> None:
        """Persist sentiment result in sentiment_log table. Requirements: 7.6"""
        self._db_manager.execute_with_retry(
            INSERT_SENTIMENT_SQL,
            (
                result.article_id,
                result.ticker,
                result.sentiment,
                result.confidence,
                result.raw_score,
                result.boosted_score,
                news_title or "",
                news_source or "",
            ),
        )
        logger.debug(
            f"Stored sentiment in SQLite for {result.ticker}",
            extra={"article_id": result.article_id},
        )
