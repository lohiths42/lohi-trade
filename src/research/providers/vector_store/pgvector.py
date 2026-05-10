"""pgvector vector-store adapter (Req 2.6, Req 2.14, Req 3.10, Req 4.6, Req 8.5).

This is the **default SaaS** ``VectorStore`` for Lohi-Research (design §3.1
/ §7.1 / §8 — ``research.vector_store.backend: pgvector`` and the
``backend: auto`` branch that resolves to this adapter whenever the
existing LOHI-TRADE Postgres exposes the ``vector`` extension). It
reuses the ``DATABASE_URL`` already used by ``backend-gateway`` rather
than standing up a second connection string, so there is exactly one
Postgres the operator has to manage for both trading and research
(Req 8.5, Req 2.14).

Implements the ``VectorStore`` protocol declared in
``src.research.providers.base`` against the ``research_chunks`` table
created by the Alembic migration in Task 4.1. Until that migration
runs, the table (and specifically its ``embedding VECTOR(dim)`` column,
sized at runtime from the active ``EmbeddingsProvider.dim``) does not
exist — any query from this adapter will then raise
``asyncpg.UndefinedTableError`` and is expected to. That is the correct
failure mode: this adapter is coded against the Phase-4 schema now so
it "just works" the instant the migration lands, without any later
code changes (design §8, tasks 2.16 → 4.1).

Row-level security (design §14, Req 4.5–4.6, Req 8.5)
-----------------------------------------------------
Every table with a ``user_id`` column in the research schema carries
an RLS policy ``USING (user_id = current_setting('app.user_id')::uuid)``.
The JWT middleware in ``backend-gateway`` sets ``app.user_id`` on each
HTTP request, but the research workers (orchestrator, indexer,
snapshotter) run outside that middleware and must set it themselves.
This adapter therefore **always** runs queries inside a transaction
and calls ``SELECT set_config('app.user_id', $1, true)`` — ``true`` is
``is_local``, so the setting is scoped to the current transaction and
is auto-cleared when the transaction ends, preventing cross-tenant
leakage even if the connection is returned to the pool and handed to a
different request afterwards.

The explicit ``WHERE user_id = current_setting('app.user_id')::uuid``
clause added to every SELECT / DELETE / COUNT is redundant with the
RLS policy, but keeps the SQL self-documenting and guarantees the
query planner sees the predicate even in a non-RLS setup (e.g. a
superuser running ad-hoc diagnostics).

Index strategy (design Open Issue #7)
-------------------------------------
Vector similarity uses the cosine-distance operator ``<=>`` and a
similarity score of ``1 - (embedding <=> query)`` so values are in
[-1, 1] with higher = better — the same shape as the Chroma adapter
and the per-model floors in ``config/settings.yaml``. The Alembic
migration (Task 4.1) is expected to create an HNSW index:

    CREATE INDEX ON research_chunks USING hnsw
        (embedding vector_cosine_ops);

HNSW is the default per design Open Issue #7; operators with very
large corpora may swap in ``ivfflat`` without changing this adapter.

Vector wire format
------------------
pgvector accepts a string literal ``"[1.0,2.0,3.0]"`` on the wire and
parses it into a ``vector`` when cast with ``$N::vector``. We pass
embeddings as ``"[…]"`` strings and cast in SQL rather than registering
an asyncpg codec, so the adapter has **no runtime dependency on the
pgvector Python package**. When reading back, we select
``embedding::text`` and parse it with the same simple format.

Lazy initialisation
-------------------
``asyncpg`` is imported lazily inside ``build()`` so the module can be
imported on a bare install that does not have the package available
(Task 1.6, Req 2.12). The connection pool itself is also created
lazily, on the first use, rather than at ``build()`` time — this keeps
``build()`` non-IO and matches the other shipped adapters (Chroma,
sentence-transformers) which all defer heavyweight initialisation
until the first call.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ..base import ChunkHit, ChunkRecord, RetrievalFilter, VectorStore

# Type-only import so static checkers understand the ``asyncpg.Pool`` /
# ``asyncpg.Connection`` annotations without forcing ``asyncpg`` to be
# installed at import time.
if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #

# Matches the pool sizes used for the research workers (small, since the
# orchestrator holds at most a few concurrent sub-agent queries per run).
# The gateway's own asyncpg pool (``backend-gateway/app/services/db_service.py``)
# uses a separate, larger pool sized by ``PG_POOL_MIN_SIZE`` /
# ``PG_POOL_MAX_SIZE`` — we deliberately don't reuse that pool so the
# research workers can come up independently of the gateway process.
_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 5

# Table lives under ``public`` in the design §4.1 migration; operators can
# override via ``research.vector_store.pgvector.schema`` if they prefer
# an isolated schema.
_DEFAULT_SCHEMA = "public"
_TABLE_NAME = "research_chunks"


# --------------------------------------------------------------------------- #
# Vector serialisation                                                        #
# --------------------------------------------------------------------------- #
def _vec_to_pg(vec: list[float]) -> str:
    """Encode an embedding vector as the pgvector literal wire format.

    pgvector accepts ``"[1.0,2.0,3.0]"`` in SELECT / INSERT when the
    value is cast with ``$N::vector``; doing it this way avoids a
    dependency on the ``pgvector`` Python package and keeps the adapter
    self-contained.
    """
    # ``repr`` on a float is deterministic enough for pgvector's parser;
    # using ``str`` loses precision on subnormals in some Python builds.
    inner = ",".join(repr(x) for x in vec)
    return f"[{inner}]"


def _pg_to_vec(raw: str) -> list[float]:
    """Parse a pgvector ``embedding::text`` string back into ``list[float]``.

    pgvector emits ``"[1,2,3]"`` (no spaces, no trailing newline) from
    ``::text``. We strip the brackets and split; malformed input raises
    ``ValueError`` from the ``float`` conversion, which is intentional —
    an unparseable vector indicates a column-type mismatch and should
    not be silently papered over.
    """
    stripped = raw.strip().lstrip("[").rstrip("]")
    if not stripped:
        return []
    return [float(part) for part in stripped.split(",")]


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #
class PgVectorVectorStore:
    """Concrete ``VectorStore`` backed by Postgres + the ``vector`` extension.

    Constructed via ``build(cfg)``; operators never instantiate this
    class directly. The constructor takes only the DSN and table-schema
    name — the actual ``asyncpg`` pool is created lazily on first use,
    guarded by an ``asyncio.Lock`` so concurrent first-call requests
    don't race and create two pools.
    """

    def __init__(self, *, dsn: str, schema: str = _DEFAULT_SCHEMA) -> None:
        self._dsn = dsn
        # Schema + table name are interpolated into the SQL as identifiers;
        # since both come from trusted config (not user input) we format
        # them into the query string rather than binding (asyncpg cannot
        # bind identifiers anyway). Validation is deferred — a malformed
        # schema name will surface as a ``asyncpg.PostgresSyntaxError`` on
        # the first query, which is a clear enough failure mode for
        # operator-supplied config.
        self._schema = schema
        self._table = f'"{schema}".{_TABLE_NAME}'
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Pool + RLS helpers                                                 #
    # ------------------------------------------------------------------ #

    async def _pool_or_create(self) -> asyncpg.Pool:
        """Return the cached pool, creating it on first use.

        The ``asyncio.Lock`` guards the double-checked-locking pattern
        so two concurrent coroutines calling this method at startup
        don't both create pools (which would leak the loser). The
        inner ``if self._pool is not None`` check is needed because
        the first caller to acquire the lock will have already
        populated ``self._pool`` by the time the second caller gets
        in.
        """
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is not None:
                return self._pool
            # Local import: keeps the module importable even when
            # ``asyncpg`` is not installed. See module docstring.
            import asyncpg  # noqa: PLC0415

            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=_POOL_MIN_SIZE,
                max_size=_POOL_MAX_SIZE,
            )
            return self._pool

    @staticmethod
    async def _set_user_id(conn: asyncpg.Connection, user_id: UUID) -> None:
        """Engage RLS for the current transaction by setting ``app.user_id``.

        Uses ``set_config(..., is_local := true)`` so the setting is
        scoped to the current transaction and auto-cleared on COMMIT
        / ROLLBACK — this prevents leakage when the connection is
        returned to the pool and handed to a different tenant next.
        Design §14 / Req 4.5, 4.6, 8.5.
        """
        await conn.execute(
            "SELECT set_config('app.user_id', $1, true)",
            str(user_id),
        )

    # ------------------------------------------------------------------ #
    # VectorStore API                                                    #
    # ------------------------------------------------------------------ #

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12).

        Groups chunks by ``user_id`` so each group runs inside a single
        transaction with ``app.user_id`` set appropriately — a mixed
        batch therefore still engages RLS correctly for every row. In
        practice the indexer always passes one user's chunks at a time,
        so this is usually a single group, but the grouping keeps the
        contract correct if an upstream caller batches across users.
        """
        if not chunks:
            return

        # Group by user_id preserving order for deterministic tests.
        groups: dict[UUID, list[ChunkRecord]] = {}
        for c in chunks:
            groups.setdefault(c.user_id, []).append(c)

        sql = (
            f"INSERT INTO {self._table} "
            "(chunk_id, document_id, user_id, symbol, position, token_count, "
            " text, embedding, embedding_model, embedding_dim) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10) "
            "ON CONFLICT (chunk_id) DO UPDATE SET "
            "  text = EXCLUDED.text, "
            "  embedding = EXCLUDED.embedding, "
            "  embedding_model = EXCLUDED.embedding_model, "
            "  embedding_dim = EXCLUDED.embedding_dim, "
            "  position = EXCLUDED.position, "
            "  token_count = EXCLUDED.token_count"
        )

        pool = await self._pool_or_create()
        async with pool.acquire() as conn:
            for user_id, group in groups.items():
                async with conn.transaction():
                    await self._set_user_id(conn, user_id)
                    rows = [
                        (
                            c.chunk_id,
                            c.document_id,
                            c.user_id,
                            c.symbol,
                            c.position,
                            c.token_count,
                            c.text,
                            _vec_to_pg(c.embedding),
                            c.embedding_model,
                            c.embedding_dim,
                        )
                        for c in group
                    ]
                    await conn.executemany(sql, rows)

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Return up to ``k`` nearest neighbours under ``filter`` (Req 3.8).

        Uses cosine distance (``embedding <=> query``) and converts to
        a similarity score ``1 - distance`` so values are in [-1, 1]
        with higher = better. ``filter.min_score`` is pushed into the
        SQL so pgvector can short-circuit at scan time — but we also
        re-check in Python because the cast-and-subtract round-trip
        through the network can lose a few ULPs.
        """
        # Build the predicate + parameter list dynamically. Param $1 is
        # always the query vector; subsequent positions are appended as
        # filters are encountered so the SQL stays valid regardless of
        # which fields are set.
        params: list[Any] = [_vec_to_pg(query_vec)]
        predicates: list[str] = [
            "user_id = current_setting('app.user_id')::uuid",
        ]
        if filter.symbol is not None:
            params.append(filter.symbol)
            predicates.append(f"symbol = ${len(params)}")
        if filter.min_score is not None:
            # ``1 - (embedding <=> q) >= min_score``  ⇔
            # ``(embedding <=> q) <= 1 - min_score``  — the rewritten
            # form avoids evaluating the vector op twice.
            params.append(1.0 - filter.min_score)
            predicates.append(f"(embedding <=> $1::vector) <= ${len(params)}")
        params.append(k)
        k_param = f"${len(params)}"

        where_sql = " AND ".join(predicates)
        sql = (
            "SELECT chunk_id, document_id, user_id, symbol, position, "
            "       token_count, text, embedding::text AS embedding_text, "
            "       embedding_model, embedding_dim, "
            "       1 - (embedding <=> $1::vector) AS score "
            f"FROM {self._table} "
            f"WHERE {where_sql} "
            "ORDER BY embedding <=> $1::vector ASC "
            f"LIMIT {k_param}"
        )

        pool = await self._pool_or_create()
        async with pool.acquire() as conn, conn.transaction():
            await self._set_user_id(conn, filter.user_id)
            rows = await conn.fetch(sql, *params)

        hits: list[ChunkHit] = []
        for row in rows:
            score = float(row["score"])
            # Re-check the floor in Python — see the note above about
            # ULP drift through the SQL round-trip.
            if filter.min_score is not None and score < filter.min_score:
                continue
            record = ChunkRecord(
                chunk_id=str(row["chunk_id"]),
                document_id=row["document_id"],
                user_id=row["user_id"],
                symbol=row["symbol"],
                position=int(row["position"]),
                token_count=int(row["token_count"]),
                text=row["text"],
                embedding=_pg_to_vec(row["embedding_text"]),
                embedding_model=row["embedding_model"],
                embedding_dim=int(row["embedding_dim"]),
            )
            hits.append(ChunkHit(chunk=record, score=score))
        return hits

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; returns count deleted (used by memory.forget).

        Uses ``RETURNING chunk_id`` + ``len()`` rather than relying on
        ``conn.execute``'s string status tag so the count is a proper
        ``int`` without having to parse ``"DELETE N"``.
        """
        params: list[Any] = []
        predicates: list[str] = [
            "user_id = current_setting('app.user_id')::uuid",
        ]
        if filter.symbol is not None:
            params.append(filter.symbol)
            predicates.append(f"symbol = ${len(params)}")

        where_sql = " AND ".join(predicates)
        sql = (
            f"DELETE FROM {self._table} "
            f"WHERE {where_sql} "
            "RETURNING chunk_id"
        )

        pool = await self._pool_or_create()
        async with pool.acquire() as conn, conn.transaction():
            await self._set_user_id(conn, filter.user_id)
            rows = await conn.fetch(sql, *params)
        return len(rows)

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1)."""
        params: list[Any] = []
        predicates: list[str] = [
            "user_id = current_setting('app.user_id')::uuid",
        ]
        if filter.symbol is not None:
            params.append(filter.symbol)
            predicates.append(f"symbol = ${len(params)}")

        where_sql = " AND ".join(predicates)
        sql = (
            f"SELECT COUNT(*) AS n FROM {self._table} WHERE {where_sql}"
        )

        pool = await self._pool_or_create()
        async with pool.acquire() as conn, conn.transaction():
            await self._set_user_id(conn, filter.user_id)
            row = await conn.fetchrow(sql, *params)
        return int(row["n"]) if row is not None else 0


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
def build(cfg: dict[str, Any]) -> VectorStore:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the full ``research.vector_store`` block from
    ``config/settings.yaml`` (plus, when called directly from tests, a
    flat per-backend dict). DSN resolution priority, highest first:

    1. ``cfg["dsn"]`` — explicit override at the top of the block.
    2. ``cfg["pgvector"]["dsn"]`` — backend-scoped override.
    3. ``DATABASE_URL`` environment variable — the same value the
       existing ``backend-gateway`` reads; this is the common path
       described in design §8 / Req 8.5.

    If none of the three produce a value, raises ``KeyError`` with a
    message that names every place that was checked — operator typos
    are then self-diagnosing from the exception alone.

    Schema resolution reads ``cfg["pgvector"]["schema"]`` and defaults
    to ``public``; the schema name is interpolated into every SQL
    statement (asyncpg cannot bind identifiers) and so must come from
    trusted config, never user input.

    The ``asyncpg`` import and the pool creation are both deferred
    until the adapter's first query, not performed here — see the
    module docstring for why.
    """
    sub = cfg.get("pgvector") if isinstance(cfg.get("pgvector"), dict) else {}

    dsn = (
        cfg.get("dsn")
        or sub.get("dsn")
        or os.environ.get("DATABASE_URL")
    )
    if not dsn:
        raise KeyError(
            "pgvector adapter requires a DSN; checked "
            "cfg['dsn'], cfg['pgvector']['dsn'], and env DATABASE_URL "
            "— none were set.",
        )

    schema = sub.get("schema", _DEFAULT_SCHEMA)
    return PgVectorVectorStore(dsn=dsn, schema=schema)


__all__ = ["PgVectorVectorStore", "build"]
