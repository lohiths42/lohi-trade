"""In-memory ``VectorStore`` fake for Phase 6–12 tests (design §17.2).

A simple list-backed implementation of the ``VectorStore`` Protocol from
``src/research/providers/base.py``. Used by:

* retrieval correctness tests (Req 3.8 / Task 6.x, Req 14.1 citation
  integrity),
* memory-scoping property (Req 14.3): two distinct users must never see
  each other's rows,
* idempotent re-indexing property (Req 14.4): re-upserting an unchanged
  ``chunk_id`` is a true upsert, not a duplicate insert.

Design notes
------------
* Backed by ``list[ChunkRecord]`` — no index structure, O(n) per query.
  That is intentional: property tests use tiny corpora, and an index
  would obscure the correctness invariants the tests are checking.
* ``upsert`` is idempotent by ``chunk_id`` (Req 3.12): it removes any
  existing row with the same id before appending the new one.
* Every read path filters on ``user_id`` first (Req 3.10, Req 4.5);
  there is no code path that skips the ``user_id`` scope, so memory
  scoping is guaranteed at the fake-backend layer too.
* Cosine similarity is computed explicitly and guarded against
  zero-norm vectors so that synthetic inputs emitted by Hypothesis
  cannot crash the store.
"""

from __future__ import annotations

import math

from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    RetrievalFilter,
    VectorStore,
)

__all__ = ["FakeVectorStore"]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity with zero-norm guard.

    Returns 0.0 when either vector has zero norm — not a realistic
    embedding, but synthetic Hypothesis inputs can produce them and we
    prefer a neutral score over a ``ZeroDivisionError``.
    """
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _matches_filter(chunk: ChunkRecord, filt: RetrievalFilter) -> bool:
    """Apply the retrieval filter predicate to a single chunk.

    ``user_id`` is mandatory (Req 4.5). ``symbol`` narrows further when
    set. ``document_type`` and ``min_score`` are handled by callers:
    ``document_type`` is not part of ``ChunkRecord`` (the real adapters
    join it from ``research_documents`` — see design §3.2, §3.3), so the
    fake intentionally ignores it; ``min_score`` is applied post-scoring
    in ``similarity_search``.
    """
    if chunk.user_id != filt.user_id:
        return False
    if filt.symbol is not None and chunk.symbol != filt.symbol:
        return False
    return True


class FakeVectorStore(VectorStore):
    """In-memory list-backed ``VectorStore`` for property tests.

    ``isinstance(FakeVectorStore(), VectorStore)`` holds because the
    Protocol is ``runtime_checkable`` in ``base.py``.
    """

    def __init__(self) -> None:
        self._chunks: list[ChunkRecord] = []

    # ------------------------------------------------------------------ #
    # VectorStore contract                                               #
    # ------------------------------------------------------------------ #

    async def upsert(self, chunks: list[ChunkRecord]) -> None:
        """Insert or update ``chunks``; idempotent by ``chunk_id`` (Req 3.12).

        For each incoming chunk, any existing row with the same
        ``chunk_id`` is removed first. This mirrors the behaviour the
        real pgvector / Chroma / Qdrant adapters are required to
        provide by the re-index idempotence property (Req 14.4).
        """
        for chunk in chunks:
            self._chunks = [c for c in self._chunks if c.chunk_id != chunk.chunk_id]
            self._chunks.append(chunk)

    async def similarity_search(
        self,
        query_vec: list[float],
        *,
        filter: RetrievalFilter,
        k: int,
    ) -> list[ChunkHit]:
        """Top-``k`` cosine nearest neighbours under ``filter`` (Req 3.8).

        1. Filter rows by ``user_id`` (mandatory) and ``symbol`` (if set).
        2. Score every surviving row with cosine similarity; zero-norm
           vectors score 0.0.
        3. Sort descending by score, take the top ``k``.
        4. Drop any hit below ``filter.min_score`` if set (design §3.3,
           Req 16.24).
        """
        scored: list[tuple[float, ChunkRecord]] = []
        for chunk in self._chunks:
            if not _matches_filter(chunk, filter):
                continue
            scored.append((_cosine(query_vec, chunk.embedding), chunk))

        scored.sort(key=lambda sc: sc[0], reverse=True)
        top = scored[:k] if k >= 0 else scored

        hits: list[ChunkHit] = []
        for score, chunk in top:
            if filter.min_score is not None and score < filter.min_score:
                continue
            hits.append(ChunkHit(chunk=chunk, score=score))
        return hits

    async def delete_by_filter(self, filter: RetrievalFilter) -> int:
        """Delete matching rows; return count deleted."""
        kept: list[ChunkRecord] = []
        deleted = 0
        for chunk in self._chunks:
            if _matches_filter(chunk, filter):
                deleted += 1
            else:
                kept.append(chunk)
        self._chunks = kept
        return deleted

    async def count(self, filter: RetrievalFilter) -> int:
        """Count matching rows; used by the health endpoint (design §5.1)."""
        return sum(1 for c in self._chunks if _matches_filter(c, filter))
