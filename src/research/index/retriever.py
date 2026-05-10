"""Hybrid BM25 + dense retriever (Req 3.8, Req 3.9, design §3.3).

Design responsibility
---------------------
Turn a user query into a ranked list of ``ChunkHit``\\s by fusing:

* **BM25** — pure-lexical, fast, catches exact-term matches that dense
  embeddings blur. Default backend is ``rank-bm25`` (design Decision
  Log #1) with a dependency-free TF-IDF fallback so the module imports
  on a bare install (see :class:`BM25Index`).
* **Dense search** — embed the query via the configured
  :class:`~src.research.providers.base.EmbeddingsProvider` and call
  ``VectorStore.similarity_search`` with the per-tenant
  :class:`~src.research.providers.base.RetrievalFilter`.

The two rankings are fused by **Reciprocal Rank Fusion** on
``1 / (1 + rank)`` — a standard RRF variant that is monotonically
decreasing in rank, bounded to ``(0, 1]``, and does not require
calibrated scores across strategies. Weights are configurable so
operators can bias toward one strategy per environment.

Why RRF here specifically? The spec asks for a
``bm25_weight * bm25_rank_score + dense_weight * dense_rank_score``
fusion where ``rank_score = 1 / (1 + rank)``. RRF is the natural
expression of that: it ignores absolute scores (which are model-
and corpus-dependent) and uses only ordering information, which is
what both strategies produce reliably.

Per-strategy ranks (``bm25_rank``, ``dense_rank``) are preserved on
every returned hit so downstream consumers (the run trace, the Judge,
the rerank pass in :mod:`.reranker`) can see which strategy surfaced
each chunk (design §3.3).

Request flow
~~~~~~~~~~~~

1. Embed the query with ``embeddings.embed([query])``.
2. Dense path: ``vector_store.similarity_search(q, filter=..., k=top_k)``.
3. BM25 path (if ``bm25_index`` is set): ``bm25_index.search(query, top_k, filter)``.
4. Fuse by RRF → sort descending by fused score → truncate to
   ``k or top_k``.

BM25 is skipped entirely when ``bm25_index is None`` — the cost of a
BM25 index is non-trivial for large corpora and Phase 6 operators may
start dense-only before adding the lexical index in Phase 8.

The BM25 backend (``rank-bm25`` vs TF-IDF fallback) is chosen **lazily
at first call** inside :class:`BM25Index`, not at import time — this
keeps the retriever importable on a bare install even before the
optional ``rank-bm25`` dependency is pulled in.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    EmbeddingsProvider,
    RetrievalFilter,
    VectorStore,
)

__all__ = ["BM25Index", "HybridRetriever"]


# --------------------------------------------------------------------------- #
# Tokenisation                                                                #
# --------------------------------------------------------------------------- #
#
# BM25 and TF-IDF both operate on token lists; the production adapters
# in Phase 8 may swap in a heavier tokeniser, but a plain lowercased
# ``\w+`` regex is good enough for the retrieval-layer unit/property
# tests and matches the default used by ``rank-bm25`` examples.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenise(text: str) -> list[str]:
    """Lowercase word-boundary tokenisation; stable across backends."""
    return _TOKEN_RE.findall(text.lower())


# --------------------------------------------------------------------------- #
# In-memory BM25 / TF-IDF index                                               #
# --------------------------------------------------------------------------- #


class BM25Index:
    """Minimal in-memory BM25 index with a TF-IDF fallback (design Decision #1).

    Two backends, chosen lazily at first ``search`` call:

    * ``rank-bm25`` — preferred (design Decision Log #1). Imported on
      demand so this module stays importable when the package is
      absent — the Phase 1 scaffolding ships without it by design.
    * pure-stdlib **TF-IDF** — fallback, uses :class:`collections.Counter`
      plus :func:`math.log` only. It is not a replacement for BM25 at
      scale, but it preserves the *ordering* signal well enough that
      the hybrid fusion still surfaces relevant chunks in tests and on
      operator laptops where ``rank-bm25`` may not yet be installed.

    The index keeps a per-chunk token list so filtering by
    :class:`RetrievalFilter` is O(n); that is fine at
    property-test / small-corpus scale. Phase 8 operators can swap this
    for a persistent BM25 index (tantivy, Whoosh) by implementing the
    same two-method surface — ``add`` + ``search``.

    Contract
    --------
    * :meth:`add` ingests ``list[ChunkRecord]``; incremental, not
      idempotent by chunk_id (callers typically rebuild the index when
      the corpus changes — ``rank-bm25`` has no in-place update).
    * :meth:`search` returns ``[(chunk, rank)]`` pairs where ``rank``
      is 1-based. The retriever converts rank to ``1 / (1 + rank)``.
    """

    def __init__(self) -> None:
        self._chunks: list[ChunkRecord] = []
        self._tokens: list[list[str]] = []
        # Lazy-resolved ``rank_bm25.BM25Okapi`` instance; ``None`` until
        # the first successful lazy import. Rebuilt from scratch on
        # every ``add`` call because ``rank-bm25`` is not incremental.
        self._bm25: Any | None = None
        # ``True`` once we've decided rank-bm25 is unavailable; avoids
        # re-attempting the import on every search call.
        self._rank_bm25_unavailable: bool = False

    # ------------------------------------------------------------------ #
    # Index maintenance                                                  #
    # ------------------------------------------------------------------ #

    def add(self, chunks: list[ChunkRecord]) -> None:
        """Append ``chunks`` to the index; invalidate any cached BM25 state.

        ``rank-bm25`` does not support incremental updates, so any
        previously-built ``BM25Okapi`` instance is dropped here and
        rebuilt on the next ``search`` call.
        """
        self._chunks.extend(chunks)
        self._tokens.extend(_tokenise(c.text) for c in chunks)
        self._bm25 = None  # Force rebuild on next search.

    # ------------------------------------------------------------------ #
    # Search                                                             #
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        k: int,
        filter: RetrievalFilter,
    ) -> list[tuple[ChunkRecord, int]]:
        """Return top-``k`` ``(chunk, rank)`` pairs matching ``filter``.

        ``rank`` is 1-based so the retriever can compute
        ``1 / (1 + rank)`` uniformly. Chunks that don't match
        ``filter.user_id`` (mandatory) or ``filter.symbol`` (optional)
        are excluded **before** ranking so corpus-level noise in other
        tenants cannot displace a genuine hit.
        """
        if k <= 0 or not self._chunks:
            return []

        query_tokens = _tokenise(query)
        if not query_tokens:
            return []

        # ---- Backend selection (lazy) ---------------------------------- #
        scores = self._score_with_rank_bm25(query_tokens)
        if scores is None:
            scores = self._score_with_tfidf(query_tokens)

        # ---- Filter + rank --------------------------------------------- #
        # Pair each chunk with its score, drop non-matching tenants,
        # and sort descending. Ties are broken by original index so
        # ordering is deterministic for property tests.
        candidates: list[tuple[float, int, ChunkRecord]] = []
        for idx, (chunk, score) in enumerate(zip(self._chunks, scores)):
            if not self._matches_filter(chunk, filter):
                continue
            candidates.append((score, idx, chunk))

        # Descending score, ascending idx for stable tie-break.
        candidates.sort(key=lambda t: (-t[0], t[1]))

        # Drop chunks whose relevance score is zero — they matched on
        # nothing. Under RRF the rank would still put them above
        # non-candidates, which is misleading.
        nonzero = [c for c in candidates if c[0] > 0.0]
        top = nonzero[:k]

        return [(chunk, rank) for rank, (_, _, chunk) in enumerate(top, start=1)]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _score_with_rank_bm25(
        self, query_tokens: list[str],
    ) -> list[float] | None:
        """Score the whole corpus with ``rank-bm25``, or ``None`` if unavailable.

        The import is attempted at most once — on failure we set
        ``_rank_bm25_unavailable`` and fall through to the TF-IDF
        scorer on every subsequent call.
        """
        if self._rank_bm25_unavailable:
            return None
        try:
            from rank_bm25 import BM25Okapi  # type: ignore[import-not-found]
        except ImportError:
            self._rank_bm25_unavailable = True
            return None

        if self._bm25 is None:
            # BM25Okapi requires at least one document with at least
            # one token — guard both to avoid cryptic ZeroDivisionError
            # from the library.
            if not self._tokens or not any(self._tokens):
                return None
            self._bm25 = BM25Okapi(self._tokens)

        # ``BM25Okapi.get_scores`` returns a numpy array; cast to list
        # so the retriever has no numpy dependency.
        return list(self._bm25.get_scores(query_tokens))

    def _score_with_tfidf(self, query_tokens: list[str]) -> list[float]:
        """Dependency-free TF-IDF fallback using :class:`Counter`.

        Computes the classic ``tf * idf`` score for each document:

        * ``tf``   — term frequency of the query token within the doc.
        * ``idf``  — ``log((N + 1) / (df + 1)) + 1`` with +1 smoothing
          so zero-df terms do not blow up to ``-inf`` and single-term
          corpora do not collapse to zero.

        The resulting score is summed over all query tokens. Good
        enough for ordering in small corpora — which is all the
        fallback is expected to handle.
        """
        n_docs = len(self._tokens)
        if n_docs == 0:
            return []

        # df[token] = number of docs containing token (at least once).
        df: Counter[str] = Counter()
        for tokens in self._tokens:
            for term in set(tokens):
                df[term] += 1

        # Pre-compute idf per query token so we don't recompute in the
        # inner loop. Smoothing keeps idf strictly positive.
        idf: dict[str, float] = {
            term: math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1.0
            for term in set(query_tokens)
        }

        scores: list[float] = []
        for tokens in self._tokens:
            tf = Counter(tokens)
            score = 0.0
            for term in query_tokens:
                score += tf.get(term, 0) * idf[term]
            scores.append(score)
        return scores

    @staticmethod
    def _matches_filter(chunk: ChunkRecord, filt: RetrievalFilter) -> bool:
        """Apply ``filter.user_id`` (mandatory) + ``filter.symbol`` (optional).

        ``document_type`` is not part of ``ChunkRecord`` (the real
        adapters join it from ``research_documents``), so we ignore
        that filter field here — matches the behaviour of
        :class:`~tests.research.fakes.vector_store.FakeVectorStore`.
        """
        if chunk.user_id != filt.user_id:
            return False
        if filt.symbol is not None and chunk.symbol != filt.symbol:
            return False
        return True


# --------------------------------------------------------------------------- #
# Hybrid retriever                                                            #
# --------------------------------------------------------------------------- #


class HybridRetriever:
    """BM25 + dense retrieval fused by reciprocal rank (Req 3.8, design §3.3).

    Construction
    ------------
    ``vector_store``  — any :class:`VectorStore` (Chroma, pgvector,
                        Qdrant, LanceDB, or the in-memory fake).
    ``embeddings``    — any :class:`EmbeddingsProvider`. Used once per
                        call to embed the query.
    ``bm25_index``    — optional :class:`BM25Index`. When ``None``, the
                        BM25 path is skipped entirely and the retriever
                        degrades to dense-only. That is a supported
                        Phase 6 configuration — Phase 8 adds the index.
    ``bm25_weight`` / ``dense_weight`` — fusion weights, default
                        ``0.4`` / ``0.6`` per design §7.1. Weights may
                        sum to anything; only the *relative* magnitude
                        matters for ordering.
    ``top_k``         — per-strategy fetch depth **and** default output
                        depth. The ``k`` kwarg on ``retrieve`` overrides
                        the output depth without changing the fetch
                        depth, so callers can ask for a small top-k
                        while still benefiting from a wide pre-fusion
                        candidate pool.
    """

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embeddings: EmbeddingsProvider,
        bm25_index: BM25Index | None = None,
        bm25_weight: float = 0.4,
        dense_weight: float = 0.6,
        top_k: int = 40,
    ) -> None:
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._bm25_index = bm25_index
        self._bm25_weight = bm25_weight
        self._dense_weight = dense_weight
        self._top_k = top_k

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def retrieve(
        self,
        query: str,
        filter: RetrievalFilter,
        *,
        k: int | None = None,
    ) -> list[ChunkHit]:
        """Return up to ``k or top_k`` fused, filtered ``ChunkHit``\\s.

        1. Embed ``query`` once.
        2. Dense search via ``vector_store.similarity_search`` with
           ``k=top_k`` (wide pre-fusion pool).
        3. BM25 search via ``bm25_index.search`` with ``k=top_k`` if an
           index was supplied; otherwise skip.
        4. Fuse: for every chunk surfaced by either strategy, compute
           ``score = bm25_weight * bm25_rrf + dense_weight * dense_rrf``
           where ``rrf = 1 / (1 + rank)`` and any missing strategy
           contributes zero.
        5. Preserve ``bm25_rank`` / ``dense_rank`` on each returned hit.
        6. Sort descending by fused score, truncate to ``k or top_k``.
        """
        limit = k if k is not None else self._top_k

        # Embed exactly once; query embeddings are not cached here —
        # Task 9.1 wires an explicit embedding cache layer.
        query_vec = (await self._embeddings.embed([query]))[0]

        # Dense candidates. ``top_k`` is the fetch depth, not the
        # output depth: the fusion step may promote a dense hit that
        # ranks poorly on its own but high on BM25.
        dense_hits = await self._vector_store.similarity_search(
            query_vec,
            filter=filter,
            k=self._top_k,
        )

        # BM25 candidates (optional). ``bm25_index is None`` means
        # "dense-only" — design §7.1 allows it explicitly.
        bm25_pairs: list[tuple[ChunkRecord, int]] = (
            self._bm25_index.search(query, self._top_k, filter)
            if self._bm25_index is not None
            else []
        )

        # ---- Fusion ---------------------------------------------------- #
        # Keyed by chunk_id so we can merge the two rankings. The value
        # holds: the ChunkRecord (always the same for a given id), the
        # BM25 rank (or None), and the dense rank (or None).
        fused: dict[str, dict[str, Any]] = {}

        for rank, (chunk, _explicit_rank) in enumerate(bm25_pairs, start=1):
            # ``_explicit_rank`` from BM25Index is already 1-based; we
            # keep the enumeration rank here for safety in case a
            # future backend returns unsorted pairs.
            fused[chunk.chunk_id] = {
                "chunk": chunk,
                "bm25_rank": rank,
                "dense_rank": None,
            }

        for rank, hit in enumerate(dense_hits, start=1):
            existing = fused.get(hit.chunk.chunk_id)
            if existing is None:
                fused[hit.chunk.chunk_id] = {
                    "chunk": hit.chunk,
                    "bm25_rank": None,
                    "dense_rank": rank,
                }
            else:
                existing["dense_rank"] = rank

        # Compute fused scores and materialise ``ChunkHit``\\s.
        results: list[ChunkHit] = []
        for entry in fused.values():
            bm25_rank = entry["bm25_rank"]
            dense_rank = entry["dense_rank"]
            bm25_rrf = 1.0 / (1.0 + bm25_rank) if bm25_rank is not None else 0.0
            dense_rrf = 1.0 / (1.0 + dense_rank) if dense_rank is not None else 0.0
            score = (
                self._bm25_weight * bm25_rrf
                + self._dense_weight * dense_rrf
            )
            results.append(
                ChunkHit(
                    chunk=entry["chunk"],
                    score=score,
                    bm25_rank=bm25_rank,
                    dense_rank=dense_rank,
                ),
            )

        # Stable ordering: primary by fused score desc, secondary by
        # chunk_id asc so Hypothesis-shrunk failures are reproducible.
        results.sort(key=lambda h: (-h.score, h.chunk.chunk_id))

        return results[:limit]
