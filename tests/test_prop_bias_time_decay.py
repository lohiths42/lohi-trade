"""Property-based tests for Bias Time Decay.

Verifies that the BiasCalculator applies exponential time decay with
half-life of 4 hours to sentiment scores, weighting recent scores more
heavily than older scores.

**Property 25: Bias Time Decay**
**Validates: Requirements 8.2**

Properties tested:
  1. Decay weight at half-life is exactly 0.5
  2. Decay weight is monotonically decreasing with time
  3. Recent articles have more influence than older articles on the final bias score
  4. The weighted average formula is correct: Σ(score × weight) / Σ(weight)
"""

import math
import sqlite3
from datetime import UTC, datetime, timedelta

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.commander.bias_calculator import BiasCalculator

# ---------------------------------------------------------------------------
# In-memory DB helper (same pattern as unit tests)
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
            """
            )
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
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_half_life = st.floats(min_value=0.5, max_value=24.0, allow_nan=False, allow_infinity=False)
_hours_ago = st.floats(min_value=0.0, max_value=24.0, allow_nan=False, allow_infinity=False)
_sentiment_score = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestBiasTimeDecayProperties:
    """**Property 25: Bias Time Decay**
    **Validates: Requirements 8.2**
    """

    @given(half_life=_half_life)
    @settings(max_examples=100)
    def test_decay_weight_at_half_life_is_half(self, half_life):
        """Property: For any half-life value, the decay weight at exactly
        one half-life should be 0.5.

        **Validates: Requirements 8.2**
        """
        calc = BiasCalculator(half_life_hours=half_life)
        weight = calc.compute_decay_weight(half_life)
        assert weight == math.exp(-math.log(2) / half_life * half_life)
        assert (
            abs(weight - 0.5) < 1e-9
        ), f"Weight at half-life {half_life}h should be 0.5, got {weight}"

    @given(
        half_life=_half_life,
        t1=_hours_ago,
        t2=_hours_ago,
    )
    @settings(max_examples=100)
    def test_decay_weight_monotonically_decreasing(self, half_life, t1, t2):
        """Property: For any two time offsets where t1 < t2, the decay weight
        at t1 should be greater than or equal to the weight at t2.

        **Validates: Requirements 8.2**
        """
        assume(t1 < t2)
        calc = BiasCalculator(half_life_hours=half_life)
        w1 = calc.compute_decay_weight(t1)
        w2 = calc.compute_decay_weight(t2)
        assert w1 >= w2, f"Weight should decrease with time: w({t1}h)={w1} < w({t2}h)={w2}"

    @given(
        score=_sentiment_score,
        recent_hours=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        old_hours=st.floats(min_value=8.0, max_value=23.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_recent_articles_have_more_influence(self, score, recent_hours, old_hours):
        """Property: A recent article should have more influence on the bias
        score than an older article with the same sentiment score. When we
        have one recent positive and one old negative article (or vice versa),
        the bias should lean toward the recent article's direction.

        **Validates: Requirements 8.2**
        """
        assume(abs(score) > 0.1)  # Need a meaningful score to see the effect

        db = InMemoryDBManager()
        now = datetime.now(UTC)

        # Recent article with +score, old article with -score
        _insert_sentiment(db, "TEST", score, now - timedelta(hours=recent_hours))
        _insert_sentiment(db, "TEST", -score, now - timedelta(hours=old_hours))

        calc = BiasCalculator(db_manager=db, half_life_hours=4.0)
        result = calc.calculate_bias("TEST", now=now)

        # The recent article should dominate, so the bias score should
        # have the same sign as the recent article's score
        if score > 0:
            assert result.score > 0, (
                f"Recent positive ({score}) at {recent_hours}h should dominate "
                f"old negative ({-score}) at {old_hours}h, but score={result.score}"
            )
        else:
            assert result.score < 0, (
                f"Recent negative ({score}) at {recent_hours}h should dominate "
                f"old positive ({-score}) at {old_hours}h, but score={result.score}"
            )

    @given(
        scores=st.lists(
            _sentiment_score,
            min_size=1,
            max_size=10,
        ),
        hours_list=st.lists(
            st.floats(min_value=0.0, max_value=23.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_weighted_average_formula_correct(self, scores, hours_list):
        """Property: The bias score should equal the weighted average
        Σ(score × weight) / Σ(weight) where weight = exp(-λ × hours_ago)
        and λ = ln(2) / 4.

        **Validates: Requirements 8.2**
        """
        # Ensure lists are the same length
        n = min(len(scores), len(hours_list))
        assume(n >= 1)
        scores = scores[:n]
        hours_list = hours_list[:n]

        db = InMemoryDBManager()
        now = datetime.now(UTC)
        half_life = 4.0
        decay_lambda = math.log(2) / half_life

        for score, hours_ago in zip(scores, hours_list):
            created_at = now - timedelta(hours=hours_ago)
            _insert_sentiment(db, "CALC", score, created_at)

        calc = BiasCalculator(db_manager=db, half_life_hours=half_life)
        result = calc.calculate_bias("CALC", now=now)

        # Manually compute expected weighted average
        weighted_sum = 0.0
        weight_total = 0.0
        for score, hours_ago in zip(scores, hours_list):
            weight = math.exp(-decay_lambda * max(0.0, hours_ago))
            weighted_sum += score * weight
            weight_total += weight

        if weight_total > 0:
            expected_score = weighted_sum / weight_total
        else:
            expected_score = 0.0

        assert abs(result.score - expected_score) < 1e-4, (
            f"Weighted average mismatch: expected={expected_score:.6f}, " f"got={result.score:.6f}"
        )
