"""Qdrant vector-store adapter — optional backend (Req 2.6, design §3.1).

This adapter implements the ``VectorStore`` protocol declared in
``src.research.providers.base`` against the `qdrant-client
<https://github.com/qdrant/qdrant-client>`_ async API. Qdrant is a
**profile-gated alternate** to the shipped defaults (Chroma for
``Persona_Self_Hosted``, pgvector for ``Persona_Cloud_SaaS``) — enabled
only when an operator explicitly sets
``research.vector_store.backend: qdrant`` in
``config/settings.yaml``. The matching container in the compose overlay
(Task 18.2) is likewise gated behind the ``qdrant`` docker-compose
profile.

The module is registered lazily via the
``"qdrant": "src.research.providers.vector_store.qdrant:build"`` entry
in ``registry.py``, so **importing this file does not pull in
``qdrant-client``** — that heavyweight import only happens inside
``build()``. That keeps the registry importable on a bare install
(Task 1.6, Req 2.12) and lets every downstream test module
``from src.research.providers.vector_store import qdrant`` without
needing the package installed.

Defaults
--------
* ``url``        — ``http://localhost:6333`` (matches the Qdrant
                   default REST port and the compose overlay in
                   Task 18.2).
* ``api_key``    — optional; forwarded to the client when set.
* Collection    — ``research_chunks`` (single collection; all
                   tenant/symbol scoping is applied through payload
                   filters, mirroring the Chroma adapter).
* Distance      — ``COSINE``. Matches the Chroma and pgvector
                   adapters and the L2-normalised BGE vectors emitted
                   by ``sentence_transformers.py`` so per-model
                   similarity floors in
                   ``research.retrieval.similarity_floor`` are
                   comparable across backends.

Lazy collection creation
------------------------
Qdrant requires the vector **size** to be declared up-front when the
collection is created, but the active embeddings provider is chosen
independently of the vector-store backend, so the adapter does not
know the dimension at ``build()`` time. We therefore defer creation
until the first ``upsert`` call — at that point the payload carries
``len(chunks[0].embedding)`` which we use as the collection's vector
size. An ``asyncio.Lock`` guards the double-checked create so two
concurrent first-call coroutines don't race and both try to create
the collection.

ID format
---------
Qdrant only accepts point IDs that are either unsigned integers or
**UUID strings** — not arbitrary strings. Our ``ChunkRecord.chunk_id``
is a hex SHA-256 (design §3.3), which is neither, so we derive a
deterministic v5 UUID from it via
``uuid.uuid5(uuid.NAMESPACE_OID, chunk_id)``. Because ``uuid5`` is
pure (same input → same output), re-upserting the same chunk_id
produces the same point ID and the ``upsert`` call stays idempotent
(Req 3.12, Req 14.4). The original ``chunk_id`` is also stored in the
payload so it round-trips unchanged through
``similarity_search``.

Namespacing (Req 3.10, Req 4.5)
-------------------------------
Every operation scopes by ``filter.user_id`` so a forgotten filter
cannot leak across tenants. ``user_id`` is stored verbatim on every
point's payload and re-emitted in the Qdrant ``Filter.must`` list on
every read, write, and delete. When ``filter.symbol`` is set it is
AND-ed with ``user_id``. ``filter.document_type`` is accepted by the
protocol but **not** forwarded to the filter (the chunk payload
doesn't carry ``document_type`` — see the Chroma adapter docstring
for the full rationale).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING, Any

from ..base import ChunkHit, ChunkRecord, RetrievalFilter, VectorStore

# Type-only imports so static checkers understand the annotations
# without forcing ``qdrant-client`` to be installed at import time.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from qdrant_client import AsyncQdrantClient


# Project defaults — see module docstring.
_DEFAULT_URL = "http://localhost:6333"
_COLLECTION_NAME = "research_chunks"


# --------------------------------------------------------------------------- #
# ID helper                                                                   #
# --------------------------------------------------------------------------- #
def _point_id(chunk_id: str) -> str:
    """Derive a Qdrant-acceptable UUID string from a SHA-256 ``chunk_id``.

    Qdrant rejects arbitrary strings as point IDs — they must be unsigned
    integers or UUIDs. ``uuid.uuid5`` is deterministic (same namespace +
    name → same UUID), so the same ``chunk_id`` always maps to the same
    point ID and ``upsert`` stays idempotent (Req 3.12).
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #
class QdrantVectorStore:
    """Concrete ``VectorStore`` wrapping an ``AsyncQdrantClient``.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The constructor stores an already-created
    ``AsyncQdrantClient`` — the heavyweight ``qdrant-client`` import
    and client construction happen exactly once inside ``build()`` so
    this class stays cheap to unit-test with a fake client.

    Collection creation is deferred until the first ``upsert`` so the
    vector size can be read from ``chunks[0].embedding`` — see the
    module docstring for the rationale.
    """

    def __init__(self, *, client: AsyncQdrantClient) -> None:
        # Kept private so callers go through the ``VectorStore``
        # protocol methods; the underlying client is not part of the
        # public contract.
        self._client = client
        self._collection_ready = False
        self._collection_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lazy collection creation                                           #
    # ------------------------------------------------------------------ #

    async def _ensure_collection(self, vector_size: int) -> None:
        """Create the ``research_chunks`` collection if it doesn't exist.

        Uses the standard double-checked-locking pattern so two
        concurrent first-call coroutines don't both try to create the
        collection and race. The outer check avoids taking the lock on
        the hot path once the collection exists.
        """
        if self._collection_ready:
            return
        async with self._collection_lock:
            if self._collection_ready:
                return
            # Local import: see module docstring.
            from qdrant_client import models as qmodels  # noqa: PLC0415

            # ``collection_exists`` is idempotent and cheap — prefer it
            # over a try/except around ``create_collection`` so we
            # don't paper over unrelated server-side errors.
            exists = await self._client.collection_exists(_COLLECTION_NAME)
            if not exists:
                await self._client.create_collection(
                    collection_name=_COLLECTION_NAME,
                    vectors_config=qmodels.VectorParams(
                        size=vector_size,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
            self._collection_ready = True

    # ------------------------------------------------------------------ #
    # Filter builder                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_filter(filter: RetrievalFilter) -> Any:
        """Translate a ``RetrievalFilter`` into a Qdrant ``Filter``.

        ``user_id`` is always included; ``symbol`` is added when set.
        Returns ``None`` is never useful here — we always constrain by
        ``user_id`` (Req 3.10, Req 4.5) — so the caller always gets a
        non-empty ``must`` list.
        """
        # Local import: keeps the module importable without
        # ``qdrant-client``. All filter construction only runs from
        # methods that already ran after ``build()``.
        from qdrant_client import models as qmodels  # noqa: PLC0415

        must: list[Any] = [
            qmodels.FieldCondition(
                key="user_id",
                match=qmodels.MatchValue(value=str(filter.user_id)),
            ),
        ]
        if filter.symbol is not None:
            must.append(
                qmodels.FieldCondition(
                    key="symbol",
                    match=qmodels.MatchValue(value=filter.symbol),
                ),
            )
        return qmodels.Filter(must=must)

    # ------------------------------------------------------------------ #
    # VectorStore API                                                    #
    # ------------------------------------------------------------------ #

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12).

        First call to this method creates the collection sized from
        ``len(chunks[0].embedding)`` — see module docstring. The
        deterministic ``uuid5`` mapping from ``chunk_id`` keeps the
        operation idempotent: re-upserting the same chunk overwrites
        the same point instead of duplicating it.
        """
        if not chunks:
            return

        await self._ensure_collection(vector_size=len(chunks[0].embedding))

        # Local import: see module docstring.
        from qdrant_client import models as qmodels  # noqa: PLC0415

        points = [
            qmodels.PointStruct(
                id=_point_id(c.chunk_id),
                vector=list(c.embedding),
                payload={
                    # Store ``chunk_id`` verbatim so it round-trips
                    # through ``similarity_search`` — the point ID
                    # itself is a derived UUID, not the sha256.
                    "chunk_id": c.chunk_id,
                    "document_id": str(c.document_id),
                    "user_id": str(c.user_id),
                    "symbol": c.symbol,
                    "position": c.position,
                    "token_count": c.token_count,
                    "text": c.text,
                    "embedding_model": c.embedding_model,
                    "embedding_dim": c.embedding_dim,
                },
            )
            for c in chunks
        ]
        await self._client.upsert(
            collection_name=_COLLECTION_NAME,
            points=points,
        )

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Return up to ``k`` nearest neighbours under ``filter`` (Req 3.8).

        Uses Qdrant's cosine similarity (configured at collection
        creation) directly — Qdrant returns a similarity score in
        [-1, 1] with higher = better, so no inversion is needed.
        Matches the pgvector and Chroma adapters' "higher is better"
        convention.

        ``filter.min_score`` is forwarded to Qdrant via ``score_threshold``
        so the server can short-circuit at scan time; we also
        re-check in Python as a belt-and-braces guard against
        floating-point drift.
        """
        q_filter = self._build_filter(filter)

        # The collection may not exist yet if ``upsert`` was never
        # called — in that case Qdrant raises. We don't pre-create here
        # because we don't know the vector size until an upsert, and
        # returning an empty list silently would mask configuration
        # errors. Let the error propagate.
        response = await self._client.search(
            collection_name=_COLLECTION_NAME,
            query_vector=list(query_vec),
            query_filter=q_filter,
            limit=k,
            score_threshold=filter.min_score,
            with_payload=True,
            with_vectors=True,
        )

        hits: list[ChunkHit] = []
        for scored_point in response:
            payload = scored_point.payload or {}
            score = float(scored_point.score)
            # Belt-and-braces: Qdrant already honoured
            # ``score_threshold`` but network round-trips can lose ULPs.
            if filter.min_score is not None and score < filter.min_score:
                continue

            # ``vector`` may be a list, numpy array, or nested dict
            # depending on client version — coerce to list[float].
            vec = scored_point.vector
            if isinstance(vec, dict):  # named-vector mode (unused here)
                vec = next(iter(vec.values()))
            embedding = [float(x) for x in (vec or [])]

            record = ChunkRecord(
                chunk_id=str(payload["chunk_id"]),
                document_id=payload["document_id"],
                user_id=payload["user_id"],
                symbol=payload["symbol"],
                position=int(payload["position"]),
                token_count=int(payload["token_count"]),
                text=payload["text"],
                embedding=embedding,
                embedding_model=payload["embedding_model"],
                embedding_dim=int(payload["embedding_dim"]),
            )
            hits.append(ChunkHit(chunk=record, score=score))
        return hits

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; returns count deleted (used by memory.forget).

        Qdrant's ``delete`` returns an ``UpdateResult`` that does not
        carry a count of affected points, so we count first (via the
        same filter) and then delete. This gives an accurate return
        value at the cost of a second round-trip; matches the Chroma
        adapter's approach.
        """
        q_filter = self._build_filter(filter)

        # Local import: see module docstring.
        from qdrant_client import models as qmodels  # noqa: PLC0415

        n = await self.count(filter)
        if n == 0:
            return 0
        await self._client.delete(
            collection_name=_COLLECTION_NAME,
            points_selector=qmodels.FilterSelector(filter=q_filter),
        )
        return n

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1).

        Uses Qdrant's ``count`` endpoint with ``exact=True`` so the
        health endpoint surfaces a truthful number rather than an
        approximate one. For collections that don't yet exist (the
        first health probe before any ingest), Qdrant raises — we
        treat that as zero so the health endpoint can report "backend
        reachable, collection empty" instead of failing outright.
        """
        q_filter = self._build_filter(filter)
        try:
            response = await self._client.count(
                collection_name=_COLLECTION_NAME,
                count_filter=q_filter,
                exact=True,
            )
        except Exception:
            # Collection doesn't exist yet (first run before any
            # ``upsert``). Any other transport/auth error will resurface
            # on the next ``upsert`` or ``similarity_search`` call where
            # it matters more.
            return 0
        return int(response.count)


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
def build(cfg: dict[str, Any]) -> VectorStore:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the full ``research.vector_store`` block from
    ``config/settings.yaml`` (plus, when called directly from tests, a
    flat per-backend dict). URL resolution priority, highest first:

    1. ``cfg["url"]`` — explicit override at the top of the block.
    2. ``cfg["qdrant"]["url"]`` — backend-scoped override.
    3. ``QDRANT_URL`` environment variable.
    4. Default ``http://localhost:6333`` — matches the Qdrant default
       REST port and the compose overlay in Task 18.2.

    ``api_key`` resolution follows the same priority ladder against
    ``cfg["api_key"]`` / ``cfg["qdrant"]["api_key"]`` / ``QDRANT_API_KEY``
    and is optional (embedded Qdrant does not require auth).

    The ``qdrant-client`` import and client construction happen here,
    not at module import, so the registry stays importable on a bare
    install (Task 1.6, Req 2.12).
    """
    # Local import: see module docstring.
    from qdrant_client import AsyncQdrantClient  # noqa: PLC0415

    sub = cfg.get("qdrant") if isinstance(cfg.get("qdrant"), dict) else {}

    url = (
        cfg.get("url")
        or sub.get("url")
        or os.environ.get("QDRANT_URL")
        or _DEFAULT_URL
    )
    api_key = (
        cfg.get("api_key")
        or sub.get("api_key")
        or os.environ.get("QDRANT_API_KEY")
    )

    client = AsyncQdrantClient(url=url, api_key=api_key)
    return QdrantVectorStore(client=client)


__all__ = ["QdrantVectorStore", "build"]
