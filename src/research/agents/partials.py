"""Partials streaming helpers for the Orchestrator / Sub_Agents (design §2.1, §3.5).

Each ``Sub_Agent`` contributes an :class:`AgentResult` to a
``Research_Run`` (see :mod:`src.research.agents.orchestrator`). As
those results land the Orchestrator ``xadd``\\s a partial event onto
the ``research:partials`` Redis stream (constant
:data:`src.research.constants.RESEARCH_PARTIALS_STREAM`); the gateway
(Phase 14, Task 16.3) re-emits the stream entries as Socket.IO events
on the ``research:<run_id>`` channel so the browser can render them
live.

This module consolidates that publish path into one reusable interface
that the Orchestrator, Sub_Agents, and future streaming paths can all
share:

* :data:`PartialsPublisher` — the callable type alias every component
  accepts at construction time. Defined here (and re-exported from
  :mod:`src.research.agents.orchestrator` for backwards compatibility)
  so there is exactly one source of truth.
* :class:`RedisPartialsPublisher` — concrete publisher that wraps a
  Redis async client's ``xadd`` against
  :data:`RESEARCH_PARTIALS_STREAM`. Errors are logged and swallowed
  (a broken Redis must not break a run — the final brief still lands
  via the gateway's REST response, design §3.12, §5.2).
* :class:`NoopPartialsPublisher` — a publisher that records calls in
  memory and never raises. Used by unit tests and the offline
  rule-based judge path that does not need to stream.
* :func:`format_agent_partial` / :func:`format_done` — helpers that
  serialise an :class:`AgentResult` (or an end-of-run marker) into
  the canonical, JSON-safe stream payload.

Event type constants
--------------------
Every partial event carries an ``event`` field picked from the small
set of :data:`EventType` constants. The names match the Socket.IO
event names the frontend listens for (design §5.2), so a single value
flows end-to-end from the Orchestrator through Redis into the UI:

* :data:`EVENT_AGENT_DONE` — one Sub_Agent has finished. Its
  ``AgentResult`` is attached as a JSON payload.
* :data:`EVENT_DONE` — the entire run is done. Carries the final
  quality label (``"high" | "medium" | "low"``) so subscribers that
  only listen to the partials stream can close their loops cleanly.
* :data:`EVENT_TOKEN` — reserved for future token-level streaming
  (design §5.2 ``research:token``). Not emitted by the current
  Orchestrator but declared here so downstream code can handle both
  granularities behind one constant.

Satisfies
---------
* Req 1.7 — the Orchestrator emits partial results to the caller as
  each Sub_Agent completes.
* Req 5.1 — first Socket.IO token event within 800 ms; enabled by
  this module's streaming contract.
* Req 5.2 — first Sub_Agent partial result within 2 s; enabled here.
* Design §2.1, §3.5 — top-down diagram and Orchestrator graph both
  show partials flowing through ``research:partials``.
* Design §3.11 — ``research:partials`` stream contract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Final, Mapping
from uuid import UUID

from src.research.constants import RESEARCH_PARTIALS_STREAM

# ``src.utils.logger`` provides the project-standard structured logger.
# Fall back to stdlib ``logging`` when it cannot be imported — same
# pattern used by :mod:`src.research.judge.async_fallback` and
# :mod:`src.research.cache.latency_events` so every observability
# helper behaves uniformly under trimmed test installs.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchPartials")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.agents.partials")


if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

    from src.research.agents.orchestrator import AgentResult


__all__ = [
    # Event type constants
    "EVENT_AGENT_DONE",
    "EVENT_DONE",
    "EVENT_TOKEN",
    # Publisher contract
    "PartialsPublisher",
    # Publisher implementations
    "RedisPartialsPublisher",
    "NoopPartialsPublisher",
    "make_redis_partials_publisher",
    # Payload helpers
    "format_agent_partial",
    "format_done",
]


# --------------------------------------------------------------------------- #
# Event type constants (design §5.2)                                          #
# --------------------------------------------------------------------------- #


#: One Sub_Agent's ``AgentResult`` has been produced (Req 1.7).
#:
#: Payload fields on the stream entry:
#:
#: * ``run_id`` — string UUID.
#: * ``event`` — literal ``"agent_done"``.
#: * ``payload`` — JSON-encoded :meth:`AgentResult.to_payload` dict.
EVENT_AGENT_DONE: Final[str] = "agent_done"

#: End-of-run marker so subscribers that only watch the partials stream
#: know the run is over (design §3.5, §5.2).
#:
#: Payload fields on the stream entry:
#:
#: * ``run_id`` — string UUID.
#: * ``event`` — literal ``"done"``.
#: * ``quality`` — final quality label (``"high" | "medium" | "low"``).
EVENT_DONE: Final[str] = "done"

#: Token-level streaming event (design §5.2 ``research:token``).
#:
#: Reserved; the current Orchestrator emits ``agent_done`` partials
#: only. Declared here so future streaming paths (the Phase 14 gateway
#: re-emit, token-level Sub_Agents) can reuse the same constant
#: without redefining it.
EVENT_TOKEN: Final[str] = "token"


# --------------------------------------------------------------------------- #
# Publisher contract                                                          #
# --------------------------------------------------------------------------- #


#: Callable that writes one entry onto the ``research:partials`` stream.
#:
#: Signature: ``(stream_name, fields_dict) -> Awaitable[Any]``.
#:
#: Mirrors ``redis.asyncio.Redis.xadd`` closely enough that
#: :func:`make_redis_partials_publisher` wraps a client into one line;
#: tests pass a recording stub. The return value is ignored by the
#: Orchestrator — Redis returns the newly-assigned stream id which
#: the caller does not need.
PartialsPublisher = Callable[[str, Mapping[str, Any]], Awaitable[Any]]


# --------------------------------------------------------------------------- #
# Payload helpers                                                             #
# --------------------------------------------------------------------------- #


def format_agent_partial(
    run_id: UUID,
    result: "AgentResult",
) -> dict[str, str]:
    """Serialise an :class:`AgentResult` into a ``research:partials`` entry.

    Redis Stream fields are string-typed; this helper returns a plain
    ``dict[str, str]`` so the caller can hand it to ``xadd`` without
    further coercion.

    The agent payload itself is JSON-encoded on the ``payload`` field
    so nested structures (chunk_ids list, token counts, reason strings)
    survive the wire format without collisions with the top-level
    stream fields.

    Parameters
    ----------
    run_id:
        Unique identifier for the run. Stamped onto the entry so the
        gateway can fan out to the right Socket.IO channel
        (``research:<run_id>``, design §5.2).
    result:
        The Sub_Agent's :class:`AgentResult`. Its
        :meth:`AgentResult.to_payload` output is the JSON body.

    Returns
    -------
    dict[str, str]
        ``{run_id, event, payload}`` with ``event`` pinned to
        :data:`EVENT_AGENT_DONE`.
    """
    return {
        "run_id": str(run_id),
        "event": EVENT_AGENT_DONE,
        "payload": _json_dumps(result.to_payload()),
    }


def format_done(run_id: UUID, *, quality: str) -> dict[str, str]:
    """Serialise an end-of-run marker into a ``research:partials`` entry.

    Parameters
    ----------
    run_id:
        Unique identifier for the run.
    quality:
        The final quality label produced by the Judge +
        re-synthesis loop (``"high" | "medium" | "low"`` — design
        §11.2). Forwarded verbatim; callers coerce it to a string
        if it is an enum upstream.

    Returns
    -------
    dict[str, str]
        ``{run_id, event, quality}`` with ``event`` pinned to
        :data:`EVENT_DONE`.
    """
    return {
        "run_id": str(run_id),
        "event": EVENT_DONE,
        "quality": str(quality),
    }


def _json_dumps(payload: Any) -> str:
    """JSON-dump a payload, keeping it Redis ``XADD``-safe.

    Redis stream fields are string-typed; ``json.dumps`` with
    ``ensure_ascii=False`` and ``separators=(",", ":")`` produces a
    compact, Unicode-safe value. Non-serialisable objects fall back
    to ``str(...)`` so a partial publish never crashes the run.
    """
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps(str(payload))


# --------------------------------------------------------------------------- #
# Concrete publishers                                                         #
# --------------------------------------------------------------------------- #


class RedisPartialsPublisher:
    """``PartialsPublisher`` that writes to Redis via ``xadd``.

    Mirrors the pattern in
    :func:`src.research.judge.async_fallback.redis_publisher_for`: a
    thin adapter around a Redis async client whose only job is to
    forward ``(stream_name, fields_dict)`` calls to
    ``client.xadd(stream_name, fields_dict)``.

    Errors are logged and swallowed. The gateway's Socket.IO path is
    an alternate route to the client (design §3.12, §5.2); a broken
    Redis stream does not take down the run, it just loses visibility
    into the partials.

    Parameters
    ----------
    redis_client:
        Async Redis client (``redis.asyncio.Redis``-compatible).
        Only :meth:`~redis.asyncio.Redis.xadd` is used.
    stream:
        Stream name to publish to. Defaults to
        :data:`RESEARCH_PARTIALS_STREAM`; tests / future streaming
        paths can override.
    maxlen:
        Optional cap on the stream length. Passed verbatim to
        ``xadd``'s ``maxlen`` keyword when set so the stream does
        not grow unbounded (design §3.11 notes the stream is a
        bounded short-term buffer). ``None`` disables trimming. The
        ``approximate=True`` flag is **not** set here — callers that
        want approximate trimming can subclass or pass a custom
        ``xadd`` through the callable contract.

    Examples
    --------
    >>> publisher = RedisPartialsPublisher(redis_client)
    >>> orchestrator = ResearchOrchestrator(..., partials_publisher=publisher)

    Or as a plain callable::

        await publisher(RESEARCH_PARTIALS_STREAM, {"run_id": "...", ...})
    """

    def __init__(
        self,
        redis_client: "Redis | Any",
        *,
        stream: str = RESEARCH_PARTIALS_STREAM,
        maxlen: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._maxlen = maxlen

    @property
    def stream(self) -> str:
        """The stream name this publisher writes to."""
        return self._stream

    async def __call__(
        self,
        stream: str,
        fields: Mapping[str, Any],
    ) -> Any:
        """Publish ``fields`` onto ``stream`` via ``xadd``.

        The ``stream`` argument is accepted (rather than hard-coded to
        ``self._stream``) to honour the :data:`PartialsPublisher`
        contract — callers that pass a different stream name are
        forwarded as-is. In practice the Orchestrator always passes
        :data:`RESEARCH_PARTIALS_STREAM`, which is identical to the
        default ``self._stream``.
        """
        # Coerce everything to str so Redis clients that require
        # string fields (``decode_responses=True`` clients) don't
        # reject the call on a stray int / None. ``None`` is replaced
        # with an empty string — the same fallback
        # ``AgentResult.to_payload`` uses for its reason field.
        safe_fields: dict[str, str] = {
            str(k): "" if v is None else str(v) for k, v in fields.items()
        }
        try:
            if self._maxlen is not None:
                return await self._redis.xadd(
                    stream,
                    safe_fields,
                    maxlen=self._maxlen,
                )
            return await self._redis.xadd(stream, safe_fields)
        except Exception as exc:  # noqa: BLE001 - best-effort publish
            _log_warning(
                "research partials publish failed",
                stream=stream,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


class NoopPartialsPublisher:
    """``PartialsPublisher`` that records calls in memory.

    Used in unit tests (where a real Redis would be overkill) and in
    the offline rule-based judge path that does not need to stream.
    Calls are captured on :attr:`calls` so tests can assert on what
    *would* have been published.

    Examples
    --------
    >>> publisher = NoopPartialsPublisher()
    >>> orchestrator = ResearchOrchestrator(..., partials_publisher=publisher)
    >>> # ... run ...
    >>> assert any(c.fields.get("event") == "done" for c in publisher.calls)
    """

    def __init__(self) -> None:
        #: List of every ``(stream, fields)`` call received, in order.
        #: Each entry is a :class:`_RecordedCall` so test assertions
        #: can destructure by attribute rather than index position.
        self.calls: list[_RecordedCall] = []

    async def __call__(
        self,
        stream: str,
        fields: Mapping[str, Any],
    ) -> None:
        """Record the call; never raises."""
        self.calls.append(_RecordedCall(stream=stream, fields=dict(fields)))

    def clear(self) -> None:
        """Drop recorded calls (useful between test phases)."""
        self.calls.clear()


class _RecordedCall:
    """One recorded publish call. Kept flat for test ergonomics.

    Not a :func:`dataclasses.dataclass` because tests import this
    through :class:`NoopPartialsPublisher.calls` and only ever read
    the two attributes — the extra import weight of ``dataclasses``
    buys us nothing here.
    """

    __slots__ = ("stream", "fields")

    def __init__(self, *, stream: str, fields: dict[str, Any]) -> None:
        self.stream = stream
        self.fields = fields

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"_RecordedCall(stream={self.stream!r}, fields={self.fields!r})"


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def make_redis_partials_publisher(
    redis_client: "Redis | Any",
    *,
    stream: str = RESEARCH_PARTIALS_STREAM,
    maxlen: int | None = None,
) -> PartialsPublisher:
    """Build a :data:`PartialsPublisher` bound to a Redis client.

    Lets the Orchestrator wire partials with one line::

        orchestrator = ResearchOrchestrator(
            ...,
            partials_publisher=make_redis_partials_publisher(redis_client),
        )

    Returns a :class:`RedisPartialsPublisher` instance — instances are
    callable and therefore satisfy the :data:`PartialsPublisher`
    callable-type alias. Kept as a thin factory so the construction
    signature is visible at the call site (the Orchestrator's
    ``partials_publisher`` kwarg accepts any callable, but readers
    should be able to see which concrete publisher is being used).
    """
    return RedisPartialsPublisher(redis_client, stream=stream, maxlen=maxlen)


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape.

    Same helper as :mod:`src.research.judge.async_fallback` — copied
    rather than imported to keep this module free of cross-package
    dependencies inside the ``src/research/`` tree.
    """
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)
