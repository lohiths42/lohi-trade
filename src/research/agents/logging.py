"""Structured-logging helpers for the Research Orchestrator + Sub_Agents.

The helpers in this module emit one JSON line per logical event so that
operators inspecting the aggregated log stream can reconstruct a
``Research_Run`` without touching the Redis streams or the Postgres
trace tables. The redaction formatter wired at
:mod:`src.utils.logger.setup_logging` already scrubs any key matching
``api_key|secret|token|password|totp`` (Req 9.6), so callers that only
pass non-sensitive fields do not need any further redaction step.

Three helpers are provided:

* :func:`log_sub_agent_invocation` — one INFO line per Sub_Agent invocation
  with ``agent_name``, ``kind``, ``section_name``, wall-time, and token
  counts. Matches the provenance set returned in
  :class:`~src.research.agents.orchestrator.AgentResult` so the log and
  the ``research_provenance`` row are always in sync.
* :func:`log_retrieval_call` — one INFO line per retrieval call,
  carrying ``k``, ``symbol``, wall-time, and ``hit_count``. Sub_Agents
  that bypass the shared retriever (e.g. the Technicals Agent) can
  still emit the same shape for uniformity.
* :func:`log_orchestrator_event` — one INFO line per Orchestrator
  milestone (``plan_done``, ``fan_out_start``, ``fan_out_done``,
  ``synthesis_done``, ``judge_done``). Free-form ``**fields`` so the
  Orchestrator can attach whatever context the event warrants.

Satisfies
---------
* Req 13.5 — structured log per Sub_Agent invocation and per retrieval call.
* Req 9.6  — sensitive fields are either absent or flow through the
  existing formatter's redaction pass (no new redactor needed).

Design references
-----------------
* §15 — operator dashboards backed by the same JSON log stream.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

# Match the import-path fallback used by
# :mod:`src.research.judge.async_fallback` and
# :mod:`src.research.guardrails.logging` so observability wiring stays
# uniform under trimmed test installs.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("ResearchAgents")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.agents.logging")


__all__ = [
    "log_sub_agent_invocation",
    "log_retrieval_call",
    "log_orchestrator_event",
]


def log_sub_agent_invocation(
    *,
    run_id: UUID,
    user_id: UUID,
    agent_name: str,
    kind: str,
    section_name: str,
    wall_time_ms: int,
    input_tokens: int,
    output_tokens: int,
    reason: str = "",
) -> None:
    """Emit one structured INFO line for a Sub_Agent invocation.

    Parameters mirror
    :class:`~src.research.agents.orchestrator.AgentResult` so the log
    line and the ``research_provenance`` row share the same field
    names. UUIDs are stringified in the extra dict so downstream JSON
    consumers can ingest them without custom decoders.

    The function never raises — a logger shape mismatch (a very old
    stdlib logger that does not accept ``extra``) falls back to a
    positional-formatting call.
    """
    fields = {
        "run_id": str(run_id),
        "user_id": str(user_id),
        "agent_name": agent_name,
        "kind": kind,
        "section_name": section_name,
        "wall_time_ms": int(wall_time_ms),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reason": reason,
    }
    _emit("sub_agent_invocation", fields)


def log_retrieval_call(
    *,
    run_id: UUID,
    user_id: UUID,
    agent_name: str,
    k: int,
    symbol: str | None,
    wall_time_ms: int,
    hit_count: int,
) -> None:
    """Emit one structured INFO line for a retrieval call.

    ``symbol`` is ``None`` for cross-symbol retrieval (e.g. a Macro
    Agent query that does not scope on a ticker). The field is kept
    in the payload so log aggregators always see the same shape.
    """
    fields = {
        "run_id": str(run_id),
        "user_id": str(user_id),
        "agent_name": agent_name,
        "k": int(k),
        "symbol": symbol,
        "wall_time_ms": int(wall_time_ms),
        "hit_count": int(hit_count),
    }
    _emit("retrieval_call", fields)


def log_orchestrator_event(
    *,
    run_id: UUID,
    user_id: UUID,
    event: str,
    **fields: Any,
) -> None:
    """Emit one structured INFO line for an Orchestrator milestone.

    ``event`` is a short kebab/snake-case tag such as ``"plan_done"``,
    ``"fan_out_start"``, ``"fan_out_done"``, ``"synthesis_done"``,
    ``"judge_done"``. The free-form ``**fields`` are forwarded
    verbatim via ``extra=`` so callers can attach context (for
    example ``agent_count`` at ``fan_out_start``).

    Sensitive fields (``api_key``, ``secret``, ``token``, ``password``,
    ``totp``) should not be placed in ``**fields``; the formatter's
    redaction pass excludes them by key when they appear, but the
    best defence is still to not log them (Req 9.6).
    """
    payload: dict[str, Any] = {
        "run_id": str(run_id),
        "user_id": str(user_id),
        "event": event,
    }
    # Free-form fields win on key collisions so callers can override the
    # defaults (e.g. stamp a per-event ``user_id`` for a background
    # event not tied to a single user). UUID-valued extras are
    # stringified defensively.
    for key, value in fields.items():
        payload[key] = str(value) if isinstance(value, UUID) else value
    _emit(event, payload)


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _emit(message: str, fields: dict[str, Any]) -> None:
    """Emit ``fields`` as the ``extra`` payload of an INFO log line.

    Shape-agnostic wrapper: the project-standard
    :class:`~src.utils.logger.ComponentLogger` accepts a single
    keyword-only ``extra`` dict, while the stdlib fallback expects
    the same keyword. We try ``extra=…`` first and fall back to a
    positional message on the rare logger variants that reject it.
    """
    try:
        _logger.info(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.info("%s %s", message, fields)
