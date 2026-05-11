"""In-memory ``EmbeddingsProvider`` fake for Phase 6–12 tests (design §17.2).

Derives a deterministic ``dim``-length unit vector from
``hashlib.sha256(text).digest()`` so that:

* Re-embedding the same text returns bit-identical vectors — required by
  the idempotent-re-indexing property (Req 14.4, Task 12.x).
* Distinct texts produce distinct vectors with high probability — the
  SHA-256 digest seeds a ``random.Random`` stream, spreading the
  256-bit input across the full ``dim``-length vector.
* Every vector has unit L2 norm, so cosine similarity is well-defined
  and ``FakeVectorStore.similarity_search`` scores collapse to a plain
  dot product — the retrieval and memory-scoping properties can reason
  about ordering without floating-point norm guards.

Defaults to ``dim=384`` to match the production
``sentence-transformers/BAAI/bge-small-en-v1.5`` embedding dimension
(Req 2.5, Task 2.11) so the same ``VECTOR(dim)`` column schema works in
both production and test configurations.

Pure-Python (``hashlib`` + ``random`` + ``math``) — no numpy, no
optional deps, safe to import on a bare install.
"""

from __future__ import annotations

import hashlib
import math
import random

from src.research.providers.base import EmbeddingsProvider

__all__ = ["FakeEmbeddingsProvider"]


class FakeEmbeddingsProvider(EmbeddingsProvider):
    """Deterministic SHA-256-seeded ``EmbeddingsProvider`` implementation.

    Implements the ``EmbeddingsProvider`` Protocol from ``base.py`` —
    ``embed``, ``model_id``, ``dim`` — so that
    ``isinstance(FakeEmbeddingsProvider(), EmbeddingsProvider)`` holds
    (provider-swap invariance, Req 14.2).
    """

    def __init__(self, *, model: str = "fake-embeddings", dim: int = 384) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self._model = model
        self._dim = dim

    # ------------------------------------------------------------------ #
    # EmbeddingsProvider contract                                        #
    # ------------------------------------------------------------------ #

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-norm ``dim``-length vector per input text.

        Derivation (deterministic):

        1. ``seed = int.from_bytes(sha256(text).digest(), "big")`` — a
           256-bit integer uniquely determined by the text.
        2. ``rng = random.Random(seed)`` — Python's Mersenne-Twister
           seeded reproducibly; same text ⇒ same stream.
        3. Draw ``dim`` floats uniformly from ``[-1, 1]``.
        4. L2-normalise so cosine similarity = dot product. If every
           draw is zero (vanishingly unlikely but guarded anyway), fall
           back to a canonical unit vector ``[1, 0, …, 0]``.
        """
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest, "big")
            rng = random.Random(seed)
            vec = [rng.uniform(-1.0, 1.0) for _ in range(self._dim)]
            norm = math.sqrt(sum(x * x for x in vec))
            if norm == 0.0:
                # Degenerate: pick a canonical unit vector so downstream
                # cosine math stays well-defined.
                unit = [0.0] * self._dim
                unit[0] = 1.0
                out.append(unit)
            else:
                out.append([x / norm for x in vec])
        return out

    @property
    def model_id(self) -> str:
        """Stable identifier used in cache keys (design §3.11, Req 5.6)."""
        return self._model

    @property
    def dim(self) -> int:
        """Embedding dimensionality; wired into ``VECTOR(dim)`` (Req 2.14)."""
        return self._dim
