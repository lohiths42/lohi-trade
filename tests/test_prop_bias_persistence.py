"""Property-based tests for Bias Persistence.

Verifies that BiasScheduler.store_bias() correctly persists BiasResult
data into the SQLite bias_log table with all fields preserved.

**Property 74: Bias Persistence**
**Validates: Requirements 8.6**

Properties tested:
  1. For any BiasResult, store_bias() persists all fields correctly
  2. Multiple bias results for the same ticker are all stored (no overwrites)
  3. Stored data matches the original BiasResult fields
  4. Score and confidence values are preserved with sufficient precision
"""

import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.bias_calculator import BiasResult
from src.commander.bias_scheduler import BiasScheduler

# ---------------------------------------------------------------------------
# In-memory DB helper
# ---------------------------------------------------------------------------


class InMemoryDBManager:
    """Lightweight in-memory SQLite for testing."""

    def __init__(self):
        self.sqlite_path = ":memory:"
        self.duckdb_path = ""
        self._sqlite_conn = None
        self._duckdb_conn = None

    def connect_sqlite(self) -> sqlite3.Connection:
        if self._sqlite_conn is None:
            self._sqlite_conn = sqlite3.connect(":memory:")
            self._sqlite_conn.row_factory = sqlite3.Row
            self._sqlite_conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bias_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    article_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )
        return self._sqlite_conn

    def get_all_rows(self):
        conn = self.connect_sqlite()
        return conn.execute("SELECT * FROM bias_log ORDER BY id").fetchall()


def _make_scheduler(db: InMemoryDBManager) -> BiasScheduler:
    return BiasScheduler(
        bias_calculator=MagicMock(),
        tickers=["RELIANCE"],
        db_manager=db,
    )


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_ticker = st.sampled_from(
    [
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "BHARTIARTL",
        "ITC",
        "KOTAKBANK",
        "LT",
    ]
)
_bias = st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL"])
_score = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_confidence = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_article_count = st.integers(min_value=0, max_value=100)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestBiasPersistenceProperties:
    """**Property 74: Bias Persistence**
    **Validates: Requirements 8.6**
    """

    @given(
        ticker=_ticker,
        bias=_bias,
        score=_score,
        confidence=_confidence,
        article_count=_article_count,
    )
    @settings(max_examples=25)
    def test_store_bias_persists_all_fields(
        self,
        ticker,
        bias,
        score,
        confidence,
        article_count,
    ):
        """For any BiasResult, store_bias() persists all fields correctly
        to the bias_log table.

        **Validates: Requirements 8.6**
        """
        db = InMemoryDBManager()
        scheduler = _make_scheduler(db)
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        result = BiasResult(
            ticker=ticker,
            bias=bias,
            score=score,
            confidence=confidence,
            article_count=article_count,
            timestamp=ts,
        )
        scheduler.store_bias(result)

        rows = db.get_all_rows()
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"

        row = rows[0]
        assert row["ticker"] == ticker
        assert row["bias"] == bias
        assert (
            abs(row["score"] - score) < 1e-6
        ), f"Score mismatch: stored={row['score']}, expected={score}"
        assert (
            abs(row["confidence"] - confidence) < 1e-6
        ), f"Confidence mismatch: stored={row['confidence']}, expected={confidence}"
        assert row["article_count"] == article_count

    @given(
        ticker=_ticker,
        biases=st.lists(_bias, min_size=2, max_size=10),
        scores=st.lists(_score, min_size=2, max_size=10),
    )
    @settings(max_examples=25)
    def test_multiple_results_same_ticker_all_stored(
        self,
        ticker,
        biases,
        scores,
    ):
        """Multiple bias results for the same ticker are all stored
        (no overwrites). Each store_bias call appends a new row.

        **Validates: Requirements 8.6**
        """
        n = min(len(biases), len(scores))
        biases = biases[:n]
        scores = scores[:n]

        db = InMemoryDBManager()
        scheduler = _make_scheduler(db)
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        for bias_val, score_val in zip(biases, scores):
            result = BiasResult(
                ticker=ticker,
                bias=bias_val,
                score=score_val,
                confidence=0.5,
                article_count=3,
                timestamp=ts,
            )
            scheduler.store_bias(result)

        rows = db.get_all_rows()
        assert len(rows) == n, f"Expected {n} rows for {n} store_bias calls, got {len(rows)}"

        # Verify each row matches the corresponding input
        for i, (bias_val, score_val) in enumerate(zip(biases, scores)):
            assert rows[i]["ticker"] == ticker
            assert rows[i]["bias"] == bias_val
            assert abs(rows[i]["score"] - score_val) < 1e-6

    @given(
        score=_score,
        confidence=_confidence,
    )
    @settings(max_examples=25)
    def test_score_and_confidence_precision_preserved(self, score, confidence):
        """Score and confidence values are preserved with sufficient
        precision (within 1e-6) after round-trip through SQLite.

        **Validates: Requirements 8.6**
        """
        db = InMemoryDBManager()
        scheduler = _make_scheduler(db)
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        result = BiasResult(
            ticker="RELIANCE",
            bias="NEUTRAL",
            score=score,
            confidence=confidence,
            article_count=1,
            timestamp=ts,
        )
        scheduler.store_bias(result)

        rows = db.get_all_rows()
        row = rows[0]
        assert (
            abs(row["score"] - score) < 1e-6
        ), f"Score precision lost: stored={row['score']}, original={score}"
        assert (
            abs(row["confidence"] - confidence) < 1e-6
        ), f"Confidence precision lost: stored={row['confidence']}, original={confidence}"

    @given(
        ticker=_ticker,
        bias=_bias,
        score=_score,
        confidence=_confidence,
        article_count=_article_count,
    )
    @settings(max_examples=25)
    def test_stored_data_retrievable_and_matches(
        self,
        ticker,
        bias,
        score,
        confidence,
        article_count,
    ):
        """Stored data can be retrieved from the bias_log table and all
        fields match the original BiasResult.

        **Validates: Requirements 8.6**
        """
        db = InMemoryDBManager()
        scheduler = _make_scheduler(db)
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        result = BiasResult(
            ticker=ticker,
            bias=bias,
            score=score,
            confidence=confidence,
            article_count=article_count,
            timestamp=ts,
        )
        scheduler.store_bias(result)

        # Retrieve by ticker
        conn = db.connect_sqlite()
        row = conn.execute(
            "SELECT * FROM bias_log WHERE ticker = ?",
            (ticker,),
        ).fetchone()

        assert row is not None, f"No row found for ticker {ticker}"
        assert row["ticker"] == result.ticker
        assert row["bias"] == result.bias
        assert abs(row["score"] - result.score) < 1e-6
        assert abs(row["confidence"] - result.confidence) < 1e-6
        assert row["article_count"] == result.article_count
        assert row["created_at"] == ts.strftime("%Y-%m-%d %H:%M:%S")
