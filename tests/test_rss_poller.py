"""Tests for RSS Feed Poller."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.commander.rss_poller import (
    DEFAULT_RSS_SOURCES,
    NewsArticle,
    RSSPoller,
    RSSSource,
    compute_content_hash,
    fetch_feed,
    parse_entry,
)


class TestComputeContentHash:
    """Tests for content hash computation."""

    def test_hash_is_deterministic(self):
        """Same inputs produce the same hash."""
        h1 = compute_content_hash("Title", "Content body here")
        h2 = compute_content_hash("Title", "Content body here")
        assert h1 == h2

    def test_different_titles_produce_different_hashes(self):
        """Different titles produce different hashes."""
        h1 = compute_content_hash("Title A", "Same content")
        h2 = compute_content_hash("Title B", "Same content")
        assert h1 != h2

    def test_uses_first_200_chars_of_content(self):
        """Hash only uses first 200 characters of content."""
        base_content = "A" * 200
        h1 = compute_content_hash("Title", base_content + "EXTRA")
        h2 = compute_content_hash("Title", base_content + "DIFFERENT")
        assert h1 == h2

    def test_hash_is_sha256_hex(self):
        """Hash is a valid SHA256 hex string (64 chars)."""
        h = compute_content_hash("Title", "Content")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestParseEntry:
    """Tests for parsing feedparser entries into NewsArticle."""

    def test_parse_basic_entry(self):
        """Parse an entry with all standard fields."""
        entry = {
            "title": "Market Rally Continues",
            "summary": "Nifty hits new highs amid strong buying.",
            "link": "https://example.com/article/1",
            "published_parsed": time.strptime("2024-01-15 10:30:00", "%Y-%m-%d %H:%M:%S"),
        }
        article = parse_entry(entry, "MoneyControl")

        assert article.title == "Market Rally Continues"
        assert article.content == "Nifty hits new highs amid strong buying."
        assert article.url == "https://example.com/article/1"
        assert article.source == "MoneyControl"
        assert article.content_hash != ""
        assert article.article_id != ""

    def test_parse_entry_with_description_fallback(self):
        """Use description when summary is not available."""
        entry = {
            "title": "Test Article",
            "description": "Description text here.",
            "link": "https://example.com/2",
        }
        article = parse_entry(entry, "EconomicTimes")
        assert article.content == "Description text here."

    def test_parse_entry_with_updated_parsed(self):
        """Use updated_parsed when published_parsed is missing."""
        entry = {
            "title": "Updated Article",
            "summary": "Content",
            "link": "https://example.com/3",
            "updated_parsed": time.strptime("2024-06-01 12:00:00", "%Y-%m-%d %H:%M:%S"),
        }
        article = parse_entry(entry, "LiveMint")
        assert article.published_at is not None

    def test_parse_entry_missing_fields(self):
        """Handle entry with missing optional fields gracefully."""
        entry = {}
        article = parse_entry(entry, "MoneyControl")

        assert article.title == ""
        assert article.content == ""
        assert article.url == ""
        assert article.source == "MoneyControl"
        assert article.content_hash != ""

    def test_parse_entry_strips_whitespace(self):
        """Title, content, and URL are stripped of whitespace."""
        entry = {
            "title": "  Padded Title  ",
            "summary": "  Padded Content  ",
            "link": "  https://example.com/4  ",
        }
        article = parse_entry(entry, "MoneyControl")
        assert article.title == "Padded Title"
        assert article.content == "Padded Content"
        assert article.url == "https://example.com/4"


class TestFetchFeed:
    """Tests for fetching and parsing RSS feeds."""

    @patch("src.commander.rss_poller.feedparser.parse")
    def test_fetch_feed_success(self, mock_parse):
        """Successfully fetch and parse articles from a feed."""
        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[
                {
                    "title": "Article 1",
                    "summary": "Summary 1",
                    "link": "https://example.com/1",
                },
                {
                    "title": "Article 2",
                    "summary": "Summary 2",
                    "link": "https://example.com/2",
                },
            ],
        )

        source = RSSSource(name="TestSource", url="https://example.com/rss")
        articles = fetch_feed(source)

        assert len(articles) == 2
        assert articles[0].title == "Article 1"
        assert articles[1].title == "Article 2"
        assert all(a.source == "TestSource" for a in articles)

    @patch("src.commander.rss_poller.feedparser.parse")
    def test_fetch_feed_bozo_with_no_entries(self, mock_parse):
        """Return empty list when feed has parse error and no entries."""
        mock_parse.return_value = MagicMock(
            bozo=True,
            bozo_exception=Exception("XML parse error"),
            entries=[],
        )

        source = RSSSource(name="BadFeed", url="https://example.com/bad")
        articles = fetch_feed(source)
        assert articles == []

    @patch("src.commander.rss_poller.feedparser.parse")
    def test_fetch_feed_bozo_with_entries(self, mock_parse):
        """Still return articles when feed has bozo flag but has entries."""
        mock_parse.return_value = MagicMock(
            bozo=True,
            entries=[
                {
                    "title": "Partial Article",
                    "summary": "Content",
                    "link": "https://example.com/partial",
                },
            ],
        )

        source = RSSSource(name="PartialFeed", url="https://example.com/partial")
        articles = fetch_feed(source)
        assert len(articles) == 1

    @patch("src.commander.rss_poller.feedparser.parse")
    def test_fetch_feed_network_error(self, mock_parse):
        """Return empty list on network error."""
        mock_parse.side_effect = Exception("Network timeout")

        source = RSSSource(name="DownFeed", url="https://example.com/down")
        articles = fetch_feed(source)
        assert articles == []

    @patch("src.commander.rss_poller.feedparser.parse")
    def test_fetch_feed_skips_bad_entries(self, mock_parse):
        """Skip entries that fail to parse, continue with others."""
        good_entry = {
            "title": "Good Article",
            "summary": "Good content",
            "link": "https://example.com/good",
        }
        # Create a bad entry that will cause parse_entry to fail
        bad_entry = MagicMock()
        bad_entry.get.side_effect = TypeError("bad entry")

        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[bad_entry, good_entry],
        )

        source = RSSSource(name="MixedFeed", url="https://example.com/mixed")
        articles = fetch_feed(source)
        assert len(articles) == 1
        assert articles[0].title == "Good Article"


class TestRSSPoller:
    """Tests for the RSSPoller class."""

    def test_default_sources(self):
        """Poller uses default sources when none provided."""
        poller = RSSPoller()
        assert len(poller.sources) == 3
        source_names = [s.name for s in poller.sources]
        assert "MoneyControl" in source_names
        assert "EconomicTimes" in source_names
        assert "LiveMint" in source_names

    def test_custom_sources(self):
        """Poller uses custom sources when provided."""
        custom = [RSSSource(name="Custom", url="https://custom.com/rss")]
        poller = RSSPoller(sources=custom)
        assert len(poller.sources) == 1
        assert poller.sources[0].name == "Custom"

    @patch("src.commander.rss_poller.fetch_feed")
    def test_poll_once(self, mock_fetch):
        """poll_once fetches from all sources and returns combined articles."""
        mock_fetch.side_effect = [
            [NewsArticle(title="A1", source="S1")],
            [NewsArticle(title="A2", source="S2")],
        ]

        sources = [
            RSSSource(name="S1", url="https://s1.com/rss"),
            RSSSource(name="S2", url="https://s2.com/rss"),
        ]
        poller = RSSPoller(sources=sources)
        articles = poller.poll_once()

        assert len(articles) == 2
        assert mock_fetch.call_count == 2

    @patch("src.commander.rss_poller.fetch_feed")
    def test_poll_once_invokes_callback(self, mock_fetch):
        """poll_once calls the on_articles callback with fetched articles."""
        mock_fetch.return_value = [NewsArticle(title="Callback Test")]

        sources = [RSSSource(name="S1", url="https://s1.com/rss")]
        poller = RSSPoller(sources=sources)

        received = []
        poller.on_articles(lambda articles: received.extend(articles))

        poller.poll_once()
        assert len(received) == 1
        assert received[0].title == "Callback Test"

    @patch("src.commander.rss_poller.fetch_feed")
    def test_poll_once_no_callback_on_empty(self, mock_fetch):
        """Callback is not invoked when no articles are fetched."""
        mock_fetch.return_value = []

        sources = [RSSSource(name="S1", url="https://s1.com/rss")]
        poller = RSSPoller(sources=sources)

        callback = MagicMock()
        poller.on_articles(callback)

        poller.poll_once()
        callback.assert_not_called()

    @patch("src.commander.rss_poller.fetch_feed")
    def test_poll_once_handles_callback_error(self, mock_fetch):
        """poll_once doesn't crash if callback raises an error."""
        mock_fetch.return_value = [NewsArticle(title="Error Test")]

        sources = [RSSSource(name="S1", url="https://s1.com/rss")]
        poller = RSSPoller(sources=sources)
        poller.on_articles(lambda _: (_ for _ in ()).throw(ValueError("callback error")))

        # Should not raise
        articles = poller.poll_once()
        assert len(articles) == 1

    def test_start_and_stop_polling(self):
        """Start and stop polling lifecycle."""
        poller = RSSPoller(sources=[])
        assert not poller.is_running

        poller.start_polling(interval_seconds=60)
        assert poller.is_running

        poller.stop_polling()
        assert not poller.is_running

    def test_start_polling_twice_is_noop(self):
        """Starting polling when already running does nothing."""
        poller = RSSPoller(sources=[])
        poller.start_polling(interval_seconds=60)
        poller.start_polling(interval_seconds=60)  # Should not raise
        assert poller.is_running
        poller.stop_polling()

    def test_stop_polling_when_not_running(self):
        """Stopping when not running does nothing."""
        poller = RSSPoller(sources=[])
        poller.stop_polling()  # Should not raise
        assert not poller.is_running


class TestNewsArticleDataclass:
    """Tests for the NewsArticle dataclass."""

    def test_default_values(self):
        """NewsArticle has sensible defaults."""
        article = NewsArticle()
        assert article.article_id != ""
        assert article.source == ""
        assert article.title == ""
        assert article.content == ""
        assert article.url == ""
        assert isinstance(article.published_at, datetime)
        assert isinstance(article.fetched_at, datetime)
        assert article.content_hash == ""

    def test_custom_values(self):
        """NewsArticle accepts custom values."""
        article = NewsArticle(
            article_id="test-id",
            source="MoneyControl",
            title="Test Title",
            content="Test Content",
            url="https://example.com",
            content_hash="abc123",
        )
        assert article.article_id == "test-id"
        assert article.source == "MoneyControl"
        assert article.title == "Test Title"


class TestRSSSource:
    """Tests for the RSSSource dataclass."""

    def test_creation(self):
        """RSSSource stores name and url."""
        source = RSSSource(name="Test", url="https://test.com/rss")
        assert source.name == "Test"
        assert source.url == "https://test.com/rss"


class TestDefaultSources:
    """Tests for default RSS source configuration."""

    def test_three_default_sources(self):
        """There are exactly 3 default sources."""
        assert len(DEFAULT_RSS_SOURCES) == 3

    def test_default_sources_have_urls(self):
        """All default sources have non-empty URLs."""
        for source in DEFAULT_RSS_SOURCES:
            assert source.url != ""
            assert source.url.startswith("https://")

    def test_default_sources_have_names(self):
        """All default sources have non-empty names."""
        for source in DEFAULT_RSS_SOURCES:
            assert source.name != ""
