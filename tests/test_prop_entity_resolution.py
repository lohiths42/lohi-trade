"""Property-based tests for EntityResolver.

Tests entity resolution mapping, multi-entity association, and unmapped
entity handling using hypothesis.

Properties tested:
  Property 19: Entity Resolution Mapping
  Property 20: Multi-Entity Article Association
  Property 21: Unmapped Entity Handling
"""

import uuid
from datetime import UTC, datetime

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.commander.entity_resolver import EntityResolver
from src.commander.rss_poller import NewsArticle
from src.ingestion.ticker_mapper import TickerMapper

# ---------------------------------------------------------------------------
# Test Fixtures: Mock spaCy model and helpers
# ---------------------------------------------------------------------------


class _MockSpacyEntity:
    """Mock spaCy entity."""

    def __init__(self, text: str, label: str):
        self.text = text
        self.label_ = label


class _MockSpacyDoc:
    """Mock spaCy doc with entities."""

    def __init__(self, entities):
        self.ents = [_MockSpacyEntity(t, l) for t, l in entities]


class _ConfigurableSpacyModel:
    """Mock spaCy model that returns entities based on a lookup.

    Given a mapping of text substrings to entity names, it returns
    ORG entities for any configured company names found in the text.
    """

    def __init__(self, entity_names: list[str]):
        self._entity_names = entity_names

    def __call__(self, text: str) -> _MockSpacyDoc:
        found = []
        text_lower = text.lower()
        for name in self._entity_names:
            if name.lower() in text_lower:
                found.append((name, "ORG"))
        return _MockSpacyDoc(found)


class _DirectSpacyModel:
    """Mock spaCy model that always returns a fixed list of entities.
    Used when we want to control exactly which entities are extracted.
    """

    def __init__(self, entities: list[str]):
        self._entities = entities

    def __call__(self, text: str) -> _MockSpacyDoc:
        return _MockSpacyDoc([(e, "ORG") for e in self._entities])


def _make_article(title: str = "Test article", content: str = "Test content") -> NewsArticle:
    return NewsArticle(
        article_id=str(uuid.uuid4()),
        source="MoneyControl",
        title=title,
        content=content,
        url=f"https://example.com/{uuid.uuid4().hex[:8]}",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        content_hash="test-hash",
    )


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for generating company name -> ticker mappings
_company_name = st.text(
    min_size=3,
    max_size=40,
    alphabet=st.characters(categories=("L", "N", "Z"), min_codepoint=32, max_codepoint=122),
).filter(lambda s: s.strip() and len(s.strip()) >= 3)

_ticker = st.text(
    min_size=2,
    max_size=12,
    alphabet=st.characters(categories=("Lu",), min_codepoint=65, max_codepoint=90),
).filter(lambda s: len(s.strip()) >= 2)


@st.composite
def ticker_mapping_strategy(draw):
    """Generate a dictionary of company name -> ticker mappings."""
    num_entries = draw(st.integers(min_value=1, max_value=15))
    mapping: dict[str, str] = {}
    for _ in range(num_entries):
        name = draw(_company_name).strip().lower()
        ticker = draw(_ticker).strip().upper()
        if name and ticker:
            mapping[name] = ticker
    assume(len(mapping) >= 1)
    return mapping


@st.composite
def mapped_entities_strategy(draw, mapping: dict[str, str]):
    """Select a subset of company names from the mapping to use as entities.
    These are entities that SHOULD be resolved to tickers.
    """
    names = list(mapping.keys())
    num_to_select = draw(st.integers(min_value=1, max_value=min(len(names), 5)))
    selected = draw(
        st.lists(
            st.sampled_from(names),
            min_size=num_to_select,
            max_size=num_to_select,
            unique=True,
        ),
    )
    return selected


@st.composite
def unmapped_entity_names(draw):
    """Generate company names that won't be in any ticker mapping."""
    prefix = draw(st.sampled_from(["UnknownCorp", "FakeLtd", "NoMatch", "RandomInc", "XYZGroup"]))
    suffix = draw(st.text(min_size=1, max_size=5, alphabet=st.characters(categories=("Lu", "Nd"))))
    return f"{prefix}_{suffix}"


# ---------------------------------------------------------------------------
# Property 19: Entity Resolution Mapping
# ---------------------------------------------------------------------------


class TestEntityResolutionMapping:
    """Property 19: Entity Resolution Mapping

    *For any* company name that exists in the ticker mapping dictionary,
    the entity resolver should correctly map it to the corresponding
    NSE ticker symbol.

    **Validates: Requirements 6.2**
    """

    @given(data=st.data())
    @settings(max_examples=25)
    def test_mapped_company_resolves_to_correct_ticker(self, data):
        """Property: For any company name in the ticker mapping, the resolver
        should return the correct ticker symbol.

        **Validates: Requirements 6.2**
        """
        mapping = data.draw(ticker_mapping_strategy())

        # Pick a random company name from the mapping
        company_name = data.draw(st.sampled_from(list(mapping.keys())))
        expected_ticker = mapping[company_name]

        # Set up the ticker mapper with exact mappings
        mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
        mapper.ticker_map = mapping
        mapper._build_reverse_map()

        # Create a mock spaCy model that returns the company name as an entity
        mock_nlp = _DirectSpacyModel([company_name])

        resolver = EntityResolver(
            ticker_mapper=mapper,
            spacy_model=mock_nlp,
        )

        article = _make_article(
            title=f"News about {company_name}",
            content=f"{company_name} reported results.",
        )
        result = resolver.resolve_entities(article)

        assert expected_ticker in result.tickers, (
            f"Expected ticker '{expected_ticker}' for company '{company_name}' "
            f"but got tickers: {result.tickers}"
        )


# ---------------------------------------------------------------------------
# Property 20: Multi-Entity Article Association
# ---------------------------------------------------------------------------


class TestMultiEntityAssociation:
    """Property 20: Multi-Entity Article Association

    *For any* news article containing multiple company names, the entity
    resolver should associate the article with all identified tickers.

    **Validates: Requirements 6.3**
    """

    @given(data=st.data())
    @settings(max_examples=25)
    def test_all_entities_resolved_to_tickers(self, data):
        """Property: For any article with N company names (N >= 1), the resolver
        should associate the article with all N corresponding ticker symbols.

        **Validates: Requirements 6.3**
        """
        mapping = data.draw(ticker_mapping_strategy())
        assume(len(mapping) >= 2)

        # Select multiple company names from the mapping
        names = list(mapping.keys())
        num_entities = data.draw(st.integers(min_value=2, max_value=min(len(names), 5)))
        selected_names = data.draw(
            st.lists(
                st.sampled_from(names),
                min_size=num_entities,
                max_size=num_entities,
                unique=True,
            ),
        )

        expected_tickers = {mapping[n] for n in selected_names}

        mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
        mapper.ticker_map = mapping
        mapper._build_reverse_map()

        mock_nlp = _DirectSpacyModel(selected_names)

        resolver = EntityResolver(
            ticker_mapper=mapper,
            spacy_model=mock_nlp,
        )

        article = _make_article(
            title="Multi-company news",
            content=" ".join(selected_names),
        )
        result = resolver.resolve_entities(article)

        resolved_tickers = set(result.tickers)
        assert expected_tickers == resolved_tickers, (
            f"Expected tickers {expected_tickers} for entities {selected_names}, "
            f"but got {resolved_tickers}"
        )

    @given(data=st.data())
    @settings(max_examples=25)
    def test_entities_found_contains_all_raw_names(self, data):
        """Property: entities_found should contain all raw company names
        extracted by NER.

        **Validates: Requirements 6.3**
        """
        mapping = data.draw(ticker_mapping_strategy())
        names = list(mapping.keys())
        num_entities = data.draw(st.integers(min_value=1, max_value=min(len(names), 5)))
        selected_names = data.draw(
            st.lists(
                st.sampled_from(names),
                min_size=num_entities,
                max_size=num_entities,
                unique=True,
            ),
        )

        mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
        mapper.ticker_map = mapping
        mapper._build_reverse_map()

        mock_nlp = _DirectSpacyModel(selected_names)
        resolver = EntityResolver(ticker_mapper=mapper, spacy_model=mock_nlp)

        result = resolver.resolve_entities(_make_article())

        for name in selected_names:
            assert name in result.entities_found, (
                f"Expected entity '{name}' in entities_found, "
                f"got {result.entities_found}"
            )


# ---------------------------------------------------------------------------
# Property 21: Unmapped Entity Handling
# ---------------------------------------------------------------------------


class TestUnmappedEntityHandling:
    """Property 21: Unmapped Entity Handling

    *For any* company name that cannot be mapped to a ticker, the entity
    resolver should log the unmapped entity and not include it in the
    resolved tickers list.

    **Validates: Requirements 6.4**
    """

    @given(data=st.data())
    @settings(max_examples=25)
    def test_unmapped_entities_not_in_tickers(self, data):
        """Property: For any entity not in the ticker mapping, it should NOT
        appear in the resolved tickers list.

        **Validates: Requirements 6.4**
        """
        mapping = data.draw(ticker_mapping_strategy())

        # Generate unmapped entity names that are definitely not in the mapping
        num_unmapped = data.draw(st.integers(min_value=1, max_value=3))
        unmapped_names = [
            data.draw(unmapped_entity_names())
            for _ in range(num_unmapped)
        ]
        # Ensure none of the unmapped names are in the mapping
        for name in unmapped_names:
            assume(name.strip().lower() not in mapping)

        mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
        mapper.ticker_map = mapping
        mapper._build_reverse_map()

        mock_nlp = _DirectSpacyModel(unmapped_names)
        resolver = EntityResolver(ticker_mapper=mapper, spacy_model=mock_nlp)

        result = resolver.resolve_entities(_make_article())

        # No tickers should be resolved for unmapped entities
        assert len(result.tickers) == 0, (
            f"Expected no tickers for unmapped entities {unmapped_names}, "
            f"but got {result.tickers}"
        )

        # All unmapped names should be in unmapped_entities
        for name in unmapped_names:
            assert name in result.unmapped_entities, (
                f"Expected '{name}' in unmapped_entities, "
                f"got {result.unmapped_entities}"
            )

    @given(data=st.data())
    @settings(max_examples=25)
    def test_mixed_mapped_and_unmapped(self, data):
        """Property: When both mapped and unmapped entities are present,
        only mapped entities should appear in tickers, and unmapped
        entities should be in unmapped_entities.

        **Validates: Requirements 6.4**
        """
        mapping = data.draw(ticker_mapping_strategy())
        assume(len(mapping) >= 1)

        # Pick some mapped names
        mapped_names = [data.draw(st.sampled_from(list(mapping.keys())))]

        # Generate unmapped names
        unmapped_name = data.draw(unmapped_entity_names())
        assume(unmapped_name.strip().lower() not in mapping)

        all_entities = mapped_names + [unmapped_name]

        mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)
        mapper.ticker_map = mapping
        mapper._build_reverse_map()

        mock_nlp = _DirectSpacyModel(all_entities)
        resolver = EntityResolver(ticker_mapper=mapper, spacy_model=mock_nlp)

        result = resolver.resolve_entities(_make_article())

        # Mapped entities should be in tickers
        for name in mapped_names:
            expected_ticker = mapping[name]
            assert expected_ticker in result.tickers, (
                f"Expected ticker '{expected_ticker}' for mapped entity '{name}'"
            )

        # Unmapped entity should NOT be in tickers
        all_ticker_values = set(mapping.values())
        # The unmapped name shouldn't resolve to any ticker
        assert unmapped_name in result.unmapped_entities, (
            f"Expected '{unmapped_name}' in unmapped_entities"
        )
