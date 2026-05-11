"""Per-request ``app.user_id`` helper for asyncpg (Req 4.6, Req 8.5, design §14).

Every research table that carries a ``user_id`` column ships with an RLS
policy of the form::

    USING (user_id = current_setting('app.user_id')::uuid)

The existing JWT middleware in ``backend-gateway`` sets ``app.user_id``
for each HTTP request, but research code that runs **outside** a request
(orchestrator workers, the indexer, memory.forget, the snapshotter) must
set it themselves before issuing any query. Forgetting to do so would
cause the RLS predicate to evaluate against ``NULL`` and the query would
silently return zero rows — a correct-but-useless outcome that hides
bugs. This module centralises the two pieces every such call site needs:

* :func:`set_rls_user_id` — the raw ``SELECT set_config`` call, used when
  you already have a connection + transaction in hand (for example, the
  pgvector adapter in ``src/research/providers/vector_store/pgvector.py``
  keeps its private copy for exactly this reason).
* :func:`rls_connection` — the canonical async context manager that
  acquires a pooled asyncpg connection, opens a transaction, sets
  ``app.user_id``, and yields the connection. Any research service
  that needs an RLS-engaged connection should go through this helper
  rather than re-implementing the pattern.

The ``set_config(..., is_local := true)`` form is important: ``is_local``
scopes the setting to the current transaction so it is auto-cleared on
COMMIT / ROLLBACK. Without that flag, the setting would persist on the
connection and leak to the next tenant when the pool reuses it — the
exact cross-tenant leakage RLS is supposed to prevent.

Requirements: 4.6, 8.5
Design: §14
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


async def set_rls_user_id(
    conn: "asyncpg.Connection",
    user_id: UUID | str,
) -> None:
    """Engage RLS on ``conn`` by setting ``app.user_id`` for the current tx.

    Runs::

        SELECT set_config('app.user_id', $1, true)

    on the supplied asyncpg connection. The third argument ``true`` is
    ``is_local``, which scopes the setting to the **current transaction**:
    Postgres auto-clears it on COMMIT / ROLLBACK, so there is no risk of
    the value persisting on the connection after it returns to the pool
    and being picked up by the next tenant (design §14).

    This helper must therefore be called **inside** a transaction — if
    the connection is in autocommit mode, ``is_local=true`` means the
    setting is cleared the moment this statement completes and the RLS
    predicate evaluates against ``NULL`` on the next query. Use
    :func:`rls_connection` if you want the transaction handled for you.

    ``user_id`` may be a :class:`uuid.UUID` or a stringified UUID; both
    are coerced to ``str`` before binding so pgvector / asyncpg's text
    parameter path accepts it cleanly.

    Requirements: 4.6, 8.5
    Design: §14
    """
    await conn.execute(
        "SELECT set_config('app.user_id', $1, true)",
        str(user_id),
    )


@asynccontextmanager
async def rls_connection(
    pool: "asyncpg.Pool",
    user_id: UUID | str,
) -> AsyncIterator["asyncpg.Connection"]:
    """Canonical acquire-connection-and-engage-RLS entry point.

    Usage::

        async with rls_connection(pool, user_id) as conn:
            rows = await conn.fetch("SELECT * FROM research_runs")

    The context manager:

    1. Acquires a connection from ``pool`` via ``pool.acquire()``.
    2. Opens a transaction on that connection.
    3. Calls :func:`set_rls_user_id` so ``app.user_id`` is set for the
       duration of the transaction.
    4. Yields the connection to the caller.
    5. On exit (normal or via exception), the transaction ends —
       COMMIT on success, ROLLBACK on exception — and because
       ``set_config`` was called with ``is_local=true`` the
       ``app.user_id`` setting is cleared at the same moment. The
       connection is then returned to the pool by
       ``pool.acquire()``'s own context manager.

    Any research service code that needs an RLS-engaged connection
    should use this helper rather than rolling its own transaction
    scope — it is the single place where the ``is_local=true``
    invariant is enforced, which keeps future audits of the RLS
    boundary tractable.

    Requirements: 4.6, 8.5
    Design: §14
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_rls_user_id(conn, user_id)
            yield conn


__all__ = ["set_rls_user_id", "rls_connection"]
