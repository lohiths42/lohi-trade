"""LanceDB vector-store adapter — optional backend (Req 2.6, design §3.1).

This adapter implements the ``VectorStore`` protocol declared in
``src.research.providers.base`` against the `lancedb
<https://lancedb.github.io/lancedb/>`_ embedded columnar store.
LanceDB is a **profile-gated alternate** to the shipped defaults
(Chroma for ``Persona_Self_Hosted``, pgvector for
``Persona_Cloud_SaaS``) — enabled only when an operator explicitly
sets ``research.vector_store.backend: lancedb`` in
``config/settings.yaml``. Unlike Qdrant it runs in-process against a
local directory, so no extra container is needed.

The module is registered lazily via the
``"lancedb": "src.research.providers.vector_store.lancedb:build"``
entry in ``registry.py``, so **importing this file does not pull in
``lancedb``** — that heavyweight import only happens inside
``build()``. That keeps the registry importable on a bare install
(Task 1.6, Req 2.12) and lets every downstream test module
``from src.research.providers.vector_store import lancedb`` without
needing the package installed.

Defaults
--------
* ``path``       — ``data/research/lance`` (mirrors the
                   ``data/research/chroma`` default for the Chroma
                   adapter, design §7.1).
* Table         — ``research_chunks`` (single table; all
                   tenant/symbol scoping is applied through SQL ``WHERE``
                   predicates — see Namespacing below).
* Distance      — ``cosine`` via ``metric("cosine")`` on every
                   search. LanceDB's default is L2; we override
                   per-search so this adapter stays consistent with
                   the Chroma / pgvector / Qdrant backends and the
                   per-model similarity floors in
                   ``research.retrieval.similarity_floor``.

Async behaviour
---------------
LanceDB is a **synchronous** library (Lance format + on-disk
segments). Calling its methods directly from an ``async def`` blocks
the event loop for the duration of the call — which for a search over
tens of thousands of chunks is easily tens of milliseconds. We
therefore offload every call to the default executor via
``loop.run_in_executor(None, …)``, matching the Chroma adapter. The
table handle itself is cached on the instance so we don't re-open it
from disk on every call.

Lazy table creation
-------------------
LanceDB infers its schema from the first batch written to a table,
so the adapter cannot create the table at ``build()`` time — the
embedding dimensionality and column types come from
``ChunkRecord``s we haven't seen yet. The first ``upsert`` call
therefore creates the table with ``db.create_table(name, data=rows,
mode="create")``; subsequent calls open the existing table with
``db.open_table(name)``. An ``asyncio.Lock`` guards this so two
concurrent first-call coroutines don't race.

Upsert semantics (Req 3.12)
---------------------------
LanceDB's ``merge_insert`` gives us a proper upsert
(``when_matched_update_all`` + ``when_not_matched_insert_all``).
Older versions of the library didn't ship that method — we fall back
to a ``delete("chunk_id IN (...)")`` + ``add(rows)`` pair when it's
missing. Both paths preserve the idempotent-by-``chunk_id``
contract: re-upserting unchanged content produces the same row set
(Req 14.4).

Namespacing (Req 3.10, Req 4.5)
-------------------------------
Every operation scopes by ``filter.user_id`` so a forgotten filter
cannot leak across tenants. ``user_id`` is stored verbatim as a
column on every row and re-emitted in the SQL ``WHERE`` clause on
every read, write, and delete. LanceDB uses standard SQL predicates,
so the clause looks like
``user_id = 'uuid-str' AND symbol = 'TCS'``. The UUIDs are
stringified first so the SQL literal is always a plain string — no
vendor-specific UUID type to worry about. ``filter.document_type`` is
accepted by the protocol but **not** forwarded (same rationale as
Chroma — ``document_type`` lives on the parent document row, not on
the chunk).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..base import ChunkHit, ChunkRecord, RetrievalFilter, VectorStore

# Type-only imports so static checkers understand the annotations
# without forcing ``lancedb`` to be installed at import time.
if TYPE_CHECKING:  # pragma: no cover - typing only
    import lancedb


# Project defaults — see module docstring.
_DEFAULT_PATH = "data/research/lance"
_TABLE_NAME = "research_chunks"


# --------------------------------------------------------------------------- #
# SQL WHERE-clause builder                                                    #
# --------------------------------------------------------------------------- #
def _sql_quote(value: str) -> str:
    """Escape a string for a SQL literal by doubling embedded single quotes.

    LanceDB's filter DSL accepts standard SQL string literals. The
    ``user_id``/``symbol`` values we emit come from trusted upstream
    (UUIDs and already-validated symbol codes), but we still escape
    defensively so a malformed symbol like ``O'Neil`` produces valid
    SQL instead of a syntax error.
    """
    return value.replace("'", "''")


def _build_where(filter: RetrievalFilter) -> str:
    """Translate a ``RetrievalFilter`` into a LanceDB SQL ``WHERE`` clause.

    ``user_id`` is always included; ``symbol`` is added when set.
    Multiple predicates are joined with ``AND``. Returns a SQL
    fragment (no leading ``WHERE``) so the caller decides whether to
    prepend it — ``search().where(...)`` takes the fragment directly
    while ``count_rows(filter=...)`` takes the same shape.
    """
    predicates: list[str] = [
        f"user_id = '{_sql_quote(str(filter.user_id))}'",
    ]
    if filter.symbol is not None:
        predicates.append(f"symbol = '{_sql_quote(filter.symbol)}'")
    return " AND ".join(predicates)


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #
class LanceDbVectorStore:
    """Concrete ``VectorStore`` wrapping an embedded LanceDB database.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The constructor stores an already-opened
    ``lancedb`` ``DBConnection`` — the heavyweight ``lancedb`` import
    and ``connect()`` call happen exactly once inside ``build()`` so
    this class stays cheap to unit-test.

    Table creation is deferred until the first ``upsert`` so LanceDB
    can infer the schema (and in particular the embedding dimension)
    from the first batch of rows — see the module docstring for the
    rationale.
    """

    def __init__(self, *, db: lancedb.DBConnection) -> None:
        # Kept private so callers go through the ``VectorStore``
        # protocol methods; the underlying connection is not part of
        # the public contract.
        self._db = db
        self._table: Any = None  # lancedb.table.Table once opened
        self._table_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Row conversion helpers                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _chunk_to_row(c: ChunkRecord) -> dict[str, Any]:
        """Flatten a ``ChunkRecord`` into a LanceDB row dict.

        UUIDs are stringified so LanceDB stores them as plain strings
        (the SQL filter builder relies on this). The embedding is
        passed as ``list[float]``; LanceDB infers a fixed-size list
        column from the first batch.
        """
        return {
            "chunk_id": c.chunk_id,
            "document_id": str(c.document_id),
            "user_id": str(c.user_id),
            "symbol": c.symbol,
            "position": c.position,
            "token_count": c.token_count,
            "text": c.text,
            "embedding": list(c.embedding),
            "embedding_model": c.embedding_model,
            "embedding_dim": c.embedding_dim,
        }

    @staticmethod
    def _row_to_chunk(row: dict[str, Any]) -> ChunkRecord:
        """Rehydrate a ``ChunkRecord`` from a LanceDB row dict.

        Pydantic coerces string UUIDs back into ``UUID`` via its
        standard validator; integer fields are cast explicitly because
        LanceDB may return numpy scalars depending on version.
        """
        # Ignore LanceDB-added columns like ``_distance`` and
        # ``_relevance_score`` so Pydantic's ``extra="forbid"`` config
        # on ``ChunkRecord`` doesn't reject them.
        return ChunkRecord(
            chunk_id=str(row["chunk_id"]),
            document_id=row["document_id"],
            user_id=row["user_id"],
            symbol=row["symbol"],
            position=int(row["position"]),
            token_count=int(row["token_count"]),
            text=row["text"],
            embedding=[float(x) for x in row["embedding"]],
            embedding_model=row["embedding_model"],
            embedding_dim=int(row["embedding_dim"]),
        )

    # ------------------------------------------------------------------ #
    # Lazy table open/create                                             #
    # ------------------------------------------------------------------ #

    async def _ensure_table(self, seed_rows: list[dict[str, Any]] | None) -> Any:
        """Open or create the ``research_chunks`` table.

        * If the table already exists, open and cache it.
        * Otherwise — and only when ``seed_rows`` is provided — create
          it using those rows so LanceDB can infer the schema
          (including the fixed-size embedding column width). Callers
          that can't provide seed rows (reads before any write) get
          ``None`` back and are expected to treat it as an empty
          result.

        Uses the standard double-checked-locking pattern so two
        concurrent first-call coroutines don't both try to create the
        table and race.
        """
        if self._table is not None:
            return self._table

        async with self._table_lock:
            if self._table is not None:
                return self._table

            loop = asyncio.get_event_loop()

            def _open_or_create() -> Any:
                # ``table_names()`` is the cross-version way to check
                # existence without a try/except around ``open_table``
                # (which behaves differently across releases).
                if _TABLE_NAME in self._db.table_names():
                    return self._db.open_table(_TABLE_NAME)
                if seed_rows is None:
                    # Table doesn't exist yet and we have no rows to
                    # infer the schema from — caller must handle None.
                    return None
                return self._db.create_table(
                    _TABLE_NAME, data=seed_rows, mode="create",
                )

            table = await loop.run_in_executor(None, _open_or_create)
            if table is not None:
                self._table = table
            return table

    # ------------------------------------------------------------------ #
    # VectorStore API                                                    #
    # ------------------------------------------------------------------ #

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12).

        First call creates the table from the rows in ``chunks`` so
        LanceDB can infer its schema (see module docstring).
        Subsequent calls use ``merge_insert`` when available, or the
        ``delete + add`` fallback — both preserve the idempotent
        contract.
        """
        if not chunks:
            return

        rows = [self._chunk_to_row(c) for c in chunks]
        table = await self._ensure_table(seed_rows=rows)
        if table is None:  # pragma: no cover - defensive
            return

        loop = asyncio.get_event_loop()

        def _do_upsert() -> None:
            # Prefer ``merge_insert`` (true upsert). It returns a
            # builder that needs ``.execute(data)`` at the end.
            merge_insert = getattr(table, "merge_insert", None)
            if callable(merge_insert):
                (
                    merge_insert("chunk_id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(rows)
                )
                return
            # Fallback for older LanceDB: delete matching chunk_ids
            # then re-add. ``IN`` requires a SQL list literal — the
            # chunk_ids are trusted hex sha256 so quoting is
            # straightforward, but escape defensively anyway.
            ids_sql = ", ".join(
                f"'{_sql_quote(r['chunk_id'])}'" for r in rows
            )
            table.delete(f"chunk_id IN ({ids_sql})")
            table.add(rows)

        await loop.run_in_executor(None, _do_upsert)

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Return up to ``k`` nearest neighbours under ``filter`` (Req 3.8).

        Runs a cosine-distance search with a SQL ``WHERE`` filter.
        LanceDB returns a ``_distance`` column on each row; cosine
        distance lies in [0, 2] and we convert to a similarity
        ``score = 1 - distance`` so values match the other backends'
        "higher is better" convention.
        """
        # No seed rows — we only want to open an existing table; if it
        # doesn't exist there are no matches to return.
        table = await self._ensure_table(seed_rows=None)
        if table is None:
            return []

        where = _build_where(filter)
        loop = asyncio.get_event_loop()

        def _do_search() -> list[dict[str, Any]]:
            return (
                table.search(list(query_vec))
                .metric("cosine")
                .where(where)
                .limit(k)
                .to_list()
            )

        rows = await loop.run_in_executor(None, _do_search)

        hits: list[ChunkHit] = []
        for row in rows:
            distance = float(row.get("_distance", 0.0))
            # LanceDB cosine distance is ``1 - cosine_similarity`` so
            # ``score = 1 - distance`` yields the cosine similarity
            # directly, matching the pgvector / Chroma / Qdrant
            # adapters' [-1, 1] range with higher = better.
            score = 1.0 - distance
            if filter.min_score is not None and score < filter.min_score:
                continue
            record = self._row_to_chunk(row)
            hits.append(ChunkHit(chunk=record, score=score))
        return hits

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; returns count deleted (used by memory.forget).

        LanceDB's ``delete`` returns ``None``, so we count first (via
        ``count_rows(filter=…)`` when available) and then delete.
        Matches the Chroma adapter's approach.
        """
        table = await self._ensure_table(seed_rows=None)
        if table is None:
            return 0

        where = _build_where(filter)
        loop = asyncio.get_event_loop()

        def _count_and_delete() -> int:
            n = _count_rows(table, where)
            if n:
                table.delete(where)
            return n

        return await loop.run_in_executor(None, _count_and_delete)

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1).

        Uses ``count_rows(filter=…)`` when the installed LanceDB
        version exposes it; falls back to materialising the filtered
        rows and taking ``len`` otherwise. Older versions don't accept
        a ``filter`` kwarg — see ``_count_rows``.
        """
        table = await self._ensure_table(seed_rows=None)
        if table is None:
            return 0

        where = _build_where(filter)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _count_rows(table, where))


# --------------------------------------------------------------------------- #
# Cross-version count helper                                                  #
# --------------------------------------------------------------------------- #
def _count_rows(table: Any, where: str) -> int:
    """Count rows matching ``where`` across LanceDB versions.

    Newer releases accept ``table.count_rows(filter=...)`` which pushes
    the predicate into the scan. Older ones only accept a no-arg
    ``count_rows()`` (whole-table count) — for those we materialise
    the filtered rows and return ``len(...)``. Both paths avoid
    fetching the ``embedding`` column where we can, since it's the
    largest column by far.
    """
    try:
        return int(table.count_rows(filter=where))
    except TypeError:
        # Older API: no ``filter`` kwarg. Materialise filtered rows
        # without the embedding column for cheapness.
        query = table.search().where(where)
        select = getattr(query, "select", None)
        if callable(select):
            query = select(["chunk_id"])
        return len(query.to_list())


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
def build(cfg: dict[str, Any]) -> VectorStore:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the full ``research.vector_store`` block from
    ``config/settings.yaml`` (plus, when called directly from tests, a
    flat per-backend dict). Path resolution priority, highest first:

    1. ``cfg["path"]`` — explicit override at the top of the block.
    2. ``cfg["lancedb"]["path"]`` — backend-scoped override.
    3. Default ``data/research/lance`` — mirrors the Chroma adapter's
       on-disk default.

    The ``lancedb`` import and ``connect()`` call happen here, not at
    module import, so the registry stays importable on a bare install
    (Task 1.6, Req 2.12).
    """
    # Local import: see module docstring.
    import lancedb  # noqa: PLC0415

    sub = cfg.get("lancedb") if isinstance(cfg.get("lancedb"), dict) else {}
    path = cfg.get("path") or sub.get("path") or _DEFAULT_PATH

    db = lancedb.connect(path)
    return LanceDbVectorStore(db=db)


__all__ = ["LanceDbVectorStore", "build"]
