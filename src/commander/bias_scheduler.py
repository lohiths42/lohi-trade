"""
Bias Recalculation Scheduler for The Commander.

Periodically recalculates sentiment bias for all configured tickers during
market hours. Publishes results to Redis Streams and stores them in the
bias_log SQLite table.

Requirements: 8.4, 8.5, 8.6
"""

import logging
import threading
from datetime import datetime, time, timezone, timedelta
from typing import List, Optional

from src.commander.bias_calculator import BiasCalculator, BiasResult
from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus

logger = logging.getLogger(__name__)

# IST offset: UTC+5:30
IST_OFFSET = timedelta(hours=5, minutes=30)

# Default market hours (IST)
DEFAULT_MARKET_OPEN = time(9, 15)
DEFAULT_MARKET_CLOSE = time(15, 30)

# Default recalculation interval in seconds
DEFAULT_INTERVAL_SECONDS = 5 * 60  # 5 minutes

INSERT_BIAS_SQL = """
    INSERT INTO bias_log (ticker, bias, score, confidence, article_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
"""


class BiasScheduler:
    """
    Schedules periodic bias recalculation during market hours.

    For each configured ticker the scheduler:
    1. Calls BiasCalculator.calculate_bias()
    2. Publishes the result to stream:bias:{ticker} via EventBus
    3. Stores the result in the bias_log SQLite table

    Requirements: 8.4, 8.5, 8.6
    """

    def __init__(
        self,
        bias_calculator: BiasCalculator,
        tickers: List[str],
        event_bus: Optional[EventBus] = None,
        db_manager: Optional[DatabaseConnectionManager] = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        market_open: time = DEFAULT_MARKET_OPEN,
        market_close: time = DEFAULT_MARKET_CLOSE,
    ) -> None:
        self._calculator = bias_calculator
        self._tickers = list(tickers)
        self._event_bus = event_bus
        self._db_manager = db_manager
        self._interval = interval_seconds
        self._market_open = market_open
        self._market_close = market_close

        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()

        logger.info(
            f"BiasScheduler created: tickers={self._tickers}, "
            f"interval={self._interval}s, "
            f"market_hours={self._market_open}-{self._market_close}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the periodic bias recalculation scheduler."""
        with self._lock:
            if self._running:
                logger.warning("BiasScheduler is already running")
                return
            self._running = True
            logger.info("BiasScheduler started")
            self._schedule_next()

    def stop(self) -> None:
        """Stop the scheduler."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            logger.info("BiasScheduler stopped")

    def is_market_hours(self, now: Optional[datetime] = None) -> bool:
        """
        Check whether the current time falls within market hours (IST).

        Args:
            now: Reference time in UTC. Defaults to current UTC time.

        Returns:
            True if within market_open–market_close IST window.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        ist_time = (now + IST_OFFSET).time()
        return self._market_open <= ist_time <= self._market_close

    def recalculate_all(self, now: Optional[datetime] = None) -> List[BiasResult]:
        """
        Recalculate bias for every ticker, publish and store results.

        Skips execution when outside market hours.

        Returns:
            List of BiasResult objects (empty if outside market hours).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if not self.is_market_hours(now):
            logger.debug("Outside market hours — skipping bias recalculation")
            return []

        results: List[BiasResult] = []
        for ticker in self._tickers:
            try:
                result = self._calculator.calculate_bias(ticker, now=now)
                self.publish_bias(result)
                self.store_bias(result)
                results.append(result)
            except Exception as e:
                logger.error(f"Error recalculating bias for {ticker}: {e}")

        logger.info(f"Bias recalculation complete: {len(results)}/{len(self._tickers)} tickers")
        return results

    # ------------------------------------------------------------------
    # Publish / Store helpers
    # ------------------------------------------------------------------

    def publish_bias(self, result: BiasResult) -> None:
        """
        Publish a BiasResult to stream:bias:{ticker}.

        Requirements: 8.5
        """
        if self._event_bus is None:
            logger.debug("No EventBus configured — skipping publish")
            return

        stream_name = f"stream:bias:{result.ticker}"
        message = {
            "ticker": result.ticker,
            "bias": result.bias,
            "score": str(result.score),
            "confidence": str(result.confidence),
            "article_count": str(result.article_count),
            "timestamp": result.timestamp.isoformat(),
        }
        try:
            self._event_bus.publish(stream_name, message, maxlen=100)
            logger.debug(f"Published bias to {stream_name}")
        except Exception as e:
            logger.error(f"Failed to publish bias for {result.ticker}: {e}")

    def store_bias(self, result: BiasResult) -> None:
        """
        Store a BiasResult in the bias_log SQLite table.

        Requirements: 8.6
        """
        if self._db_manager is None:
            logger.debug("No DatabaseConnectionManager configured — skipping store")
            return

        created_at = result.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = self._db_manager.connect_sqlite()
            conn.execute(
                INSERT_BIAS_SQL,
                (
                    result.ticker,
                    result.bias,
                    result.score,
                    result.confidence,
                    result.article_count,
                    created_at,
                ),
            )
            conn.commit()
            logger.debug(f"Stored bias for {result.ticker} in bias_log")
        except Exception as e:
            logger.error(f"Failed to store bias for {result.ticker}: {e}")

    # ------------------------------------------------------------------
    # Internal scheduling
    # ------------------------------------------------------------------

    def _schedule_next(self) -> None:
        """Schedule the next recalculation cycle."""
        if not self._running:
            return

        def _run() -> None:
            if not self._running:
                return
            try:
                self.recalculate_all()
            except Exception as e:
                logger.error(f"Error in scheduled bias recalculation: {e}")
            finally:
                if self._running:
                    self._schedule_next()

        self._timer = threading.Timer(self._interval, _run)
        self._timer.daemon = True
        self._timer.start()
