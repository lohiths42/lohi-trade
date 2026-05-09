"""BSE public-announcement feed poller (Req 3.1, design §3.2, §4.3).

Periodically fetches the BSE public announcements JSON feed, filters to
the configured watchlist symbols, runs every candidate URL through
:class:`RobotsChecker` (Req 3.3), and publishes index events onto the
:data:`RESEARCH_INDEX_EVENTS_STREAM` Redis stream for the
``research-indexer`` worker to consume.

Event payload shape (design §3.2, §4.3)::

    {
        "document_url": "<absolute URL to the filing PDF/HTML>",
        "symbol": "<NSE/BSE ticker, upper-case>",
        "document_type": "announcement",
        "published_at": "<ISO-8601 timestamp, UTC>",
        "source": "bse",
    }

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2 — ingestion
  layer and ``research-indexer`` worker.
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §4.3 — the
  ``research:index_events`` stream schema.

Satisfies
---------
* **Req 3.1** — ingest BSE public announcement feed.
* **Req 3.3** — honour ``robots.txt`` for each document URL emitted.

Integration caveats
-------------------
* The BSE API surface (hostname, path, query parameters) evolves over
  time. The default endpoint embedded here
  (``api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w``) reflects
  the public JSON endpoint used by the BSE corporate-announcements page
  at time of writing, and the response shape is assumed to be a list of
  rows each carrying approximate fields ``NEWSID``, ``SCRIP_CD``,
  ``NEWSSUB``, ``NEWS_DT``, ``ATTACHMENTNAME``. The helpers in
  :func:`_extract_event` are deliberately forgiving: unknown/missing
  fields are skipped rather than raised, and operators can override the
  endpoint via ``research.ingest.sources.bse_feed.endpoint`` in
  ``config/settings.yaml``. Integration tests (Phase 5) pin the
  *contract* against fakes; the real shape is validated by operators.
* Upstream BSE servers require a browser-like ``User-Agent`` and a
  ``Referer`` header pointing at ``https://www.bseindia.com/``; without
  them the API returns 403. Both are set on the :class:`httpx.AsyncClient`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Final, Iterable

import httpx

from src.research.constants import RESEARCH_INDEX_EVENTS_STREAM
from src.research.ingest.robots import DEFAULT_USER_AGENT, RobotsChecker
from src.utils.logger import ComponentLogger, get_logger

_LOGGER_COMPONENT: Final[str] = "BseFeedPoller"
_SOURCE_TAG: Final[str] = "bse"
_DOCUMENT_TYPE: Final[str] = "announcement"

# Public BSE corporate-announcements JSON endpoint. Operators override
# via the config key ``research.ingest.sources.bse_feed.endpoint``.
_DEFAULT_ENDPOINT: Final[str] = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
)

# Referer required by upstream CORS / bot-filtering layer.
_DEFAULT_REFERER: Final[str] = "https://www.bseindia.com/"

# Short per-poll HTTP timeout — the poll loop is periodic, so a hung
# upstream must not stall subsequent iterations.
_FETCH_TIMEOUT_SEC: Final[float] = 15.0


class BseFeedPoller:
    """Periodic poller for the BSE public-announcements JSON feed.

    The poller is a long-lived asyncio task owned by the
    ``research-indexer`` worker (design §2.2, §3.2). Use
    :meth:`run_forever` to drive it from a worker main loop, or
    :meth:`poll_once` for a single pass (useful in tests and for manual
    backfills).

    Parameters
    ----------
    watchlist_symbols:
        Upper-cased ticker symbols to filter announcements by. Rows for
        symbols outside this list are dropped before the ``robots.txt``
        check to avoid unnecessary network I/O.
    redis_client:
        An already-connected async Redis client (``redis.asyncio.Redis``
        or compatible). The poller calls :meth:`xadd` on it and owns no
        part of its lifecycle — creation and shutdown belong to the
        caller (design §3.11).
    robots:
        Shared :class:`RobotsChecker` instance.
    poll_interval_sec:
        Seconds between polls. Default 300 (5 minutes), matching
        ``research.ingest.sources.bse_feed.poll_interval_sec`` in
        ``config/settings.yaml``.
    user_agent:
        User-agent sent both to the BSE endpoint and passed to
        ``robots.is_allowed``. Defaults to
        :data:`~src.research.ingest.robots.DEFAULT_USER_AGENT`.
    endpoint:
        Override the BSE JSON endpoint. Used by tests.
    """

    def __init__(
        self,
        *,
        watchlist_symbols: list[str],
        redis_client: Any,
        robots: RobotsChecker,
        poll_interval_sec: int = 300,
        user_agent: str = DEFAULT_USER_AGENT,
        endpoint: str = _DEFAULT_ENDPOINT,
    ) -> None:
        # Normalise symbols once so downstream comparisons are O(1) and
        # case-insensitive regardless of upstream casing.
        self._watchlist: set[str] = {s.strip().upper() for s in watchlist_symbols if s}
        self._redis = redis_client
        self._robots = robots
        self.poll_interval_sec: int = int(poll_interval_sec)
        self._user_agent = user_agent
        self._endpoint = endpoint
        # Track (symbol, document_url) tuples already emitted this
        # process lifetime so we do not repeatedly XADD the same
        # announcement across successive polls. Deduplication at the
        # index level is handled by the SHA-256 content hash (Task 5.13)
        # — this set is a cheap in-memory short-circuit.
        self._seen: set[tuple[str, str]] = set()
        self._logger: ComponentLogger = get_logger(_LOGGER_COMPONENT)

    async def run_forever(self) -> None:
        """Infinite loop: poll, sleep, repeat.

        Catches and logs transport-level errors per iteration so a
        single bad poll does not kill the worker.
        """
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — top of loop
                self._logger.error(
                    "BSE poll iteration failed",
                    extra={"error_class": type(exc).__name__, "error": str(exc)},
                    exc_info=True,
                )
            await asyncio.sleep(self.poll_interval_sec)

    async def poll_once(self) -> int:
        """Run a single poll cycle.

        Returns the count of events XADD'd onto
        :data:`RESEARCH_INDEX_EVENTS_STREAM`. Visible in the return
        type for test assertions; the worker main loop ignores it.
        """
        rows = await self._fetch_rows()
        if not rows:
            return 0

        published_count = 0
        for row in rows:
            event = self._extract_event(row)
            if event is None:
                continue
            if event["symbol"] not in self._watchlist:
                continue

            dedup_key = (event["symbol"], event["document_url"])
            if dedup_key in self._seen:
                continue

            if not await self._robots.is_allowed(event["document_url"], self._user_agent):
                # Still record it as "seen" so we do not re-check the
                # same disallowed URL on every poll.
                self._seen.add(dedup_key)
                continue

            await self._redis.xadd(RESEARCH_INDEX_EVENTS_STREAM, event)
            self._seen.add(dedup_key)
            published_count += 1

        if published_count:
            self._logger.info(
                "Published BSE index events",
                extra={"count": published_count, "source": _SOURCE_TAG},
            )
        return published_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_rows(self) -> list[dict[str, Any]]:
        """Fetch the BSE feed JSON and return the list of row dicts.

        Returns an empty list on any transport or parse error — the
        caller logs and continues. BSE's response wraps the list under
        a ``"Table"`` key in most observed shapes; we accept both the
        wrapped and the bare-list variants.
        """
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
            "Referer": _DEFAULT_REFERER,
        }
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT_SEC, headers=headers
            ) as client:
                response = await client.get(self._endpoint)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._logger.warning(
                "BSE feed fetch failed",
                extra={
                    "endpoint": self._endpoint,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return []

        if isinstance(payload, dict):
            rows = payload.get("Table") or payload.get("data") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    def _extract_event(self, row: dict[str, Any]) -> dict[str, str] | None:
        """Map a single BSE feed row to the canonical event shape.

        Returns ``None`` when the row lacks the minimum fields (symbol
        + document URL + published date). All values are normalised to
        ``str`` because ``redis.asyncio.xadd`` requires string fields.
        """
        symbol = _first_nonempty(row, ("SCRIP_CD", "scrip_cd", "Symbol", "symbol"))
        document_url = _first_nonempty(
            row,
            ("ATTACHMENTNAME", "attachmentname", "NSURL", "DocumentURL"),
        )
        published_at_raw = _first_nonempty(
            row, ("NEWS_DT", "news_dt", "DT_TM", "published_at")
        )

        if not symbol or not document_url or not published_at_raw:
            return None

        return {
            "document_url": document_url,
            "symbol": str(symbol).strip().upper(),
            "document_type": _DOCUMENT_TYPE,
            "published_at": _to_iso8601_utc(published_at_raw),
            "source": _SOURCE_TAG,
        }


def _first_nonempty(row: dict[str, Any], keys: Iterable[str]) -> str | None:
    """Return the first non-empty string value found under *keys*."""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _to_iso8601_utc(value: str) -> str:
    """Best-effort normalisation of BSE date strings to ISO-8601 UTC.

    BSE typically serialises dates as ``YYYY-MM-DDTHH:MM:SS`` (naive) or
    ``YYYY-MM-DD HH:MM:SS``. Anything already ISO-8601 is returned
    unchanged; unparseable input is returned verbatim so the event can
    still be published (the downstream parser will fail loudly if it
    matters).
    """
    text = value.strip()
    candidates = (text, text.replace(" ", "T"))
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return text


async def build(
    cfg: dict,
    redis_client: Any,
    *,
    robots: RobotsChecker | None = None,
) -> BseFeedPoller:
    """Factory entry point (Req 2.12-style one-line extension pattern).

    Parameters
    ----------
    cfg:
        The ``research.ingest.sources.bse_feed`` block from
        ``config/settings.yaml`` merged with any caller-provided
        overrides. Recognised keys: ``poll_interval_sec``,
        ``watchlist_symbols``, ``endpoint``, ``user_agent``.
    redis_client:
        Async Redis client used for ``XADD``.
    robots:
        Shared :class:`RobotsChecker`. Required — callers must create
        one ``RobotsChecker`` per indexer process and pass it to every
        source poller to keep the per-origin cache shared.
    """
    if robots is None:
        raise ValueError(
            "bse_feed.build requires a RobotsChecker; pass a shared instance "
            "created once per research-indexer worker (design §3.2)."
        )
    return BseFeedPoller(
        watchlist_symbols=list(cfg.get("watchlist_symbols", []) or []),
        redis_client=redis_client,
        robots=robots,
        poll_interval_sec=int(cfg.get("poll_interval_sec", 300)),
        user_agent=str(cfg.get("user_agent", DEFAULT_USER_AGENT)),
        endpoint=str(cfg.get("endpoint", _DEFAULT_ENDPOINT)),
    )


__all__ = ["BseFeedPoller", "build"]
