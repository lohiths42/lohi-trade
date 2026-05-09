"""Chroma vector-store adapter (Req 2.6, Req 2.13, Req 3.10, design §3.1).

This is the **default self-hosted** ``VectorStore`` for Lohi-Research
(design §3.1 / §7.1 — ``research.vector_store.backend: chroma`` with
``path: data/research/chroma``). It is selected automatically for the
``Persona_Self_Hosted`` deployment profile when no external Postgres
with the ``vector`` extension is reachable (design §8, Req 2.13), and
runs **embedded in-process** with an on-disk persistence directory so
no extra container is required in the compose overlay (Req 7.2).

This module implements the ``VectorStore`` protocol declared in
``src.research.providers.base`` against the embedded ``chromadb``
runtime and nothing else. It is registered lazily by ``registry.py``
via the
``"chroma": "src.research.providers.vector_store.chroma:build"``
entry, so **importing this file does not pull in ``chromadb``** — that
heavyweight import only happens inside ``build()``. That keeps the
registry importable on a bare install (Task 1.6, Req 2.12) and lets
every downstream test module
``from src.research.providers.vector_store import chroma`` without
needing the package installed.

Defaults
--------
* ``path`` — ``data/research/chroma`` (design §7.1, Req 2.13).
* Collection name — ``research_chunks`` (single collection; all
  tenant/symbol scoping is applied through metadata filters — see the
  Namespacing section below).
* Distance metric — ``cosine`` (``hnsw:space = "cosine"``). Matches
  the pgvector adapter (Task 2.16) and the L2-normalised BGE vectors
  emitted by ``sentence_transformers.py`` so per-model similarity
  floors in ``research.retrieval.similarity_floor`` are comparable
  across backends.

Namespacing (Req 3.10, Req 4.5)
-------------------------------
Every ``VectorStore`` operation scopes by ``filter.user_id`` so a
forgotten filter cannot leak across tenants. The ``user_id`` is
stored verbatim on every chunk's metadata payload and re-emitted in
the Chroma ``where`` clause on every read, write, and delete. When
``filter.symbol`` is set it is AND-ed with ``user_id`` — Chroma
requires the explicit ``$and`` operator for multi-field filters.

``filter.document_type`` is accepted by the protocol but is **not**
forwarded to the Chroma ``where`` clause by this adapter:
``ChunkRecord`` only carries document-level context implicitly through
``document_id``, and ``document_type`` lives on the parent document
row (design §3.2), not on the chunk. A future task may copy
``document_type`` down to chunk metadata; until then the caller gets
a (possibly superset) result that document-type-aware call sites can
filter in Python.

Async behaviour
---------------
``chromadb`` is a **synchronous** library (SQLite + HNSW under the
hood). Calling its methods directly from an ``async def`` blocks the
event loop for the duration of the call — which for a ``query`` over
tens of thousands of chunks is easily tens of milliseconds. We
therefore offload every call to the default executor via
``loop.run_in_executor(None, …)`` so the orchestrator's other
coroutines (snapshot invalidations, partial emissions on
``research:partials``) stay responsive (design §3.4).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..base import ChunkHit, ChunkRecord, RetrievalFilter, VectorStore

# Type-only import so ``mypy`` understands the Collection annotations
# without forcing ``chromadb`` to be installed at import time.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from chromadb.api.models.Collection import Collection


# Project defaults — see module docstring and design §7.1.
_DEFAULT_PATH = "data/research/chroma"
_COLLECTION_NAME = "research_chunks"


# --------------------------------------------------------------------------- #
# Where-clause builder                                                        #
# --------------------------------------------------------------------------- #
def _build_where(filter: RetrievalFilter) -> dict[str, Any]:
    """Translate a ``RetrievalFilter`` into a Chroma ``where`` clause.

    Chroma accepts a flat ``{"key": "value"}`` dict when exactly one
    field is constrained, but **requires** the explicit ``$and``
    operator when multiple fields are constrained. We therefore build
    the list of single-field predicates first, then collapse:

    * one predicate  → ``{"user_id": "…"}``
    * many predicates → ``{"$and": [{"user_id": "…"}, {"symbol": "…"}]}``

    ``user_id`` is always included — dropping it would leak across
    tenants (Req 3.10, Req 4.5). ``symbol`` is added when set.
    ``document_type`` is intentionally **not** forwarded: see the
    module docstring for the rationale.
    """
    predicates: list[dict[str, Any]] = [{"user_id": str(filter.user_id)}]
    if filter.symbol is not None:
        predicates.append({"symbol": filter.symbol})

    if len(predicates) == 1:
        return predicates[0]
    return {"$and": predicates}


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #
class ChromaVectorStore:
    """Concrete ``VectorStore`` wrapping an embedded ``chromadb`` collection.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The constructor takes an already-opened Chroma
    ``Collection`` so the heavyweight ``PersistentClient`` + ``hnsw``
    initialisation happens exactly once inside ``build()`` and this
    class stays cheap to unit-test with a fake collection.
    """

    def __init__(self, *, collection: "Collection") -> None:
        # Kept private so callers go through the ``VectorStore``
        # protocol methods; the underlying Chroma ``Collection`` is
        # not part of the public contract.
        self._collection = collection

    # ------------------------------------------------------------------ #
    # VectorStore API                                                    #
    # ------------------------------------------------------------------ #

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12).

        Chroma's ``collection.upsert`` takes parallel arrays and is
        idempotent on ``ids``. The ``chunk_id`` field is derived
        deterministically upstream (``sha256(document_sha256 ||
        chunker_version || position)``, design §3.3), so re-ingesting
        unchanged content overwrites the same row rather than
        duplicating it (Req 14.4).
        """
        if not chunks:
            return

        ids = [str(c.chunk_id) for c in chunks]
        embeddings = [c.embedding for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {
                "user_id": str(c.user_id),
                "symbol": c.symbol,
                "document_id": str(c.document_id),
                "position": c.position,
                "token_count": c.token_count,
                "embedding_model": c.embedding_model,
                "embedding_dim": c.embedding_dim,
            }
            for c in chunks
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            ),
        )

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Return up to ``k`` nearest neighbours under ``filter`` (Req 3.8).

        Uses Chroma's cosine distance (configured at collection
        creation via ``hnsw:space = "cosine"``) and converts to a
        similarity score with ``score = 1 - distance`` so downstream
        similarity-floor comparisons (``research.retrieval.similarity_floor``,
        design §3.3, Req 16.24) operate on a "higher is better"
        quantity — matching the pgvector adapter and the per-model
        floors in ``config/settings.yaml``.

        When ``filter.min_score`` is set, hits with a score below the
        floor are dropped before being returned.
        """
        where = _build_where(filter)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[query_vec],
                n_results=k,
                where=where,
                include=["metadatas", "documents", "embeddings", "distances"],
            ),
        )

        # ``query_embeddings`` was a list of one, so every returned
        # array is a list-of-one-list. Index [0] into each to flatten.
        ids = (response.get("ids") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        documents = (response.get("documents") or [[]])[0]
        embeddings = (response.get("embeddings") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]

        hits: list[ChunkHit] = []
        for chunk_id, meta, text, embedding, distance in zip(
            ids, metadatas, documents, embeddings, distances
        ):
            # Cosine distance in Chroma is in [0, 2]; similarity = 1 - distance
            # lies in [-1, 1] with 1 being identical. Matches the pgvector
            # adapter's ``1 - (embedding <=> query)`` expression.
            score = 1.0 - float(distance)
            if filter.min_score is not None and score < filter.min_score:
                continue

            record = ChunkRecord(
                chunk_id=str(chunk_id),
                document_id=meta["document_id"],
                user_id=meta["user_id"],
                symbol=meta["symbol"],
                position=int(meta["position"]),
                token_count=int(meta["token_count"]),
                text=text,
                embedding=list(embedding),
                embedding_model=meta["embedding_model"],
                embedding_dim=int(meta["embedding_dim"]),
            )
            hits.append(ChunkHit(chunk=record, score=score))

        return hits

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; returns count deleted (used by memory.forget).

        Chroma's ``collection.delete(where=…)`` returns ``None``, so
        we first ``get(where=…, include=[])`` to count the matching
        IDs and then run the delete. ``include=[]`` skips fetching
        metadatas / documents / embeddings so the count is cheap.
        ``collection.count()`` on its own does **not** accept a
        ``where`` clause and would return the full collection size,
        which is why we go via ``get`` instead.
        """
        where = _build_where(filter)

        loop = asyncio.get_event_loop()

        def _delete_and_count() -> int:
            matching = self._collection.get(where=where, include=[])
            ids = matching.get("ids") or []
            count = len(ids)
            if count:
                self._collection.delete(where=where)
            return count

        return await loop.run_in_executor(None, _delete_and_count)

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1).

        ``collection.count()`` in Chroma does not accept a ``where``
        clause (it returns the full collection size). We therefore
        use ``get(where=…, include=[])`` to fetch only the matching
        IDs and return their length. ``include=[]`` is important:
        without it Chroma also fetches metadatas / documents /
        embeddings, which would be wasteful for a simple count.
        """
        where = _build_where(filter)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._collection.get(where=where, include=[]),
        )
        return len(response.get("ids") or [])


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
def build(cfg: dict[str, Any]) -> VectorStore:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the full ``research.vector_store`` block from
    ``config/settings.yaml`` — it contains ``backend`` plus per-backend
    sub-dicts (``chroma``, ``pgvector``, …). This adapter reads its
    own sub-block; all keys are optional:

    * ``path`` — on-disk persistence directory; defaults to
                 ``data/research/chroma`` (design §7.1, Req 2.13).

    The heavyweight ``chromadb`` import lives inside this function so
    the module can be imported (and registered lazily) on a bare
    install that does not have ``chromadb`` available (Task 1.6,
    Req 2.12).
    """
    # Local import: keeps the module importable even when ``chromadb``
    # is not installed. ``build()`` is the only code path that
    # actually needs the package, and the registry only calls
    # ``build()`` once the operator has selected this backend in
    # ``config/settings.yaml``.
    import chromadb  # noqa: PLC0415

    # The registry forwards the full ``research.vector_store`` block,
    # so look for the ``chroma`` sub-dict first and fall back to the
    # top level so simpler cfg shapes (used in tests) also work.
    sub = cfg.get("chroma") if isinstance(cfg.get("chroma"), dict) else cfg
    path = sub.get("path", _DEFAULT_PATH)

    client = chromadb.PersistentClient(path=path)
    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return ChromaVectorStore(collection=collection)


__all__ = ["ChromaVectorStore", "build"]
