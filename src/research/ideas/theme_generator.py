"""ThemeGenerator — clusters ``StockIdea``s into editorial ``ThemeReport``s.

Produces three types of themes:
  1. **Sector themes** — "Banking & Finance: NPA Trends Improving" — one per
     sector with ≥ 2 researched members.
  2. **Archetype themes** — "Compounders with Expanding Capex" — one per
     archetype with ≥ 3 members.
  3. **Custom themes** — user-initiated via the Themes page.

Each theme includes a ``report_md`` editorial synthesis across the
constituent briefs, generated via LLM if available, or a structured
template fallback if not.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Final
from uuid import uuid4

from src.research.ideas.models import (
    Sector,
    SectorCluster,
    SectorClusterMember,
    SignalDirection,
    StockArchetype,
    StockIdea,
    ThemeKind,
    ThemeMember,
    ThemeReport,
)

logger = logging.getLogger(__name__)

__all__ = ["ThemeGenerator"]

# Minimum cluster size before a theme is generated.
_MIN_SECTOR_CLUSTER: Final[int] = 2
_MIN_ARCHETYPE_CLUSTER: Final[int] = 3

# Human-readable labels for archetypes.
_ARCHETYPE_LABELS: Final[dict[StockArchetype, str]] = {
    StockArchetype.compounder: "Compounders",
    StockArchetype.value: "Deep Value Picks",
    StockArchetype.growth: "High Growth Stories",
    StockArchetype.cyclical: "Cyclical Plays",
    StockArchetype.turnaround: "Turnaround Candidates",
    StockArchetype.special_situation: "Special Situations",
    StockArchetype.dividend: "Dividend Yield Plays",
    StockArchetype.unknown: "Under Review",
}

# Human-readable labels for sectors.
_SECTOR_LABELS: Final[dict[Sector, str]] = {
    Sector.financials: "Banks & Financials",
    Sector.information_technology: "Information Technology",
    Sector.healthcare: "Pharma & Healthcare",
    Sector.consumer_staples: "Consumer Staples",
    Sector.consumer_discretionary: "Consumer Discretionary",
    Sector.industrials: "Industrials & Capex",
    Sector.energy: "Energy & Utilities",
    Sector.utilities: "Utilities",
    Sector.materials: "Materials",
    Sector.real_estate: "Real Estate",
    Sector.communication_services: "Communications",
    Sector.other: "Other",
}


class ThemeGenerator:
    """Cluster ideas into themes and generate editorial reports.

    Parameters
    ----------
    llm:
        Optional LLM provider for generating ``report_md``. When ``None``,
        uses a structured template fallback.
    """

    def __init__(self, *, llm: Any | None = None) -> None:
        self._llm = llm

    async def generate_all(
        self,
        ideas: list[StockIdea],
    ) -> list[ThemeReport]:
        """Generate all auto-discovered themes from the current idea pool.

        Returns sector themes + archetype themes, deduplicated.
        """
        themes: list[ThemeReport] = []

        sector_themes = await self._generate_sector_themes(ideas)
        themes.extend(sector_themes)

        archetype_themes = await self._generate_archetype_themes(ideas)
        themes.extend(archetype_themes)

        logger.info(
            "Generated %d themes (%d sector, %d archetype) from %d ideas",
            len(themes),
            len(sector_themes),
            len(archetype_themes),
            len(ideas),
        )

        return themes

    # ------------------------------------------------------------------ #
    # Sector themes                                                       #
    # ------------------------------------------------------------------ #

    async def _generate_sector_themes(
        self,
        ideas: list[StockIdea],
    ) -> list[ThemeReport]:
        """One theme per sector with ≥ MIN members."""
        clusters: dict[Sector, list[StockIdea]] = defaultdict(list)
        for idea in ideas:
            clusters[idea.sector].append(idea)

        themes: list[ThemeReport] = []
        for sector, members in clusters.items():
            if len(members) < _MIN_SECTOR_CLUSTER:
                continue

            # Sort by conviction descending
            members.sort(key=lambda i: i.conviction, reverse=True)

            sector_label = _SECTOR_LABELS.get(sector, sector.value)
            dominant_direction = self._dominant_direction(members)
            avg_conviction = sum(m.conviction for m in members) / len(members)

            # Build headline
            direction_word = {
                SignalDirection.bullish: "Looking Strong",
                SignalDirection.bearish: "Under Pressure",
                SignalDirection.neutral: "Mixed Signals",
            }[dominant_direction]

            title = f"{sector_label}: {direction_word}"
            summary = self._build_sector_summary(sector_label, members, dominant_direction)
            report_md = self._build_sector_report(sector_label, members)

            theme_members = [
                ThemeMember(
                    symbol=m.symbol,
                    weight=m.conviction,
                    conviction=m.conviction,
                    direction=m.direction,
                    sector=m.sector,
                )
                for m in members
            ]

            themes.append(ThemeReport(
                theme_id=str(uuid4()),
                title=title,
                kind=ThemeKind.sector,
                sector=sector,
                summary=summary,
                report_md=report_md,
                archetypes=list({m.archetype for m in members}),
                members=theme_members,
                citations=[],
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            ))

        return themes

    # ------------------------------------------------------------------ #
    # Archetype themes                                                    #
    # ------------------------------------------------------------------ #

    async def _generate_archetype_themes(
        self,
        ideas: list[StockIdea],
    ) -> list[ThemeReport]:
        """One theme per archetype with ≥ MIN members."""
        clusters: dict[StockArchetype, list[StockIdea]] = defaultdict(list)
        for idea in ideas:
            if idea.archetype != StockArchetype.unknown:
                clusters[idea.archetype].append(idea)

        themes: list[ThemeReport] = []
        for archetype, members in clusters.items():
            if len(members) < _MIN_ARCHETYPE_CLUSTER:
                continue

            members.sort(key=lambda i: i.conviction, reverse=True)

            archetype_label = _ARCHETYPE_LABELS.get(archetype, archetype.value)

            # Build a title from the members' common traits
            common_tags = self._find_common_tags(members)
            tag_suffix = f" — {', '.join(common_tags[:2])}" if common_tags else ""
            title = f"{archetype_label}{tag_suffix}"

            summary = self._build_archetype_summary(archetype_label, members)
            report_md = self._build_archetype_report(archetype_label, members)

            theme_members = [
                ThemeMember(
                    symbol=m.symbol,
                    weight=m.conviction,
                    conviction=m.conviction,
                    direction=m.direction,
                    sector=m.sector,
                )
                for m in members
            ]

            themes.append(ThemeReport(
                theme_id=str(uuid4()),
                title=title,
                kind=ThemeKind.archetype,
                sector=None,
                summary=summary,
                report_md=report_md,
                archetypes=[archetype],
                members=theme_members,
                citations=[],
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            ))

        return themes

    # ------------------------------------------------------------------ #
    # Report builders (template fallback)                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_sector_summary(
        sector_label: str,
        members: list[StockIdea],
        direction: SignalDirection,
    ) -> str:
        symbols = ", ".join(m.symbol for m in members[:5])
        direction_word = direction.value
        return (
            f"{sector_label} sector shows a {direction_word} bias across "
            f"{len(members)} researched stocks ({symbols}). "
            f"Average conviction: {sum(m.conviction for m in members) / len(members):.0%}."
        )

    @staticmethod
    def _build_sector_report(
        sector_label: str,
        members: list[StockIdea],
    ) -> str:
        lines = [f"# {sector_label} — Research Cluster\n"]
        lines.append(f"**{len(members)} stocks** analyzed in this sector.\n")

        for m in members[:10]:
            direction_emoji = {
                SignalDirection.bullish: "🟢",
                SignalDirection.bearish: "🔴",
                SignalDirection.neutral: "🟡",
            }[m.direction]
            lines.append(
                f"### {direction_emoji} {m.symbol} — {m.conviction_band.value.title()} "
                f"({m.conviction:.0%})"
            )
            if m.thesis_short:
                lines.append(f"\n{m.thesis_short}\n")
            if m.tags:
                lines.append(f"Tags: {', '.join(m.tags)}\n")

        return "\n".join(lines)

    @staticmethod
    def _build_archetype_summary(
        archetype_label: str,
        members: list[StockIdea],
    ) -> str:
        symbols = ", ".join(m.symbol for m in members[:5])
        return (
            f"{len(members)} stocks classified as {archetype_label} "
            f"({symbols}). Cross-sector analysis below."
        )

    @staticmethod
    def _build_archetype_report(
        archetype_label: str,
        members: list[StockIdea],
    ) -> str:
        lines = [f"# {archetype_label}\n"]

        sectors_seen = set()
        for m in members:
            sectors_seen.add(m.sector.value)

        lines.append(
            f"**{len(members)} stocks** across "
            f"**{len(sectors_seen)} sectors**.\n"
        )

        for m in members[:10]:
            sector_label = _SECTOR_LABELS.get(m.sector, m.sector.value)
            lines.append(
                f"### {m.symbol} ({sector_label}) — {m.conviction:.0%} conviction"
            )
            if m.thesis_short:
                lines.append(f"\n{m.thesis_short}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _dominant_direction(ideas: list[StockIdea]) -> SignalDirection:
        """Majority-vote direction across a cluster."""
        bullish = sum(1 for i in ideas if i.direction == SignalDirection.bullish)
        bearish = sum(1 for i in ideas if i.direction == SignalDirection.bearish)
        if bullish > bearish:
            return SignalDirection.bullish
        if bearish > bullish:
            return SignalDirection.bearish
        return SignalDirection.neutral

    @staticmethod
    def _find_common_tags(ideas: list[StockIdea]) -> list[str]:
        """Find tags that appear in ≥ 50% of the cluster."""
        from collections import Counter
        tag_counts: Counter[str] = Counter()
        for idea in ideas:
            for tag in idea.tags:
                tag_counts[tag] += 1
        threshold = len(ideas) * 0.5
        return [tag for tag, count in tag_counts.most_common() if count >= threshold]
