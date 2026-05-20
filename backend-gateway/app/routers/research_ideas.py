"""Research Ideas / Themes / Sectors / Signals router.

REST endpoints that serve the multibagg-style surface of the Research
dashboard. All data is populated by the background ``ResearchScheduler``
and served from the ``IdeaStore``.

Endpoints
---------
GET  /ideas           → list ideas (filterable by sector, archetype, direction)
GET  /ideas/:id       → single idea
GET  /themes          → list themes
GET  /themes/:id      → single theme
POST /themes/generate → on-demand theme generation
GET  /sectors         → list sector clusters
GET  /sectors/:sector → single sector cluster detail
GET  /signals         → list research signals
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level reference — set by ``set_idea_store()`` from ``main.py``.
_idea_store: Any | None = None
_theme_generator: Any | None = None
_sector_analyzer: Any | None = None


def set_idea_services(
    idea_store: Any,
    theme_generator: Any | None = None,
    sector_analyzer: Any | None = None,
) -> None:
    """Inject the IdeaStore and generators from the gateway lifespan."""
    global _idea_store, _theme_generator, _sector_analyzer
    _idea_store = idea_store
    _theme_generator = theme_generator
    _sector_analyzer = sector_analyzer


# ========================================================================== #
# Ideas                                                                      #
# ========================================================================== #


@router.get("/ideas")
async def list_ideas(
    limit: int = Query(default=50, ge=1, le=200),
    sector: Optional[str] = None,
    archetype: Optional[str] = None,
    direction: Optional[str] = None,
) -> list[dict]:
    """List stock ideas, most recent / highest conviction first."""
    if _idea_store is None:
        return []

    ideas = await _idea_store.list_ideas(
        limit=limit,
        sector=sector,
        archetype=archetype,
        direction=direction,
    )
    return [i.model_dump() for i in ideas]


@router.get("/ideas/{idea_id}")
async def get_idea(idea_id: str) -> dict | None:
    """Fetch a single idea by id."""
    if _idea_store is None:
        return None

    idea = await _idea_store.get_idea(idea_id)
    if idea is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea.model_dump()


# ========================================================================== #
# Themes                                                                     #
# ========================================================================== #


@router.get("/themes")
async def list_themes(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """List all auto-generated and custom themes."""
    if _idea_store is None:
        return []

    themes = await _idea_store.list_themes(limit=limit)
    return [t.model_dump() for t in themes]


@router.get("/themes/{theme_id}")
async def get_theme(theme_id: str) -> dict | None:
    """Fetch a single theme report by id."""
    if _idea_store is None:
        return None

    theme = await _idea_store.get_theme(theme_id)
    if theme is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Theme not found")
    return theme.model_dump()


@router.post("/themes/generate", status_code=202)
async def generate_theme(body: dict) -> dict:
    """On-demand theme generation from a symbol cohort."""
    if _idea_store is None or _theme_generator is None:
        return {"error": "Theme generation not available"}

    symbols = body.get("symbols", [])
    title = body.get("title", "Custom Theme")

    # Gather ideas for requested symbols
    ideas = []
    for sym in symbols:
        idea = await _idea_store.get_idea_by_symbol(sym)
        if idea:
            ideas.append(idea)

    if not ideas:
        return {"error": "No researched symbols found in the request"}

    # Generate themes from this subset
    from src.research.ideas.models import ThemeKind, ThemeMember, ThemeReport
    from uuid import uuid4
    from datetime import datetime, timezone

    theme = ThemeReport(
        theme_id=str(uuid4()),
        title=title,
        kind=ThemeKind.custom,
        summary=f"Custom theme with {len(ideas)} stocks: {', '.join(i.symbol for i in ideas)}",
        report_md="",
        archetypes=list({i.archetype for i in ideas}),
        members=[
            ThemeMember(
                symbol=i.symbol,
                weight=i.conviction,
                conviction=i.conviction,
                direction=i.direction,
                sector=i.sector,
            )
            for i in ideas
        ],
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    await _idea_store.upsert_theme(theme)

    return {
        "theme_id": theme.theme_id,
        "run_ids": [i.source_run_id for i in ideas if i.source_run_id],
        "channel": f"research:theme:{theme.theme_id}",
    }


# ========================================================================== #
# Sectors                                                                    #
# ========================================================================== #


@router.get("/sectors")
async def list_sector_clusters() -> list[dict]:
    """List all sector clusters from auto-discovery."""
    if _idea_store is None:
        return []

    clusters = await _idea_store.list_sector_clusters()
    return [c.model_dump() for c in clusters]


@router.get("/sectors/{sector}")
async def get_sector_cluster(sector: str) -> dict | None:
    """Fetch a single sector cluster."""
    if _idea_store is None:
        return None

    cluster = await _idea_store.get_sector_cluster(sector)
    if cluster is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Sector cluster not found")
    return cluster.model_dump()


@router.post("/sectors/{sector}/generate", status_code=202)
async def generate_sector_theme(sector: str) -> dict:
    """Trigger regeneration of a sector-cluster theme."""
    if _idea_store is None or _theme_generator is None:
        return {"error": "Sector analysis not available"}

    ideas = await _idea_store.list_ideas(limit=200, sector=sector)
    if not ideas:
        return {"error": f"No ideas found for sector '{sector}'"}

    themes = await _theme_generator._generate_sector_themes(ideas)
    for theme in themes:
        await _idea_store.upsert_theme(theme)

    return {
        "theme_id": themes[0].theme_id if themes else None,
        "run_ids": [],
        "channel": f"research:sector:{sector}",
    }


# ========================================================================== #
# Signals                                                                    #
# ========================================================================== #


@router.get("/signals")
async def list_signals(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """List research-derived signals for the algo bridge."""
    if _idea_store is None:
        return []

    signals = await _idea_store.list_signals(limit=limit)
    return [s.model_dump() for s in signals]
