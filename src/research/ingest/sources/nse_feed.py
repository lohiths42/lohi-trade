"""NSE public-announcement feed poller (Req 3.1, design §3.2, §4.3).

Sibling of :mod:`src.research.ingest.sources.bse_feed` against the NSE
corporate-announcements JSON endpoint. Identical event payload shape
except ``source: "nse"`` so downstream consumers can distinguish the
two feeds when both fire for the same symbol (design §3.2).

Event payload shape (design §3.2, §4.3)::

    {
        "document_url": "<absolute URL to the filing PDF/HTML>",
        "symbol": "<NSE ticker, upper-case>",
        "document_type": "announcement",
        "published_at": "<ISO-8601 timestamp, UTC>",
        "source": "nse",
    }

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2.
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §4.3.

Satisfies
---------
* **Req 3.1** — ingest NSE public announcement feed.
* **Req 3.3** — honour ``robots.txt`` for each document URL emitted.

Integration caveats
-------------------
* NSE aggressively filters unfamiliar user-agents and requires a
  ``Referer`` header pointing back at ``https://www.nseindia.com/``.
  The ``User-Agent`` is deliberately browser-like — without it the API
  silently returns an empty body. Operators can override both via
  ``research.ingest.sources.nse_feed.user_agent`` / ``.referer`` in
  ``config/settings.yaml`` if NSE tightens the filter further.
* NSE's anti-bot layer also requires a valid session cookie acquired by
  first GET'ing ``https://www.nseindia.com/``. We perform that warm-up
  request inside the same :class:`httpx.AsyncClient` so the cookie jar
  is populated before we hit the JSON endpoint.
* The JSON response has been observed to use both a bare list and a
  wrapper dict with ``"data"`` key; both are accepted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from src.research.constants import RESEARCH_INDEX_EVENTS_STREAM
from src.research.ingest.robots import DEFAULT_USER_AGENT, RobotsChecker
from src.utils.logger import ComponentLogger, get_logger

_LOGGER_COMPONENT: Final[str] = "NseFeedPoller"
_SOURCE_TAG: Final[str] = "nse"
_DOCUMENT_TYPE: Final[str] = "announcement"

_DEFAULT_ENDPOINT: Final[str] = (
    "https://www.nseindia.com/api/corporate-announcements?index=equities"
)
_WARMUP_URL: Final[str] = "https://www.nseindia.com/"
_DEFAULT_REFERER: Final[str] = "https://www.nseindia.com/"

# NSE expects a browser-like ``User-Agent``. We keep ``Lohi-ResearchBot``
# as the *robots.txt* identity (so operators can set a disallow rule if
# they need to) but send a browser string for the actual fetch. Both
# values are sent verbatim to ``robots.is_allowed`` under the bot UA so
# the REP check still reflects our true identity.
_BROWSER_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_FETCH_TIMEOUT_SEC: Final[float] = 15.0


class NseFeedPoller:
    """Periodic poller for the NSE public-announcements JSON feed.

    Mirrors :class:`~src.research.ingest.sources.bse_feed.BseFeedPoller`
    in both lifecycle and responsibilities; see that class for the
    ``run_forever`` / ``poll_once`` contract.

    Parameters
    ----------
    watchlist_symbols:
        Upper-cased NSE tickers to filter by.
    redis_client:
        Async Redis client used for ``XADD``. Not owned by this class.
    robots:
        Shared :class:`RobotsChecker` instance.
    poll_interval_sec:
        Seconds between polls. Default 300.
    user_agent:
        User-agent advertised to the NSE ``robots.txt`` check (the
        actual browser UA used to hit the JSON endpoint is separate and
        fixed — see :data:`_BROWSER_USER_AGENT`).
    endpoint:
        Override the JSON endpoint (used by tests).
    browser_user_agent:
        Override the browser UA sent on the HTTP fetch. Operators set
        this when NSE changes its anti-bot filter.
    referer:
        Override the ``Referer`` header. Defaults to
        ``https://www.nseindia.com/``.

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
        browser_user_agent: str = _BROWSER_USER_AGENT,
        referer: str = _DEFAULT_REFERER,
    ) -> None:
        self._watchlist: set[str] = {s.strip().upper() for s in watchlist_symbols if s}
        self._redis = redis_client
        self._robots = robots
        self.poll_interval_sec: int = int(poll_interval_sec)
        self._user_agent = user_agent
        self._endpoint = endpoint
        self._browser_user_agent = browser_user_agent
        self._referer = referer
        self._seen: set[tuple[str, str]] = set()
        self._logger: ComponentLogger = get_logger(_LOGGER_COMPONENT)

    async def run_forever(self) -> None:
        """Infinite loop: poll, sleep, repeat (see BseFeedPoller)."""
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.error(
                    "NSE poll iteration failed",
                    extra={"error_class": type(exc).__name__, "error": str(exc)},
                    exc_info=True,
                )
            await asyncio.sleep(self.poll_interval_sec)

    async def poll_once(self) -> int:
        """Run a single poll cycle. Returns the number of events XADD'd."""
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
                self._seen.add(dedup_key)
                continue

            await self._redis.xadd(RESEARCH_INDEX_EVENTS_STREAM, event)
            self._seen.add(dedup_key)
            published_count += 1

        if published_count:
            self._logger.info(
                "Published NSE index events",
                extra={"count": published_count, "source": _SOURCE_TAG},
            )
        return published_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_rows(self) -> list[dict[str, Any]]:
        """Fetch the NSE feed JSON and return the list of row dicts.

        Performs the warm-up GET against the site root first to prime
        the cookie jar — NSE rejects direct ``/api/...`` calls from a
        cookieless client with an empty body.
        """
        headers = {
            "User-Agent": self._browser_user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self._referer,
        }
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT_SEC,
                headers=headers,
                follow_redirects=True,
            ) as client:
                # Warm-up: populate the session cookie jar. Errors here
                # are not fatal — we still try the API call; if NSE has
                # dropped the cookie requirement the direct GET will
                # succeed.
                try:
                    await client.get(_WARMUP_URL)
                except httpx.HTTPError:
                    pass

                response = await client.get(self._endpoint)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._logger.warning(
                "NSE feed fetch failed",
                extra={
                    "endpoint": self._endpoint,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return []

        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("rows") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    def _extract_event(self, row: dict[str, Any]) -> dict[str, str] | None:
        """Map a single NSE feed row to the canonical event shape."""
        symbol = _first_nonempty(row, ("symbol", "Symbol", "scrip"))
        document_url = _first_nonempty(
            row,
            ("attchmntFile", "attachmentFile", "attachment", "fileLink"),
        )
        published_at_raw = _first_nonempty(
            row, ("an_dt", "exchdisstime", "sort_date", "published_at"),
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
    """Best-effort ISO-8601 UTC normalisation.

    NSE has been observed to use several date shapes including
    ``DD-MMM-YYYY HH:MM:SS`` and ``YYYY-MM-DDTHH:MM:SS``. We attempt
    :func:`datetime.fromisoformat` variants and fall back to returning
    the raw string — the downstream parser treats unparseable values as
    "now" with a warning.
    """
    text = value.strip()
    candidates = (text, text.replace(" ", "T"))
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return text


async def build(
    cfg: dict,
    redis_client: Any,
    *,
    robots: RobotsChecker | None = None,
) -> NseFeedPoller:
    """Factory entry point.

    Parameters
    ----------
    cfg:
        The ``research.ingest.sources.nse_feed`` block, plus optional
        ``watchlist_symbols`` / ``endpoint`` / ``user_agent`` /
        ``browser_user_agent`` / ``referer`` overrides.
    redis_client:
        Async Redis client.
    robots:
        Shared :class:`RobotsChecker`.

    """
    if robots is None:
        raise ValueError(
            "nse_feed.build requires a RobotsChecker; pass a shared instance "
            "created once per research-indexer worker (design §3.2).",
        )
    return NseFeedPoller(
        watchlist_symbols=list(cfg.get("watchlist_symbols", []) or []),
        redis_client=redis_client,
        robots=robots,
        poll_interval_sec=int(cfg.get("poll_interval_sec", 300)),
        user_agent=str(cfg.get("user_agent", DEFAULT_USER_AGENT)),
        endpoint=str(cfg.get("endpoint", _DEFAULT_ENDPOINT)),
        browser_user_agent=str(
            cfg.get("browser_user_agent", _BROWSER_USER_AGENT),
        ),
        referer=str(cfg.get("referer", _DEFAULT_REFERER)),
    )


__all__ = ["NseFeedPoller", "build"]
