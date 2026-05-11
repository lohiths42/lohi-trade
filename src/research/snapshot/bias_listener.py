"""Commander bias → snapshot invalidation bridge (Task 15.2).

Listens on the Commander's existing ``bias`` Redis stream/pubsub
(design §2.1, Req 8.3) and, for every new bias event on a symbol,
publishes a ``snapshot_invalidation`` event onto
:data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM` for every
``(user_id, symbol)`` pair where that user's active watchlist
contains the symbol (Req 11.3, design §3.10).

Why a separate listener module?
-------------------------------
The snapshotter worker (Task 15.1) already consumes the invalidation
stream. Folding the bias-pubsub → invalidation translation directly
into the worker would entangle two concerns: the worker would need to
know about watchlists, and tests for the worker would need to model
the Commander's stream shape. Splitting the translation out keeps
each module single-purpose:

* This module: subscribe to ``stream:bias:*`` → fan out per-user
  invalidations onto ``research:snapshot_invalidations``.
* :class:`~src.research.workers.snapshotter.SnapshotWorker`: consume
  the invalidations and run a debounced regeneration.

The snapshotter accepts the same invalidation shape no matter which
publisher wrote it (ingestion's "new document" path, this listener's
bias-triggered path, or a future high-impact-sentiment path, design
§3.10).

Listener contract
-----------------
``BiasInvalidationListener`` is an async long-running task in the
same mould as :class:`src.research.ingest.sources.bse_feed.BseFeedPoller`
— construct once, ``await listener.run_forever()`` from a worker
entrypoint. A :meth:`process_event` method is exposed so unit tests
can exercise one event at a time without having to juggle a pubsub
loop.

Watchlist lookup
----------------
The listener does not query the watchlists DB directly — that would
create a cross-package dependency on the gateway's
:mod:`backend-gateway.app.services.watchlist_service`. Instead it
takes a :class:`WatchlistResolver` protocol at construction: any
callable ``(symbol) -> Iterable[UUID]`` returning the user_ids that
currently hold ``symbol`` in an active watchlist. Production wiring
implements the protocol against the gateway's watchlist service;
unit tests pass a simple in-memory stub.

Event input/output shapes
-------------------------
* **Input** — the Commander's ``stream:bias:<ticker>`` entries carry
  at minimum a ``ticker`` field plus the bias payload (see
  :mod:`src.commander.bias_scheduler`). This listener only cares
  about the ticker value; bias magnitude / direction are forwarded
  verbatim into the invalidation payload for observability but are
  not used for filtering (design §3.10 says "any new bias event for
  a watchlist symbol invalidates the Snapshot").
* **Output** — each invalidation entry written to
  :data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM` is a plain
  ``{field: str}`` dict with the canonical shape::

      {
          "user_id": "<uuid>",
          "symbol": "<TICKER>",
          "trigger": "bias",
          "bias_event_id": "<redis entry id of the source event>",
      }

  The snapshotter's debounce logic keys on ``(user_id, symbol)`` so
  the exact payload doesn't change worker behaviour — the trailing
  fields are informational and surface in structured logs.

Satisfies
---------
* **Req 8.3** — reuses the Commander's ``bias`` stream; does not
  re-ingest or republish the source event.
* **Req 11.3** — "new bias for a watchlist symbol invalidates the
  Snapshot".
* Design §3.10 — invalidation events path for the snapshotter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import (
    Any,
    Final,
    Protocol,
    runtime_checkable,
)
from uuid import UUID

from src.research.agents._stream import (
    RedisStreamReader,
    StreamEvent,
    parse_stream_entry,
)
from src.research.constants import (
    RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM,
)

# ``src.utils.logger`` provides the project-standard structured
# logger; fall back to stdlib ``logging`` on trimmed installs. Same
# pattern every :mod:`src.research` module uses.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("BiasInvalidationListener")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.snapshot.bias_listener")


__all__ = [
    "BiasInvalidationListener",
    "WatchlistResolver",
    "build_invalidation_fields",
]


# The Commander's bias-stream shard prefix — bias events live on
# ``stream:bias:<TICKER>`` (see :mod:`src.commander.bias_scheduler`).
# The listener lets operators override the logical prefix so a
# non-default Commander topology still works.
_DEFAULT_BIAS_STREAM_PREFIX: Final[str] = "stream:bias"

# How many events to pull per ``xrevrange`` in a single poll. The
# listener is meant to shadow the Commander's publish cadence (the
# bias scheduler publishes every few minutes, not per-tick); a small
# batch keeps the invalidation stream lag bounded without hammering
# Redis. Operators can tune via the ``events_per_poll`` constructor
# arg.
_DEFAULT_EVENTS_PER_POLL: Final[int] = 20

# Default poll cadence. The bias scheduler publishes at most once
# per minute per ticker (see :mod:`src.commander.bias_scheduler`);
# a 30-second poll cadence keeps the worst-case invalidation latency
# under a minute without wasting round-trips.
_DEFAULT_POLL_INTERVAL_SEC: Final[float] = 30.0


@runtime_checkable
class WatchlistResolver(Protocol):
    """Contract the listener needs from the watchlist layer.

    Returns the user_ids that currently hold ``symbol`` in an active
    watchlist. The protocol is async so production implementations
    can hit the gateway's Postgres directly without a sync
    round-trip; in-memory test stubs return a static mapping.

    Raising is allowed but the listener treats it as "no users" — a
    failed watchlist lookup must not kill the stream consumption
    loop. This matches the best-effort posture of every
    :mod:`src.research` worker.
    """

    async def users_watching(self, symbol: str) -> Iterable[UUID]:
        """Return user_ids watching ``symbol``. Empty iterable = no users."""
        ...


@dataclass
class _StreamDiscovery:
    """How the listener finds the set of bias streams to read.

    The Commander publishes to ``stream:bias:<ticker>`` sharded per
    ticker. The listener supports two discovery modes via the
    constructor parameters:

    * **Explicit** — the caller passes an iterable of stream names
      (``streams=...``). Useful when the watchlist is small and
      stable.
    * **Scan-based** — the caller passes a ``redis_scan`` callable
      that returns all keys matching ``"{prefix}:*"``. Each poll
      pass re-scans so streams for newly-watchlisted tickers show
      up without restarting the worker. This is the default mode
      when ``streams`` is ``None``.
    """

    explicit_streams: tuple[str, ...] | None
    prefix: str
    scan: Callable[[str], Awaitable[list[str]]] | None


class BiasInvalidationListener:
    """Async consumer: Commander bias → snapshot invalidation.

    Parameters
    ----------
    redis_reader:
        :class:`RedisStreamReader` exposing ``xrevrange``. Used to
        pull the most-recent ``events_per_poll`` entries from every
        configured bias stream on each poll cycle.
    invalidation_publisher:
        Async callable ``(stream_name, fields) -> awaitable`` that
        writes an entry onto :data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM`.
        The callable contract matches
        :data:`~src.research.agents.partials.PartialsPublisher` so
        production wiring can reuse
        :func:`~src.research.agents.partials.make_redis_partials_publisher`
        style helpers; tests pass a recording stub.
    watchlist_resolver:
        Callable implementing :class:`WatchlistResolver`. The
        listener fans out one invalidation per user per symbol.
    streams:
        Optional explicit iterable of bias stream names to consume.
        When ``None`` the listener scans Redis for
        ``"{stream_prefix}:*"`` keys on every poll using
        ``redis_scan`` (required if ``streams`` is ``None``).
    stream_prefix:
        Used for scan-based discovery; defaults to ``"stream:bias"``
        (Commander convention).
    redis_scan:
        Async callable ``(pattern) -> list[str]`` returning every
        Redis key matching ``pattern``. Required when ``streams is
        None``. Production wiring wraps
        ``redis.asyncio.Redis.scan_iter``; tests pass an in-memory
        stub.
    events_per_poll:
        Max events fetched from each stream per poll. Default
        :data:`_DEFAULT_EVENTS_PER_POLL`.
    poll_interval_sec:
        Seconds between poll cycles. Default
        :data:`_DEFAULT_POLL_INTERVAL_SEC`.
    invalidation_stream:
        Override for
        :data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM`. Used in
        tests to isolate streams per test.

    Dedup
    -----
    The listener tracks ``(stream, entry_id)`` pairs it has already
    translated this process lifetime so a re-read on the next poll
    does not re-publish the same invalidation. The set is unbounded
    but the listener is a long-lived worker that restarts with the
    process; for realistic bias cadences the set grows by ≤ a few
    thousand entries per day. A future enhancement (not required by
    Req 11.3) is to cap the set by bounded time / size, mirroring
    the BSE poller's :attr:`~BseFeedPoller._seen` pattern.

    """

    def __init__(
        self,
        *,
        redis_reader: RedisStreamReader,
        invalidation_publisher: Callable[
            [str, Mapping[str, Any]], Awaitable[Any],
        ],
        watchlist_resolver: WatchlistResolver,
        streams: Iterable[str] | None = None,
        stream_prefix: str = _DEFAULT_BIAS_STREAM_PREFIX,
        redis_scan: Callable[[str], Awaitable[list[str]]] | None = None,
        events_per_poll: int = _DEFAULT_EVENTS_PER_POLL,
        poll_interval_sec: float = _DEFAULT_POLL_INTERVAL_SEC,
        invalidation_stream: str = RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM,
    ) -> None:
        if streams is None and redis_scan is None:
            raise ValueError(
                "BiasInvalidationListener requires either `streams` (an "
                "explicit iterable) or `redis_scan` (for dynamic "
                "discovery). Neither was provided.",
            )
        self._reader = redis_reader
        self._publisher = invalidation_publisher
        self._resolver = watchlist_resolver
        self._discovery = _StreamDiscovery(
            explicit_streams=tuple(streams) if streams is not None else None,
            prefix=stream_prefix,
            scan=redis_scan,
        )
        self._events_per_poll = max(1, int(events_per_poll))
        self._poll_interval_sec = max(0.0, float(poll_interval_sec))
        self._invalidation_stream = invalidation_stream
        # ``(stream, entry_id)`` we have already translated.
        self._seen: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ #
    # Public run loop                                                    #
    # ------------------------------------------------------------------ #

    async def run_forever(self) -> None:
        """Infinite poll loop; cancel-aware.

        Catches and logs iteration-level errors so a transient Redis
        hiccup or watchlist-resolver exception does not kill the
        worker (matches the posture of the BSE poller).
        """
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — top of loop
                _log_warning(
                    "bias invalidation listener poll failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            await asyncio.sleep(self._poll_interval_sec)

    async def poll_once(self) -> int:
        """One poll cycle — discover streams, pull events, fan out.

        Returns the number of invalidation events published on this
        cycle so tests can assert on outcomes without inspecting the
        publisher stub directly.
        """
        stream_names = await self._discover_streams()
        if not stream_names:
            return 0

        published = 0
        for stream_name in stream_names:
            raw_entries = await self._reader.xrevrange(
                stream_name,
                count=self._events_per_poll,
            )
            for entry in raw_entries:
                event = parse_stream_entry(stream=stream_name, entry=entry)
                key = (stream_name, event.event_id)
                if key in self._seen:
                    continue
                published += await self._dispatch_event(event)
                # Always mark as seen so a resolver miss (or a
                # symbol-less event) doesn't cause repeated lookups.
                self._seen.add(key)
        return published

    async def process_event(self, event: StreamEvent) -> int:
        """Translate one already-parsed event; return invalidation count.

        Exposed for unit tests and for composition with alternate
        dispatch loops that want to bypass the poll/xrevrange path.
        """
        return await self._dispatch_event(event)

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    async def _discover_streams(self) -> list[str]:
        """Return the bias stream names to consume this cycle."""
        if self._discovery.explicit_streams is not None:
            return list(self._discovery.explicit_streams)
        # Scan mode — re-scan every poll so streams for newly-added
        # watchlist tickers show up without a worker restart. The
        # pattern matches the Commander's shard shape.
        assert self._discovery.scan is not None  # enforced in __init__
        pattern = f"{self._discovery.prefix}:*"
        try:
            raw = await self._discovery.scan(pattern)
        except Exception as exc:  # noqa: BLE001 — discovery is best-effort
            _log_warning(
                "bias stream discovery failed",
                pattern=pattern,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return []
        # Coerce to str in case the Redis client handed back bytes.
        return [
            s.decode("utf-8") if isinstance(s, (bytes, bytearray)) else str(s)
            for s in raw
        ]

    async def _dispatch_event(self, event: StreamEvent) -> int:
        """Resolve the watchlist + publish per-user invalidations.

        Returns the number of invalidation events published for this
        single source event (``0`` when the symbol is not watched by
        any user).
        """
        symbol = _symbol_from_event(event)
        if symbol is None:
            _log_debug(
                "bias event has no resolvable symbol; skipping",
                stream=event.stream,
                event_id=event.event_id,
            )
            return 0

        try:
            users = list(await self._resolver.users_watching(symbol))
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log_warning(
                "watchlist resolver raised; skipping event",
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return 0

        if not users:
            return 0

        published = 0
        for user_id in users:
            fields = build_invalidation_fields(
                user_id=user_id,
                symbol=symbol,
                trigger="bias",
                source_event_id=event.event_id,
            )
            try:
                await self._publisher(self._invalidation_stream, fields)
            except Exception as exc:  # noqa: BLE001 — best-effort
                _log_warning(
                    "snapshot invalidation publish failed",
                    symbol=symbol,
                    user_id=str(user_id),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                continue
            published += 1
        return published


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def build_invalidation_fields(
    *,
    user_id: UUID,
    symbol: str,
    trigger: str,
    source_event_id: str | None = None,
) -> dict[str, str]:
    """Build the canonical invalidation-stream entry.

    Kept as a small helper so the snapshotter worker's unit tests
    (Task 15.1) can reuse the exact shape when crafting synthetic
    events.
    """
    fields: dict[str, str] = {
        "user_id": str(user_id),
        "symbol": symbol.strip().upper(),
        "trigger": trigger,
    }
    if source_event_id:
        fields["source_event_id"] = str(source_event_id)
    return fields


def _symbol_from_event(event: StreamEvent) -> str | None:
    """Extract the ticker from a bias event.

    The Commander's bias entries carry ``ticker`` in the fields
    dict, and the stream is additionally sharded by ticker
    (``stream:bias:<TICKER>``). We prefer the fields value and fall
    back to the stream-name suffix so the listener still works on
    trimmed test fixtures that only populate one of the two.
    """
    if event.symbol:
        return event.symbol.strip().upper()
    # Fall back to the suffix of ``stream:bias:<TICKER>``.
    # ``rpartition`` handles any prefix length without assumptions.
    prefix, sep, suffix = event.stream.rpartition(":")
    if sep and suffix and suffix != event.stream:
        return suffix.strip().upper()
    return None


def _log_debug(message: str, **fields: Any) -> None:
    """Emit a DEBUG log, adapting to the available logger shape."""
    try:
        _logger.debug(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.debug("%s %s", message, fields)


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape."""
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)
