"""Async-Judge fallback — background Judge execution when budget is tight (design §11.3).

The Orchestrator (Phase 12) calls the Judge_LLM synchronously after the
Report_Synthesizer produces a brief (design §3.5). When the synchronous
call would push total ``Research_Run`` latency over
``research.latency_budgets.full_brief_ms`` (Req 5.3), this module
provides the async-fallback path documented in design §11.3:

1. The caller decides — via :func:`should_run_async` — whether the
   Judge would blow the budget given ``elapsed_ms`` and the expected
   Judge latency (``research.judge.async_fallback_budget_ms``, Req 15.7).
2. If yes, the caller emits the brief immediately with
   ``judge_pending=true`` (design §4.2 ``ResearchBrief.judge_pending``)
   so the UI can render the "verifying…" badge (Req 15.8, §3.13
   ``JudgeVerifyingBadge``).
3. :func:`schedule_background_judge` kicks off the Judge on the current
   :mod:`asyncio` event loop via :func:`asyncio.create_task`, awaits
   the resulting :class:`JudgeReport`, and hands it to a
   caller-supplied publisher.
4. The default publisher publishes the report on the
   :data:`~src.research.constants.RESEARCH_JUDGE_REPORT_CHANNEL`
   Redis pubsub channel; the gateway re-emits it as the
   ``research:judge_report`` Socket.IO event (design §5.2) and the UI
   replaces the "verifying…" badge with the final verdict.

Why two callables (not one Redis client)
-----------------------------------------
Tests drive this module without a real Redis. The public surface takes
either:

* a :class:`Redis`-like client on which we call
  :func:`publish_judge_report` (the factory
  :func:`redis_publisher_for` wraps the client into the callable the
  scheduler expects), **or**
* a user-supplied ``Callable[[str, dict], Awaitable[None]]`` that
  publishes however it likes (Socket.IO directly, an internal bus,
  nothing in a unit test).

This keeps the production wiring one line while letting every test in
``tests/research/test_async_fallback.py`` use a plain ``list.append``
stub.

Satisfies
---------
* Req 15.7 — the Judge call MUST add ≤2 000 ms to full-brief latency;
  :func:`should_run_async` returns ``True`` when the current ``elapsed_ms``
  plus the expected Judge cost would exceed ``full_brief_ms``.
* Req 15.8 — when the budget would be exceeded the Judge runs
  asynchronously and the final :class:`JudgeReport` arrives on
  :data:`RESEARCH_JUDGE_REPORT_CHANNEL` once it completes.

Design references
-----------------
* §3.7  — ``JudgeReport`` schema.
* §4.2  — ``ResearchBrief.judge_pending`` flag.
* §5.2  — ``research:judge_report`` Socket.IO event.
* §11.3 — async fallback workflow.
* §13.1 — full-brief latency budget (15 s reference, 60 s offline).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.research.constants import RESEARCH_JUDGE_REPORT_CHANNEL
from src.research.judge.judge import JudgeReport

# ``src.utils.logger`` provides the project-standard structured logger.
# Fall back to stdlib ``logging`` when it cannot be imported — the same
# pattern used in :mod:`src.research.cache.latency_events` so both
# observability helpers behave uniformly under trimmed test installs.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchAsyncJudge")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.judge.async_fallback")

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = [
    "JudgeReportPublisher",
    "should_run_async",
    "schedule_background_judge",
    "publish_judge_report",
    "redis_publisher_for",
    "budget_for_mode",
]


# --------------------------------------------------------------------------- #
# Publisher contract                                                          #
# --------------------------------------------------------------------------- #

#: Callable that publishes a ``JudgeReport`` payload to some channel.
#:
#: Takes ``(channel, payload_dict)`` and returns an awaitable. ``payload_dict``
#: is the already-deserialised :meth:`JudgeReport.model_dump` output —
#: the publisher itself chooses whether to ``json.dumps`` it (Redis) or
#: forward the object (in-process bus, test stub). Keeping the payload
#: as a dict (rather than pre-serialised JSON) lets test doubles assert
#: on structured fields directly without re-parsing JSON.
JudgeReportPublisher = Callable[[str, dict], Awaitable[None]]


# --------------------------------------------------------------------------- #
# Decision — sync vs async Judge                                              #
# --------------------------------------------------------------------------- #


def should_run_async(
    elapsed_ms: int,
    expected_judge_ms: int,
    full_brief_ms_budget: int,
) -> bool:
    """Decide whether the Judge must run in the background (design §11.3).

    Returns ``True`` exactly when ``elapsed_ms + expected_judge_ms``
    **exceeds** ``full_brief_ms_budget``. Equal is not exceeded — the
    Orchestrator should prefer the synchronous path on a tie so that
    the brief lands with ``judge_pending=false`` and the UI never
    shows the "verifying…" badge for a run that would have fit
    comfortably.

    Parameters
    ----------
    elapsed_ms:
        Wall-clock time already spent on the ``Research_Run`` up to
        and including synthesis + the numeric validator (design §3.5).
        The Orchestrator snapshots this just before the Judge would
        otherwise run.
    expected_judge_ms:
        Operator's expected Judge cost. In production this is
        ``research.judge.async_fallback_budget_ms`` (default 2 000,
        design §7.1, Req 15.7); the callsite passes it in so tests
        can force any boundary.
    full_brief_ms_budget:
        Full-brief latency budget (``research.latency_budgets.full_brief_ms``,
        default 15 000 for the reference config; 60 000 offline —
        design §13.1, Req 15.4/15.5). The Orchestrator substitutes the
        offline value at boot when ``LOHI_RESEARCH_OFFLINE=true`` so
        this helper stays mode-agnostic.

    Returns
    -------
    bool
        ``True`` when the Judge MUST run asynchronously, ``False``
        when the synchronous path fits within budget.

    Raises
    ------
    ValueError
        When any of the three arguments is negative. Negative budgets
        are always a caller bug — returning a silent ``True`` would
        mask the misconfiguration, which is the opposite of what
        Req 7.6 (fail fast on bad config) intends.
    """
    if elapsed_ms < 0:
        raise ValueError(f"elapsed_ms must be non-negative; got {elapsed_ms}")
    if expected_judge_ms < 0:
        raise ValueError(
            f"expected_judge_ms must be non-negative; got {expected_judge_ms}"
        )
    if full_brief_ms_budget < 0:
        raise ValueError(
            f"full_brief_ms_budget must be non-negative; got {full_brief_ms_budget}"
        )

    # Strictly greater — equal fits by the budget's own definition.
    return (elapsed_ms + expected_judge_ms) > full_brief_ms_budget


# --------------------------------------------------------------------------- #
# Mode-aware full-brief budget                                                #
# --------------------------------------------------------------------------- #


def budget_for_mode(
    full_brief_ms: int,
    offline_full_brief_ms: int,
    offline: bool | None = None,
) -> int:
    """Pick the full-brief latency budget appropriate to the current mode.

    Satisfies Req 15.5 and design §13.1: when offline the budget is
    relaxed from the reference ``research.latency_budgets.full_brief_ms``
    (default 15 000) to ``research.latency_budgets.offline_full_brief_ms``
    (default 60 000) to accommodate Ollama + local embeddings latency.

    Parameters
    ----------
    full_brief_ms:
        The reference-configuration budget, i.e.
        ``research.latency_budgets.full_brief_ms`` (Req 5.3, Req 15.4).
    offline_full_brief_ms:
        The offline budget,
        ``research.latency_budgets.offline_full_brief_ms`` (Req 15.5,
        design §13.1).
    offline:
        Explicit mode override. ``True`` forces the offline budget,
        ``False`` forces the reference budget, and ``None`` (the
        default) reads ``LOHI_RESEARCH_OFFLINE`` from the environment
        — matching the env-var convention the registry's
        :func:`src.research.providers.registry._is_offline` helper
        already uses (Req 9.4). Callers that know the mode statically
        (e.g. a worker boot that stored the mode on a field) pass
        ``True`` / ``False`` directly so the helper stays pure; the
        env-probing default exists so call sites without a mode field
        (tests, one-off callers) get the right answer out of the box.

    Returns
    -------
    int
        The budget in milliseconds appropriate to the current mode.
    """
    if offline is None:
        offline = os.environ.get(
            "LOHI_RESEARCH_OFFLINE", ""
        ).strip().lower() in ("true", "1", "yes")
    return offline_full_brief_ms if offline else full_brief_ms


# --------------------------------------------------------------------------- #
# Background scheduler                                                        #
# --------------------------------------------------------------------------- #


def schedule_background_judge(
    judge_coro: Awaitable[JudgeReport],
    *,
    publisher: JudgeReportPublisher,
    channel: str = RESEARCH_JUDGE_REPORT_CHANNEL,
    task_name: str = "research-async-judge",
) -> "asyncio.Task[None]":
    """Schedule ``judge_coro`` on the current event loop and publish the result.

    The returned :class:`asyncio.Task` is started **immediately** (the
    coroutine begins executing in the next event-loop iteration per
    :func:`asyncio.create_task` semantics) — callers that emit the
    brief with ``judge_pending=true`` should kick this off right after
    the emit so the background work runs concurrently with the
    client's Socket.IO receive loop.

    The wrapper coroutine this function schedules:

    1. Awaits ``judge_coro`` to obtain a :class:`JudgeReport`.
    2. Calls ``publisher(channel, report.model_dump(mode='json'))``.
       ``mode='json'`` matches what a caller wanting ``model_dump_json``
       would get (UUIDs stringified, tuples kept as lists) and leaves
       the payload JSON-serialisable for the default Redis publisher.
    3. Swallows any exception from ``judge_coro`` or ``publisher`` and
       logs it at ``WARNING``. A background Judge failure must not
       crash the event loop — the brief is already in the user's hands
       with ``judge_pending=true``, and the UI will simply keep
       rendering the "verifying…" badge. An operator inspecting the
       logs sees the reason.

    Parameters
    ----------
    judge_coro:
        A coroutine or awaitable that resolves to a
        :class:`JudgeReport`. In production this is
        ``judge.invoke(run_id=…, brief=…, chunks=…, numeric_findings=…,
        llm=…)``; tests pass any coroutine function that returns a
        canned report (or raises, to exercise the error path).
    publisher:
        Async callable that accepts ``(channel, payload_dict)`` and
        publishes the payload. See :data:`JudgeReportPublisher`.
    channel:
        Redis pubsub channel to publish on. Defaults to
        :data:`RESEARCH_JUDGE_REPORT_CHANNEL` so production callers
        don't need to thread the constant through; tests pass a
        custom channel to assert on the value.
    task_name:
        Name attached to the created :class:`asyncio.Task` so it
        shows up in ``asyncio.all_tasks()`` diagnostics with a
        recognisable label. Defaults to ``"research-async-judge"``.

    Returns
    -------
    asyncio.Task[None]
        The scheduled task. Callers that want to confirm completion
        (integration tests, graceful-shutdown hooks) can ``await``
        it. Production callers ignore the return value — the point
        of the fallback is to return to the caller immediately.
    """
    return asyncio.create_task(
        _run_and_publish(judge_coro, publisher=publisher, channel=channel),
        name=task_name,
    )


async def _run_and_publish(
    judge_coro: Awaitable[JudgeReport],
    *,
    publisher: JudgeReportPublisher,
    channel: str,
) -> None:
    """Await the Judge and publish the result; swallow all errors.

    Extracted so :func:`schedule_background_judge` stays a pure
    scheduling primitive — the error-handling policy lives here so
    it can be tested directly with ``asyncio.run(_run_and_publish(...))``.
    """
    try:
        report = await judge_coro
    except Exception as exc:  # noqa: BLE001 - best-effort background
        _log_warning(
            "async judge invocation failed",
            channel=channel,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return

    # ``mode='json'`` produces a JSON-serialisable dict (UUIDs → str,
    # tuples → lists). We keep the payload as a dict so in-process
    # publishers (tests, Socket.IO bridges) can introspect fields
    # without re-parsing; the Redis publisher serialises via json.dumps.
    try:
        payload = report.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - defensive
        _log_warning(
            "async judge report serialisation failed",
            channel=channel,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return

    try:
        await publisher(channel, payload)
    except Exception as exc:  # noqa: BLE001 - best-effort publish
        _log_warning(
            "async judge report publish failed",
            channel=channel,
            error_type=type(exc).__name__,
            error=str(exc),
        )


# --------------------------------------------------------------------------- #
# Redis-backed publisher                                                      #
# --------------------------------------------------------------------------- #


async def publish_judge_report(
    redis_client: "Redis | Any",
    channel: str,
    payload: dict,
) -> None:
    """Publish a JSON-serialised :class:`JudgeReport` on a Redis channel.

    Mirrors the pattern in
    :func:`src.research.cache.latency_events.emit_latency_budget_exceeded`:
    one ``PUBLISH``, best-effort error handling, single warning log
    on failure. Used by the default publisher built by
    :func:`redis_publisher_for`; tests can call it directly against a
    fake Redis client.

    Parameters
    ----------
    redis_client:
        Async Redis client (``redis.asyncio.Redis``-compatible).
        Only ``publish`` is used.
    channel:
        Pubsub channel name. Normally
        :data:`RESEARCH_JUDGE_REPORT_CHANNEL`.
    payload:
        JSON-serialisable :class:`JudgeReport` payload (typically
        produced by ``report.model_dump(mode='json')``).
    """
    try:
        serialised = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        _log_warning(
            "async judge report JSON encoding failed",
            channel=channel,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return

    try:
        await redis_client.publish(channel, serialised)
    except Exception:  # noqa: BLE001 - best-effort publish
        _log_warning(
            "async judge report redis publish failed",
            channel=channel,
        )


def redis_publisher_for(redis_client: "Redis | Any") -> JudgeReportPublisher:
    """Build a :data:`JudgeReportPublisher` bound to a Redis client.

    Lets the Orchestrator wire ``schedule_background_judge`` with one
    line::

        schedule_background_judge(
            judge.invoke(...),
            publisher=redis_publisher_for(redis_client),
        )

    A thin adapter rather than a closure-factory-returning-closure so
    the resulting callable's signature matches :data:`JudgeReportPublisher`
    exactly — mypy / pyright can verify the contract at the call site.
    """

    async def _publish(channel: str, payload: dict) -> None:
        await publish_judge_report(redis_client, channel, payload)

    return _publish


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape.

    Same helper as :mod:`src.research.cache.latency_events` — copied
    rather than imported to keep this module free of cross-package
    dependencies inside the ``src/research/`` tree (the latency
    helper lives under ``cache/`` whose import graph we want to
    keep one-way toward the Judge, not the reverse).
    """
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)
