"""Latency-budget event emission on the ``research:latency_budget`` channel.

Publishes structured ``latency_budget_exceeded`` events when any Phase 1
latency budget from Req 5.1–5.3 is exceeded. The payload shape is the
one defined in design §13.4::

    {
      "phase": "<phase name>",
      "observed_ms": <int>,
      "budget_ms":   <int>,
      "exceeded_by_ms": <int>
    }

Events are published on :data:`RESEARCH_LATENCY_BUDGET_CHANNEL` via
``redis_client.publish(channel, payload)``. The same event is also
logged once at ``WARNING`` via :mod:`src.utils.logger` — which gives
operators visibility through the structured JSON log even when the
pubsub channel has no subscribers.

Satisfies:
    - Req 5.9 — emit a structured ``latency_budget_exceeded`` event
      with ``phase``, ``observed_ms``, ``budget_ms`` whenever any
      latency budget in Req 5.1–5.3 is exceeded.

Design references:
    - §3.11 (Caches + latency plumbing)
    - §13.4 (Latency budgets and events)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.research.constants import RESEARCH_LATENCY_BUDGET_CHANNEL

# ``src.utils.logger`` provides the project-standard structured logger.
# If it cannot be imported (e.g. tests running against a trimmed
# research-only install), we fall back to stdlib ``logging`` so this
# module still emits something visible. The fallback keeps the event
# emission path dependency-light for Phase 8 property tests.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchLatencyBudget")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.cache.latency_events")

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = ["emit_latency_budget_exceeded"]


async def emit_latency_budget_exceeded(
    *,
    redis_client: "Redis | Any",
    phase: str,
    observed_ms: int,
    budget_ms: int,
) -> None:
    """Publish a ``latency_budget_exceeded`` event for ``phase``.

    Exactly one Redis ``PUBLISH`` and exactly one ``WARNING`` log line
    are emitted per call. The event payload includes the derived
    ``exceeded_by_ms = observed_ms - budget_ms`` so subscribers don't
    need to duplicate the subtraction (design §13.4 specifies the
    three required fields — the derived field is additive).

    Parameters
    ----------
    redis_client:
        Async Redis client (``redis.asyncio.Redis``-compatible).
        Only ``publish`` is used.
    phase:
        Human-readable phase name (e.g. ``"first_token"``,
        ``"filings_agent"``, ``"judge"``). Free-form string — consumers
        match on it but this helper does not validate values.
    observed_ms:
        Wall-clock duration actually observed, in milliseconds.
    budget_ms:
        Budget that was exceeded, in milliseconds.

    Notes
    -----
    This function is **best-effort**: a Redis publish failure is
    logged at ``WARNING`` and swallowed. Exposing a publish failure
    to the orchestrator would turn an observability miss into a hard
    failure, which is the opposite of what Req 5.9 intends.
    """
    exceeded_by_ms = observed_ms - budget_ms

    event = {
        "phase": phase,
        "observed_ms": observed_ms,
        "budget_ms": budget_ms,
        "exceeded_by_ms": exceeded_by_ms,
    }
    payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)

    # Single WARNING log line — operators who can't subscribe to
    # pubsub still see the event in the structured log.
    _log_warning(
        "research latency budget exceeded",
        phase=phase,
        observed_ms=observed_ms,
        budget_ms=budget_ms,
        exceeded_by_ms=exceeded_by_ms,
    )

    try:
        await redis_client.publish(RESEARCH_LATENCY_BUDGET_CHANNEL, payload)
    except Exception:  # noqa: BLE001 - best-effort publish
        _log_warning(
            "research latency budget publish failed",
            channel=RESEARCH_LATENCY_BUDGET_CHANNEL,
            phase=phase,
        )


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape.

    :class:`src.utils.logger.ComponentLogger` takes ``extra=dict``;
    stdlib :class:`logging.Logger` takes ``extra=dict`` via kwargs of
    the same name. Both spellings work, but the ComponentLogger path
    adds the component name automatically — we prefer it when present.
    """
    # Both loggers accept ``extra={...}``; use ``warning`` uniformly.
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)
