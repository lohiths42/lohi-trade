"""
Property-based tests for NewsDeduplicator.

Uses hypothesis to verify that news deduplication correctly filters
duplicate articles based on content hash comparison, retaining only
the earliest version of each unique article.

**Validates: Requirements 5.4, 5.5**

Properties tested:
  1. No two articles in the deduplicated result share the same content_hash
  2. The earliest version (first occurrence) of each unique hash is retained
  3. The number of unique articles equals the number of distinct content hashes
  4. All articles in the result were present in the original input
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.news_deduplicator import HASH_TTL_SECONDS, NewsDeduplicator
from src.commander.rss_poller import NewsArticle, compute_content_hash


# ---------------------------------------------------------------------------
# Mock Redis Client (dict-based in-memory storage)
# ---------------------------------------------------------------------------


class MockRedisClient:
    """In-memory Redis client that simulates get/set with a dict."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        self._store[key] = str(value)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_title = st.text(min_size=1, max_size=120, alphabet=st.characters(categories=("L", "N", "P", "Z")))
_content = st.text(min_size=0, max_size=500, alphabet=st.characters(categories=("L", "N", "P", "Z")))


@st.composite
def article_strategy(draw, title=None, content=None):
    """Generate a single NewsArticle with optional fixed title/content."""
    t = title if title is not None else draw(_title)
    c = content if content is not None else draw(_content)
    return NewsArticle(
        article_id=str(uuid.uuid4()),
        source=draw(st.sampled_from(["MoneyControl", "EconomicTimes", "LiveMint"])),
        title=t,
        content=c,
        url=f"https://example.com/{uuid.uuid4().hex[:8]}",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        content_hash=compute_content_hash(t, c),
    )


@st.composite
def articles_with_duplicates(draw):
    """
    Generate a list of articles where some may share the same content hash.

    Strategy: generate a pool of unique (title, content) pairs, then build
    a list of articles by sampling from that pool (allowing repeats).
    This naturally creates duplicate content hashes.
    """
    num_unique = draw(st.integers(min_value=1, max_value=8))
    unique_pairs = [
        (draw(_title), draw(_content))
        for _ in range(num_unique)
    ]

    num_articles = draw(st.integers(min_value=1, max_value=20))
    articles: List[NewsArticle] = []
    for _ in range(num_articles):
        idx = draw(st.integers(min_value=0, max_value=num_unique - 1))
        title, content = unique_pairs[idx]
        articles.append(
            NewsArticle(
                article_id=str(uuid.uuid4()),
                source=draw(st.sampled_from(["MoneyControl", "EconomicTimes", "LiveMint"])),
                title=title,
                content=content,
                url=f"https://example.com/{uuid.uuid4().hex[:8]}",
                published_at=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                content_hash=compute_content_hash(title, content),
            )
        )

    return articles


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestNewsDeduplicationProperties:
    """
    **Validates: Requirements 5.4, 5.5**

    Property 18: News Deduplication
    """

    @given(articles=articles_with_duplicates())
    @settings(max_examples=25)
    def test_no_duplicate_hashes_in_result(self, articles):
        """
        Property: After deduplication, no two articles share the same content_hash.

        **Validates: Requirements 5.4**
        """
        deduplicator = NewsDeduplicator(MockRedisClient())
        result = deduplicator.deduplicate(articles)

        hashes = [a.content_hash for a in result]
        assert len(hashes) == len(set(hashes)), (
            f"Duplicate hashes found in result: {len(hashes)} articles but "
            f"only {len(set(hashes))} unique hashes"
        )

    @given(articles=articles_with_duplicates())
    @settings(max_examples=25)
    def test_earliest_version_retained(self, articles):
        """
        Property: The first occurrence of each unique hash in the input is
        the one retained in the output.

        **Validates: Requirements 5.5**
        """
        deduplicator = NewsDeduplicator(MockRedisClient())
        result = deduplicator.deduplicate(articles)

        # Build map of first occurrence per hash from the input
        first_occurrence: Dict[str, str] = {}
        for article in articles:
            if article.content_hash not in first_occurrence:
                first_occurrence[article.content_hash] = article.article_id

        for article in result:
            assert article.article_id == first_occurrence[article.content_hash], (
                f"Expected earliest article_id {first_occurrence[article.content_hash]} "
                f"for hash {article.content_hash[:12]}..., got {article.article_id}"
            )

    @given(articles=articles_with_duplicates())
    @settings(max_examples=25)
    def test_unique_count_equals_distinct_hashes(self, articles):
        """
        Property: The number of articles in the result equals the number of
        distinct content hashes in the input.

        **Validates: Requirements 5.4**
        """
        deduplicator = NewsDeduplicator(MockRedisClient())
        result = deduplicator.deduplicate(articles)

        distinct_hashes = len({a.content_hash for a in articles})
        assert len(result) == distinct_hashes, (
            f"Expected {distinct_hashes} unique articles, got {len(result)}"
        )

    @given(articles=articles_with_duplicates())
    @settings(max_examples=25)
    def test_all_results_from_original_input(self, articles):
        """
        Property: Every article in the deduplicated result was present in
        the original input list.

        **Validates: Requirements 5.4, 5.5**
        """
        deduplicator = NewsDeduplicator(MockRedisClient())
        result = deduplicator.deduplicate(articles)

        input_ids = {a.article_id for a in articles}
        for article in result:
            assert article.article_id in input_ids, (
                f"Result article {article.article_id} not found in original input"
            )
