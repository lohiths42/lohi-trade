"""Episodic memory layer — Postgres, per ``(user_id, symbol)`` timeline (design §3.4, §4.1).

**Episodic_Memory** is the per-tenant, per-symbol *history* of research
activity. Every successful :class:`Research_Run` drops a summary row
here (Req 4.7); when the Orchestrator later primes context for a new
run on the same symbol, it reads the latest N rows so the conversation
picks up where the previous one left off.

Unlike :mod:`src.research.memory.semantic`, this layer does not carry
an embedding column: the access pattern is a simple "latest-first by
``created_at``" scan filtered by ``(user_id, symbol)``. The schema
from design §4.1 / migration 002 provides a matching composite index
on ``(user_id, symbol, created_at DESC)`` so the read is an index
seek regardless of how many rows the tenant accumulates.

RLS engagement
--------------
Identical to :mod:`semantic` — every operation goes through an
injected ``connection_factory`` whose contract is
``(user_id) -> AsyncContextManager[asyncpg.Connection]``. The returned
connection has ``app.user_id`` set (Req 4.6, design §14) so the
``rls_episodic_memory`` policy rejects any row whose ``user_id`` does
not match the caller, including inserts that accidentally carry a
stray UUID.

Requirements: 4.4, 4.7
Design: §3.4, §4.1
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from contextlib import AbstractAsyncContextManager

    import asyncpg


__all__ = ["EpisodicMemory"]


logger = logging.getLogger(__name__)


# Default page size for :meth:`read`. Matches the orchestrator's
# "recent runs" priming window — large enough to give a multi-run arc
# of context, small enough that the payload stays well under the
# summarisation budget when fed back into a prompt.
_DEFAULT_LIMIT: Final[int] = 10


class EpisodicMemory:
    """CRUD over ``research_episodic_memory`` with RLS engaged per call.

    Parameters
    ----------
    connection_factory:
        Callable ``(user_id) -> AsyncContextManager[asyncpg.Connection]``.
        Every method invokes it with the operation's ``user_id`` so
        the underlying transaction has ``app.user_id`` set for the
        duration. The policy on this table is identical in shape to
        the semantic-memory policy — ``USING (user_id =
        current_setting('app.user_id')::uuid)`` — so reads, inserts,
        and deletes all pick up tenant scoping automatically.

    Why "read" (not "query")
    ------------------------
    The method name intentionally mirrors :meth:`WorkingMemory.read`
    rather than :meth:`SemanticMemory.query`. Episodic memory is
    always accessed by ``(user_id, symbol)`` — there is no
    free-form ``kind`` discriminator to query by, and no embedding
    column to vector-search. The surface is narrower on purpose,
    which is why the method name is narrower too.

    Requirements: 4.4, 4.7
    Design: §3.4, §4.1

    """

    def __init__(
        self,
        *,
        connection_factory: Callable[
            [UUID],
            AbstractAsyncContextManager[asyncpg.Connection],
        ],
    ) -> None:
        self._conn_factory = connection_factory

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    async def add(
        self,
        user_id: UUID,
        symbol: str,
        run_id: UUID,
        summary: str,
    ) -> UUID:
        """Insert one timeline entry and return its ``id``.

        Called by the Orchestrator at the tail of a successful
        :class:`Research_Run` (Req 4.7) with a short natural-language
        summary of the brief. ``run_id`` is a foreign key into
        ``research_runs`` (migration 002) — the insert will fail with
        a clean FK violation if the caller passes an unknown run,
        which is the correct behaviour: an episodic row must always
        be traceable back to the run that produced it.

        The INSERT is RLS-gated: ``app.user_id`` is set before the
        statement runs, so the policy's implicit ``WITH CHECK``
        (defaulted to the ``USING`` predicate in migration 002)
        rejects any row whose ``user_id`` does not match the tenant
        even if a future refactor drops ``user_id`` from the
        parameter list.

        Returns the generated UUID so callers can thread it through
        a downstream audit-log row or UI confirmation payload.

        Requirements: 4.4, 4.7
        """
        async with self._conn_factory(user_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO research_episodic_memory
                    (user_id, symbol, run_id, summary)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                symbol,
                run_id,
                summary,
            )
        # ``RETURNING id`` always yields one row on successful INSERT,
        # but guard anyway so a driver-level oddity surfaces clearly.
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError(
                "episodic_memory.add: INSERT … RETURNING id returned no row",
            )
        return row["id"]

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    async def read(
        self,
        user_id: UUID,
        symbol: str,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict]:
        """Return the latest ``limit`` entries for ``(user_id, symbol)``.

        Ordered by ``created_at DESC`` — the composite index
        ``research_episodic_memory_user_symbol_created_idx`` makes
        this an index-only seek, so even a tenant with thousands of
        runs pays roughly the same cost as a tenant with ten.

        Tenant scoping is carried by the RLS-engaged connection, not
        by a ``WHERE user_id = $1`` clause. This follows the design
        §14 principle — "scoping is a property of the connection,
        not of every query" — and keeps the module consistent with
        :class:`SemanticMemory`. A future row added outside the
        policy's USING predicate (e.g. a superuser-scope INSERT in a
        migration) would simply not be visible here, which is the
        correct failure mode.

        ``limit`` must be non-negative; zero yields an empty list
        (Postgres accepts ``LIMIT 0``). The caller is trusted to
        choose a sensible upper bound — the method deliberately does
        not clamp because the Orchestrator occasionally reads the
        full timeline during a "start fresh" priming path.

        Returns plain ``dict``s rather than a Pydantic model because
        downstream code (orchestrator context builder, brief
        renderer) attaches domain-specific keys on top of each row
        — forcing a model here would add a copy without a
        correctness benefit, matching the choice made in
        :meth:`SemanticMemory.query`.

        Requirements: 4.4, 4.5, 4.6
        """
        if limit < 0:
            raise ValueError(f"limit must be non-negative, got {limit}")

        async with self._conn_factory(user_id) as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, symbol, run_id, summary, created_at
                FROM research_episodic_memory
                WHERE symbol = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                symbol,
                limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Deletes                                                            #
    # ------------------------------------------------------------------ #

    async def delete(
        self,
        user_id: UUID,
        *,
        symbol: str | None = None,
    ) -> int:
        """Delete the tenant's rows, optionally narrowed by ``symbol``.

        * ``symbol=None`` → delete every episodic row the tenant can
          see. RLS scopes the DELETE to the tenant's rows; the
          policy's USING predicate forbids touching anyone else's.
        * ``symbol="RELIANCE"`` → delete only rows for that symbol
          (used by the ``forget(scope="symbol:<SYMBOL>")`` dispatch
          in :mod:`src.research.memory.forget`).

        Returns the count of deleted rows, parsed out of asyncpg's
        ``DELETE N`` command tag the same way
        :meth:`SemanticMemory.delete` does. Keeping the parser local
        (rather than importing from ``semantic``) keeps the two
        modules independent so either can be edited without a
        cross-module coupling hazard.

        Requirements: 4.4, 4.6, 4.8
        Design: §3.4, §14
        """
        async with self._conn_factory(user_id) as conn:
            if symbol is None:
                result = await conn.execute(
                    "DELETE FROM research_episodic_memory",
                )
            else:
                result = await conn.execute(
                    "DELETE FROM research_episodic_memory WHERE symbol = $1",
                    symbol,
                )
        return _parse_delete_count(result)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _parse_delete_count(command_tag: str | Any) -> int:
    """Extract the row count from an asyncpg ``DELETE N`` command tag.

    ``conn.execute("DELETE …")`` returns a string of the form
    ``"DELETE 42"`` on success. Any other shape (empty string on a
    no-op, or an unexpected format from a driver upgrade) collapses
    to ``0`` — better to under-report than to crash a cleanup
    operation that the user explicitly asked for.

    Duplicates the parser in :mod:`semantic` intentionally. Both
    helpers are ~10 lines and keeping them local avoids a private
    cross-module import that would couple two otherwise-independent
    memory layers at the implementation level.
    """
    if not isinstance(command_tag, str):
        return 0
    parts = command_tag.strip().split()
    if len(parts) >= 2 and parts[0].upper() == "DELETE":
        try:
            return int(parts[1])
        except ValueError:
            return 0
    return 0
