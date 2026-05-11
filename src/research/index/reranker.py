"""Cross-encoder reranker over ``HybridRetriever`` output (Req 3.9, design §3.3).

Why a second-stage reranker?
----------------------------
``HybridRetriever`` (BM25 + dense) gives a wide, reasonably-ranked
candidate pool. A cross-encoder — which scores ``(query, candidate)``
pairs jointly rather than independently — reorders that pool with
substantially higher precision at the top-k, which is what the
Sub_Agent actually consumes (design §3.3, Req 3.9).

Default model: ``BAAI/bge-reranker-base`` (design Decision Log #2).
Default state: **disabled**, because the model weights are ~280 MB and
loading them eagerly would blow the 16 GB RAM budget on the offline
reference configuration (Req 15.5). Operators flip
``research.providers.reranker.enabled: true`` when they want it.

Lazy imports
------------
``sentence_transformers`` (which transitively imports ``torch``) is
imported **inside** :meth:`CrossEncoderReranker._ensure_loaded`, not at
module scope. That keeps this module importable on a bare install and
avoids paying the torch-import cost for every caller that only wants
the retriever.

Async + thread-pool
-------------------
:class:`sentence_transformers.CrossEncoder` is a synchronous CPU (or
CUDA-blocking) operation; calling it directly from an async request
handler would stall the event loop. :meth:`rerank` therefore runs
``.predict`` inside :func:`asyncio.to_thread` so the Orchestrator's
``asyncio.gather`` of parallel Sub_Agents is not pinned by a single
rerank call.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.research.providers.base import ChunkHit

__all__ = ["CrossEncoderReranker"]


class CrossEncoderReranker:
    """Optional second-stage reranker over :class:`ChunkHit` lists.

    Parameters
    ----------
    model_id
        HuggingFace model identifier. Default
        ``BAAI/bge-reranker-base`` per design Decision Log #2.
    enabled
        Master switch. When ``False`` (default), :meth:`rerank` is a
        cheap ``hits[:top_k]`` and never touches ``sentence_transformers``
        or ``torch`` — critical for the offline configuration where
        the reranker weights are optional (design §7.1).

    """

    def __init__(
        self,
        *,
        model_id: str = "BAAI/bge-reranker-base",
        enabled: bool = False,
    ) -> None:
        self._model_id = model_id
        self._enabled = enabled
        # Loaded on first ``rerank`` call when ``enabled=True``; stays
        # ``None`` forever when disabled so importing this module
        # never pulls ``sentence_transformers``/``torch`` into memory.
        self._model: Any | None = None
        # Guards concurrent first-call loads so we don't load the
        # model twice from two parallel Sub_Agent requests.
        self._load_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        """Expose the enabled flag for run-trace / health endpoint use."""
        return self._enabled

    @property
    def model_id(self) -> str:
        """Exposed for the run trace and ``/research/health`` output."""
        return self._model_id

    async def rerank(
        self,
        query: str,
        hits: list[ChunkHit],
        *,
        top_k: int,
    ) -> list[ChunkHit]:
        """Re-order ``hits`` by cross-encoder score and truncate to ``top_k``.

        Fast paths
        ----------
        * ``enabled=False``           → ``hits[:top_k]`` unchanged (no
          model load, no torch import).
        * ``hits == []``              → ``[]`` — nothing to score.
        * ``top_k <= 0``              → ``[]``.

        Slow path (enabled + non-empty)
        -------------------------------
        1. Ensure the cross-encoder is loaded (lazy, once per process).
        2. Run ``.predict([(query, hit.chunk.text), ...])`` in a
           worker thread via :func:`asyncio.to_thread` so the event
           loop stays responsive.
        3. Sort descending by rerank score.
        4. Stamp ``rerank_rank`` (1-based) on each hit via Pydantic
           :meth:`model_copy` — we never mutate the input list.
        5. Truncate to ``top_k``.
        """
        if not self._enabled:
            # Honour ``top_k`` even in the no-op path so callers can
            # rely on the output size contract.
            return hits[:top_k] if top_k >= 0 else list(hits)

        if not hits or top_k <= 0:
            return []

        model = await self._ensure_loaded()

        # Build ``(query, text)`` pairs once; the list ordering is
        # preserved so scores[i] corresponds to hits[i].
        pairs = [(query, hit.chunk.text) for hit in hits]

        # ``CrossEncoder.predict`` is blocking (numpy + torch on CPU
        # or CUDA). Offload to the default thread pool to avoid
        # stalling the event loop.
        scores = await asyncio.to_thread(model.predict, pairs)

        # Zip + sort. Cast scores to float explicitly — ``.predict``
        # can return numpy floats which compare fine but serialise
        # awkwardly through Pydantic.
        scored = sorted(
            zip(hits, (float(s) for s in scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )

        # Stamp the 1-based rerank rank and replace the fused score
        # with the cross-encoder score so downstream consumers see
        # the rerank ordering reflected in ``ChunkHit.score`` too.
        reranked: list[ChunkHit] = []
        for rank, (hit, ce_score) in enumerate(scored[:top_k], start=1):
            reranked.append(
                hit.model_copy(
                    update={
                        "score": ce_score,
                        "rerank_rank": rank,
                    },
                ),
            )
        return reranked

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    async def _ensure_loaded(self) -> Any:
        """Load :class:`sentence_transformers.CrossEncoder` lazily, once.

        The import is inside this method (not at module scope) so
        that:

        * Importing :mod:`src.research.index.reranker` on a bare
          install succeeds even when ``sentence_transformers`` /
          ``torch`` are not present — the retriever path never needs
          them.
        * A missing dependency surfaces as a descriptive
          :class:`ImportError` **at first rerank call**, alongside a
          hint to install the optional extras, rather than breaking
          imports on every code path.

        The lock serialises the first-call load so two parallel
        Sub_Agent requests don't each trigger a 280 MB model download.
        Subsequent calls hit the fast path without acquiring the lock.
        """
        if self._model is not None:
            return self._model

        async with self._load_lock:
            # Re-check under the lock — another coroutine may have
            # finished loading while we waited.
            if self._model is not None:
                return self._model

            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError(
                    "CrossEncoderReranker(enabled=True) requires the "
                    "'sentence-transformers' package (and its 'torch' "
                    "dependency). Install with "
                    "`pip install sentence-transformers torch` or set "
                    "research.providers.reranker.enabled: false.",
                ) from exc

            # Model construction itself is blocking I/O (HuggingFace
            # download + weight load) — push it off the event loop.
            self._model = await asyncio.to_thread(CrossEncoder, self._model_id)
            return self._model
