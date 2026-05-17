"""Unit tests for EntityResolver.

Validates entity extraction via spaCy NER, ticker mapping with fuzzy
matching, unmapped entity handling, and publishing to stream:entities.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.commander.entity_resolver import (
    ENTITIES_STREAM_MAXLEN,
    ENTITIES_STREAM_NAME,
    EntityResolver,
)
from src.commander.rss_poller import NewsArticle
from src.ingestion.ticker_mapper import TickerMapper


def _make_article(**overrides) -> NewsArticle:
    defaults = dict(
        article_id="test-article-001",
        source="MoneyControl",
        title="Reliance Industries reports strong Q3 results",
        content="Reliance Industries Limited posted record profits this quarter.",
        url="https://example.com/article/1",
        published_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        fetched_at=datetime(2024, 1, 15, 10, 0, 5, tzinfo=UTC),
        content_hash="abc123",
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


def _make_ticker_mapper() -> TickerMapper:
    """Create a TickerMapper with some test mappings."""
    mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
    mapper.ticker_map = {
        "reliance industries": "RELIANCE",
        "reliance industries limited": "RELIANCE",
        "reliance": "RELIANCE",
        "tcs": "TCS",
        "tata consultancy services": "TCS",
        "infosys": "INFY",
        "hdfc bank": "HDFCBANK",
    }
    mapper._build_reverse_map()
    return mapper


class _MockSpacyEntity:
    """Mock spaCy entity."""

    def __init__(self, text: str, label: str):
        self.text = text
        self.label_ = label


class _MockSpacyDoc:
    """Mock spaCy doc with entities."""

    def __init__(self, entities):
        self.ents = [_MockSpacyEntity(t, l) for t, l in entities]


class _MockSpacyModel:
    """Mock spaCy NLP model that returns configured entities."""

    def __init__(self, entities):
        self._entities = entities

    def __call__(self, text):
        return _MockSpacyDoc(self._entities)


class TestEntityExtraction:
    """Tests for spaCy NER entity extraction (17.1)."""

    def test_extracts_org_entities(self):
        """ORG entities should be extracted from text."""
        mock_nlp = _MockSpacyModel(
            [
                ("Reliance Industries", "ORG"),
                ("TCS", "ORG"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        entities = resolver.extract_entities("Reliance Industries and TCS reported results")
        assert "Reliance Industries" in entities
        assert "TCS" in entities

    def test_ignores_non_org_entities(self):
        """Non-ORG entities (PERSON, GPE, etc.) should be ignored."""
        mock_nlp = _MockSpacyModel(
            [
                ("Reliance Industries", "ORG"),
                ("Mumbai", "GPE"),
                ("Mukesh Ambani", "PERSON"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        entities = resolver.extract_entities("Some text")
        assert entities == ["Reliance Industries"]

    def test_deduplicates_entities(self):
        """Duplicate entity names should appear only once."""
        mock_nlp = _MockSpacyModel(
            [
                ("TCS", "ORG"),
                ("TCS", "ORG"),
                ("tcs", "ORG"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        entities = resolver.extract_entities("TCS TCS tcs")
        assert len(entities) == 1

    def test_returns_empty_when_no_model(self):
        """If spaCy model is not loaded, return empty list."""
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=None,
        )
        resolver._nlp = None
        entities = resolver.extract_entities("Reliance Industries")
        assert entities == []


class TestTickerMapping:
    """Tests for ticker mapping with fuzzy matching (17.2)."""

    def test_maps_known_company_to_ticker(self):
        """Known company names should map to correct tickers."""
        mock_nlp = _MockSpacyModel([("Reliance Industries", "ORG")])
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_entities(_make_article())
        assert "RELIANCE" in result.tickers

    def test_handles_multiple_companies(self):
        """Multiple companies in one article should all be resolved."""
        mock_nlp = _MockSpacyModel(
            [
                ("Reliance Industries", "ORG"),
                ("TCS", "ORG"),
                ("Infosys", "ORG"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        article = _make_article(
            title="Reliance, TCS, and Infosys lead market rally",
            content="Major IT and energy stocks surged today.",
        )
        result = resolver.resolve_entities(article)
        assert set(result.tickers) == {"RELIANCE", "TCS", "INFY"}

    def test_no_duplicate_tickers(self):
        """Same ticker from different entity names should appear once."""
        mock_nlp = _MockSpacyModel(
            [
                ("Reliance Industries", "ORG"),
                ("Reliance", "ORG"),
            ]
        )
        mapper = _make_ticker_mapper()
        resolver = EntityResolver(ticker_mapper=mapper, spacy_model=mock_nlp)
        result = resolver.resolve_entities(_make_article())
        assert result.tickers.count("RELIANCE") == 1

    def test_entities_found_contains_raw_names(self):
        """entities_found should contain the raw NER-extracted names."""
        mock_nlp = _MockSpacyModel([("TCS", "ORG")])
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_entities(_make_article())
        assert "TCS" in result.entities_found


class TestUnmappedEntities:
    """Tests for unmapped entity handling (17.5)."""

    def test_unmapped_entities_logged(self):
        """Unmapped entities should be in unmapped_entities list."""
        mock_nlp = _MockSpacyModel(
            [
                ("Reliance Industries", "ORG"),
                ("Unknown Corp", "ORG"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_entities(_make_article())
        assert "Unknown Corp" in result.unmapped_entities
        assert "Unknown Corp" not in [e for t in result.tickers for e in [t]]

    def test_unmapped_entities_not_in_tickers(self):
        """Unmapped entities should not appear in the tickers list."""
        mock_nlp = _MockSpacyModel([("FakeCompany Ltd", "ORG")])
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_entities(_make_article())
        assert len(result.tickers) == 0
        assert "FakeCompany Ltd" in result.unmapped_entities

    def test_mixed_mapped_and_unmapped(self):
        """Both mapped and unmapped entities should be handled correctly."""
        mock_nlp = _MockSpacyModel(
            [
                ("TCS", "ORG"),
                ("SomeRandom Inc", "ORG"),
                ("Infosys", "ORG"),
            ]
        )
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_entities(_make_article())
        assert set(result.tickers) == {"TCS", "INFY"}
        assert "SomeRandom Inc" in result.unmapped_entities


class TestStreamPublishing:
    """Tests for publishing to stream:entities (17.7)."""

    def test_publishes_to_stream_entities(self):
        """Resolved entities should be published to stream:entities."""
        mock_nlp = _MockSpacyModel([("TCS", "ORG")])
        event_bus = MagicMock()
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            event_bus=event_bus,
            spacy_model=mock_nlp,
        )
        resolver.resolve_and_publish(_make_article())
        event_bus.publish.assert_called_once()
        assert event_bus.publish.call_args[0][0] == ENTITIES_STREAM_NAME

    def test_publishes_with_correct_maxlen(self):
        """Publish should use maxlen=5000."""
        mock_nlp = _MockSpacyModel([("TCS", "ORG")])
        event_bus = MagicMock()
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            event_bus=event_bus,
            spacy_model=mock_nlp,
        )
        resolver.resolve_and_publish(_make_article())
        assert event_bus.publish.call_args[1]["maxlen"] == ENTITIES_STREAM_MAXLEN

    def test_publishes_correct_fields(self):
        """Published message should contain article_id, tickers_json, entities_found_json, timestamp."""
        mock_nlp = _MockSpacyModel([("TCS", "ORG"), ("Infosys", "ORG")])
        event_bus = MagicMock()
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            event_bus=event_bus,
            spacy_model=mock_nlp,
        )
        article = _make_article(article_id="pub-test-001")
        resolver.resolve_and_publish(article)

        message = event_bus.publish.call_args[0][1]
        assert message["article_id"] == "pub-test-001"
        tickers = json.loads(message["tickers_json"])
        assert set(tickers) == {"TCS", "INFY"}
        entities = json.loads(message["entities_found_json"])
        assert "TCS" in entities
        assert "Infosys" in entities
        assert "timestamp" in message

    def test_does_not_publish_when_no_tickers(self):
        """If no tickers resolved, should not publish to stream."""
        mock_nlp = _MockSpacyModel([("Unknown Corp", "ORG")])
        event_bus = MagicMock()
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            event_bus=event_bus,
            spacy_model=mock_nlp,
        )
        resolver.resolve_and_publish(_make_article())
        event_bus.publish.assert_not_called()

    def test_does_not_publish_when_no_event_bus(self):
        """If no event_bus provided, resolve_and_publish should still work."""
        mock_nlp = _MockSpacyModel([("TCS", "ORG")])
        resolver = EntityResolver(
            ticker_mapper=_make_ticker_mapper(),
            event_bus=None,
            spacy_model=mock_nlp,
        )
        result = resolver.resolve_and_publish(_make_article())
        assert "TCS" in result.tickers
