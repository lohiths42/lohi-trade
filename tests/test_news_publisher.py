"""Unit tests for NewsPublisher.

Validates that unique news articles are published to stream:news
and stored in the SQLite news_articles table.

Requirements: 5.6, 5.7
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.commander.news_publisher import (
    NEWS_STREAM_MAXLEN,
    NEWS_STREAM_NAME,
    NewsPublisher,
)
from src.commander.rss_poller import NewsArticle


def _make_article(**overrides) -> NewsArticle:
    defaults = dict(
        article_id="test-uuid-001",
        source="MoneyControl",
        title="Reliance Q3 results beat estimates",
        content="Reliance Industries reported strong quarterly results...",
        url="https://example.com/article/1",
        published_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        fetched_at=datetime(2024, 1, 15, 10, 0, 5, tzinfo=UTC),
        content_hash="abc123def456",
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


class TestNewsPublisherStreamPublishing:
    """Tests for publishing articles to the Redis stream."""

    def test_publishes_to_stream_news(self):
        """Articles should be published to stream:news."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        article = _make_article()
        publisher.publish(article)

        event_bus.publish.assert_called_once()
        assert event_bus.publish.call_args[0][0] == NEWS_STREAM_NAME

    def test_publishes_with_correct_maxlen(self):
        """Publish should use maxlen=5000."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        publisher.publish(_make_article())

        assert event_bus.publish.call_args[1]["maxlen"] == NEWS_STREAM_MAXLEN

    def test_serializes_all_required_fields(self):
        """Published message should contain all stream:news fields from the design."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        ts_pub = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        ts_fetch = datetime(2024, 1, 15, 10, 0, 5, tzinfo=UTC)
        article = _make_article(
            article_id="id-42",
            source="EconomicTimes",
            title="TCS wins mega deal",
            content="TCS announced a multi-billion dollar deal...",
            url="https://example.com/tcs",
            published_at=ts_pub,
            fetched_at=ts_fetch,
            content_hash="hash999",
        )
        publisher.publish(article)

        message = event_bus.publish.call_args[0][1]
        assert message["article_id"] == "id-42"
        assert message["source"] == "EconomicTimes"
        assert message["title"] == "TCS wins mega deal"
        assert message["content"] == "TCS announced a multi-billion dollar deal..."
        assert message["url"] == "https://example.com/tcs"
        assert message["published_at"] == ts_pub.isoformat()
        assert message["fetched_at"] == ts_fetch.isoformat()
        assert message["content_hash"] == "hash999"


class TestNewsPublisherSQLiteStorage:
    """Tests for storing articles in SQLite."""

    def test_stores_article_in_sqlite(self):
        """Each published article should be persisted via execute_with_retry."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        article = _make_article(article_id="store-001")
        publisher.publish(article)

        db.execute_with_retry.assert_called_once()
        sql = db.execute_with_retry.call_args[0][0]
        assert "INSERT" in sql
        assert "news_articles" in sql

    def test_stores_correct_params(self):
        """SQL params should match the article fields."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        ts_pub = datetime(2024, 2, 1, 9, 0, 0, tzinfo=UTC)
        ts_fetch = datetime(2024, 2, 1, 9, 0, 3, tzinfo=UTC)
        article = _make_article(
            article_id="param-check",
            source="LiveMint",
            title="HDFC merger update",
            content="HDFC Bank merger progresses...",
            url="https://example.com/hdfc",
            published_at=ts_pub,
            fetched_at=ts_fetch,
            content_hash="hashXYZ",
        )
        publisher.publish(article)

        params = db.execute_with_retry.call_args[0][1]
        assert params[0] == "param-check"
        assert params[1] == "LiveMint"
        assert params[2] == "HDFC merger update"
        assert params[3] == "HDFC Bank merger progresses..."
        assert params[4] == "https://example.com/hdfc"
        assert params[5] == ts_pub.isoformat()
        assert params[6] == ts_fetch.isoformat()
        assert params[7] == "hashXYZ"


class TestNewsPublisherBatch:
    """Tests for batch publishing."""

    def test_publish_batch_publishes_all(self):
        """publish_batch should publish every article in the list."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        articles = [
            _make_article(article_id="b1"),
            _make_article(article_id="b2"),
            _make_article(article_id="b3"),
        ]
        count = publisher.publish_batch(articles)

        assert count == 3
        assert event_bus.publish.call_count == 3
        assert db.execute_with_retry.call_count == 3

    def test_publish_batch_continues_on_failure(self):
        """If one article fails, the rest should still be published."""
        event_bus = MagicMock()
        # Fail on the second publish call
        event_bus.publish.side_effect = [
            "msg-1",
            ConnectionError("Redis down"),
            "msg-3",
        ]
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        articles = [
            _make_article(article_id="f1"),
            _make_article(article_id="f2"),
            _make_article(article_id="f3"),
        ]
        count = publisher.publish_batch(articles)

        # f1 succeeds, f2 fails (stream publish raises before sqlite), f3 succeeds
        assert count == 2

    def test_publish_batch_empty_list(self):
        """An empty list should return 0 and make no calls."""
        event_bus = MagicMock()
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        count = publisher.publish_batch([])
        assert count == 0
        event_bus.publish.assert_not_called()
        db.execute_with_retry.assert_not_called()


class TestNewsPublisherErrorHandling:
    """Tests for error handling."""

    def test_stream_failure_does_not_crash(self):
        """If EventBus.publish raises, publish should propagate the error."""
        event_bus = MagicMock()
        event_bus.publish.side_effect = ConnectionError("Redis down")
        db = MagicMock()
        publisher = NewsPublisher(event_bus, db)

        with pytest.raises(ConnectionError):
            publisher.publish(_make_article())

    def test_sqlite_failure_does_not_crash(self):
        """If db.execute_with_retry raises, publish should propagate the error."""
        event_bus = MagicMock()
        db = MagicMock()
        db.execute_with_retry.side_effect = Exception("DB locked")
        publisher = NewsPublisher(event_bus, db)

        with pytest.raises(Exception, match="DB locked"):
            publisher.publish(_make_article())
