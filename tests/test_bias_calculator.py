"""
Unit tests for the BiasCalculator.

Tests core calculation logic:
- Exponential time decay weights
- Weighted average score computation
- Bias classification thresholds
- Cache (get_current_bias)
- Edge cases (no articles, single article, all same score)

Requirements: 8.1, 8.2, 8.3
"""

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import pytest

from src.commander.bias_calculator import (
    BiasCalculator,
    BiasResult,
    DEFAULT_HALF_LIFE_HOURS,
)
from src.state.database import DatabaseConnectionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class InMemoryDBManager(DatabaseConnectionManager):
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
            self._sqlite_conn.executescript("""
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
                );
                CREATE INDEX idx_sentiment_ticker ON sentiment_log(ticker);
                CREATE INDEX idx_sentiment_created_at ON sentiment_log(created_at);
            """)
        return self._sqlite_conn


def _insert_sentiment(
    db: InMemoryDBManager,
    ticker: str,
    score: float,
    created_at: datetime,
) -> None:
    """Insert a sentiment row into the in-memory database."""
    conn = db.connect_sqlite()
    conn.execute(
        """INSERT INTO sentiment_log
           (article_id, ticker, sentiment, confidence, raw_score,
            boosted_score, news_title, news_source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"art-{score}-{created_at.isoformat()}",
            ticker,
            "POSITIVE" if score > 0 else ("NEGATIVE" if score < 0 else "NEUTRAL"),
            0.9,
            score,
            score,
            "Test headline",
            "TestSource",
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests: Decay weight
# ---------------------------------------------------------------------------

class TestDecayWeight:
    """Tests for compute_decay_weight."""

    def test_weight_at_zero_hours(self):
        calc = BiasCalculator()
        assert calc.compute_decay_weight(0.0) == pytest.approx(1.0)

    def test_weight_at_half_life(self):
        calc = BiasCalculator(half_life_hours=4.0)
        assert calc.compute_decay_weight(4.0) == pytest.approx(0.5, rel=1e-6)

    def test_weight_at_two_half_lives(self):
        calc = BiasCalculator(half_life_hours=4.0)
        assert calc.compute_decay_weight(8.0) == pytest.approx(0.25, rel=1e-6)

    def test_weight_at_three_half_lives(self):
        calc = BiasCalculator(half_life_hours=4.0)
        assert calc.compute_decay_weight(12.0) == pytest.approx(0.125, rel=1e-6)

    def test_weight_at_24_hours(self):
        calc = BiasCalculator(half_life_hours=4.0)
        # 24h = 6 half-lives → weight = 2^-6 = 1/64
        assert calc.compute_decay_weight(24.0) == pytest.approx(1 / 64, rel=1e-6)

    def test_weight_always_positive(self):
        calc = BiasCalculator()
        for h in [0, 1, 10, 100, 1000]:
            assert calc.compute_decay_weight(h) > 0

    def test_custom_half_life(self):
        calc = BiasCalculator(half_life_hours=2.0)
        assert calc.compute_decay_weight(2.0) == pytest.approx(0.5, rel=1e-6)
        assert calc.compute_decay_weight(4.0) == pytest.approx(0.25, rel=1e-6)


# ---------------------------------------------------------------------------
# Tests: Classification
# ---------------------------------------------------------------------------

class TestClassification:
    """Tests for bias classification thresholds."""

    def test_bullish(self):
        calc = BiasCalculator()
        assert calc._classify(0.3) == "BULLISH"
        assert calc._classify(0.21) == "BULLISH"
        assert calc._classify(1.0) == "BULLISH"

    def test_bearish(self):
        calc = BiasCalculator()
        assert calc._classify(-0.3) == "BEARISH"
        assert calc._classify(-0.21) == "BEARISH"
        assert calc._classify(-1.0) == "BEARISH"

    def test_neutral(self):
        calc = BiasCalculator()
        assert calc._classify(0.0) == "NEUTRAL"
        assert calc._classify(0.2) == "NEUTRAL"
        assert calc._classify(-0.2) == "NEUTRAL"
        assert calc._classify(0.1) == "NEUTRAL"
        assert calc._classify(-0.1) == "NEUTRAL"

    def test_boundary_exactly_0_2(self):
        calc = BiasCalculator()
        # score == 0.2 → NEUTRAL (not > 0.2)
        assert calc._classify(0.2) == "NEUTRAL"

    def test_boundary_exactly_neg_0_2(self):
        calc = BiasCalculator()
        # score == -0.2 → NEUTRAL (-0.2 ≤ score ≤ 0.2)
        assert calc._classify(-0.2) == "NEUTRAL"

    def test_custom_thresholds(self):
        calc = BiasCalculator(bullish_threshold=0.5, bearish_threshold=-0.5)
        assert calc._classify(0.3) == "NEUTRAL"
        assert calc._classify(0.6) == "BULLISH"
        assert calc._classify(-0.6) == "BEARISH"


# ---------------------------------------------------------------------------
# Tests: calculate_bias with database
# ---------------------------------------------------------------------------

class TestCalculateBias:
    """Tests for the full calculate_bias pipeline."""

    def test_no_articles_returns_neutral(self):
        db = InMemoryDBManager()
        db.connect_sqlite()
        calc = BiasCalculator(db_manager=db)
        now = datetime.now(timezone.utc)

        result = calc.calculate_bias("RELIANCE", now=now)

        assert result.ticker == "RELIANCE"
        assert result.bias == "NEUTRAL"
        assert result.score == 0.0
        assert result.confidence == 0.0
        assert result.article_count == 0

    def test_single_recent_positive_article(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)
        _insert_sentiment(db, "TCS", 0.8, now - timedelta(minutes=5))

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("TCS", now=now)

        assert result.bias == "BULLISH"
        assert result.score == pytest.approx(0.8, abs=0.05)
        assert result.article_count == 1

    def test_single_recent_negative_article(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)
        _insert_sentiment(db, "INFY", -0.7, now - timedelta(minutes=10))

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("INFY", now=now)

        assert result.bias == "BEARISH"
        assert result.score < -0.2
        assert result.article_count == 1

    def test_old_articles_have_less_weight(self):
        """A recent positive article should outweigh an old negative one."""
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        # Old negative article (20 hours ago — heavily decayed)
        _insert_sentiment(db, "HDFC", -0.5, now - timedelta(hours=20))
        # Recent positive article (30 min ago — almost full weight)
        _insert_sentiment(db, "HDFC", 0.5, now - timedelta(minutes=30))

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("HDFC", now=now)

        # The recent positive should dominate
        assert result.score > 0
        assert result.article_count == 2

    def test_articles_outside_lookback_excluded(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        # Article 25 hours ago — outside 24h lookback
        _insert_sentiment(db, "SBIN", 0.9, now - timedelta(hours=25))
        # Article 1 hour ago — inside lookback
        _insert_sentiment(db, "SBIN", -0.5, now - timedelta(hours=1))

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("SBIN", now=now)

        # Only the recent negative article should count
        assert result.article_count == 1
        assert result.score < 0

    def test_equal_opposing_articles_same_time(self):
        """Two articles at the same time with opposite scores → near zero."""
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)
        t = now - timedelta(hours=1)

        _insert_sentiment(db, "ITC", 0.5, t)
        _insert_sentiment(db, "ITC", -0.5, t)

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("ITC", now=now)

        assert result.bias == "NEUTRAL"
        assert result.score == pytest.approx(0.0, abs=0.01)

    def test_ticker_isolation(self):
        """Sentiment for one ticker should not affect another."""
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        _insert_sentiment(db, "RELIANCE", 0.9, now - timedelta(hours=1))
        _insert_sentiment(db, "TCS", -0.9, now - timedelta(hours=1))

        calc = BiasCalculator(db_manager=db)

        rel_result = calc.calculate_bias("RELIANCE", now=now)
        tcs_result = calc.calculate_bias("TCS", now=now)

        assert rel_result.bias == "BULLISH"
        assert tcs_result.bias == "BEARISH"

    def test_weighted_average_correctness(self):
        """Verify the weighted average formula manually."""
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        # Article at t=0h ago (weight=1.0), score=0.6
        _insert_sentiment(db, "TEST", 0.6, now)
        # Article at t=4h ago (weight=0.5), score=-0.4
        _insert_sentiment(db, "TEST", -0.4, now - timedelta(hours=4))

        calc = BiasCalculator(db_manager=db, half_life_hours=4.0)
        result = calc.calculate_bias("TEST", now=now)

        # Expected: (0.6*1.0 + (-0.4)*0.5) / (1.0 + 0.5) = 0.4/1.5 ≈ 0.2667
        expected_score = (0.6 * 1.0 + (-0.4) * 0.5) / (1.0 + 0.5)
        assert result.score == pytest.approx(expected_score, abs=0.01)
        assert result.bias == "BULLISH"  # 0.2667 > 0.2


# ---------------------------------------------------------------------------
# Tests: get_current_bias (cache)
# ---------------------------------------------------------------------------

class TestGetCurrentBias:
    """Tests for the in-memory bias cache."""

    def test_returns_none_before_calculation(self):
        calc = BiasCalculator()
        assert calc.get_current_bias("RELIANCE") is None

    def test_returns_cached_result_after_calculation(self):
        db = InMemoryDBManager()
        db.connect_sqlite()
        calc = BiasCalculator(db_manager=db)
        now = datetime.now(timezone.utc)

        result = calc.calculate_bias("RELIANCE", now=now)
        cached = calc.get_current_bias("RELIANCE")

        assert cached is not None
        assert cached.ticker == "RELIANCE"
        assert cached.score == result.score
        assert cached.bias == result.bias

    def test_cache_updates_on_recalculation(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        calc = BiasCalculator(db_manager=db)

        # First calculation — no articles
        calc.calculate_bias("X", now=now)
        assert calc.get_current_bias("X").article_count == 0

        # Add an article and recalculate
        _insert_sentiment(db, "X", 0.8, now - timedelta(minutes=5))
        calc.calculate_bias("X", now=now)
        assert calc.get_current_bias("X").article_count == 1


# ---------------------------------------------------------------------------
# Tests: no database manager
# ---------------------------------------------------------------------------

class TestNoDatabaseManager:
    """Tests when no database manager is provided."""

    def test_returns_neutral_without_db(self):
        calc = BiasCalculator(db_manager=None)
        result = calc.calculate_bias("RELIANCE")

        assert result.bias == "NEUTRAL"
        assert result.score == 0.0
        assert result.article_count == 0


# ---------------------------------------------------------------------------
# Tests: confidence calculation
# ---------------------------------------------------------------------------

class TestConfidence:
    """Tests for the confidence metric."""

    def test_confidence_increases_with_article_count(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)

        # 1 article
        _insert_sentiment(db, "A", 0.5, now - timedelta(minutes=10))
        calc = BiasCalculator(db_manager=db)
        r1 = calc.calculate_bias("A", now=now)

        # 10 articles (same score for consistency)
        db2 = InMemoryDBManager()
        for i in range(10):
            _insert_sentiment(db2, "B", 0.5, now - timedelta(minutes=i + 1))
        calc2 = BiasCalculator(db_manager=db2)
        r2 = calc2.calculate_bias("B", now=now)

        assert r2.confidence > r1.confidence

    def test_confidence_bounded_0_to_1(self):
        db = InMemoryDBManager()
        now = datetime.now(timezone.utc)
        for i in range(20):
            _insert_sentiment(db, "Z", 0.5, now - timedelta(minutes=i + 1))

        calc = BiasCalculator(db_manager=db)
        result = calc.calculate_bias("Z", now=now)

        assert 0.0 <= result.confidence <= 1.0
