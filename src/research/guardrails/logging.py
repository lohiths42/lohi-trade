"""Persist :class:`GuardrailDecision` rows to Postgres and the structured log.

Every allow/modify/refuse decision returned by a :class:`Guardrail`
implementation should eventually land in two places:

1. The ``research_guardrail_decisions`` Postgres table, which is
   RLS-scoped per ``user_id`` (see migration in Task 4.1). Rows are
   inserted with the caller-provided ``run_id`` linkage so the
   ``ResearchBrief.provenance`` block can be assembled by a simple
   join (Req 16.11, design §4.1).
2. The structured JSON log, via :func:`src.utils.logger.get_logger`,
   so operators see the same fields without needing to query the
   database.

The two paths are deliberately independent — a failure to persist
should still produce a log line, and vice versa — so this module does
not raise on Postgres errors; it logs them at WARNING and moves on.

Satisfies:
    - Req 16.11 — every guardrail decision logged with ``rule_id``,
      ``action``, and ``reason`` and summarised into the
      ``ResearchBrief.provenance`` block.

Design references:
    - §3.6 (Guardrail_Layer logging sidecar)
    - §4.1 (``research_guardrail_decisions`` schema)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.research.guardrails.pydantic_guard import GuardrailDecision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from contextlib import AbstractAsyncContextManager

    import asyncpg


__all__ = ["log_guardrail_decision"]


# ``src.utils.logger.get_logger`` is the project-standard structured
# logger. Fall back to stdlib logging in trimmed test installs where
# the full utils tree is unavailable — the function must not import-
# fail, because Phase 9 property tests need to exercise it.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("Guardrail")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.guardrails.logging")


# SQL for the audit insert. Written as a bare statement with
# positional parameters so the asyncpg driver can prepare it once per
# connection. The ``id`` column defaults to ``gen_random_uuid()`` in
# the migration, so we do not supply it here.
_INSERT_SQL = (
    "INSERT INTO research_guardrail_decisions "
    "(run_id, phase, rule_id, action, reason) "
    "VALUES ($1, $2, $3, $4, $5)"
)


# Factory protocol: callable returning an async context manager that
# yields an asyncpg connection with ``app.user_id`` already set for
# the transaction (design §14). Matches the signature used by
# :class:`SemanticMemory` et al.
ConnectionFactory = Callable[[UUID], "AbstractAsyncContextManager[asyncpg.Connection]"]


async def log_guardrail_decision(
    decision: GuardrailDecision,
    *,
    run_id: UUID | None,
    user_id: UUID,
    connection_factory: ConnectionFactory | None,
) -> None:
    """Log + persist one guardrail decision.

    Parameters
    ----------
    decision:
        The :class:`GuardrailDecision` emitted by the guard. All five
        audit fields (``phase``, ``rule_id``, ``action``, ``reason``,
        and — via the structured log — the pre/post content) come
        from here.
    run_id:
        The owning ``Research_Run`` id, or ``None`` for decisions
        taken outside a run (e.g. during ad-hoc Orchestrator calls).
        Nullable in the schema.
    user_id:
        Tenant id. Passed to ``connection_factory`` so the underlying
        asyncpg transaction has ``app.user_id`` set, engaging RLS
        (Req 4.6). Also emitted on the log line so log aggregators
        can filter per-tenant.
    connection_factory:
        Callable that returns an async context manager yielding an
        asyncpg connection. When ``None``, the function skips the
        Postgres insert and only emits the structured log line —
        useful in tests that run without a database.

    Notes
    -----
    The function never raises. Postgres errors are logged at WARNING
    and swallowed; the primary audit trail is the structured log,
    and the database insert is a best-effort sidecar.

    """
    # Structured log — always emitted so operators have a trail even
    # when Postgres is unreachable.
    _logger.info(
        "guardrail_decision",
        extra={
            "run_id": str(run_id) if run_id is not None else None,
            "user_id": str(user_id),
            "phase": decision.phase,
            "rule_id": decision.rule_id,
            "action": decision.action,
            "reason": decision.reason,
        },
    )

    # Prometheus counter (Task 20.2, Req 13.2). Only ``refuse`` and
    # ``modify`` decisions count as blocks — ``allow`` is the healthy
    # path and operators do not need to alert on it. Imported lazily
    # so a trimmed test install without ``prometheus_client`` does not
    # break the structured-log path above.
    if decision.action in ("refuse", "modify"):
        try:
            from src.research.observability.metrics import (
                research_guardrail_blocks_total,
            )

            research_guardrail_blocks_total.labels(rule_id=decision.rule_id).inc()
        except Exception:  # noqa: BLE001 - best-effort metrics
            pass

    if connection_factory is None:
        return

    try:
        async with connection_factory(user_id) as conn:
            await conn.execute(
                _INSERT_SQL,
                run_id,
                decision.phase,
                decision.rule_id,
                decision.action,
                decision.reason,
            )
    except Exception as exc:  # noqa: BLE001 - sidecar must not fail caller
        _logger.warning(
            "guardrail_decision_persist_failed",
            extra={
                "user_id": str(user_id),
                "run_id": str(run_id) if run_id is not None else None,
                "rule_id": decision.rule_id,
                "error": repr(exc),
            },
        )
