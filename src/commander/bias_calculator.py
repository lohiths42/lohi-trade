"""Bias Calculator for The Commander.

Aggregates sentiment from the last 24 hours with exponential time decay
(half-life 4 hours) to produce a trading bias for each ticker. The bias
is classified as BULLISH, BEARISH, or NEUTRAL based on configurable
thresholds.

Requirements: 8.1, 8.2, 8.3
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.state.database import DatabaseConnectionManager

logger = logging.getLogger(__name__)

# Decay constant: λ = ln(2) / half_life_hours
# With half-life of 4 hours: λ ≈ 0.1732867951
DEFAULT_HALF_LIFE_HOURS = 4.0
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_BULLISH_THRESHOLD = 0.2
DEFAULT_BEARISH_THRESHOLD = -0.2

FETCH_SENTIMENT_SQL = """
    SELECT boosted_score, created_at
    FROM sentiment_log
    WHERE ticker = ?
      AND created_at >= ?
    ORDER BY created_at DESC
"""


@dataclass
class BiasResult:
    """Result of bias calculation for a ticker.

    Attributes:
        ticker: NSE ticker symbol.
        bias: Classification — 'BULLISH', 'NEUTRAL', or 'BEARISH'.
        score: Weighted average sentiment score (-1.0 to 1.0).
        confidence: Confidence based on article count and score consistency.
        article_count: Number of articles used in the calculation.
        timestamp: When the bias was calculated.

    """

    ticker: str = ""
    bias: str = "NEUTRAL"
    score: float = 0.0
    confidence: float = 0.0
    article_count: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class BiasCalculator:
    """Aggregates sentiment with exponential time decay to produce trading bias.

    The calculator:
    - Fetches sentiment scores from the last 24 hours (configurable)
    - Applies exponential decay: weight = exp(-λ × hours_ago)
      where λ = ln(2) / half_life_hours
    - Computes weighted average: score = Σ(score × weight) / Σ(weight)
    - Classifies: BULLISH (>0.2), BEARISH (<-0.2), NEUTRAL (otherwise)
    - Caches the latest bias per ticker in memory

    Requirements: 8.1, 8.2, 8.3
    """

    def __init__(
        self,
        db_manager: DatabaseConnectionManager | None = None,
        half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
        bullish_threshold: float = DEFAULT_BULLISH_THRESHOLD,
        bearish_threshold: float = DEFAULT_BEARISH_THRESHOLD,
    ) -> None:
        """Initialize the bias calculator.

        Args:
            db_manager: Database connection manager for querying sentiment_log.
            half_life_hours: Half-life for exponential decay in hours.
            lookback_hours: How many hours of sentiment to aggregate.
            bullish_threshold: Score above which bias is BULLISH.
            bearish_threshold: Score below which bias is BEARISH.

        """
        self._db_manager = db_manager
        self._half_life_hours = half_life_hours
        self._lookback_hours = lookback_hours
        self._bullish_threshold = bullish_threshold
        self._bearish_threshold = bearish_threshold

        # λ = ln(2) / half_life
        self._decay_lambda = math.log(2) / self._half_life_hours

        # In-memory cache: ticker -> latest BiasResult
        self._cache: dict[str, BiasResult] = {}

        logger.info(
            f"BiasCalculator initialized: half_life={half_life_hours}h, "
            f"lookback={lookback_hours}h, λ={self._decay_lambda:.6f}, "
            f"thresholds=[{bearish_threshold}, {bullish_threshold}]",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_bias(
        self,
        ticker: str,
        now: datetime | None = None,
    ) -> BiasResult:
        """Calculate bias for a ticker by aggregating recent sentiment.

        Fetches all sentiment scores from the last ``lookback_hours``,
        applies exponential time decay, and computes a weighted average.

        Args:
            ticker: NSE ticker symbol.
            now: Reference time for the calculation (defaults to UTC now).

        Returns:
            BiasResult with score, classification, and metadata.

        Requirements: 8.1, 8.2

        """
        if now is None:
            now = datetime.now(UTC)

        # Fetch sentiment data
        sentiment_rows = self._fetch_sentiment(ticker, now)

        if not sentiment_rows:
            result = BiasResult(
                ticker=ticker,
                bias="NEUTRAL",
                score=0.0,
                confidence=0.0,
                article_count=0,
                timestamp=now,
            )
            self._cache[ticker] = result
            logger.info(
                f"Bias for {ticker}: NEUTRAL (no articles in last "
                f"{self._lookback_hours}h)",
            )
            return result

        # Calculate weighted average with time decay
        score, confidence = self._compute_weighted_score(sentiment_rows, now)

        # Classify
        bias = self._classify(score)

        result = BiasResult(
            ticker=ticker,
            bias=bias,
            score=round(score, 6),
            confidence=round(confidence, 4),
            article_count=len(sentiment_rows),
            timestamp=now,
        )

        self._cache[ticker] = result

        logger.info(
            f"Bias for {ticker}: {bias} (score={score:.4f}, "
            f"confidence={confidence:.4f}, articles={len(sentiment_rows)})",
        )
        return result

    def get_current_bias(self, ticker: str) -> BiasResult | None:
        """Retrieve the most recently cached bias for a ticker.

        Returns:
            The cached BiasResult, or None if no bias has been calculated.

        """
        return self._cache.get(ticker)

    # ------------------------------------------------------------------
    # Time decay helpers
    # ------------------------------------------------------------------

    def compute_decay_weight(self, hours_ago: float) -> float:
        """Compute the exponential decay weight for a given age.

        Formula: weight = exp(-λ × hours_ago)
        where λ = ln(2) / half_life_hours

        At hours_ago == half_life, weight ≈ 0.5.

        Args:
            hours_ago: Age of the sentiment score in hours.

        Returns:
            Decay weight in (0, 1].

        """
        return math.exp(-self._decay_lambda * hours_ago)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_sentiment(
        self,
        ticker: str,
        now: datetime,
    ) -> list[tuple[float, datetime]]:
        """Fetch sentiment scores from the last ``lookback_hours``.

        Returns list of (boosted_score, created_at) tuples.

        Requirements: 8.1
        """
        if self._db_manager is None:
            logger.warning("No database manager configured, returning empty sentiment")
            return []

        cutoff = now - timedelta(hours=self._lookback_hours)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        try:
            conn = self._db_manager.connect_sqlite()
            cursor = conn.execute(FETCH_SENTIMENT_SQL, (ticker, cutoff_str))
            rows = cursor.fetchall()

            result: list[tuple[float, datetime]] = []
            for row in rows:
                score = float(row["boosted_score"])
                created_str = row["created_at"]
                # Parse the timestamp — SQLite stores as string
                try:
                    created_at = datetime.strptime(
                        created_str, "%Y-%m-%d %H:%M:%S",
                    ).replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    # Try ISO format as fallback
                    try:
                        created_at = datetime.fromisoformat(
                            created_str,
                        ).replace(tzinfo=UTC)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Skipping row with unparseable timestamp: {created_str}",
                        )
                        continue
                result.append((score, created_at))

            logger.debug(
                f"Fetched {len(result)} sentiment rows for {ticker} "
                f"(cutoff={cutoff_str})",
            )
            return result

        except Exception as e:
            logger.error(f"Failed to fetch sentiment for {ticker}: {e}")
            return []

    def _compute_weighted_score(
        self,
        sentiment_rows: list[tuple[float, datetime]],
        now: datetime,
    ) -> tuple[float, float]:
        """Compute the weighted average score using exponential time decay.

        bias_score = Σ(sentiment_score × weight) / Σ(weight)

        Confidence is derived from article count and score consistency:
        - More articles → higher confidence (capped at 1.0)
        - Lower variance → higher confidence

        Args:
            sentiment_rows: List of (score, timestamp) tuples.
            now: Reference time for decay calculation.

        Returns:
            (weighted_score, confidence) tuple.

        Requirements: 8.2

        """
        weighted_sum = 0.0
        weight_total = 0.0

        for score, created_at in sentiment_rows:
            hours_ago = (now - created_at).total_seconds() / 3600.0
            # Clamp to non-negative (in case of clock skew)
            hours_ago = max(0.0, hours_ago)
            weight = self.compute_decay_weight(hours_ago)
            weighted_sum += score * weight
            weight_total += weight

        if weight_total == 0.0:
            return 0.0, 0.0

        weighted_score = weighted_sum / weight_total

        # Confidence calculation:
        # - Article count factor: min(article_count / 10, 1.0)
        # - Consistency factor: 1 - normalised weighted variance
        article_count = len(sentiment_rows)
        count_factor = min(article_count / 10.0, 1.0)

        # Weighted variance
        variance_sum = 0.0
        for score, created_at in sentiment_rows:
            hours_ago = max(0.0, (now - created_at).total_seconds() / 3600.0)
            weight = self.compute_decay_weight(hours_ago)
            variance_sum += weight * (score - weighted_score) ** 2

        weighted_variance = variance_sum / weight_total
        # Normalise variance (max possible variance for scores in [-1,1] is 4)
        consistency_factor = max(0.0, 1.0 - weighted_variance / 4.0)

        confidence = count_factor * consistency_factor
        return weighted_score, confidence

    def _classify(self, score: float) -> str:
        """Classify a bias score into BULLISH, BEARISH, or NEUTRAL.

        Requirements: 8.3
        """
        if score > self._bullish_threshold:
            return "BULLISH"
        if score < self._bearish_threshold:
            return "BEARISH"
        return "NEUTRAL"
