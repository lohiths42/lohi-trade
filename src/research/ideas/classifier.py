"""IdeaClassifier — extracts a ``StockIdea`` from a completed ``ResearchBrief``.

After the Orchestrator produces a brief and the Judge scores it, the
classifier derives:
  • Archetype (compounder / value / growth / cyclical / turnaround / dividend)
  • Direction (bullish / bearish / neutral)
  • Conviction score [0, 1] — derived from the Judge's groundedness scores
  • Tags — extracted from key sections
  • headline + thesis_short — summaries for the Ideas feed

The classifier is deterministic first (heuristic rules on financial metrics),
LLM-assisted second (for direction / headline when the brief is ambiguous).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final
from uuid import uuid4

from src.research.ideas.models import (
    Citation,
    ConvictionBand,
    Sector,
    SectorClusterMember,
    SignalDirection,
    StockArchetype,
    StockIdea,
)

logger = logging.getLogger(__name__)

__all__ = ["IdeaClassifier"]


# --------------------------------------------------------------------------- #
# Sector classification map                                                   #
# --------------------------------------------------------------------------- #

# Maps the backend SectorService's 15 sectors to the GICS-ish `Sector` enum.
_SECTOR_MAP: Final[dict[str, Sector]] = {
    "pharma": Sector.healthcare,
    "it/technology": Sector.information_technology,
    "ai/deep tech": Sector.information_technology,
    "metals & mining": Sector.materials,
    "banking & finance": Sector.financials,
    "fmcg": Sector.consumer_staples,
    "energy": Sector.energy,
    "automobile": Sector.consumer_discretionary,
    "telecom": Sector.communication_services,
    "real estate": Sector.real_estate,
    "infrastructure": Sector.industrials,
    "chemicals": Sector.materials,
    "media & entertainment": Sector.communication_services,
    "insurance": Sector.financials,
    "miscellaneous": Sector.other,
}


# --------------------------------------------------------------------------- #
# Tag extraction patterns                                                     #
# --------------------------------------------------------------------------- #

_TAG_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    ("Monopoly", re.compile(r"monopol|duopol|oligopol|dominant\s+market\s+share", re.I)),
    ("Capex Cycle", re.compile(r"capex|capital\s+expenditure|expansion|greenfield", re.I)),
    ("Debt Reduction", re.compile(r"deleverage|debt\s+reduc|debt-free|net\s+cash", re.I)),
    ("High ROE", re.compile(r"(?:ROE|return\s+on\s+equity)\s*(?:>|above|over)\s*(?:15|20|25)", re.I)),
    ("Turnaround", re.compile(r"turnaround|recovery|restructur|turn\s*-?\s*around", re.I)),
    ("Dividend", re.compile(r"dividend\s+(?:yield|payout|growth)|high\s+dividend", re.I)),
    ("Export", re.compile(r"export\s+(?:driven|led|oriented)|global\s+revenue", re.I)),
    ("PSU", re.compile(r"\bPSU\b|public\s+sector\s+undertaking|government\s+owned", re.I)),
    ("ESG", re.compile(r"\bESG\b|sustainab|green\s+energy|carbon\s+neutral", re.I)),
    ("FII Buying", re.compile(r"FII\s+(?:buying|inflow|accumulation)", re.I)),
    ("DII Buying", re.compile(r"DII\s+(?:buying|inflow|accumulation)", re.I)),
    ("Promoter Buying", re.compile(r"promoter\s+(?:buying|increasing|stake\s+increase)", re.I)),
    ("Insider Selling", re.compile(r"insider\s+sell|promoter\s+sell|promoter\s+pledg", re.I)),
]


# --------------------------------------------------------------------------- #
# Classifier                                                                  #
# --------------------------------------------------------------------------- #


class IdeaClassifier:
    """Extract a ``StockIdea`` from a completed research brief.

    Parameters
    ----------
    llm:
        Optional LLM provider for direction/headline extraction when
        the heuristic is ambiguous. When ``None``, falls back to pure
        heuristic classification.
    """

    def __init__(self, *, llm: Any | None = None) -> None:
        self._llm = llm

    async def classify(
        self,
        *,
        brief: Mapping[str, Any],
        judge_report: Any | None = None,
        symbol: str,
        sector_hint: str | None = None,
        run_id: str | None = None,
    ) -> StockIdea:
        """Classify a completed brief into a ``StockIdea``.

        Parameters
        ----------
        brief:
            The ``dict[str, Any]`` returned by ``orchestrator.run()``.
            Expected keys: ``summary``, ``thesis``, ``risks``,
            ``financial_highlights``, ``management_commentary``,
            ``technical_view``, ``peers``, ``macro_context``,
            ``citations``, ``quality``.
        judge_report:
            Optional ``JudgeReport`` for conviction scoring. When
            ``None``, conviction defaults to 0.5.
        symbol:
            The ticker symbol (e.g. ``"RELIANCE"``).
        sector_hint:
            Optional sector string from the ``securities`` table. Mapped
            to the GICS-ish ``Sector`` enum.
        run_id:
            The ``run_id`` of the research run that produced this brief.

        Returns
        -------
        StockIdea
            A fully populated idea ready for persistence.
        """
        now = datetime.now(timezone.utc).isoformat()

        # 1) Sector classification
        sector = self._classify_sector(sector_hint)

        # 2) Direction from thesis
        thesis = str(brief.get("thesis", ""))
        summary = str(brief.get("summary", ""))
        direction = self._classify_direction(thesis, summary)

        # 3) Conviction from Judge report
        conviction = self._compute_conviction(judge_report)
        conviction_band = self._conviction_to_band(conviction)

        # 4) Archetype from financial highlights
        financial = str(brief.get("financial_highlights", ""))
        archetype = self._classify_archetype(financial, thesis, direction)

        # 5) Tags from all sections
        all_text = " ".join(
            str(brief.get(k, ""))
            for k in (
                "thesis", "risks", "financial_highlights",
                "management_commentary", "technical_view", "peers",
            )
        )
        tags = self._extract_tags(all_text)

        # 6) Headline and thesis_short
        headline = self._build_headline(symbol, direction, conviction_band, archetype)
        thesis_short = self._extract_thesis_short(thesis, summary)

        # 7) Brief preview (first 300 chars of summary)
        brief_preview = summary[:300] if summary else None

        # 8) Citations (first 5)
        raw_citations = brief.get("citations", "[]")
        if isinstance(raw_citations, str):
            try:
                chunk_ids = json.loads(raw_citations)
            except (json.JSONDecodeError, TypeError):
                chunk_ids = []
        elif isinstance(raw_citations, list):
            chunk_ids = raw_citations
        else:
            chunk_ids = []

        key_citations = [
            Citation(chunk_id=cid, text="", source="")
            for cid in chunk_ids[:5]
            if isinstance(cid, str)
        ]

        return StockIdea(
            idea_id=str(uuid4()),
            symbol=symbol.upper(),
            archetype=archetype,
            sector=sector,
            subsector=None,
            headline=headline,
            thesis_short=thesis_short,
            direction=direction,
            conviction=conviction,
            conviction_band=conviction_band,
            tags=tags,
            key_citations=key_citations,
            source_run_id=run_id,
            created_at=now,
            updated_at=now,
            brief_preview=brief_preview,
        )

    # ------------------------------------------------------------------ #
    # Sector                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_sector(sector_hint: str | None) -> Sector:
        if not sector_hint:
            return Sector.other
        normalized = sector_hint.strip().lower()
        return _SECTOR_MAP.get(normalized, Sector.other)

    # ------------------------------------------------------------------ #
    # Direction                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_direction(thesis: str, summary: str) -> SignalDirection:
        """Heuristic direction from thesis/summary text."""
        text = (thesis + " " + summary).lower()

        bullish_signals = sum(1 for w in (
            "bullish", "buy", "outperform", "strong growth",
            "positive", "upside", "attractive valuation",
            "undervalued", "re-rating", "accumulate",
        ) if w in text)

        bearish_signals = sum(1 for w in (
            "bearish", "sell", "underperform", "weak",
            "negative", "downside", "overvalued",
            "de-rating", "avoid", "headwind", "declining",
        ) if w in text)

        if bullish_signals > bearish_signals and bullish_signals >= 1:
            return SignalDirection.bullish
        if bearish_signals > bullish_signals and bearish_signals >= 1:
            return SignalDirection.bearish
        return SignalDirection.neutral

    # ------------------------------------------------------------------ #
    # Conviction                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_conviction(judge_report: Any | None) -> float:
        """Derive conviction [0, 1] from the Judge's groundedness scores."""
        if judge_report is None:
            return 0.5

        scores: dict[str, float] = {}
        if hasattr(judge_report, "groundedness_score"):
            scores = judge_report.groundedness_score or {}
        elif isinstance(judge_report, Mapping):
            scores = judge_report.get("groundedness_score", {})

        if not scores:
            return 0.5

        # Weighted average: thesis and financial_highlights weighted 2x
        weighted_sum = 0.0
        weight_total = 0.0
        for section, score in scores.items():
            w = 2.0 if section in ("thesis", "financial_highlights") else 1.0
            weighted_sum += score * w
            weight_total += w

        return round(weighted_sum / weight_total, 3) if weight_total > 0 else 0.5

    @staticmethod
    def _conviction_to_band(conviction: float) -> ConvictionBand:
        if conviction >= 0.8:
            return ConvictionBand.high
        if conviction >= 0.65:
            return ConvictionBand.building
        if conviction >= 0.4:
            return ConvictionBand.watch
        return ConvictionBand.speculative

    # ------------------------------------------------------------------ #
    # Archetype                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_archetype(
        financial: str,
        thesis: str,
        direction: SignalDirection,
    ) -> StockArchetype:
        """Heuristic archetype classification from financial/thesis text."""
        text = (financial + " " + thesis).lower()

        # Check for turnaround signals first (they override others)
        if any(w in text for w in ("turnaround", "recovery", "restructur")):
            return StockArchetype.turnaround

        # Compounder: consistent high ROE, steady growth
        compounder_signals = sum(1 for w in (
            "consistent", "compounding", "steady growth",
            "roe above", "return on equity", "moat", "monopoly",
        ) if w in text)
        if compounder_signals >= 2:
            return StockArchetype.compounder

        # Growth: high revenue/profit growth
        growth_signals = sum(1 for w in (
            "high growth", "rapid growth", "revenue growth",
            "cagr", "expanding market", "scalable",
        ) if w in text)
        if growth_signals >= 2:
            return StockArchetype.growth

        # Value: low PE, undervalued
        value_signals = sum(1 for w in (
            "undervalued", "low pe", "low p/e", "margin of safety",
            "below book", "deep value", "cheap",
        ) if w in text)
        if value_signals >= 2:
            return StockArchetype.value

        # Dividend: yield focus
        if any(w in text for w in ("dividend yield", "dividend payout", "income stock")):
            return StockArchetype.dividend

        # Cyclical: commodity / cycle language
        if any(w in text for w in ("cyclical", "commodity cycle", "upcycle", "downcycle")):
            return StockArchetype.cyclical

        return StockArchetype.unknown

    # ------------------------------------------------------------------ #
    # Tags                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_tags(text: str) -> list[str]:
        """Extract tags from the brief text using pattern matching."""
        tags: list[str] = []
        for tag_name, pattern in _TAG_PATTERNS:
            if pattern.search(text):
                tags.append(tag_name)
        return tags[:8]  # Cap at 8 tags

    # ------------------------------------------------------------------ #
    # Headline / thesis_short                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_headline(
        symbol: str,
        direction: SignalDirection,
        band: ConvictionBand,
        archetype: StockArchetype,
    ) -> str:
        """Build a headline like 'RELIANCE: High-conviction growth story'."""
        direction_word = {
            SignalDirection.bullish: "Bullish",
            SignalDirection.bearish: "Cautious",
            SignalDirection.neutral: "Neutral",
        }[direction]

        archetype_word = {
            StockArchetype.compounder: "compounder",
            StockArchetype.value: "value pick",
            StockArchetype.growth: "growth story",
            StockArchetype.cyclical: "cyclical play",
            StockArchetype.turnaround: "turnaround candidate",
            StockArchetype.special_situation: "special situation",
            StockArchetype.dividend: "dividend yield play",
            StockArchetype.unknown: "opportunity",
        }[archetype]

        band_word = {
            ConvictionBand.high: "High-conviction",
            ConvictionBand.building: "Building-conviction",
            ConvictionBand.watch: "On the radar",
            ConvictionBand.speculative: "Speculative",
        }[band]

        return f"{symbol}: {band_word} {direction_word.lower()} {archetype_word}"

    @staticmethod
    def _extract_thesis_short(thesis: str, summary: str) -> str:
        """Extract a one-sentence thesis from the brief."""
        source = thesis if thesis.strip() else summary
        if not source.strip():
            return ""

        # Take the first sentence (up to first period + space or newline)
        for sep in (". ", ".\n", "\n"):
            idx = source.find(sep)
            if idx > 0 and idx < 300:
                return source[: idx + 1].strip()

        # Fallback: first 200 chars
        return source[:200].strip()
