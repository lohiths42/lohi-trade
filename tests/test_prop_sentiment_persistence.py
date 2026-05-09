"""
Property-based tests for Sentiment Persistence.

Validates that sentiment results are correctly published to the Redis
Stream (stream:sentiment) and stored in the SQLite sentiment_log table.

**Property 73: Sentiment Persistence**
**Validates: Requirements 7.6**

Properties tested:
  1. Every analyze_and_publish call stores a row in sentiment_log
  2. Stored row matches the SentimentResult fields
  3. Every analyze_and_publish call publishes to stream:sentiment
  4. Published message fields match the SentimentResult
"""

import sqlite3
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.sentiment_analyzer import (
    INSERT_SENTIMENT_SQL,
    SENTIMENT_STREAM_NAME,
    SentimentAnalyzer,
    SentimentResult,
)


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class FakeTokenizer:
    def __call__(self, text, **kwargs):
        seq_len = kwargs.get("max_length", 512)
        return {
            "input_ids": np.ones((1, seq_len), dtype=np.int64),
            "attention_mask": np.ones((1, seq_len), dtype=np.int64),
        }


class FakeOnnxSession:
    def __init__(self, logits=None):
        self._logits = np.array([logits or [0.3, -0.2, 0.1]], dtype=np.float32)

    def run(self, output_names, inputs):
        return [self._logits]

    def get_providers(self):
        return ["CPUExecutionProvider"]


class MockEventBus:
    """Records all published messages."""

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []

    def publish(self, stream_name: str, message: Dict[str, Any], maxlen=None) -> str:
        self.messages.append({"stream": stream_name, "data": message})
        return f"mock-{len(self.messages)}"


class MockDatabaseManager:
    """In-memory SQLite for testing persistence."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("""
            CREATE TABLE sentiment_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                confidence REAL NOT NULL,
                raw_score REAL NOT NULL,
                boosted_score REAL NOT NULL,
                news_title TEXT NOT NULL,
                news_source TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def execute_with_retry(self, query, params=(), **kwargs):
        cursor = self._conn.execute(query, params)
        self._conn.commit()
        return cursor

    def get_all_rows(self) -> List[Dict[str, Any]]:
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute("SELECT * FROM sentiment_log").fetchall()
        return [dict(r) for r in rows]


def _build_analyzer(event_bus=None, db_manager=None) -> SentimentAnalyzer:
    analyzer = SentimentAnalyzer.__new__(SentimentAnalyzer)
    analyzer._tokenizer = FakeTokenizer()
    analyzer._session = FakeOnnxSession()
    analyzer._model_loaded = True
    analyzer._keywords = {"positive": {}, "negative": {}}
    analyzer._event_bus = event_bus
    analyzer._db_manager = db_manager
    analyzer._model_path = "fake"
    analyzer._tokenizer_path = "fake"
    return analyzer


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_text = st.text(min_size=1, max_size=200, alphabet=st.characters(categories=("L", "N", "P", "Z")))
_ticker = st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"])
_source = st.sampled_from(["MoneyControl", "EconomicTimes", "LiveMint"])
_title = st.text(min_size=1, max_size=100, alphabet=st.characters(categories=("L", "N", "P", "Z")))


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestSentimentPersistenceProperties:
    """
    **Property 73: Sentiment Persistence**
    **Validates: Requirements 7.6**
    """

    @given(text=_text, ticker=_ticker, title=_title, source=_source)
    @settings(max_examples=25)
    def test_sqlite_row_created(self, text, ticker, title, source):
        """Each analyze_and_publish creates exactly one sentiment_log row."""
        db = MockDatabaseManager()
        analyzer = _build_analyzer(db_manager=db)
        article_id = str(uuid.uuid4())

        analyzer.analyze_and_publish(
            text, article_id=article_id, ticker=ticker,
            news_title=title, news_source=source,
        )

        rows = db.get_all_rows()
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"

    @given(text=_text, ticker=_ticker, title=_title, source=_source)
    @settings(max_examples=25)
    def test_sqlite_row_matches_result(self, text, ticker, title, source):
        """Stored row fields match the SentimentResult."""
        db = MockDatabaseManager()
        analyzer = _build_analyzer(db_manager=db)
        article_id = str(uuid.uuid4())

        result = analyzer.analyze_and_publish(
            text, article_id=article_id, ticker=ticker,
            news_title=title, news_source=source,
        )

        rows = db.get_all_rows()
        row = rows[0]
        assert row["article_id"] == article_id
        assert row["ticker"] == ticker
        assert row["sentiment"] == result.sentiment
        assert abs(row["confidence"] - result.confidence) < 1e-3
        assert abs(row["raw_score"] - result.raw_score) < 1e-3
        assert abs(row["boosted_score"] - result.boosted_score) < 1e-3
        assert row["news_title"] == title
        assert row["news_source"] == source

    @given(text=_text, ticker=_ticker)
    @settings(max_examples=25)
    def test_stream_message_published(self, text, ticker):
        """Each analyze_and_publish publishes to stream:sentiment."""
        bus = MockEventBus()
        analyzer = _build_analyzer(event_bus=bus)
        article_id = str(uuid.uuid4())

        analyzer.analyze_and_publish(text, article_id=article_id, ticker=ticker)

        assert len(bus.messages) == 1
        assert bus.messages[0]["stream"] == SENTIMENT_STREAM_NAME

    @given(text=_text, ticker=_ticker)
    @settings(max_examples=25)
    def test_stream_message_fields_match(self, text, ticker):
        """Published message fields match the SentimentResult."""
        bus = MockEventBus()
        analyzer = _build_analyzer(event_bus=bus)
        article_id = str(uuid.uuid4())

        result = analyzer.analyze_and_publish(text, article_id=article_id, ticker=ticker)

        data = bus.messages[0]["data"]
        assert data["article_id"] == article_id
        assert data["ticker"] == ticker
        assert data["sentiment"] == result.sentiment
        assert data["confidence"] == str(result.confidence)
        assert data["raw_score"] == str(result.raw_score)
        assert data["boosted_score"] == str(result.boosted_score)
