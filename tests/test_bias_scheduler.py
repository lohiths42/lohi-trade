"""Tests for BiasScheduler.

Covers:
- Scheduler start/stop lifecycle
- publish_bias publishes correct fields to stream:bias:{ticker}
- store_bias inserts into bias_log table
- Market hours check

Requirements: 8.4, 8.5, 8.6
"""

import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.commander.bias_calculator import BiasResult
from src.commander.bias_scheduler import (
    IST_OFFSET,
    BiasScheduler,
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
                CREATE TABLE IF NOT EXISTS sentiment_log (
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
            """
            )
        return self._sqlite_conn


def _make_result(
    ticker: str = "RELIANCE",
    bias: str = "BULLISH",
    score: float = 0.35,
    confidence: float = 0.8,
    article_count: int = 5,
    ts: datetime | None = None,
) -> BiasResult:
    return BiasResult(
        ticker=ticker,
        bias=bias,
        score=score,
        confidence=confidence,
        article_count=article_count,
        timestamp=ts or datetime(2025, 1, 15, 5, 0, 0, tzinfo=UTC),
    )


def _utc_for_ist(hour: int, minute: int = 0) -> datetime:
    """Return a UTC datetime whose IST equivalent is hour:minute on a weekday."""
    ist_dt = datetime(2025, 1, 15, hour, minute, 0, tzinfo=UTC)
    return ist_dt - IST_OFFSET


# ---------------------------------------------------------------------------
# Market hours
# ---------------------------------------------------------------------------


class TestMarketHours:
    def test_during_market_hours(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(10, 0)  # 10:00 IST
        assert scheduler.is_market_hours(now) is True

    def test_before_market_open(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(9, 0)  # 09:00 IST — before 09:15
        assert scheduler.is_market_hours(now) is False

    def test_after_market_close(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(16, 0)  # 16:00 IST — after 15:30
        assert scheduler.is_market_hours(now) is False

    def test_at_market_open_boundary(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(9, 15)  # exactly 09:15 IST
        assert scheduler.is_market_hours(now) is True

    def test_at_market_close_boundary(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(15, 30)  # exactly 15:30 IST
        assert scheduler.is_market_hours(now) is True


# ---------------------------------------------------------------------------
# publish_bias
# ---------------------------------------------------------------------------


class TestPublishBias:
    def test_publishes_correct_fields(self):
        mock_bus = MagicMock()
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            event_bus=mock_bus,
        )
        result = _make_result()
        scheduler.publish_bias(result)

        mock_bus.publish.assert_called_once()
        args, kwargs = mock_bus.publish.call_args
        stream_name = args[0]
        message = args[1]

        assert stream_name == "stream:bias:RELIANCE"
        assert message["ticker"] == "RELIANCE"
        assert message["bias"] == "BULLISH"
        assert message["score"] == "0.35"
        assert message["confidence"] == "0.8"
        assert message["article_count"] == "5"
        assert "timestamp" in message
        assert kwargs.get("maxlen") == 100

    def test_skips_when_no_event_bus(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            event_bus=None,
        )
        # Should not raise
        scheduler.publish_bias(_make_result())

    def test_publishes_to_correct_stream_per_ticker(self):
        mock_bus = MagicMock()
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["TCS"],
            event_bus=mock_bus,
        )
        scheduler.publish_bias(_make_result(ticker="TCS"))
        stream_name = mock_bus.publish.call_args[0][0]
        assert stream_name == "stream:bias:TCS"


# ---------------------------------------------------------------------------
# store_bias
# ---------------------------------------------------------------------------


class TestStoreBias:
    def test_inserts_into_bias_log(self):
        db = InMemoryDBManager()
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            db_manager=db,
        )
        result = _make_result()
        scheduler.store_bias(result)

        conn = db.connect_sqlite()
        row = conn.execute("SELECT * FROM bias_log WHERE ticker = 'RELIANCE'").fetchone()
        assert row is not None
        assert row["ticker"] == "RELIANCE"
        assert row["bias"] == "BULLISH"
        assert float(row["score"]) == pytest.approx(0.35)
        assert float(row["confidence"]) == pytest.approx(0.8)
        assert row["article_count"] == 5

    def test_skips_when_no_db_manager(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            db_manager=None,
        )
        # Should not raise
        scheduler.store_bias(_make_result())

    def test_stores_multiple_entries(self):
        db = InMemoryDBManager()
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            db_manager=db,
        )
        scheduler.store_bias(_make_result(score=0.1, bias="NEUTRAL"))
        scheduler.store_bias(_make_result(score=0.4, bias="BULLISH"))

        conn = db.connect_sqlite()
        rows = conn.execute("SELECT * FROM bias_log ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["bias"] == "NEUTRAL"
        assert rows[1]["bias"] == "BULLISH"


# ---------------------------------------------------------------------------
# Scheduler start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_sets_running(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            interval_seconds=60,
        )
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()

    def test_stop_clears_running(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            interval_seconds=60,
        )
        scheduler.start()
        scheduler.stop()
        assert scheduler.is_running is False

    def test_double_start_is_safe(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
            interval_seconds=60,
        )
        scheduler.start()
        scheduler.start()  # should not raise
        assert scheduler.is_running is True
        scheduler.stop()

    def test_stop_without_start_is_safe(self):
        scheduler = BiasScheduler(
            bias_calculator=MagicMock(),
            tickers=["RELIANCE"],
        )
        scheduler.stop()  # should not raise
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# recalculate_all
# ---------------------------------------------------------------------------


class TestRecalculateAll:
    def test_skips_outside_market_hours(self):
        calc = MagicMock()
        scheduler = BiasScheduler(
            bias_calculator=calc,
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(8, 0)  # 08:00 IST — before market
        results = scheduler.recalculate_all(now=now)
        assert results == []
        calc.calculate_bias.assert_not_called()

    def test_recalculates_during_market_hours(self):
        result = _make_result()
        calc = MagicMock()
        calc.calculate_bias.return_value = result

        scheduler = BiasScheduler(
            bias_calculator=calc,
            tickers=["RELIANCE"],
        )
        now = _utc_for_ist(10, 0)
        results = scheduler.recalculate_all(now=now)
        assert len(results) == 1
        assert results[0].ticker == "RELIANCE"
        calc.calculate_bias.assert_called_once_with("RELIANCE", now=now)

    def test_recalculates_all_tickers(self):
        calc = MagicMock()
        calc.calculate_bias.side_effect = [
            _make_result(ticker="RELIANCE"),
            _make_result(ticker="TCS"),
        ]
        scheduler = BiasScheduler(
            bias_calculator=calc,
            tickers=["RELIANCE", "TCS"],
        )
        now = _utc_for_ist(12, 0)
        results = scheduler.recalculate_all(now=now)
        assert len(results) == 2
        assert calc.calculate_bias.call_count == 2

    def test_continues_on_single_ticker_error(self):
        calc = MagicMock()
        calc.calculate_bias.side_effect = [
            RuntimeError("db error"),
            _make_result(ticker="TCS"),
        ]
        scheduler = BiasScheduler(
            bias_calculator=calc,
            tickers=["RELIANCE", "TCS"],
        )
        now = _utc_for_ist(12, 0)
        results = scheduler.recalculate_all(now=now)
        # Only TCS should succeed
        assert len(results) == 1
        assert results[0].ticker == "TCS"
