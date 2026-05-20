"""IdeaStore — persistence layer for Ideas, Themes, and Sector Clusters.

Uses PostgreSQL with JSONB columns for flexible storage. Falls back
gracefully to in-memory storage when no database pool is available
(development / demo mode).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from src.research.ideas.models import (
    Citation,
    ConvictionBand,
    Sector,
    SectorCluster,
    SectorClusterMember,
    SignalDirection,
    StockArchetype,
    StockIdea,
    ThemeKind,
    ThemeMember,
    ThemeReport,
    ResearchSignal,
)

logger = logging.getLogger(__name__)

__all__ = ["IdeaStore"]


class IdeaStore:
    """CRUD operations for Ideas, Themes, Sector Clusters, and Signals.

    When ``db_pool`` is ``None``, all data is stored in-memory — functional
    for development but not persisted across restarts.

    Parameters
    ----------
    db_pool:
        An ``asyncpg`` connection pool. ``None`` for in-memory mode.
    """

    def __init__(self, db_pool: Any | None = None) -> None:
        self._pool = db_pool

        # In-memory fallback stores
        self._ideas: dict[str, StockIdea] = {}
        self._themes: dict[str, ThemeReport] = {}
        self._sectors: dict[str, SectorCluster] = {}
        self._signals: dict[str, ResearchSignal] = {}

    # ================================================================== #
    # Ideas                                                               #
    # ================================================================== #

    async def upsert_idea(self, idea: StockIdea) -> None:
        """Insert or update an idea. Upserts by symbol (one idea per symbol)."""
        # Check if we already have an idea for this symbol — update it
        existing_id = None
        for eid, existing in self._ideas.items():
            if existing.symbol == idea.symbol:
                existing_id = eid
                break

        if existing_id:
            idea.idea_id = existing_id
            idea.created_at = self._ideas[existing_id].created_at

        self._ideas[idea.idea_id] = idea

        if self._pool is not None:
            await self._db_upsert_idea(idea)

        logger.info(
            "Idea upserted: symbol=%s archetype=%s direction=%s conviction=%.2f",
            idea.symbol,
            idea.archetype.value,
            idea.direction.value,
            idea.conviction,
        )

    async def list_ideas(
        self,
        *,
        limit: int = 50,
        sector: str | None = None,
        archetype: str | None = None,
        direction: str | None = None,
    ) -> list[StockIdea]:
        """List ideas, most recent first, with optional filters."""
        ideas = list(self._ideas.values())

        if sector:
            ideas = [i for i in ideas if i.sector.value == sector]
        if archetype:
            ideas = [i for i in ideas if i.archetype.value == archetype]
        if direction:
            ideas = [i for i in ideas if i.direction.value == direction]

        # Sort by conviction descending, then by updated_at
        ideas.sort(key=lambda i: (-i.conviction, i.updated_at), reverse=False)

        return ideas[:limit]

    async def get_idea(self, idea_id: str) -> StockIdea | None:
        """Get a single idea by id."""
        return self._ideas.get(idea_id)

    async def get_idea_by_symbol(self, symbol: str) -> StockIdea | None:
        """Get the most recent idea for a symbol."""
        for idea in self._ideas.values():
            if idea.symbol == symbol.upper():
                return idea
        return None

    # ================================================================== #
    # Themes                                                              #
    # ================================================================== #

    async def upsert_theme(self, theme: ThemeReport) -> None:
        """Insert or update a theme."""
        self._themes[theme.theme_id] = theme

        if self._pool is not None:
            await self._db_upsert_theme(theme)

        logger.info(
            "Theme upserted: id=%s title=%s members=%d",
            theme.theme_id,
            theme.title,
            len(theme.members),
        )

    async def list_themes(self, *, limit: int = 20) -> list[ThemeReport]:
        """List themes, most recent first."""
        themes = list(self._themes.values())
        themes.sort(key=lambda t: t.updated_at, reverse=True)
        return themes[:limit]

    async def get_theme(self, theme_id: str) -> ThemeReport | None:
        """Get a single theme by id."""
        return self._themes.get(theme_id)

    # ================================================================== #
    # Sector Clusters                                                     #
    # ================================================================== #

    async def upsert_sector_cluster(self, cluster: SectorCluster) -> None:
        """Upsert a sector cluster (keyed by sector enum value)."""
        self._sectors[cluster.sector.value] = cluster

        if self._pool is not None:
            await self._db_upsert_sector(cluster)

    async def list_sector_clusters(self) -> list[SectorCluster]:
        """List all sector clusters, ordered by absolute bias."""
        clusters = list(self._sectors.values())
        clusters.sort(key=lambda c: abs(c.bias), reverse=True)
        return clusters

    async def get_sector_cluster(self, sector: str) -> SectorCluster | None:
        """Get a single sector cluster."""
        return self._sectors.get(sector)

    # ================================================================== #
    # Signals                                                             #
    # ================================================================== #

    async def upsert_signal(self, signal: ResearchSignal) -> None:
        """Upsert a research signal."""
        self._signals[signal.signal_id] = signal

    async def list_signals(self, *, limit: int = 50) -> list[ResearchSignal]:
        """List signals, most recent first."""
        signals = list(self._signals.values())
        signals.sort(key=lambda s: s.emitted_at, reverse=True)
        return signals[:limit]

    # ================================================================== #
    # DB persistence (PostgreSQL)                                         #
    # ================================================================== #

    async def _db_upsert_idea(self, idea: StockIdea) -> None:
        """Persist an idea to PostgreSQL."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO research_ideas (
                        idea_id, symbol, archetype, sector, subsector,
                        headline, thesis_short, direction, conviction,
                        conviction_band, tags, key_citations, source_run_id,
                        brief_preview, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11::jsonb, $12::jsonb, $13, $14, $15, $16
                    )
                    ON CONFLICT (symbol) DO UPDATE SET
                        archetype = EXCLUDED.archetype,
                        sector = EXCLUDED.sector,
                        headline = EXCLUDED.headline,
                        thesis_short = EXCLUDED.thesis_short,
                        direction = EXCLUDED.direction,
                        conviction = EXCLUDED.conviction,
                        conviction_band = EXCLUDED.conviction_band,
                        tags = EXCLUDED.tags,
                        key_citations = EXCLUDED.key_citations,
                        source_run_id = EXCLUDED.source_run_id,
                        brief_preview = EXCLUDED.brief_preview,
                        updated_at = EXCLUDED.updated_at
                    """,
                    idea.idea_id,
                    idea.symbol,
                    idea.archetype.value,
                    idea.sector.value,
                    idea.subsector,
                    idea.headline,
                    idea.thesis_short,
                    idea.direction.value,
                    idea.conviction,
                    idea.conviction_band.value,
                    json.dumps(idea.tags),
                    json.dumps([c.model_dump() for c in idea.key_citations]),
                    idea.source_run_id,
                    idea.brief_preview,
                    idea.created_at,
                    idea.updated_at,
                )
        except Exception:
            logger.exception("Failed to persist idea for %s", idea.symbol)

    async def _db_upsert_theme(self, theme: ThemeReport) -> None:
        """Persist a theme to PostgreSQL."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO research_themes (
                        theme_id, title, kind, sector, summary, report_md,
                        archetypes, members, citations, hero_url,
                        created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7::jsonb, $8::jsonb, $9::jsonb, $10,
                        $11, $12
                    )
                    ON CONFLICT (theme_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        report_md = EXCLUDED.report_md,
                        members = EXCLUDED.members,
                        citations = EXCLUDED.citations,
                        updated_at = EXCLUDED.updated_at
                    """,
                    theme.theme_id,
                    theme.title,
                    theme.kind.value,
                    theme.sector.value if theme.sector else None,
                    theme.summary,
                    theme.report_md,
                    json.dumps([a.value for a in theme.archetypes]),
                    json.dumps([m.model_dump() for m in theme.members]),
                    json.dumps([c.model_dump() for c in theme.citations]),
                    theme.hero_url,
                    theme.created_at,
                    theme.updated_at,
                )
        except Exception:
            logger.exception("Failed to persist theme %s", theme.theme_id)

    async def _db_upsert_sector(self, cluster: SectorCluster) -> None:
        """Persist a sector cluster to PostgreSQL."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO research_sector_clusters (
                        sector, members, bias, theme_id, headline, updated_at
                    ) VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                    ON CONFLICT (sector) DO UPDATE SET
                        members = EXCLUDED.members,
                        bias = EXCLUDED.bias,
                        theme_id = EXCLUDED.theme_id,
                        headline = EXCLUDED.headline,
                        updated_at = EXCLUDED.updated_at
                    """,
                    cluster.sector.value,
                    json.dumps([m.model_dump() for m in cluster.members]),
                    cluster.bias,
                    cluster.theme_id,
                    cluster.headline,
                    cluster.updated_at,
                )
        except Exception:
            logger.exception("Failed to persist sector cluster %s", cluster.sector.value)

    # ================================================================== #
    # Bulk load from DB on startup                                        #
    # ================================================================== #

    async def load_from_db(self) -> None:
        """Load all persisted data from PostgreSQL into memory.

        Called once at gateway startup so the in-memory cache is warm.
        Safe to call when ``db_pool`` is ``None`` — returns immediately.
        """
        if self._pool is None:
            return

        try:
            async with self._pool.acquire() as conn:
                # Load ideas
                rows = await conn.fetch(
                    "SELECT * FROM research_ideas ORDER BY conviction DESC LIMIT 200",
                )
                for row in rows:
                    idea = self._row_to_idea(row)
                    self._ideas[idea.idea_id] = idea

                # Load themes
                rows = await conn.fetch(
                    "SELECT * FROM research_themes ORDER BY updated_at DESC LIMIT 50",
                )
                for row in rows:
                    theme = self._row_to_theme(row)
                    self._themes[theme.theme_id] = theme

                # Load sector clusters
                rows = await conn.fetch("SELECT * FROM research_sector_clusters")
                for row in rows:
                    cluster = self._row_to_sector(row)
                    self._sectors[cluster.sector.value] = cluster

            logger.info(
                "Loaded from DB: %d ideas, %d themes, %d sectors",
                len(self._ideas),
                len(self._themes),
                len(self._sectors),
            )
        except Exception:
            logger.warning(
                "Failed to load research data from DB — starting with empty stores. "
                "This is normal if the tables don't exist yet."
            )

    @staticmethod
    def _row_to_idea(row: Any) -> StockIdea:
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tags = json.loads(tags)
        citations = row.get("key_citations") or []
        if isinstance(citations, str):
            citations = json.loads(citations)

        return StockIdea(
            idea_id=str(row["idea_id"]),
            symbol=row["symbol"],
            archetype=StockArchetype(row.get("archetype", "unknown")),
            sector=Sector(row.get("sector", "other")),
            subsector=row.get("subsector"),
            headline=row.get("headline", ""),
            thesis_short=row.get("thesis_short", ""),
            direction=SignalDirection(row.get("direction", "neutral")),
            conviction=float(row.get("conviction", 0.0)),
            conviction_band=ConvictionBand(row.get("conviction_band", "speculative")),
            tags=tags if isinstance(tags, list) else [],
            key_citations=[
                Citation(**c) if isinstance(c, dict) else c
                for c in (citations if isinstance(citations, list) else [])
            ],
            source_run_id=row.get("source_run_id"),
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
            brief_preview=row.get("brief_preview"),
        )

    @staticmethod
    def _row_to_theme(row: Any) -> ThemeReport:
        archetypes = row.get("archetypes") or []
        if isinstance(archetypes, str):
            archetypes = json.loads(archetypes)
        members = row.get("members") or []
        if isinstance(members, str):
            members = json.loads(members)
        citations = row.get("citations") or []
        if isinstance(citations, str):
            citations = json.loads(citations)

        return ThemeReport(
            theme_id=str(row["theme_id"]),
            title=row.get("title", ""),
            kind=ThemeKind(row.get("kind", "custom")),
            sector=Sector(row["sector"]) if row.get("sector") else None,
            summary=row.get("summary", ""),
            report_md=row.get("report_md", ""),
            archetypes=[StockArchetype(a) for a in archetypes if isinstance(a, str)],
            members=[
                ThemeMember(**m) if isinstance(m, dict) else m
                for m in (members if isinstance(members, list) else [])
            ],
            citations=[
                Citation(**c) if isinstance(c, dict) else c
                for c in (citations if isinstance(citations, list) else [])
            ],
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
            hero_url=row.get("hero_url"),
        )

    @staticmethod
    def _row_to_sector(row: Any) -> SectorCluster:
        members = row.get("members") or []
        if isinstance(members, str):
            members = json.loads(members)

        return SectorCluster(
            sector=Sector(row["sector"]),
            members=[
                SectorClusterMember(**m) if isinstance(m, dict) else m
                for m in (members if isinstance(members, list) else [])
            ],
            bias=float(row.get("bias", 0.0)),
            updated_at=str(row.get("updated_at", "")),
            theme_id=row.get("theme_id"),
            headline=row.get("headline"),
        )
