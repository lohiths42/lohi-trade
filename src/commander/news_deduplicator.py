"""
News Deduplication for The Commander.

Deduplicates news articles using content hash comparison via Redis.
Each article's content_hash is stored as an individual Redis key with
a 24-hour TTL, ensuring duplicates are discarded and the earliest
version is retained.

Requirements: 5.4, 5.5
"""

import logging
from typing import List

from src.commander.rss_poller import NewsArticle
from src.state.redis_client import RedisClient


logger = logging.getLogger(__name__)

# Redis key prefix for deduplication hashes
HASH_KEY_PREFIX = "news:hash:"

# TTL for seen hashes: 24 hours in seconds
HASH_TTL_SECONDS = 86400


class NewsDeduplicator:
    """
    Deduplicates news articles using content hash stored in Redis.

    Each article's content_hash is checked against Redis. If the hash
    already exists, the article is a duplicate and is discarded. Otherwise,
    the hash is stored with a 24-hour TTL and the article is retained.

    This ensures the earliest version of any article is kept.

    Requirements: 5.4, 5.5
    """

    def __init__(self, redis_client: RedisClient) -> None:
        """
        Initialize the deduplicator.

        Args:
            redis_client: Redis client instance for hash storage.
        """
        self._redis = redis_client

    def _key_for(self, content_hash: str) -> str:
        """Build the Redis key for a given content hash."""
        return f"{HASH_KEY_PREFIX}{content_hash}"

    def is_duplicate(self, article: NewsArticle) -> bool:
        """
        Check whether an article has already been seen.

        Args:
            article: The news article to check.

        Returns:
            True if the article's content_hash is already in Redis.
        """
        key = self._key_for(article.content_hash)
        existing = self._redis.get(key)
        return existing is not None

    def mark_seen(self, article: NewsArticle) -> None:
        """
        Record an article's content_hash in Redis with 24-hour TTL.

        Args:
            article: The news article to mark as seen.
        """
        key = self._key_for(article.content_hash)
        self._redis.set(key, article.article_id, ex=HASH_TTL_SECONDS)

    def deduplicate(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        Filter a list of articles, removing duplicates.

        For each article, checks if its content_hash has been seen before.
        Unique articles are marked as seen and included in the result.
        Duplicates are discarded, retaining the earliest version.

        Args:
            articles: List of news articles to deduplicate.

        Returns:
            List of unique (non-duplicate) articles.
        """
        unique: List[NewsArticle] = []

        for article in articles:
            if self.is_duplicate(article):
                logger.debug(
                    f"Duplicate article discarded: '{article.title}' "
                    f"(hash={article.content_hash[:12]}...)"
                )
                continue

            self.mark_seen(article)
            unique.append(article)

        if len(articles) != len(unique):
            logger.info(
                f"Deduplicated {len(articles)} articles -> {len(unique)} unique "
                f"({len(articles) - len(unique)} duplicates removed)"
            )

        return unique
