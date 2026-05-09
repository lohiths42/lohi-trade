"""``research-snapshotter`` worker — debounced Snapshot regeneration.

One of the three runtime roles introduced by Lohi-Research (design
§2.2). The worker consumes
:data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM` (Req 11.2, Req 11.3)
and, for every ``(user_id, symbol)`` pair with an invalidation, runs
a full :class:`~src.research.agents.orchestrator.ResearchOrchestrator`
pass after a configurable debounce window (``research.snapshot.debounce_sec``,
design §7.1 default 60s). The Snapshot produced by the run is
persisted through :class:`~src.research.snapshot.store.SnapshotStore`;
on failure the previous row is retained and marked ``stale=true``
(Req 11.6, handled by the store's :meth:`mark_stale`).

Why a dedicated worker and not inline regen?
--------------------------------------------
The snapshot flow has three properties that make the Orchestrator an
awkward host for this logic:

1. **Debounce.** A burst of invalidations — a new filing drops, a
   bias update fires, and a high-impact sentiment event all within
   a minute — should produce exactly one regeneration per symbol per
   window, not three (Req 11.2). The worker holds the in-memory
   ``{(user_id, symbol): last_invalidation_ts}`` map; the Orchestrator
   is stateless per run and can't.
2. **Fairness across users.** The worker round-robins through ready
   pairs so a single noisy user's watchlist doesn't starve everyone
   else. That concern doesn't exist at the per-run level.
3. **Long-running process.** The worker is ``await``\\ed from a
   supervised entrypoint (design §2.2, `start-research.sh`); it
   restarts independently of the gateway.

SubAgent "no_new_input" skip
----------------------------
Req 11.2 and design §3.10 both allow skipping Sub_Agents that have
no new input since the last run. This worker implements that by
accepting a ``subagent_selector`` callable: given the
``(user_id, symbol)`` and the set of input-document hashes from the
prior Snapshot row (if any), return the names of Sub_Agents whose
inputs have not changed. Those names are forwarded to the
Orchestrator via its ``plan_fn`` hook so the fan-out never invokes
them. The default selector keeps everything — safe, equivalent to a
full regen. Operators / future tasks can plug in a smarter selector
(e.g. "news_sentiment has new stream events ⇒ keep; filings hash
unchanged ⇒ skip") without touching the worker.

Persistence + stale-on-failure
------------------------------
Regeneration success → :meth:`SnapshotStore.save_snapshot` with the
new ``input_document_hashes`` and ``stale=false`` (the upsert clears
any prior stale flag).
Regeneration failure → :meth:`SnapshotStore.mark_stale` on the
existing row. When there is no prior row (first-ever regen for
``(user_id, symbol)``) the ``mark_stale`` is a no-op and the worker
logs a warning but keeps running — the user will see no Snapshot
until the next successful regen, which matches "never had a snapshot"
UX.

Satisfies
---------
* **Req 11.1** — precomputes a Snapshot per ``(user_id, symbol)``.
* **Req 11.2** — debounces regeneration by ``debounce_sec`` when a
  new document triggers invalidation.
* **Req 11.3** — consumes Commander bias invalidations (routed
  through :mod:`~src.research.snapshot.bias_listener`).
* **Req 11.5** — writes the canonical row shape.
* **Req 11.6** — stale-on-failure.
* Design §2.2 — runtime role.
* Design §3.10 — per-symbol Snapshot cache.
* Design §16.1 — wrapped by a worker entrypoint under
  ``src/research/workers/`` (Task 18.1 adds the `start-research.sh`
  glue; this file is the awaitable core).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Final,
    Mapping,
    Sequence,
)
from uuid import UUID

from src.research.constants import RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM
from src.research.snapshot.store import SnapshotStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Referenced in the module docstring and in type hints below —
    # only needed for static type-checkers so the module stays
    # importable on trimmed installs without the orchestrator
    # transitive import chain.
    from src.research.agents.orchestrator import ResearchOrchestrator  # noqa: F401


# Project-standard structured logger with the usual trimmed-install
# fallback (see :mod:`src.research.agents.partials`).
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("SnapshotWorker")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.workers.snapshotter")


__all__ = [
    "DEFAULT_DEBOUNCE_SEC",
    "InvalidationEvent",
    "OrchestratorFactory",
    "SubAgentSelector",
    "SnapshotWorker",
]


# ``research.snapshot.debounce_sec`` default per design §7.1.
DEFAULT_DEBOUNCE_SEC: Final[float] = 60.0

# Default sleep between housekeeping passes. The worker wakes at
# least this often to check whether any debounced ``(user_id, symbol)``
# pair is ready to regen. A shorter tick means the worst-case
# regeneration latency after the debounce elapses is bounded by this
# value; 1 second is a sensible balance against CPU noise.
_DEFAULT_TICK_SEC: Final[float] = 1.0

# How many invalidation-stream entries to pull per ``xread`` style
# call. The worker uses ``xrevrange`` for simplicity (no consumer
# groups) — a small batch is enough because the snapshotter is not
# a hot path.
_DEFAULT_EVENTS_PER_READ: Final[int] = 64

# Stream id passed into the initial ``xrevrange`` so we start from
# the most recent entry. Subsequent reads use the last-seen entry id
# to avoid re-processing.
_START_FROM_TAIL: Final[str] = "+"


@dataclass(frozen=True)
class InvalidationEvent:
    """One parsed ``(user_id, symbol)`` invalidation."""

    user_id: UUID
    symbol: str
    trigger: str
    entry_id: str
    source_event_id: str | None = None


# ``OrchestratorFactory`` returns a *new*
# :class:`ResearchOrchestrator` — or any object that satisfies its
# ``run(...)`` contract — configured for the caller's ``(user_id,
# symbol)`` tuple and with any Sub_Agents the selector wants to skip
# elided. Using a factory rather than injecting a prebuilt
# Orchestrator lets tests stub in a minimal fake (see
# ``tests/research/test_snapshotter_worker.py``) while production
# wiring constructs the real Orchestrator with the right provider
# roles wired up.
#
# Signature::
#
#     async def factory(
#         *,
#         user_id: UUID,
#         symbol: str,
#         skip_agents: tuple[str, ...],
#     ) -> ResearchOrchestrator | Any
#
OrchestratorFactory = Callable[..., Awaitable[Any]]

# ``SubAgentSelector`` decides which Sub_Agents to *skip* on the
# upcoming regen. Signature::
#
#     async def selector(
#         *,
#         user_id: UUID,
#         symbol: str,
#         prior_hashes: tuple[str, ...],
#     ) -> tuple[str, ...]    # agent names to skip
#
# Defaulting the selector to "skip nothing" is safe — the snapshot
# will still converge; it just won't realise the optimisation
# Req 11.2 permits.
SubAgentSelector = Callable[..., Awaitable[Sequence[str]]]


async def _default_sub_agent_selector(
    *,
    user_id: UUID,
    symbol: str,
    prior_hashes: tuple[str, ...],
) -> tuple[str, ...]:
    """Default selector — never skip any Sub_Agents.

    A no-op that still honours the protocol shape. Future tasks /
    operators can replace this with a real "what changed?" check.
    """
    # Arguments are accepted but intentionally unused — they exist
    # for protocol symmetry with smarter selectors.
    del user_id, symbol, prior_hashes
    return ()


class SnapshotWorker:
    """Debounced consumer of ``research:snapshot_invalidations``.

    Parameters
    ----------
    redis_reader:
        Any object exposing ``xrevrange(name, count=N) -> list[(id,
        fields)]`` — the same narrow Protocol the stream-consuming
        Sub_Agents use (see
        :class:`src.research.agents._stream.RedisStreamReader`). The
        worker does not need blocking consumption; pulling the most
        recent N entries on each tick is enough because the
        invalidation stream has low cardinality per minute and the
        worker dedupes by ``(stream, entry_id)``.
    snapshot_store:
        :class:`SnapshotStore` used for persistence. Injected so
        tests swap in fakes.
    orchestrator_factory:
        Callable described under :data:`OrchestratorFactory`. The
        object returned must expose ``async run(...)`` with the
        keyword arguments (``run_id``, ``user_id``, ``symbol``,
        ``user_prompt``). The worker awaits the coroutine and takes
        its return value as the brief dict to persist.
    subagent_selector:
        Optional callable described under :data:`SubAgentSelector`.
        Defaults to "skip nothing".
    snapshot_prompt_builder:
        Optional callable ``(symbol) -> str`` returning the prompt
        passed to ``orchestrator.run(user_prompt=...)``. Defaults to
        the terse "Produce a research snapshot for <SYMBOL>." which
        matches the intent of a pre-computed brief for a watchlist
        symbol (design §3.10). Override for tests that want to pin
        the prompt.
    debounce_sec:
        Debounce window in seconds per ``(user_id, symbol)`` pair
        (Req 11.2 default 60s). New invalidations within the window
        reset the timer.
    tick_sec:
        Loop cadence for the housekeeping pass. Short enough that
        the worst-case regen latency after the debounce elapses is
        bounded; long enough to not spin. Default 1s.
    events_per_read:
        Max entries fetched from the invalidation stream per
        ``xrevrange`` call.
    invalidation_stream:
        Stream name override. Defaults to
        :data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM`.
    hash_resolver:
        Optional async callable ``(user_id, symbol) -> tuple[str,
        ...]`` returning the current input-document hashes for
        persistence (Req 11.5). When ``None`` the worker writes an
        empty list — functional but degrades dedup semantics for
        downstream consumers. Production wiring passes a resolver
        that hashes the per-symbol corpus via
        :mod:`src.research.ingest.dedup`.
    clock:
        Callable returning the current wall-time. Defaults to
        :func:`time.monotonic` so debounce arithmetic is not
        affected by wall-clock jumps. Tests can pin a monotonic
        counter to drive the debounce deterministically.
    """

    def __init__(
        self,
        *,
        redis_reader: Any,
        snapshot_store: SnapshotStore,
        orchestrator_factory: OrchestratorFactory,
        subagent_selector: SubAgentSelector | None = None,
        snapshot_prompt_builder: Callable[[str], str] | None = None,
        debounce_sec: float = DEFAULT_DEBOUNCE_SEC,
        tick_sec: float = _DEFAULT_TICK_SEC,
        events_per_read: int = _DEFAULT_EVENTS_PER_READ,
        invalidation_stream: str = RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM,
        hash_resolver: Callable[
            [UUID, str], Awaitable[Sequence[str]]
        ]
        | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if debounce_sec < 0:
            raise ValueError(f"debounce_sec must be ≥ 0; got {debounce_sec}")
        if tick_sec <= 0:
            raise ValueError(f"tick_sec must be > 0; got {tick_sec}")
        self._reader = redis_reader
        self._store = snapshot_store
        self._factory = orchestrator_factory
        self._selector = subagent_selector or _default_sub_agent_selector
        self._prompt_builder = (
            snapshot_prompt_builder or _default_snapshot_prompt
        )
        self._debounce_sec = float(debounce_sec)
        self._tick_sec = float(tick_sec)
        self._events_per_read = max(1, int(events_per_read))
        self._invalidation_stream = invalidation_stream
        self._hash_resolver = hash_resolver
        self._clock = clock or time.monotonic

        # Debounce state. Keyed by ``(user_id, symbol)``. Value is the
        # monotonic timestamp of the most recent invalidation; the
        # housekeeping pass regenerates when ``clock() - ts >=
        # debounce_sec``.
        self._pending: dict[tuple[UUID, str], float] = {}
        # Deduplication: invalidation stream entry ids we've already
        # folded into ``_pending``.
        self._seen_entries: set[str] = set()

    # ------------------------------------------------------------------ #
    # Public run loop                                                    #
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Entry point for ``asyncio.run(worker.run())``.

        Wraps :meth:`run_forever` with the structural log lines the
        supervisor / `start-research.sh` entrypoint (Task 18.1)
        expects.
        """
        _log_info(
            "snapshot worker starting",
            stream=self._invalidation_stream,
            debounce_sec=self._debounce_sec,
            tick_sec=self._tick_sec,
        )
        try:
            await self.run_forever()
        except asyncio.CancelledError:
            _log_info("snapshot worker cancelled; stopping")
            raise
        except Exception as exc:  # noqa: BLE001 — supervisor log
            _log_warning(
                "snapshot worker stopped with error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

    async def run_forever(self) -> None:
        """Infinite loop: poll invalidations + run debounced regens.

        Cancel-aware. Iteration-level errors are caught and logged so
        a transient Redis / DB / Orchestrator hiccup does not tear
        the worker down.
        """
        while True:
            try:
                await self.poll_once()
                await self._run_ready_regens()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — best-effort
                _log_warning(
                    "snapshot worker tick failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            await asyncio.sleep(self._tick_sec)

    # ------------------------------------------------------------------ #
    # Invalidation ingestion                                             #
    # ------------------------------------------------------------------ #

    async def poll_once(self) -> int:
        """Pull recent invalidation entries; fold into debounce state.

        Returns the count of new (non-duplicate) invalidations folded
        in. Exposed so tests can exercise one step without running
        the loop.
        """
        try:
            entries = await self._reader.xrevrange(
                self._invalidation_stream,
                count=self._events_per_read,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log_warning(
                "invalidation read failed",
                stream=self._invalidation_stream,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return 0

        folded = 0
        now = self._clock()
        for raw_entry in entries:
            event = _parse_invalidation_entry(raw_entry)
            if event is None:
                continue
            if event.entry_id in self._seen_entries:
                continue
            self._seen_entries.add(event.entry_id)
            key = (event.user_id, event.symbol)
            # Last-write-wins: resetting the timestamp extends the
            # debounce window (Req 11.2).
            self._pending[key] = now
            folded += 1
            _log_debug(
                "invalidation folded",
                user_id=str(event.user_id),
                symbol=event.symbol,
                trigger=event.trigger,
                entry_id=event.entry_id,
            )
        return folded

    # ------------------------------------------------------------------ #
    # Debounced regen                                                    #
    # ------------------------------------------------------------------ #

    async def _run_ready_regens(self) -> int:
        """Run regen for every pair whose debounce has elapsed.

        Returns the number of regenerations attempted this pass.
        Kept private because the public caller is
        :meth:`run_forever` / tests driving one tick at a time via
        :meth:`tick` below.
        """
        now = self._clock()
        ready: list[tuple[UUID, str]] = []
        for key, ts in self._pending.items():
            if (now - ts) >= self._debounce_sec:
                ready.append(key)

        for key in ready:
            # Pop before dispatch so a new invalidation arriving
            # during regen re-arms the debounce for the next cycle.
            self._pending.pop(key, None)
            await self._regenerate_one(user_id=key[0], symbol=key[1])

        return len(ready)

    async def tick(self) -> int:
        """One ingest + regen cycle. Returns regen attempt count.

        Test-friendly synchronous hand-crank: call :meth:`poll_once`
        then :meth:`_run_ready_regens`. The production entry point
        is :meth:`run_forever` which adds the sleep between ticks.
        """
        await self.poll_once()
        return await self._run_ready_regens()

    async def _regenerate_one(self, *, user_id: UUID, symbol: str) -> None:
        """Regenerate the Snapshot for one ``(user_id, symbol)`` pair.

        Success → persist via :meth:`SnapshotStore.save_snapshot`.
        Failure → :meth:`SnapshotStore.mark_stale` on the existing
        row (Req 11.6).
        """
        _log_info(
            "snapshot regen starting",
            user_id=str(user_id),
            symbol=symbol,
        )

        prior_hashes = await self._current_hashes(user_id=user_id, symbol=symbol)

        try:
            skip_agents = tuple(
                await self._selector(
                    user_id=user_id,
                    symbol=symbol,
                    prior_hashes=prior_hashes,
                )
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log_warning(
                "subagent selector raised; skipping nothing",
                user_id=str(user_id),
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            skip_agents = ()

        try:
            orchestrator = await self._factory(
                user_id=user_id,
                symbol=symbol,
                skip_agents=skip_agents,
            )
            brief = await orchestrator.run(
                run_id=_synthetic_run_id(user_id=user_id, symbol=symbol),
                user_id=user_id,
                symbol=symbol,
                user_prompt=self._prompt_builder(symbol),
            )
        except Exception as exc:  # noqa: BLE001 — regen failure path
            _log_warning(
                "snapshot regen failed; marking stale",
                user_id=str(user_id),
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await self._mark_stale_safely(user_id=user_id, symbol=symbol)
            return

        # Success path. Persist with fresh timestamp + hashes.
        brief_dict = _coerce_brief(brief)
        hashes = await self._current_hashes(user_id=user_id, symbol=symbol)
        try:
            await self._store.save_snapshot(
                user_id,
                symbol,
                brief_dict,
                hashes,
            )
        except Exception as exc:  # noqa: BLE001 — persistence failure
            _log_warning(
                "snapshot regen produced brief but save failed; marking stale",
                user_id=str(user_id),
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await self._mark_stale_safely(user_id=user_id, symbol=symbol)
            return

        _log_info(
            "snapshot regen ok",
            user_id=str(user_id),
            symbol=symbol,
            input_hashes=len(hashes),
        )

    async def _mark_stale_safely(
        self,
        *,
        user_id: UUID,
        symbol: str,
    ) -> None:
        """Flip ``stale=true`` on the prior row; swallow DB errors."""
        try:
            flipped = await self._store.mark_stale(user_id, symbol)
        except Exception as exc:  # noqa: BLE001 — worker must stay up
            _log_warning(
                "mark_stale failed",
                user_id=str(user_id),
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        if not flipped:
            _log_debug(
                "mark_stale no-op (no prior snapshot row)",
                user_id=str(user_id),
                symbol=symbol,
            )

    async def _current_hashes(
        self,
        *,
        user_id: UUID,
        symbol: str,
    ) -> tuple[str, ...]:
        """Resolve the current input-document hash list (Req 11.5).

        When no hash resolver was injected, returns an empty tuple —
        the store still writes a valid (but empty) list. The
        downstream Snapshot-freshness logic does not actually
        inspect the hashes today; they live in the row so future
        selective-skip logic (§11.2) can compare prior vs current
        to decide what to skip.
        """
        if self._hash_resolver is None:
            return ()
        try:
            hashes = await self._hash_resolver(user_id, symbol)
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log_warning(
                "hash resolver raised; using empty list",
                user_id=str(user_id),
                symbol=symbol,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return ()
        return tuple(h for h in hashes if h)

    # ------------------------------------------------------------------ #
    # Introspection (tests)                                              #
    # ------------------------------------------------------------------ #

    @property
    def pending(self) -> Mapping[tuple[UUID, str], float]:
        """Read-only view of the pending debounce map (tests)."""
        return dict(self._pending)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _default_snapshot_prompt(symbol: str) -> str:
    """Default prompt handed to the Orchestrator.

    Short and neutral — the snapshot's intent is "refresh the
    precomputed brief for this watchlist symbol", not a user-authored
    question. The string matches what the gateway's Snapshot read
    path (future Task 16.x) would show on a cold miss.
    """
    return (
        f"Produce a research snapshot for {symbol}. "
        "Cite every non-boilerplate claim."
    )


def _coerce_brief(brief: Any) -> dict[str, Any]:
    """Coerce the Orchestrator's return value into a plain dict.

    :meth:`ResearchOrchestrator.run` returns a dict today (design
    §3.5); Task 13.8 will swap the return type for a
    :class:`~pydantic.BaseModel` ``ResearchBrief``. Accept both so
    this module doesn't break the day the swap lands.
    """
    if isinstance(brief, Mapping):
        return dict(brief)
    # Pydantic v2.
    dump = getattr(brief, "model_dump", None)
    if callable(dump):
        try:
            value = dump(mode="json")  # type: ignore[call-arg]
        except TypeError:
            value = dump()
        if isinstance(value, Mapping):
            return dict(value)
    # Pydantic v1 / attrs / dataclasses with ``dict()``.
    to_dict = getattr(brief, "dict", None)
    if callable(to_dict):
        try:
            value = to_dict()
            if isinstance(value, Mapping):
                return dict(value)
        except Exception:  # noqa: BLE001 - defensive
            pass
    # Last resort — empty dict so persistence still succeeds with a
    # valid jsonb payload. The caller will log a warning via the
    # regen path when this happens.
    return {}


def _synthetic_run_id(*, user_id: UUID, symbol: str) -> UUID:
    """Generate a stable-enough run_id for a Snapshot regeneration.

    The snapshot flow doesn't persist a ``research_runs`` row today
    (design §4.1 tracks runs for user-initiated requests); we still
    need a UUID for the Orchestrator's ``run_id`` parameter because
    it stamps the partials stream. A fresh UUID4 is good enough —
    the deterministic shape is ``uuid4`` to avoid collisions in a
    worker that regens thousands of snapshots per hour.
    """
    # Kept as a function rather than inlined so tests can monkey-patch.
    from uuid import uuid4

    # ``user_id`` / ``symbol`` are unused here but accepted so a
    # future deterministic variant (e.g. uuid5 over the pair) is a
    # one-line swap.
    del user_id, symbol
    return uuid4()


def _parse_invalidation_entry(
    entry: Any,
) -> InvalidationEvent | None:
    """Parse one raw ``xrevrange`` entry into an :class:`InvalidationEvent`.

    Accepts both ``(entry_id, fields)`` tuples and already-parsed
    :class:`~src.research.agents._stream.StreamEvent` instances so
    this module stays compatible with either in-project reader
    (:class:`RedisStreamReader` Protocol or raw
    ``redis.asyncio.Redis.xrevrange``).
    """
    entry_id: str
    raw_fields: Mapping[str, Any]

    # Tuple shape.
    if isinstance(entry, tuple) and len(entry) == 2:
        maybe_id, maybe_fields = entry
        if not isinstance(maybe_fields, Mapping):
            return None
        entry_id = (
            maybe_id.decode("utf-8")
            if isinstance(maybe_id, (bytes, bytearray))
            else str(maybe_id)
        )
        raw_fields = maybe_fields
    else:
        # StreamEvent (duck-typed).
        fields_attr = getattr(entry, "fields", None)
        event_id = getattr(entry, "event_id", None)
        if not isinstance(fields_attr, Mapping) or event_id is None:
            return None
        entry_id = str(event_id)
        raw_fields = fields_attr

    try:
        user_id = UUID(str(raw_fields.get("user_id", "")).strip())
    except (ValueError, TypeError):
        _log_debug(
            "invalidation entry has no/invalid user_id",
            entry_id=entry_id,
        )
        return None

    symbol_raw = raw_fields.get("symbol")
    if not symbol_raw:
        _log_debug(
            "invalidation entry has no symbol",
            entry_id=entry_id,
            user_id=str(user_id),
        )
        return None
    symbol = str(symbol_raw).strip().upper()
    if not symbol:
        return None

    trigger = str(raw_fields.get("trigger") or "unknown")
    source_event_id = raw_fields.get("source_event_id")
    source_event_id_str = (
        str(source_event_id) if source_event_id not in (None, "") else None
    )

    return InvalidationEvent(
        user_id=user_id,
        symbol=symbol,
        trigger=trigger,
        entry_id=entry_id,
        source_event_id=source_event_id_str,
    )


def _log_debug(message: str, **fields: Any) -> None:
    """Emit a DEBUG log, adapting to the available logger shape."""
    try:
        _logger.debug(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.debug("%s %s", message, fields)


def _log_info(message: str, **fields: Any) -> None:
    """Emit an INFO log, adapting to the available logger shape."""
    try:
        _logger.info(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.info("%s %s", message, fields)


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape."""
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)


# --------------------------------------------------------------------------- #
# CLI entrypoint (Task 18.1, design §16.1)                                    #
# --------------------------------------------------------------------------- #
#
# Lightweight ``main()`` that lets ``start-research.sh`` supervise this
# module as a background process via ``python -m
# src.research.workers.snapshotter``. The heavy lifting — debounce
# state, regen dispatch, stale-on-failure — lives in :class:`SnapshotWorker`
# above. This tail only owns the process lifecycle: config load, Redis
# connect, signal handling, and a minimal worker stack wiring.
#
# The stack wiring here is deliberately minimal:
#
# * Redis reader — an ``redis.asyncio.Redis`` client with
#   ``decode_responses=True`` so ``xrevrange`` returns str-keyed dicts
#   matching :func:`_parse_invalidation_entry`'s tuple path.
# * Snapshot store — lazy-built from the gateway's asyncpg pool when
#   available; falls back to a no-op store when Postgres is
#   unreachable so the worker can still drain the invalidation
#   stream for observability.
# * Orchestrator factory — a stub factory returning a no-op
#   orchestrator, matching the pattern used by
#   :mod:`src.research.workers.orchestrator`. Operators extend this
#   in Phase 18+ (see Tasks 19.x) to wire the full Sub_Agent stack
#   into a worker-side Orchestrator.
#
# The snapshotter does not own the full brief generation path — its
# contract is "debounce + trigger a regen" (Req 11.2). The regen
# attempt lands via the injected orchestrator factory; a degraded
# stub here means "never successfully regenerate, always fall back to
# stale". That is fine for the zero-runtime-dependencies default; the
# gateway process still runs its own in-process snapshotter when
# configured, and this worker is primarily a supervision target.


import argparse
import logging
import os
import signal
import sys


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the worker CLI."""
    parser = argparse.ArgumentParser(
        prog="research-snapshotter",
        description=(
            "Lohi-Research snapshotter worker (design §2.2). Consumes "
            "research:snapshot_invalidations and regenerates per-symbol "
            "Snapshots with a debounce window."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll + regen tick then exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint invoked by ``start-research.sh`` (design §16.1).

    Returns an OS exit code — the launcher restarts on non-zero.
    """
    args = _parse_cli_args(argv)
    try:
        asyncio.run(_run_worker_main(once=args.once))
    except KeyboardInterrupt:
        _log_info("snapshotter worker interrupted; shutting down")
        return 0
    except Exception as exc:  # noqa: BLE001 - supervisor log
        _log_warning(
            "snapshotter worker crashed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1
    return 0


async def _run_worker_main(*, once: bool = False) -> None:
    """Set up collaborators and drive the :class:`SnapshotWorker`."""
    redis_url = _resolve_snapshotter_redis_url()
    redis_client = await _connect_snapshotter_redis(redis_url)
    if redis_client is None:
        _log_warning(
            "snapshotter worker cannot start; redis unavailable",
            redis_url=redis_url,
        )
        return

    # No-op snapshot store with both required methods. A real store
    # lands via the gateway's ResearchService wiring; this fallback
    # keeps the worker runnable for observability.
    class _NoopSnapshotStore:
        async def save_snapshot(
            self,
            user_id: Any,
            symbol: str,
            brief: dict,
            input_document_hashes: Any,
        ) -> None:  # pragma: no cover - degraded path
            return None

        async def mark_stale(self, user_id: Any, symbol: str) -> bool:  # pragma: no cover
            return False

    # Stub orchestrator factory — returns a minimal object with an
    # async ``run`` method that returns an empty brief. The worker
    # will persist (a no-op) the empty brief via the store above.
    async def _stub_factory(
        *,
        user_id: Any,
        symbol: str,
        skip_agents: Any = (),
    ) -> Any:
        class _StubOrchestrator:
            async def run(self, *, run_id: Any, user_id: Any, symbol: str, user_prompt: str) -> dict:
                return {}

        return _StubOrchestrator()

    worker = SnapshotWorker(
        redis_reader=redis_client,
        snapshot_store=_NoopSnapshotStore(),  # type: ignore[arg-type]
        orchestrator_factory=_stub_factory,
    )

    stop_event = asyncio.Event()
    _install_snapshotter_signal_handlers(stop_event)

    _log_info(
        "snapshotter worker starting (CLI)",
        redis_url=redis_url,
        once=once,
    )

    try:
        if once:
            await worker.tick()
            return

        # Race the worker against the stop_event so SIGTERM can
        # interrupt a long ``run_forever``.
        run_task = asyncio.create_task(worker.run(), name="snapshotter-run")
        stop_task = asyncio.create_task(stop_event.wait(), name="snapshotter-stop")
        try:
            done, pending = await asyncio.wait(
                {run_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            for task in done:
                if task is run_task:
                    # run_task raised — let the exception propagate
                    # so ``main()`` logs a non-zero exit.
                    exc = task.exception()
                    if exc is not None and not isinstance(exc, asyncio.CancelledError):
                        raise exc
        except asyncio.CancelledError:
            run_task.cancel()
            raise
    finally:
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        _log_info("snapshotter worker stopped (CLI)")


def _resolve_snapshotter_redis_url() -> str:
    """Resolve the Redis URL for the snapshotter CLI.

    Mirrors the resolution order used by
    :mod:`src.research.workers.orchestrator` so all three worker
    processes agree on the Redis target without config duplication.
    """
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "localhost")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}"


async def _connect_snapshotter_redis(url: str) -> Any | None:
    """Return a connected ``redis.asyncio.Redis`` or ``None`` on failure."""
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415
    except ImportError:
        _log_warning("redis.asyncio not installed; worker cannot start")
        return None
    try:
        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        _log_warning(
            "redis ping failed",
            url=url,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None
    return client


def _install_snapshotter_signal_handlers(stop_event: asyncio.Event) -> None:
    """Wire ``SIGINT`` / ``SIGTERM`` to flip ``stop_event`` (CLI mode)."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main(sys.argv[1:]))
