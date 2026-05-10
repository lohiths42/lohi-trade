"""Semantic memory layer — Postgres + vector (design §3.4, §4.1).

**Semantic_Memory** holds per-user summarised knowledge that survives
across conversations: preferences, watchlist-linked facts, session
summaries (Req 4.3). It lives in the Postgres table
``research_semantic_memory`` with a per-row ``kind`` discriminator and
an optional ``embedding`` vector that is present only when the
pgvector backend is active (see migration 002 docstring).

RLS engagement
--------------
Every read and write in this module goes through the injected
``connection_factory`` — a callable that returns an *async context
manager* yielding an asyncpg connection with ``app.user_id`` already
set for the current transaction (Req 4.6). In production the factory
is :meth:`ResearchService.connection`, which wraps
:func:`app.services.research.rls.rls_connection` around the gateway's
shared asyncpg pool. In tests it can be any callable with the same
signature — for example, a wrapper around a pytest-managed asyncpg
pool, or a fake that records RLS engagement.

Requirements: 4.3, 4.5, 4.6
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


__all__ = ["SemanticMemory"]


logger = logging.getLogger(__name__)


# Default ``kind`` allow-list used for soft validation at insert time.
# The column is ``VARCHAR(32)`` so any matching string is accepted by
# Postgres; the allow-list here documents the intended vocabulary
# (design §4.1 migration comment: ``preference | watchlist_fact |
# session_summary``) without turning free-form kinds into runtime
# errors. The symbol-fact convention used by :mod:`forget` —
# ``"symbol_fact:<SYMBOL>"`` — is also a valid kind and deliberately
# uses the ``":"`` separator so it can be matched with a LIKE clause.
_KNOWN_KINDS: Final[frozenset[str]] = frozenset(
    {"preference", "watchlist_fact", "session_summary", "symbol_fact"},
)


# Sensible default page size for ``query`` — matches the UI's "recent
# items" widget size and keeps the response payload bounded.
_DEFAULT_LIMIT: Final[int] = 20


class SemanticMemory:
    """CRUD over ``research_semantic_memory`` with RLS engaged per call.

    Parameters
    ----------
    connection_factory:
        Callable ``(user_id) -> AsyncContextManager[asyncpg.Connection]``.
        Every method invokes it with the operation's ``user_id`` so
        the underlying transaction has ``app.user_id`` set for the
        duration — the RLS policy
        ``USING (user_id = current_setting('app.user_id')::uuid)``
        then both scopes reads (Req 4.5) and authorises inserts /
        deletes against the same tenant (Req 4.6).

    Notes on the ``embedding`` column
    ---------------------------------
    The ``embedding`` column is created conditionally by the Alembic
    migration when the pgvector extension is present. This module
    handles both deployments with one code path:

    * When ``embedding=None`` is passed to :meth:`add`, the INSERT
      omits the column entirely — works under both pgvector and
      Chroma profiles.
    * When a vector is supplied, we issue ``INSERT … embedding =
      $n::vector`` so the pgvector parser runs server-side. Under
      Chroma-backed deployments the column does not exist and the
      INSERT would fail; callers that pass a vector are declaring
      pgvector is active. This is the same invariant the pgvector
      adapter in :mod:`src.research.providers.vector_store.pgvector`
      relies on, and there is no point duplicating a runtime check
      here — a clear Postgres error at INSERT time is easier to
      diagnose than a silent fall-through.

    Requirements: 4.3, 4.5, 4.6
    Design: §3.4, §4.1

    """

    def __init__(
        self,
        *,
        connection_factory: Callable[
            [UUID], AbstractAsyncContextManager[asyncpg.Connection],
        ],
    ) -> None:
        self._conn_factory = connection_factory

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    async def add(
        self,
        user_id: UUID,
        kind: str,
        content: str,
        embedding: list[float] | None = None,
    ) -> UUID:
        """Insert one row and return its ``id``.

        The INSERT is RLS-gated: the connection has ``app.user_id`` set
        before the statement runs, so Postgres refuses any row whose
        ``user_id`` does not match the current tenant even if a future
        refactor accidentally took ``user_id`` out of the parameter
        list. RLS on INSERT uses the ``WITH CHECK`` predicate, which
        defaults to the same expression as ``USING`` for the policies
        in migration 002, so "set app.user_id, insert row where
        user_id = that same value" is safe.

        ``kind`` soft validation: the method does not raise on an
        unknown kind, but does emit a ``WARNING`` log so operators
        notice drift from the documented vocabulary. Keeping the
        check soft avoids breaking rare but legitimate extensions
        (e.g. a future Sub_Agent that wants to introduce a new
        ``kind``) while still surfacing accidental typos.

        Returns the generated UUID so callers can thread it through a
        subsequent UPDATE or audit-log row.

        Requirements: 4.3, 4.6
        """
        if kind not in _KNOWN_KINDS and not kind.startswith("symbol_fact:"):
            logger.warning(
                "semantic_memory.add: unknown kind=%r (known: %s); "
                "inserting anyway",
                kind,
                sorted(_KNOWN_KINDS),
            )

        async with self._conn_factory(user_id) as conn:
            if embedding is None:
                row = await conn.fetchrow(
                    """
                    INSERT INTO research_semantic_memory
                        (user_id, kind, content)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    user_id,
                    kind,
                    content,
                )
            else:
                # ``$4::vector`` triggers pgvector's text-to-vector
                # parser; callers are responsible for supplying a
                # list of floats whose length matches the column's
                # configured ``dim`` (see migration 002).
                row = await conn.fetchrow(
                    """
                    INSERT INTO research_semantic_memory
                        (user_id, kind, content, embedding)
                    VALUES ($1, $2, $3, $4::vector)
                    RETURNING id
                    """,
                    user_id,
                    kind,
                    content,
                    _format_vector_literal(embedding),
                )
        # ``RETURNING id`` always yields one row on successful INSERT,
        # but guard anyway so a driver-level oddity surfaces clearly.
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError(
                "semantic_memory.add: INSERT … RETURNING id returned no row",
            )
        return row["id"]

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    async def query(
        self,
        user_id: UUID,
        *,
        kind: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict]:
        """Return the most recent rows for ``user_id``, optionally by kind.

        * ``kind=None`` → every row the tenant owns, most recent first.
        * ``kind="foo"`` → rows with that exact ``kind`` only.

        RLS does the tenant scoping, not the WHERE clause — the
        ``user_id`` parameter is used to pick the factory / set
        ``app.user_id``, and the SQL intentionally omits
        ``WHERE user_id = $1``. This matches the principle of design
        §14: "scoping is a property of the connection, not of every
        query". It also means a future row added outside the policy's
        USING predicate (e.g. by direct SQL under a superuser) would
        be invisible here, which is the right behaviour.

        ``limit`` is clamped to a positive int; passing zero returns
        an empty list (Postgres accepts ``LIMIT 0``).

        Returns plain ``dict``s rather than a Pydantic model because
        the callers (orchestrator, snapshot service) need to attach
        domain-specific keys on top of the row — forcing a model
        here would add a copy without a correctness benefit.

        Requirements: 4.3, 4.5, 4.6
        """
        if limit < 0:
            raise ValueError(f"limit must be non-negative, got {limit}")

        async with self._conn_factory(user_id) as conn:
            if kind is None:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, kind, content, created_at
                    FROM research_semantic_memory
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, kind, content, created_at
                    FROM research_semantic_memory
                    WHERE kind = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    kind,
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
        kind: str | None = None,
    ) -> int:
        """Delete the tenant's rows, optionally narrowed by ``kind``.

        * ``kind=None`` → delete every row the tenant can see (RLS
          scopes it to their own rows; the policy's USING predicate
          forbids touching anyone else's).
        * ``kind="foo"`` → delete only rows with that ``kind``.
        * ``kind="symbol_fact:RELIANCE"`` is a valid call because
          that is a real stored ``kind`` — used by the ``forget(scope)``
          dispatch in :mod:`src.research.memory.forget` for the
          ``symbol:<SYMBOL>`` scope.

        Returns the count of deleted rows. asyncpg exposes this via
        the ``DELETE N`` string at the end of the command tag, which
        we parse below.

        Requirements: 4.3, 4.6
        Design: §3.4, §14
        """
        async with self._conn_factory(user_id) as conn:
            if kind is None:
                result = await conn.execute(
                    "DELETE FROM research_semantic_memory",
                )
            else:
                result = await conn.execute(
                    "DELETE FROM research_semantic_memory WHERE kind = $1",
                    kind,
                )
        return _parse_delete_count(result)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _format_vector_literal(vec: list[float]) -> str:
    """Render a Python list of floats as pgvector's text literal.

    Pgvector accepts ``'[1.0,2.0,3.0]'::vector``. Using the text form
    plus a server-side ``::vector`` cast (as done by :meth:`add`) means
    this module does **not** need the optional ``pgvector`` Python
    package on the driver side — a plain asyncpg client is enough.
    That keeps the research stack installable under the
    ``Persona_Self_Hosted`` profile where pgvector may not even be in
    use (design §8 auto-selection).

    The format is compact (no spaces, full precision) so round-tripping
    through the database preserves bit-for-bit equality on platforms
    whose float repr is deterministic.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _parse_delete_count(command_tag: str | Any) -> int:
    """Extract the row count from an asyncpg ``DELETE N`` command tag.

    ``conn.execute("DELETE …")`` returns a string of the form
    ``"DELETE 42"`` on success. Any other shape (empty string on a
    no-op, or an unexpected format from a driver upgrade) collapses to
    ``0`` — better to under-report than to crash a cleanup operation.
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
