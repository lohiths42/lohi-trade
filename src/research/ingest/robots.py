"""Per-source ``robots.txt`` enforcement (Req 3.3, Req 9.2, design §3.2).

Every outbound fetch performed by the ingestion layer
(:mod:`src.research.ingest.sources`) passes through
:meth:`RobotsChecker.is_allowed` before a document is retrieved. The
checker caches one :class:`urllib.robotparser.RobotFileParser` per origin
(``scheme://netloc``) so a given host is only fetched once per process
lifetime, and disallowed URLs are skipped silently — each origin is
logged at most once at INFO level, matching Req 3.3 ("skipped silently
and logged once per origin").

Design reference
----------------
* :file:`.kiro/specs/lohi-research-dashboard/design.md` §3.2
  ("Robots.txt enforcement. Every outbound fetch passes through
  ``robots.is_allowed(url, user_agent)``; disallowed URLs are skipped
  silently and logged once (Req 3.3, Req 9.2).").

Satisfies
---------
* **Req 3.3** — respect each source's ``robots.txt`` for the configured
  user-agent.
* **Req 9.2** — no outbound network calls at runtime other than to
  explicitly user-configured endpoints; fetching ``/robots.txt`` is part
  of that explicit contract.

Design notes
------------
* The parser is :class:`urllib.robotparser.RobotFileParser` from the
  Python standard library, so this module has no third-party runtime
  dependency beyond ``httpx`` (which is already a project dep — see
  ``backend-gateway/requirements.txt``).
* ``RobotFileParser.read()`` performs its own blocking ``urllib`` fetch,
  which would block the asyncio event loop. We therefore fetch the
  ``robots.txt`` body ourselves via :class:`httpx.AsyncClient` and hand
  the decoded lines to :meth:`RobotFileParser.parse`.
* Fail-open policy: if ``/robots.txt`` cannot be fetched (connection
  refused, timeout, 404, 5xx, malformed body), we treat the origin as
  fully permissive. Req 3.3 only obliges us to skip *disallowed* URLs —
  a missing ``robots.txt`` is, by the REP spec, equivalent to blanket
  allow.
"""

from __future__ import annotations

import asyncio
from typing import Final
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from src.utils.logger import ComponentLogger, get_logger

# Default user-agent. Operators override via
# ``research.ingest.robots_user_agent`` (config/settings.yaml).
DEFAULT_USER_AGENT: Final[str] = "Lohi-ResearchBot/0.1"

# Short timeout on ``/robots.txt`` fetches — a slow origin must not
# stall the ingestion loop. Three seconds matches the task specification
# and is comfortably above p99 for well-behaved hosts.
_ROBOTS_FETCH_TIMEOUT_SEC: Final[float] = 3.0

_LOGGER_COMPONENT: Final[str] = "RobotsChecker"


def _origin_of(url: str) -> str:
    """Return the canonical ``scheme://netloc`` origin of *url*.

    Lowercases the scheme/netloc so ``HTTPS://Example.COM`` and
    ``https://example.com`` share a single cache entry. Raises
    :class:`ValueError` if *url* is missing either component so callers
    can fail fast on malformed input.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"url is missing scheme or netloc: {url!r}")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


class RobotsChecker:
    """Per-origin ``robots.txt`` cache and ``is_allowed`` query.

    A single instance is shared across every ingestion source in a
    process (one checker per ``research-indexer`` worker). Safe to share
    across coroutines thanks to an internal :class:`asyncio.Lock` that
    serialises the first fetch per origin; subsequent calls hit the
    in-memory cache without awaiting.

    Parameters
    ----------
    user_agent:
        Default user-agent presented to ``RobotFileParser.can_fetch``
        when the caller does not override it in ``is_allowed``. Also
        sent as the ``User-Agent`` header when fetching
        ``/robots.txt`` itself.

    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._default_user_agent: str = user_agent
        # Origin → parsed robots.txt. A sentinel (empty parser that
        # allows everything) is stored on fail-open so we do not refetch
        # broken origins on every URL.
        self._cache: dict[str, RobotFileParser] = {}
        # Per-origin lock to prevent duplicate concurrent fetches for
        # the same origin. We intentionally keep a separate per-origin
        # lock (rather than one global lock) so that a slow fetch to
        # host A does not block checks against host B.
        self._locks: dict[str, asyncio.Lock] = {}
        # Origins whose disallow decision has already been logged at
        # INFO. Req 3.3 requires "logged once per origin".
        self._logged_disallowed_origins: set[str] = set()
        self._logger: ComponentLogger = get_logger(_LOGGER_COMPONENT)

    async def is_allowed(
        self,
        url: str,
        user_agent: str | None = None,
    ) -> bool:
        """Return ``True`` if *url* may be fetched under REP.

        Looks up (and populates on miss) the cached
        :class:`RobotFileParser` for ``url``'s origin, then defers to
        :meth:`RobotFileParser.can_fetch`. Fail-open on any fetch or
        parse error.
        """
        ua = user_agent or self._default_user_agent
        origin = _origin_of(url)

        parser = await self._get_or_fetch(origin)
        allowed = parser.can_fetch(ua, url)

        if not allowed and origin not in self._logged_disallowed_origins:
            # Log once per origin at INFO — the ingestion loop would
            # otherwise spam the log when the same host is polled on a
            # schedule (Req 3.3).
            self._logged_disallowed_origins.add(origin)
            self._logger.info(
                "Skipping URL disallowed by robots.txt",
                extra={"origin": origin, "user_agent": ua, "url": url},
            )

        return allowed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_or_fetch(self, origin: str) -> RobotFileParser:
        """Return the cached parser for *origin* or fetch + cache it."""
        cached = self._cache.get(origin)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            # Re-check under the lock — another coroutine may have
            # populated the cache while we waited.
            cached = self._cache.get(origin)
            if cached is not None:
                return cached

            parser = await self._fetch(origin)
            self._cache[origin] = parser
            return parser

    async def _fetch(self, origin: str) -> RobotFileParser:
        """Fetch ``{origin}/robots.txt`` and return a primed parser.

        On any failure (connection error, timeout, non-2xx status,
        decode error) returns a sentinel parser that allows every URL
        and logs a single warning for the origin.
        """
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")

        try:
            async with httpx.AsyncClient(
                timeout=_ROBOTS_FETCH_TIMEOUT_SEC,
                headers={"User-Agent": self._default_user_agent},
                follow_redirects=True,
            ) as client:
                response = await client.get(f"{origin}/robots.txt")
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # Fail open per the module docstring. Log at WARNING because
            # an unreachable origin is usually an operator-visible
            # problem even though it does not block ingestion.
            self._logger.warning(
                "robots.txt fetch failed; allowing all URLs for origin",
                extra={
                    "origin": origin,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            # Empty-parse allows everything via can_fetch.
            parser.parse([])
            return parser

        if response.status_code == 404:
            # Per the REP spec, an absent robots.txt is an implicit
            # blanket allow. Do not log.
            parser.parse([])
            return parser

        if response.status_code >= 400:
            self._logger.warning(
                "robots.txt fetch returned non-2xx; allowing all URLs for origin",
                extra={"origin": origin, "status_code": response.status_code},
            )
            parser.parse([])
            return parser

        try:
            body = response.text
        except UnicodeDecodeError:
            # Non-text body; treat as absent.
            parser.parse([])
            return parser

        # ``RobotFileParser.parse`` expects an iterable of lines.
        parser.parse(body.splitlines())
        return parser


__all__ = ["DEFAULT_USER_AGENT", "RobotsChecker"]
