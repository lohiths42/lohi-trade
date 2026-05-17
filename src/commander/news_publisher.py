"""News Publisher for The Commander.

Publishes unique news articles to the Event Bus (stream:news) and stores
them in the SQLite news_articles table for later sentiment analysis.

Requirements: 5.6, 5.7
"""

import time

from src.commander.rss_poller import NewsArticle
from src.state.database import DatabaseConnectionManager
from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("NewsPublisher")

NEWS_STREAM_NAME = "stream:news"
NEWS_STREAM_MAXLEN = 5000

INSERT_NEWS_ARTICLE_SQL = """
    INSERT OR IGNORE INTO news_articles
        (article_id, source, title, content, url, published_at, fetched_at, content_hash)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


class NewsPublisher:
    """Publishes unique news articles to Redis Stream and stores them in SQLite.

    Publishes to ``stream:news`` with maxlen=5000 and persists each article
    in the ``news_articles`` table.  The sentiment column is left NULL at
    ingestion time and will be filled later by the sentiment analyser.

    Requirements: 5.6, 5.7
    """

    def __init__(self, event_bus: EventBus, db_manager: DatabaseConnectionManager) -> None:
        self._event_bus = event_bus
        self._db = db_manager
        logger.info("NewsPublisher initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(self, article: NewsArticle) -> None:
        """Publish a single article to the Event Bus and store in SQLite.

        Args:
            article: The unique news article to publish.

        """
        start = time.monotonic()

        self._publish_to_stream(article)
        self._store_in_sqlite(article)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"Published article '{article.title[:60]}' in {elapsed_ms:.2f}ms",
            extra={
                "article_id": article.article_id,
                "source": article.source,
                "latency_ms": round(elapsed_ms, 2),
            },
        )

        if elapsed_ms > 5000:
            logger.warning(
                f"News publish latency {elapsed_ms:.2f}ms exceeds 5000ms threshold",
                extra={"article_id": article.article_id},
            )

    def publish_batch(self, articles: list[NewsArticle]) -> int:
        """Publish multiple articles.

        Args:
            articles: List of unique news articles to publish.

        Returns:
            Number of articles successfully published.

        """
        published = 0
        for article in articles:
            try:
                self.publish(article)
                published += 1
            except Exception as e:
                logger.error(
                    f"Failed to publish article '{article.title[:60]}': {e}",
                    extra={"article_id": article.article_id},
                )
        logger.info(f"Batch published {published}/{len(articles)} articles")
        return published

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish_to_stream(self, article: NewsArticle) -> str:
        """Publish article to stream:news via the Event Bus."""
        message = {
            "article_id": article.article_id,
            "source": article.source,
            "title": article.title,
            "content": article.content,
            "url": article.url,
            "published_at": article.published_at.isoformat(),
            "fetched_at": article.fetched_at.isoformat(),
            "content_hash": article.content_hash,
        }
        return self._event_bus.publish(
            NEWS_STREAM_NAME,
            message,
            maxlen=NEWS_STREAM_MAXLEN,
        )

    def _store_in_sqlite(self, article: NewsArticle) -> None:
        """Persist article in the news_articles table."""
        self._db.execute_with_retry(
            INSERT_NEWS_ARTICLE_SQL,
            (
                article.article_id,
                article.source,
                article.title,
                article.content,
                article.url,
                article.published_at.isoformat(),
                article.fetched_at.isoformat(),
                article.content_hash,
            ),
        )
