"""Pydantic domain models for Ideas, Themes, and Sector Clusters.

These mirror the frontend TypeScript types in
``Lohi-TRADE Web App Design/src/lib/research-ideas-types.ts`` and are the
canonical backend source of truth for the REST surface at
``/api/v2/research/{ideas,themes,sectors,signals}``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class StockArchetype(str, Enum):
    compounder = "compounder"
    value = "value"
    growth = "growth"
    cyclical = "cyclical"
    turnaround = "turnaround"
    special_situation = "special_situation"
    dividend = "dividend"
    unknown = "unknown"


class Sector(str, Enum):
    financials = "financials"
    information_technology = "information_technology"
    healthcare = "healthcare"
    consumer_staples = "consumer_staples"
    consumer_discretionary = "consumer_discretionary"
    industrials = "industrials"
    energy = "energy"
    utilities = "utilities"
    materials = "materials"
    real_estate = "real_estate"
    communication_services = "communication_services"
    other = "other"


class SignalDirection(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"


class ConvictionBand(str, Enum):
    speculative = "speculative"
    watch = "watch"
    building = "building"
    high = "high"


class ThemeKind(str, Enum):
    archetype = "archetype"
    sector = "sector"
    custom = "custom"


# --------------------------------------------------------------------------- #
# Domain models                                                               #
# --------------------------------------------------------------------------- #


class Citation(BaseModel):
    """A single citation backing a claim."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    text: str = ""
    source: str = ""


class StockIdea(BaseModel):
    """A single investment idea extracted from a research brief."""
    model_config = ConfigDict(extra="ignore")

    idea_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    archetype: StockArchetype = StockArchetype.unknown
    sector: Sector = Sector.other
    subsector: Optional[str] = None
    headline: str = ""
    thesis_short: str = ""
    direction: SignalDirection = SignalDirection.neutral
    conviction: float = Field(default=0.0, ge=0.0, le=1.0)
    conviction_band: ConvictionBand = ConvictionBand.speculative
    tags: list[str] = Field(default_factory=list)
    key_citations: list[Citation] = Field(default_factory=list)
    source_run_id: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    brief_preview: Optional[str] = None


class ThemeMember(BaseModel):
    """A single symbol's contribution to a Theme."""
    model_config = ConfigDict(extra="ignore")

    symbol: str
    weight: float = 1.0
    conviction: float = 0.0
    direction: SignalDirection = SignalDirection.neutral
    sector: Optional[Sector] = None


class ThemeReport(BaseModel):
    """A cross-symbol thematic report."""
    model_config = ConfigDict(extra="ignore")

    theme_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    kind: ThemeKind = ThemeKind.custom
    sector: Optional[Sector] = None
    summary: str = ""
    report_md: str = ""
    archetypes: list[StockArchetype] = Field(default_factory=list)
    members: list[ThemeMember] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    hero_url: Optional[str] = None


class SectorClusterMember(BaseModel):
    """A single symbol within a sector cluster."""
    model_config = ConfigDict(extra="ignore")

    symbol: str
    archetype: StockArchetype = StockArchetype.unknown
    conviction: float = 0.0
    direction: SignalDirection = SignalDirection.neutral


class SectorCluster(BaseModel):
    """A sector cluster produced by auto-discovery."""
    model_config = ConfigDict(extra="ignore")

    sector: Sector
    members: list[SectorClusterMember] = Field(default_factory=list)
    bias: float = 0.0
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    theme_id: Optional[str] = None
    headline: Optional[str] = None


class ResearchSignal(BaseModel):
    """A research-derived trading signal for the algo bridge."""
    model_config = ConfigDict(extra="ignore")

    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    direction: SignalDirection = SignalDirection.neutral
    conviction: float = 0.0
    archetype: StockArchetype = StockArchetype.unknown
    sector: Optional[Sector] = None
    source_run_id: str = ""
    thesis_short: str = ""
    emitted_at: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp(),
    )
    expires_at: float = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc).timestamp() + 86400
        ),  # 24h default
    )
    consumed_by_algo: bool = False
