"""``ResearchScheduler`` — periodic background research engine.

The "always-on brain" that drives proactive research. Unlike the
reactive ``POST /runs`` flow (user clicks → orchestrator runs),
this scheduler continuously:

1. Researches **watchlist symbols** at configurable intervals
2. Classifies briefs into **StockIdeas** (with conviction scoring)
3. Generates **ThemeReports** by clustering ideas
4. Builds **SectorClusters** for the sector auto-discovery grid

Market-hours aware: runs more frequently during IST 9:15–15:30,
slower off-hours.

Lifecycle: Started as an ``asyncio.Task`` from the gateway lifespan.
Cancellation-safe — stops cleanly on ``SIGINT``/``SIGTERM``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Final
from uuid import UUID, uuid4

from src.research.ideas.classifier import IdeaClassifier
from src.research.ideas.models import Sector, StockIdea
from src.research.ideas.sector_analyzer import SectorAnalyzer
from src.research.ideas.store import IdeaStore
from src.research.ideas.theme_generator import ThemeGenerator

logger = logging.getLogger(__name__)

__all__ = ["ResearchScheduler"]

# IST offset
_IST_OFFSET: Final[timedelta] = timedelta(hours=5, minutes=30)

# Market hours in IST
_MARKET_OPEN_HOUR: Final[int] = 9
_MARKET_OPEN_MIN: Final[int] = 15
_MARKET_CLOSE_HOUR: Final[int] = 15
_MARKET_CLOSE_MIN: Final[int] = 30


# --------------------------------------------------------------------------- #
# Schedule config                                                             #
# --------------------------------------------------------------------------- #


class ScheduleConfig:
    """Configurable intervals for the scheduler."""

    def __init__(
        self,
        *,
        # Market hours intervals (minutes)
        watchlist_interval_market: int = 120,
        sector_interval_market: int = 60,
        theme_interval_market: int = 120,
        # Off-hours intervals (minutes)
        watchlist_interval_offhours: int = 360,
        sector_interval_offhours: int = 720,
        theme_interval_offhours: int = 1440,
        # Limits
        max_symbols_per_cycle: int = 10,
        freshness_window_min: int = 110,
    ) -> None:
        self.watchlist_interval_market = watchlist_interval_market
        self.sector_interval_market = sector_interval_market
        self.theme_interval_market = theme_interval_market
        self.watchlist_interval_offhours = watchlist_interval_offhours
        self.sector_interval_offhours = sector_interval_offhours
        self.theme_interval_offhours = theme_interval_offhours
        self.max_symbols_per_cycle = max_symbols_per_cycle
        self.freshness_window_min = freshness_window_min

    @classmethod
    def from_settings(cls, settings: dict) -> "ScheduleConfig":
        """Build from ``config/settings.yaml`` → ``research.scheduler``."""
        scheduler_cfg = (
            settings.get("research", {}).get("scheduler", {})
        )
        market = scheduler_cfg.get("market_hours", {})
        off = scheduler_cfg.get("off_hours", {})

        return cls(
            watchlist_interval_market=market.get("watchlist_interval_min", 120),
            sector_interval_market=market.get("sector_interval_min", 60),
            theme_interval_market=market.get("theme_interval_min", 120),
            watchlist_interval_offhours=off.get("watchlist_interval_min", 360),
            sector_interval_offhours=off.get("sector_interval_min", 720),
            theme_interval_offhours=off.get("theme_interval_min", 1440),
            max_symbols_per_cycle=scheduler_cfg.get("max_symbols_per_cycle", 10),
            freshness_window_min=scheduler_cfg.get("freshness_window_min", 110),
        )


# --------------------------------------------------------------------------- #
# Scheduler                                                                   #
# --------------------------------------------------------------------------- #


class ResearchScheduler:
    """Periodic background research engine.

    Parameters
    ----------
    orchestrator_factory:
        Callable that returns a new ``ResearchOrchestrator``. The scheduler
        creates a fresh one per research run to avoid state leaks.
    idea_classifier:
        ``IdeaClassifier`` instance for extracting ideas from briefs.
    theme_generator:
        ``ThemeGenerator`` for clustering ideas into themes.
    sector_analyzer:
        ``SectorAnalyzer`` for building sector clusters.
    idea_store:
        ``IdeaStore`` for persistence.
    watchlist_resolver:
        Async callable returning the current watchlist symbols.
        Signature: ``async () -> list[str]``.
    sector_resolver:
        Optional async callable returning sector info for a symbol.
        Signature: ``async (symbol: str) -> str | None``.
    config:
        Schedule intervals and limits.
    """

    def __init__(
        self,
        *,
        orchestrator_factory: Callable[..., Awaitable[Any]],
        idea_classifier: IdeaClassifier,
        theme_generator: ThemeGenerator,
        sector_analyzer: SectorAnalyzer,
        idea_store: IdeaStore,
        watchlist_resolver: Callable[[], Awaitable[list[str]]],
        sector_resolver: Callable[[str], Awaitable[str | None]] | None = None,
        config: ScheduleConfig | None = None,
    ) -> None:
        self._orch_factory = orchestrator_factory
        self._classifier = idea_classifier
        self._theme_gen = theme_generator
        self._sector_analyzer = sector_analyzer
        self._store = idea_store
        self._watchlist_resolver = watchlist_resolver
        self._sector_resolver = sector_resolver
        self._config = config or ScheduleConfig()

        # Last-run timestamps (monotonic)
        self._last_watchlist_run: float = 0.0
        self._last_sector_run: float = 0.0
        self._last_theme_run: float = 0.0

        # Per-symbol freshness tracker: {symbol: last_research_time}
        self._symbol_freshness: dict[str, float] = {}

    # ================================================================== #
    # Main loop                                                           #
    # ================================================================== #

    async def run(self) -> None:
        """Entry point — logs start, delegates to run_forever."""
        logger.info(
            "Research scheduler starting — intervals: "
            "watchlist=%dm/%dm sector=%dm/%dm theme=%dm/%dm",
            self._config.watchlist_interval_market,
            self._config.watchlist_interval_offhours,
            self._config.sector_interval_market,
            self._config.sector_interval_offhours,
            self._config.theme_interval_market,
            self._config.theme_interval_offhours,
        )
        try:
            await self.run_forever()
        except asyncio.CancelledError:
            logger.info("Research scheduler cancelled; stopping")
            raise
        except Exception as exc:
            logger.exception(
                "Research scheduler stopped with error: %s", exc
            )
            raise

    async def run_forever(self) -> None:
        """Infinite loop — check what's due and dispatch."""
        # Initial delay to let the gateway fully start
        await asyncio.sleep(10)

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler tick failed — will retry next cycle")

            # Sleep 30 seconds between ticks
            await asyncio.sleep(30)

    async def _tick(self) -> None:
        """One scheduler tick — check due tasks and dispatch."""
        now = time.monotonic()
        market_hours = self._is_market_hours()

        # Determine intervals based on market hours
        w_interval = (
            self._config.watchlist_interval_market
            if market_hours
            else self._config.watchlist_interval_offhours
        ) * 60  # Convert to seconds

        s_interval = (
            self._config.sector_interval_market
            if market_hours
            else self._config.sector_interval_offhours
        ) * 60

        t_interval = (
            self._config.theme_interval_market
            if market_hours
            else self._config.theme_interval_offhours
        ) * 60

        # Check what's due
        if now - self._last_watchlist_run >= w_interval:
            await self._run_watchlist_research()
            self._last_watchlist_run = now

        if now - self._last_sector_run >= s_interval:
            await self._run_sector_analysis()
            self._last_sector_run = now

        if now - self._last_theme_run >= t_interval:
            await self._run_theme_generation()
            self._last_theme_run = now

    # ================================================================== #
    # Watchlist research                                                  #
    # ================================================================== #

    async def _run_watchlist_research(self) -> None:
        """Research all watchlist symbols that aren't fresh."""
        logger.info("Scheduler: starting watchlist research cycle")

        try:
            symbols = await self._watchlist_resolver()
        except Exception:
            logger.exception("Failed to resolve watchlist")
            return

        if not symbols:
            logger.info("Scheduler: no watchlist symbols to research")
            return

        # Filter out recently-researched symbols
        now = time.monotonic()
        freshness_sec = self._config.freshness_window_min * 60
        stale_symbols = [
            s for s in symbols
            if now - self._symbol_freshness.get(s, 0.0) >= freshness_sec
        ]

        # Cap per cycle
        batch = stale_symbols[: self._config.max_symbols_per_cycle]

        if not batch:
            logger.info(
                "Scheduler: all %d symbols are fresh — skipping",
                len(symbols),
            )
            return

        logger.info(
            "Scheduler: researching %d/%d symbols: %s",
            len(batch),
            len(symbols),
            ", ".join(batch[:5]),
        )

        for symbol in batch:
            try:
                await self._research_single_symbol(symbol)
                self._symbol_freshness[symbol] = time.monotonic()
            except Exception:
                logger.exception(
                    "Scheduler: research failed for %s — continuing",
                    symbol,
                )

    async def _research_single_symbol(self, symbol: str) -> None:
        """Run the orchestrator for one symbol and classify the result."""
        run_id = uuid4()
        user_id = UUID("00000000-0000-0000-0000-000000000000")  # system user

        logger.info("Scheduler: researching %s (run_id=%s)", symbol, run_id)

        try:
            orchestrator = await self._orch_factory(
                user_id=user_id,
                symbol=symbol,
                skip_agents=(),
            )
        except Exception:
            logger.exception("Scheduler: orchestrator factory failed for %s", symbol)
            return

        prompt = f"Produce a comprehensive research brief for {symbol}. Cite every non-boilerplate claim."

        try:
            brief = await orchestrator.run(
                run_id=run_id,
                user_id=user_id,
                symbol=symbol,
                user_prompt=prompt,
            )
        except Exception:
            logger.exception("Scheduler: orchestrator.run failed for %s", symbol)
            return

        if not brief:
            logger.warning("Scheduler: empty brief for %s", symbol)
            return

        # Coerce to dict
        brief_dict: dict[str, Any] = {}
        if isinstance(brief, Mapping):
            brief_dict = dict(brief)
        elif hasattr(brief, "model_dump"):
            try:
                brief_dict = brief.model_dump(mode="json")
            except TypeError:
                brief_dict = brief.model_dump()

        # Resolve sector for the symbol
        sector_hint: str | None = None
        if self._sector_resolver:
            try:
                sector_hint = await self._sector_resolver(symbol)
            except Exception:
                pass

        # Classify into idea
        try:
            idea = await self._classifier.classify(
                brief=brief_dict,
                judge_report=brief_dict.get("judge_report"),
                symbol=symbol,
                sector_hint=sector_hint,
                run_id=str(run_id),
            )
            await self._store.upsert_idea(idea)
            logger.info(
                "Scheduler: idea extracted for %s — %s %.0f%% %s",
                symbol,
                idea.direction.value,
                idea.conviction * 100,
                idea.archetype.value,
            )
        except Exception:
            logger.exception("Scheduler: idea classification failed for %s", symbol)

    # ================================================================== #
    # Sector analysis                                                     #
    # ================================================================== #

    async def _run_sector_analysis(self) -> None:
        """Rebuild sector clusters from current ideas."""
        logger.info("Scheduler: running sector analysis")

        ideas = await self._store.list_ideas(limit=200)
        if not ideas:
            logger.info("Scheduler: no ideas — skipping sector analysis")
            return

        try:
            clusters = await self._sector_analyzer.analyze(ideas)
            for cluster in clusters:
                await self._store.upsert_sector_cluster(cluster)
            logger.info(
                "Scheduler: built %d sector clusters", len(clusters)
            )
        except Exception:
            logger.exception("Scheduler: sector analysis failed")

    # ================================================================== #
    # Theme generation                                                    #
    # ================================================================== #

    async def _run_theme_generation(self) -> None:
        """Generate themes from current ideas."""
        logger.info("Scheduler: running theme generation")

        ideas = await self._store.list_ideas(limit=200)
        if not ideas:
            logger.info("Scheduler: no ideas — skipping theme generation")
            return

        try:
            themes = await self._theme_gen.generate_all(ideas)
            for theme in themes:
                await self._store.upsert_theme(theme)
            logger.info(
                "Scheduler: generated %d themes", len(themes)
            )
        except Exception:
            logger.exception("Scheduler: theme generation failed")

    # ================================================================== #
    # Market hours                                                        #
    # ================================================================== #

    @staticmethod
    def _is_market_hours() -> bool:
        """Check if current time is within IST market hours."""
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + _IST_OFFSET
        ist_time = ist_now.time()

        market_open = ist_time.replace(
            hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MIN, second=0
        )
        market_close = ist_time.replace(
            hour=_MARKET_CLOSE_HOUR, minute=_MARKET_CLOSE_MIN, second=0
        )

        return market_open <= ist_time <= market_close
