"""Unit tests for NewsDeduplicator.

Requirements: 5.4, 5.5
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.commander.news_deduplicator import (
    HASH_KEY_PREFIX,
    HASH_TTL_SECONDS,
    NewsDeduplicator,
)
from src.commander.rss_poller import NewsArticle, compute_content_hash


def _make_article(title: str = "Test Article", content: str = "Some content") -> NewsArticle:
    """Helper to create a NewsArticle with a computed content_hash."""
    return NewsArticle(
        article_id=str(uuid.uuid4()),
        source="TestSource",
        title=title,
        content=content,
        url="https://example.com/article",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        content_hash=compute_content_hash(title, content),
    )


@pytest.fixture
def mock_redis():
    """Create a mock RedisClient."""
    return MagicMock()


@pytest.fixture
def deduplicator(mock_redis):
    """Create a NewsDeduplicator with a mock Redis client."""
    return NewsDeduplicator(mock_redis)


class TestIsDuplicate:
    """Tests for is_duplicate method."""

    def test_returns_false_when_hash_not_in_redis(self, deduplicator, mock_redis):
        mock_redis.get.return_value = None
        article = _make_article()

        assert deduplicator.is_duplicate(article) is False
        mock_redis.get.assert_called_once_with(f"{HASH_KEY_PREFIX}{article.content_hash}")

    def test_returns_true_when_hash_exists_in_redis(self, deduplicator, mock_redis):
        mock_redis.get.return_value = "some-article-id"
        article = _make_article()

        assert deduplicator.is_duplicate(article) is True


class TestMarkSeen:
    """Tests for mark_seen method."""

    def test_stores_hash_with_24h_ttl(self, deduplicator, mock_redis):
        article = _make_article()
        deduplicator.mark_seen(article)

        expected_key = f"{HASH_KEY_PREFIX}{article.content_hash}"
        mock_redis.set.assert_called_once_with(
            expected_key,
            article.article_id,
            ex=HASH_TTL_SECONDS,
        )

    def test_ttl_is_86400_seconds(self):
        assert HASH_TTL_SECONDS == 86400


class TestDeduplicate:
    """Tests for deduplicate method."""

    def test_all_unique_articles_are_retained(self, deduplicator, mock_redis):
        mock_redis.get.return_value = None
        articles = [
            _make_article("Article A", "Content A"),
            _make_article("Article B", "Content B"),
            _make_article("Article C", "Content C"),
        ]

        result = deduplicator.deduplicate(articles)

        assert len(result) == 3
        assert mock_redis.set.call_count == 3

    def test_duplicate_articles_are_discarded(self, deduplicator, mock_redis):
        # First call: not seen. Second call: already seen (same hash).
        mock_redis.get.side_effect = [None, "existing-id"]

        article1 = _make_article("Same Title", "Same Content")
        article2 = _make_article("Same Title", "Same Content")

        result = deduplicator.deduplicate([article1, article2])

        assert len(result) == 1
        assert result[0].article_id == article1.article_id

    def test_earliest_version_is_retained(self, deduplicator, mock_redis):
        """The first occurrence should be kept, later duplicates discarded."""
        mock_redis.get.side_effect = [None, "already-seen"]

        early = _make_article("Breaking News", "Details here")
        late = _make_article("Breaking News", "Details here")

        result = deduplicator.deduplicate([early, late])

        assert len(result) == 1
        assert result[0].article_id == early.article_id

    def test_mixed_unique_and_duplicate(self, deduplicator, mock_redis):
        # unique, duplicate, unique
        mock_redis.get.side_effect = [None, "existing-id", None]

        a = _make_article("A", "Content A")
        b = _make_article("B", "Content B")  # will be flagged as duplicate
        c = _make_article("C", "Content C")

        result = deduplicator.deduplicate([a, b, c])

        assert len(result) == 2
        assert result[0].article_id == a.article_id
        assert result[1].article_id == c.article_id

    def test_empty_list_returns_empty(self, deduplicator, mock_redis):
        result = deduplicator.deduplicate([])
        assert result == []
        mock_redis.get.assert_not_called()

    def test_within_batch_dedup(self, deduplicator, mock_redis):
        """When the same article appears twice in one batch, only the first is kept.

        The first call to get returns None (not seen), mark_seen stores it.
        The second call to get returns the stored id (now seen).
        """
        article = _make_article("Duplicate", "Same body")
        dup = _make_article("Duplicate", "Same body")

        # First get -> None, mark_seen stores it, second get -> found
        mock_redis.get.side_effect = [None, article.article_id]

        result = deduplicator.deduplicate([article, dup])

        assert len(result) == 1
        assert result[0].article_id == article.article_id

    def test_marks_each_unique_article_as_seen(self, deduplicator, mock_redis):
        mock_redis.get.return_value = None
        articles = [_make_article(f"Title {i}", f"Content {i}") for i in range(5)]

        deduplicator.deduplicate(articles)

        assert mock_redis.set.call_count == 5
        for call_args in mock_redis.set.call_args_list:
            # Verify TTL is always 24 hours
            assert call_args[1]["ex"] == HASH_TTL_SECONDS or call_args[0][2] == HASH_TTL_SECONDS


class TestKeyPrefix:
    """Tests for Redis key format."""

    def test_key_format(self, deduplicator):
        article = _make_article()
        key = deduplicator._key_for(article.content_hash)
        assert key == f"news:hash:{article.content_hash}"

    def test_key_prefix_constant(self):
        assert HASH_KEY_PREFIX == "news:hash:"
