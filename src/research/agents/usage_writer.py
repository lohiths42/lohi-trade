"""``llm_usage`` writer — one row per provider call (Req 12.5, design §4.1).

Role in the Orchestrator graph
------------------------------
Every LLM invocation made during a ``Research_Run`` — by any
Sub_Agent, by the plan node, by the Report_Synthesizer, by the
Judge — contributes a row to the ``llm_usage`` table (design §4.1,
Req 12.5). The row carries

* ``user_id`` — the tenant the call is charged against;
* ``research_run_id`` — the run the call belongs to (nullable: the
  plan and the post-run async Judge may land before or after the
  run row is finalised);
* ``provider`` / ``model`` — the adapter identifiers from the
  Provider_Contract (Req 2.11);
* ``input_tokens`` / ``output_tokens`` — raw counts from the
  completion;
* ``cost_estimate_usd`` — optional, computed by the caller when a
  price table is configured (this module treats it as a best-effort
  extra and defaults to zero when absent).

This module is the tiny, injectable writer that the Orchestrator /
Sub_Agents hand each completion to. It owns two behaviours the
Orchestrator must not duplicate at every call site:

1. **Best-effort persistence.** A broken DB must not kill the run.
   Writes are wrapped in a single try/except that logs the failure
   and swallows it (design §4.1 mirrors the same pattern for the
   ``research_audit_log`` trigger). The run still completes; the
   gateway's ``ResearchBrief`` still emits. Observability is
   recoverable; a half-finished research run is not.
2. **No-op for tests.** Unit tests that do not care about DB wiring
   use :class:`NoopUsageWriter`; the writer protocol matches so
   nothing else has to change.

Injection shape
---------------
The concrete :class:`UsageWriter` takes a ``connection_factory``
mirroring the pattern used by :mod:`src.research.memory.semantic` and
:mod:`src.research.memory.episodic` — a callable
``(user_id) -> AsyncContextManager[asyncpg.Connection]`` that yields
a connection with ``app.user_id`` already set for the current
transaction so RLS on ``llm_usage`` engages (design §14). In
production the factory is :meth:`ResearchService.connection`; in
tests it is any compatible async context manager that yields an
``execute``-able stub.

Accepting a factory rather than a pool lets tests substitute a
minimal fake without pulling ``asyncpg`` into the import path, and
lets the Orchestrator stay unaware of pool lifecycle — the writer is
the single place that cares about RLS engagement for this table.

Design references
-----------------
* §3.5 — Orchestrator graph ("Every provider call writes a row to
  ``llm_usage``").
* §4.1 — ``llm_usage`` DDL.
* §14 — RLS engagement via ``app.user_id``.
* Req 12.5 — per-run, per-provider usage table schema.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from contextlib import AbstractAsyncContextManager

    import asyncpg


# ``src.utils.logger`` provides the project-standard structured
# logger; fall back to stdlib ``logging`` on trimmed installs the
# same way :mod:`src.research.agents.orchestrator` does. Keeps the
# observability wiring uniform whether we're inside the gateway
# process or a bare research worker.
try:  # pragma: no cover - import-path fallback
    from src.utils.logger import get_logger

    _logger: Any = get_logger("UsageWriter")
except Exception:  # noqa: BLE001 - best-effort logger wiring
    import logging

    _logger = logging.getLogger("research.agents.usage_writer")


__all__ = [
    "NoopUsageWriter",
    "UsageWriter",
    "UsageWriterProtocol",
]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class UsageWriterProtocol(Protocol):
    """Contract the Orchestrator + Sub_Agents see (design §3.5).

    One method, :meth:`write`, takes the full per-call record and
    persists it (or no-ops in the test variant). The method is
    ``async`` because the production implementation issues a
    Postgres INSERT; the no-op implementation matches the signature
    so callers don't have to special-case it.

    The ``purpose`` and ``latency_ms`` parameters carry observability
    context the ``llm_usage`` table does not store today but every
    call site already has at hand. They are accepted so callers have
    a single-method contract — the writer logs them even when the DB
    schema has no column for them. Adding columns in a future
    migration becomes a one-line change in :meth:`UsageWriter.write`.
    """

    async def write(
        self,
        *,
        run_id: UUID | None,
        user_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        latency_ms: int,
        cost_estimate_usd: Decimal | float | None = None,
    ) -> None:
        """Persist one ``llm_usage`` row for the given provider call."""
        ...


# ---------------------------------------------------------------------------
# Concrete writer
# ---------------------------------------------------------------------------


class UsageWriter:
    """Writes a single row to ``llm_usage`` per provider call (Req 12.5).

    Parameters
    ----------
    connection_factory:
        Async context manager factory yielding an ``asyncpg``
        connection with ``app.user_id`` already set for the current
        transaction (design §14). The production factory is
        :meth:`ResearchService.connection`; tests pass a lightweight
        stub that exposes an ``execute(sql, *args)`` coroutine.

        The factory is called per :meth:`write` so every INSERT
        participates in its own short transaction. A long-lived
        writer-owned connection would hold RLS context across calls
        and, worse, would mean a failed INSERT could poison a
        transaction we'd otherwise want kept open for the rest of
        the run.

    Best-effort semantics
    ---------------------
    Any exception raised during the INSERT path (connection acquire,
    transaction start, ``execute``, the factory's own context
    manager ``__aexit__``) is caught, logged via ``_logger.warning``,
    and swallowed. The caller never sees it. Rationale:

    * The ``llm_usage`` table is an **observability** sink. Missing a
      row degrades usage telemetry but does not affect run
      correctness — there is no tight feedback loop that reads back
      the row we just wrote.
    * A broken DB would otherwise cascade from "Postgres is flapping"
      into "every Sub_Agent call fails" and then "the whole research
      run errors". That is exactly the blast-radius the design §3.5
      best-effort note wants to avoid.

    We deliberately log at ``WARNING`` (not ``ERROR``) so the run is
    not flagged as failed in dashboards that alert on error lines;
    a persistent flood of warnings is the right signal for
    operators investigating degraded observability.

    The INSERT itself lists every non-default column so
    ``created_at`` falls back to the server-side ``DEFAULT now()`` in
    the migration (design §4.1) — keeping the writer insulated from
    the gateway's clock.

    """

    # ``INSERT ... ON CONFLICT DO NOTHING`` is not required — the
    # ``llm_usage`` PK is a generated UUID, collisions are
    # vanishingly rare and treated as a real error. Ordering
    # parameters positionally matches the migration column order so
    # a future ``UPDATE`` won't have to reshuffle.
    _INSERT_SQL = (
        "INSERT INTO llm_usage "
        "(user_id, research_run_id, provider, model, "
        "input_tokens, output_tokens, cost_estimate_usd) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)"
    )

    def __init__(
        self,
        *,
        connection_factory: Callable[
            [UUID],
            AbstractAsyncContextManager[asyncpg.Connection],
        ],
    ) -> None:
        self._conn_factory = connection_factory

    async def write(
        self,
        *,
        run_id: UUID | None,
        user_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        latency_ms: int,
        cost_estimate_usd: Decimal | float | None = None,
    ) -> None:
        """Persist one ``llm_usage`` row. Logs + swallows any DB error.

        Parameters mirror the :class:`UsageWriterProtocol`
        specification. ``purpose`` and ``latency_ms`` are captured in
        the warning log on failure and in the debug log on success;
        they will map to real columns in a future migration.

        ``cost_estimate_usd`` defaults to ``Decimal('0')`` because the
        underlying column is ``NUMERIC(12,6) NOT NULL DEFAULT 0``
        (design §4.1). Callers with a populated price table hand in
        the real figure; the Orchestrator's plan node and any test
        that hasn't wired pricing can simply omit it.

        Requirements: 12.5.
        """
        if input_tokens < 0:
            raise ValueError(
                f"input_tokens must be non-negative; got {input_tokens}",
            )
        if output_tokens < 0:
            raise ValueError(
                f"output_tokens must be non-negative; got {output_tokens}",
            )

        # Normalise the cost to a ``Decimal`` once at the boundary so
        # the SQL layer always sees a single type. ``asyncpg`` binds
        # ``Decimal`` to ``NUMERIC`` natively; binding a ``float``
        # would round-trip through ``float8`` and lose precision.
        cost: Decimal
        if cost_estimate_usd is None:
            cost = Decimal(0)
        elif isinstance(cost_estimate_usd, Decimal):
            cost = cost_estimate_usd
        else:
            # ``Decimal(str(x))`` is the safe idiom — ``Decimal(float)``
            # preserves the binary float artefacts in the string form.
            cost = Decimal(str(cost_estimate_usd))

        try:
            async with self._conn_factory(user_id) as conn:
                await conn.execute(
                    self._INSERT_SQL,
                    user_id,
                    run_id,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    cost,
                )
        except Exception as exc:  # noqa: BLE001 - best-effort sink
            # Swallow + log. See class docstring for the rationale.
            _log_warning(
                "llm_usage write failed",
                error_type=type(exc).__name__,
                error=str(exc),
                provider=provider,
                model=model,
                purpose=purpose,
                latency_ms=latency_ms,
                run_id=str(run_id) if run_id is not None else None,
                user_id=str(user_id),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return

        _log_debug(
            "llm_usage row written",
            provider=provider,
            model=model,
            purpose=purpose,
            latency_ms=latency_ms,
            run_id=str(run_id) if run_id is not None else None,
            user_id=str(user_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# No-op writer
# ---------------------------------------------------------------------------


class NoopUsageWriter:
    """A :class:`UsageWriterProtocol` that throws every call away.

    Use from tests and from the offline-only rule-based path (design
    §11.4) where there is no Postgres to write to. The class is
    deliberately a separate implementation, not a ``None`` sentinel,
    so the Orchestrator's type annotation stays a single concrete
    protocol — callers never have to special-case "is there a
    writer?" at the call site.

    Captures the most recent call on :attr:`last_call` so tests that
    want to assert *what* would have been written (without wiring a
    fake DB) can do so without extra plumbing. The attribute is
    cleared on first call so it always holds the most recent record,
    never a growing list that could leak memory in a long-running
    test suite.
    """

    def __init__(self) -> None:
        self.last_call: dict[str, Any] | None = None
        self.call_count: int = 0

    async def write(
        self,
        *,
        run_id: UUID | None,
        user_id: UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        latency_ms: int,
        cost_estimate_usd: Decimal | float | None = None,
    ) -> None:
        """Record the call parameters and return.

        Matches :class:`UsageWriterProtocol.write` exactly so a
        :class:`NoopUsageWriter` is a drop-in substitute for
        :class:`UsageWriter` in any call site.
        """
        self.call_count += 1
        self.last_call = {
            "run_id": run_id,
            "user_id": user_id,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "purpose": purpose,
            "latency_ms": latency_ms,
            "cost_estimate_usd": cost_estimate_usd,
        }


# ---------------------------------------------------------------------------
# Logger shims
# ---------------------------------------------------------------------------


def _log_warning(message: str, **fields: Any) -> None:
    """Emit a WARNING log, adapting to the available logger shape.

    ``src.utils.logger``'s :class:`ComponentLogger` accepts an
    ``extra=`` mapping, while a stdlib ``logging.Logger`` fallback
    may reject it — so we try the structured form first and fall
    back to a formatted message. Mirrors
    :func:`src.research.agents.orchestrator._log_warning`.
    """
    try:
        _logger.warning(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.warning("%s %s", message, fields)


def _log_debug(message: str, **fields: Any) -> None:
    """Emit a DEBUG log, adapting to the available logger shape."""
    try:
        _logger.debug(message, extra=fields)
    except TypeError:  # pragma: no cover - very old logger variants
        _logger.debug("%s %s", message, fields)
