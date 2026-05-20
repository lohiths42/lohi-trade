"""SectorAnalyzer — builds ``SectorCluster``s from the researched idea pool.

Produces one ``SectorCluster`` per GICS-ish ``Sector`` that has at least
one researched symbol. Each cluster has:
  - Members ordered by conviction
  - Aggregate bias (positive = bullish tilt)
  - Optional link to the sector's ThemeReport
  - One-line AI-generated headline
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Final

from src.research.ideas.models import (
    Sector,
    SectorCluster,
    SectorClusterMember,
    SignalDirection,
    StockIdea,
)

logger = logging.getLogger(__name__)

__all__ = ["SectorAnalyzer"]

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


class SectorAnalyzer:
    """Build sector clusters from the researched idea pool.

    Parameters
    ----------
    llm:
        Optional LLM for generating sector headlines. Falls back
        to heuristic headline if ``None``.
    """

    def __init__(self, *, llm: Any | None = None) -> None:
        self._llm = llm

    async def analyze(
        self,
        ideas: list[StockIdea],
        *,
        theme_map: dict[str, str] | None = None,
    ) -> list[SectorCluster]:
        """Build sector clusters from ideas.

        Parameters
        ----------
        ideas:
            All current ``StockIdea`` instances.
        theme_map:
            Optional ``{sector_value: theme_id}`` mapping from previously
            generated sector themes. Used to link clusters to their themes.

        Returns
        -------
        list[SectorCluster]
            One cluster per sector with ≥ 1 member, ordered by absolute bias.
        """
        theme_map = theme_map or {}

        # Group ideas by sector
        groups: dict[Sector, list[StockIdea]] = defaultdict(list)
        for idea in ideas:
            groups[idea.sector].append(idea)

        now = datetime.now(timezone.utc).isoformat()
        clusters: list[SectorCluster] = []

        for sector, members in groups.items():
            # Sort by conviction
            members.sort(key=lambda i: i.conviction, reverse=True)

            # Compute aggregate bias
            bias = self._compute_bias(members)

            # Build cluster members
            cluster_members = [
                SectorClusterMember(
                    symbol=m.symbol,
                    archetype=m.archetype,
                    conviction=m.conviction,
                    direction=m.direction,
                )
                for m in members
            ]

            # Generate headline
            headline = self._build_headline(sector, members, bias)

            clusters.append(SectorCluster(
                sector=sector,
                members=cluster_members,
                bias=round(bias, 3),
                updated_at=now,
                theme_id=theme_map.get(sector.value),
                headline=headline,
            ))

        # Sort by absolute bias (strongest signal first)
        clusters.sort(key=lambda c: abs(c.bias), reverse=True)

        logger.info(
            "Analyzed %d sectors from %d ideas",
            len(clusters),
            len(ideas),
        )

        return clusters

    # ------------------------------------------------------------------ #
    # Bias computation                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_bias(members: list[StockIdea]) -> float:
        """Compute aggregate sector bias [-1, +1].

        Formula: weighted mean of signed conviction.
        bullish → +conviction, bearish → -conviction, neutral → 0.
        """
        if not members:
            return 0.0

        weighted_sum = 0.0
        for m in members:
            sign = {
                SignalDirection.bullish: 1.0,
                SignalDirection.bearish: -1.0,
                SignalDirection.neutral: 0.0,
            }[m.direction]
            weighted_sum += sign * m.conviction

        return weighted_sum / len(members)

    # ------------------------------------------------------------------ #
    # Headline                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_headline(
        sector: Sector,
        members: list[StockIdea],
        bias: float,
    ) -> str:
        """Build a one-line headline for the sector cluster."""
        sector_label = _SECTOR_LABELS.get(sector, sector.value)
        n = len(members)

        if bias > 0.3:
            tone = "Strong bullish momentum"
        elif bias > 0.1:
            tone = "Modestly bullish"
        elif bias < -0.3:
            tone = "Under selling pressure"
        elif bias < -0.1:
            tone = "Cautious outlook"
        else:
            tone = "Mixed signals"

        # Mention top stock
        top = members[0] if members else None
        top_mention = f" — {top.symbol} leads at {top.conviction:.0%}" if top else ""

        return f"{sector_label}: {tone} across {n} stocks{top_mention}"
