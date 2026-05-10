"""RSS Feed Poller for The Commander - News Ingestion.

Polls financial news RSS feeds from MoneyControl, Economic Times, and LiveMint
every 60 seconds, extracting article data for sentiment analysis.

Requirements: 5.1, 5.3
"""

import hashlib
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import mktime

import feedparser

logger = logging.getLogger(__name__)


@dataclass
class RSSSource:
    """Configuration for an RSS feed source."""

    name: str
    url: str


@dataclass
class NewsArticle:
    """Represents a news article fetched from an RSS feed.

    Attributes:
        article_id: Unique identifier (UUID)
        source: Name of the RSS feed source
        title: Article title
        content: Article content/summary
        url: Link to the full article
        published_at: When the article was published
        fetched_at: When the article was fetched by the poller
        content_hash: SHA256 hash of title + first 200 chars of content

    """

    article_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""


# Default RSS feed sources for Indian financial news
DEFAULT_RSS_SOURCES = [
    RSSSource(name="MoneyControl", url="https://www.moneycontrol.com/rss/latestnews.xml"),
    RSSSource(name="EconomicTimes", url="https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    RSSSource(name="LiveMint", url="https://www.livemint.com/rss/markets"),
]


def compute_content_hash(title: str, content: str) -> str:
    """Compute SHA256 hash for deduplication.

    Uses title + first 200 characters of content.

    Args:
        title: Article title
        content: Article content/summary

    Returns:
        Hex-encoded SHA256 hash string

    """
    raw = title + content[:200]
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_entry(entry: dict, source_name: str) -> NewsArticle:
    """Parse a single feedparser entry into a NewsArticle.

    Args:
        entry: A feedparser entry dict
        source_name: Name of the RSS source

    Returns:
        NewsArticle with extracted fields

    """
    title = entry.get("title", "").strip()

    # Extract content: prefer summary, fall back to description
    content = ""
    if "summary" in entry:
        content = entry["summary"].strip()
    elif "description" in entry:
        content = entry["description"].strip()

    url = entry.get("link", "").strip()

    # Parse published date
    published_at = datetime.now(UTC)
    if entry.get("published_parsed"):
        try:
            published_at = datetime.fromtimestamp(
                mktime(entry["published_parsed"]), tz=UTC,
            )
        except (ValueError, OverflowError, OSError):
            pass
    elif entry.get("updated_parsed"):
        try:
            published_at = datetime.fromtimestamp(
                mktime(entry["updated_parsed"]), tz=UTC,
            )
        except (ValueError, OverflowError, OSError):
            pass

    content_hash = compute_content_hash(title, content)

    return NewsArticle(
        article_id=str(uuid.uuid4()),
        source=source_name,
        title=title,
        content=content,
        url=url,
        published_at=published_at,
        fetched_at=datetime.now(UTC),
        content_hash=content_hash,
    )


def fetch_feed(source: RSSSource) -> list[NewsArticle]:
    """Fetch and parse articles from a single RSS feed source.

    Args:
        source: RSS source configuration

    Returns:
        List of parsed NewsArticle objects

    """
    articles: list[NewsArticle] = []

    try:
        feed = feedparser.parse(source.url)

        if feed.bozo and not feed.entries:
            logger.warning(
                f"RSS feed parse error for {source.name}: {feed.bozo_exception}",
            )
            return articles

        for entry in feed.entries:
            try:
                article = parse_entry(entry, source.name)
                articles.append(article)
            except Exception as e:
                logger.error(
                    f"Error parsing entry from {source.name}: {e}",
                    exc_info=True,
                )

        logger.info(f"Fetched {len(articles)} articles from {source.name}")

    except Exception as e:
        logger.error(f"Failed to fetch RSS feed from {source.name}: {e}", exc_info=True)

    return articles


class RSSPoller:
    """RSS Feed Poller for financial news sources.

    Polls MoneyControl, Economic Times, and LiveMint RSS feeds at a
    configurable interval (default 60 seconds). Extracts title, content,
    url, published_at, and source from each article.

    Requirements: 5.1, 5.3
    """

    def __init__(self, sources: list[RSSSource] | None = None):
        """Initialize RSS Poller with feed sources.

        Args:
            sources: List of RSS feed sources. Uses defaults if None.

        """
        self.sources = sources if sources is not None else DEFAULT_RSS_SOURCES
        self._timer: threading.Timer | None = None
        self._running = False
        self._lock = threading.Lock()
        self._on_articles: Callable[[list[NewsArticle]], None] | None = None

    @property
    def is_running(self) -> bool:
        """Whether the poller is currently running."""
        return self._running

    def on_articles(self, callback: Callable[[list[NewsArticle]], None]) -> None:
        """Register a callback for when new articles are fetched.

        Args:
            callback: Function called with list of fetched articles

        """
        self._on_articles = callback

    def poll_once(self) -> list[NewsArticle]:
        """Perform a single poll of all configured RSS sources.

        Returns:
            List of all fetched NewsArticle objects from all sources

        """
        all_articles: list[NewsArticle] = []

        for source in self.sources:
            articles = fetch_feed(source)
            all_articles.extend(articles)

        logger.info(
            f"Poll complete: {len(all_articles)} total articles "
            f"from {len(self.sources)} sources",
        )

        if self._on_articles and all_articles:
            try:
                self._on_articles(all_articles)
            except Exception as e:
                logger.error(f"Error in articles callback: {e}", exc_info=True)

        return all_articles

    def start_polling(self, interval_seconds: int = 60) -> None:
        """Start periodic polling of RSS feeds.

        Args:
            interval_seconds: Seconds between polls (default 60)

        """
        with self._lock:
            if self._running:
                logger.warning("RSS poller is already running")
                return

            self._running = True
            logger.info(
                f"Starting RSS poller with {interval_seconds}s interval "
                f"for {len(self.sources)} sources",
            )
            self._schedule_poll(interval_seconds)

    def stop_polling(self) -> None:
        """Stop periodic polling."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            logger.info("RSS poller stopped")

    def _schedule_poll(self, interval_seconds: int) -> None:
        """Schedule the next poll cycle."""
        if not self._running:
            return

        def _run() -> None:
            if not self._running:
                return
            try:
                self.poll_once()
            except Exception as e:
                logger.error(f"Error during scheduled poll: {e}", exc_info=True)
            finally:
                if self._running:
                    self._schedule_poll(interval_seconds)

        self._timer = threading.Timer(interval_seconds, _run)
        self._timer.daemon = True
        self._timer.start()
