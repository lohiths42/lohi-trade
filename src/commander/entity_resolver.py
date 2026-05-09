"""
Entity Resolver for The Commander.

Extracts company names from news articles using spaCy NER (Named Entity
Recognition) and maps them to NSE ticker symbols using the TickerMapper
with fuzzy matching support. Publishes resolved entities to stream:entities.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.commander.rss_poller import NewsArticle
from src.ingestion.ticker_mapper import TickerMapper
from src.state.event_bus import EventBus

logger = logging.getLogger(__name__)

ENTITIES_STREAM_NAME = "stream:entities"
ENTITIES_STREAM_MAXLEN = 5000

# Try to load spaCy; gracefully degrade if unavailable
try:
    import spacy

    SPACY_AVAILABLE = True
except Exception:
    SPACY_AVAILABLE = False
    logging.warning("spaCy not available, NER extraction will be disabled")


@dataclass
class ResolvedEntity:
    """
    Result of entity resolution for a news article.

    Attributes:
        article_id: UUID of the source article
        tickers: List of resolved NSE ticker symbols
        entities_found: Raw company names extracted by NER
        unmapped_entities: Company names that could not be mapped
        timestamp: When the resolution was performed
    """

    article_id: str
    tickers: List[str] = field(default_factory=list)
    entities_found: List[str] = field(default_factory=list)
    unmapped_entities: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EntityResolver:
    """
    Extracts company names from news and maps to NSE tickers.

    Uses spaCy en_core_web_sm for Named Entity Recognition (ORG entities)
    and the TickerMapper for fuzzy matching of company names to ticker
    symbols.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    def __init__(
        self,
        ticker_mapper: TickerMapper,
        event_bus: Optional[EventBus] = None,
        spacy_model: Optional[object] = None,
    ) -> None:
        """
        Initialize the entity resolver.

        Args:
            ticker_mapper: TickerMapper instance with loaded mappings.
            event_bus: Optional EventBus for publishing resolved entities.
            spacy_model: Optional pre-loaded spaCy model. If None, loads
                         en_core_web_sm automatically.
        """
        self._ticker_mapper = ticker_mapper
        self._event_bus = event_bus
        self._nlp = spacy_model

        if self._nlp is None and SPACY_AVAILABLE:
            try:
                self._nlp = spacy.load("en_core_web_sm")
                logger.info("Loaded spaCy en_core_web_sm model for NER")
            except OSError:
                logger.warning(
                    "spaCy en_core_web_sm model not found. "
                    "Run: python -m spacy download en_core_web_sm"
                )
                self._nlp = None

    def extract_entities(self, text: str) -> List[str]:
        """
        Extract ORG entities from text using spaCy NER.

        Args:
            text: News article text (title + content).

        Returns:
            List of unique company/organization names found.

        Requirements: 6.1
        """
        if self._nlp is None:
            logger.warning("spaCy model not loaded, cannot extract entities")
            return []

        doc = self._nlp(text)
        entities: List[str] = []
        seen: set = set()

        for ent in doc.ents:
            if ent.label_ == "ORG":
                name = ent.text.strip()
                name_lower = name.lower()
                if name_lower not in seen and name:
                    seen.add(name_lower)
                    entities.append(name)

        logger.debug(f"Extracted {len(entities)} ORG entities from text")
        return entities

    def resolve_entities(self, article: NewsArticle) -> ResolvedEntity:
        """
        Extract company names from a news article and map to tickers.

        Combines title and content for NER extraction, then maps each
        entity to an NSE ticker symbol. Unmapped entities are logged
        and excluded from the tickers list.

        Args:
            article: News article to process.

        Returns:
            ResolvedEntity with tickers, raw entities, and unmapped entities.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
        """
        # Combine title and content for better entity extraction
        text = f"{article.title} {article.content}"
        raw_entities = self.extract_entities(text)

        tickers: List[str] = []
        unmapped: List[str] = []
        seen_tickers: set = set()

        for entity_name in raw_entities:
            ticker = self._ticker_mapper.get_ticker(entity_name, use_fuzzy=True)

            if ticker is not None:
                if ticker not in seen_tickers:
                    tickers.append(ticker)
                    seen_tickers.add(ticker)
                logger.debug(f"Mapped entity '{entity_name}' -> {ticker}")
            else:
                unmapped.append(entity_name)
                logger.info(
                    f"Unmapped entity '{entity_name}' in article "
                    f"'{article.title[:60]}' - skipping sentiment processing",
                    extra={
                        "article_id": article.article_id,
                        "unmapped_entity": entity_name,
                    },
                )

        resolved = ResolvedEntity(
            article_id=article.article_id,
            tickers=tickers,
            entities_found=raw_entities,
            unmapped_entities=unmapped,
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(
            f"Resolved {len(tickers)} tickers from {len(raw_entities)} entities "
            f"({len(unmapped)} unmapped) for article '{article.title[:60]}'",
            extra={
                "article_id": article.article_id,
                "tickers": tickers,
                "unmapped_count": len(unmapped),
            },
        )

        return resolved

    def resolve_and_publish(self, article: NewsArticle) -> ResolvedEntity:
        """
        Resolve entities and publish to stream:entities.

        Args:
            article: News article to process.

        Returns:
            ResolvedEntity with resolved tickers.

        Requirements: 6.1
        """
        resolved = self.resolve_entities(article)

        if self._event_bus is not None and resolved.tickers:
            self._publish_to_stream(resolved)

        return resolved

    def _publish_to_stream(self, resolved: ResolvedEntity) -> str:
        """
        Publish resolved entity to stream:entities.

        Args:
            resolved: The resolved entity to publish.

        Returns:
            Message ID from the stream.

        Requirements: 6.1
        """
        message = {
            "article_id": resolved.article_id,
            "tickers_json": json.dumps(resolved.tickers),
            "entities_found_json": json.dumps(resolved.entities_found),
            "timestamp": resolved.timestamp.isoformat(),
        }
        msg_id = self._event_bus.publish(
            ENTITIES_STREAM_NAME, message, maxlen=ENTITIES_STREAM_MAXLEN
        )
        logger.debug(
            f"Published resolved entities to {ENTITIES_STREAM_NAME}: {msg_id}",
            extra={"article_id": resolved.article_id},
        )
        return msg_id
