"""Property-based tests for News Article Completeness.

Uses hypothesis to verify that parsed RSS entries always produce
NewsArticle objects with all required fields populated: non-empty
title, content, url, source, valid timestamps, valid UUID article_id,
and valid SHA256 content_hash.

**Validates: Requirements 5.3**

Properties tested:
  1. Parsed articles have non-empty title, content, url, and source
  2. content_hash is always a valid 64-character hex string (SHA256)
  3. article_id is always a non-empty UUID string
  4. published_at and fetched_at are always valid datetime objects
  5. source field always matches the source_name passed to parse_entry
"""

import re
import time
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from src.commander.rss_poller import NewsArticle, parse_entry

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

_non_empty_text = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
)

_source_name = st.sampled_from(
    ["MoneyControl", "EconomicTimes", "LiveMint", "Reuters", "Bloomberg"]
)

_url = st.from_regex(r"https://[a-z]{3,12}\.[a-z]{2,4}/[a-z0-9]{1,20}", fullmatch=True)


def _make_time_struct(year=2024, month=6, day=15, hour=10, minute=30, second=0):
    """Create a time.struct_time suitable for feedparser entries."""
    return time.struct_time((year, month, day, hour, minute, second, 0, 0, 0))


_time_struct = st.builds(
    _make_time_struct,
    year=st.integers(min_value=2020, max_value=2025),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)


@st.composite
def rss_entry_strategy(draw):
    """Generate a feedparser-style entry dict with valid fields.

    Randomly chooses between summary and description for content,
    and between published_parsed and updated_parsed for timestamp.
    """
    title = draw(_non_empty_text)
    link = draw(_url)
    ts = draw(_time_struct)

    # Choose content field: summary or description
    use_summary = draw(st.booleans())
    content_text = draw(_non_empty_text)

    entry = {"title": title, "link": link}

    if use_summary:
        entry["summary"] = content_text
    else:
        entry["description"] = content_text

    # Choose timestamp field: published_parsed or updated_parsed
    use_published = draw(st.booleans())
    if use_published:
        entry["published_parsed"] = ts
    else:
        entry["updated_parsed"] = ts

    return entry


# ---------------------------------------------------------------------------
# SHA256 hex pattern
# ---------------------------------------------------------------------------

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestNewsArticleCompletenessProperties:
    """**Validates: Requirements 5.3**

    Property 17: News Article Completeness
    """

    @given(entry=rss_entry_strategy(), source_name=_source_name)
    @settings(max_examples=25)
    def test_parsed_article_has_non_empty_required_fields(self, entry, source_name):
        """Property: For any valid RSS entry with title, content, link, and
        timestamp, the parsed NewsArticle has non-empty title, content,
        url, and source.

        **Validates: Requirements 5.3**
        """
        article = parse_entry(entry, source_name)

        assert isinstance(article, NewsArticle)
        assert article.title, "title must be non-empty"
        assert article.content, "content must be non-empty"
        assert article.url, "url must be non-empty"
        assert article.source, "source must be non-empty"

    @given(entry=rss_entry_strategy(), source_name=_source_name)
    @settings(max_examples=25)
    def test_content_hash_is_valid_sha256(self, entry, source_name):
        """Property: The content_hash is always a valid 64-character hex
        string (SHA256 digest).

        **Validates: Requirements 5.3**
        """
        article = parse_entry(entry, source_name)

        assert SHA256_HEX_PATTERN.match(
            article.content_hash
        ), f"content_hash '{article.content_hash}' is not a valid SHA256 hex string"

    @given(entry=rss_entry_strategy(), source_name=_source_name)
    @settings(max_examples=25)
    def test_article_id_is_valid_uuid(self, entry, source_name):
        """Property: The article_id is always a non-empty string in UUID format.

        **Validates: Requirements 5.3**
        """
        article = parse_entry(entry, source_name)

        assert article.article_id, "article_id must be non-empty"
        assert UUID_PATTERN.match(
            article.article_id
        ), f"article_id '{article.article_id}' is not a valid UUID"

    @given(entry=rss_entry_strategy(), source_name=_source_name)
    @settings(max_examples=25)
    def test_timestamps_are_valid_datetimes(self, entry, source_name):
        """Property: published_at and fetched_at are always valid datetime
        objects with timezone info.

        **Validates: Requirements 5.3**
        """
        article = parse_entry(entry, source_name)

        assert isinstance(
            article.published_at, datetime
        ), f"published_at must be a datetime, got {type(article.published_at)}"
        assert isinstance(
            article.fetched_at, datetime
        ), f"fetched_at must be a datetime, got {type(article.fetched_at)}"
        assert article.published_at.tzinfo is not None, "published_at must have timezone info"
        assert article.fetched_at.tzinfo is not None, "fetched_at must have timezone info"

    @given(entry=rss_entry_strategy(), source_name=_source_name)
    @settings(max_examples=25)
    def test_source_matches_source_name(self, entry, source_name):
        """Property: The source field always matches the source_name
        passed to parse_entry.

        **Validates: Requirements 5.3**
        """
        article = parse_entry(entry, source_name)

        assert (
            article.source == source_name
        ), f"Expected source '{source_name}', got '{article.source}'"
