"""Embedding cache — Redis get/set wrapper around an ``EmbeddingsProvider``.

Wraps any :class:`~src.research.providers.base.EmbeddingsProvider` with a
Redis-backed lookup on the key template

    research:emb:{embedding_model}:{sha256(text)}

(see :data:`src.research.constants.EMBEDDING_CACHE_KEY_TEMPLATE`). On a
hit, the cached vector is returned without calling the inner provider;
on a miss, only the *miss* subset of ``texts`` is passed to
``inner.embed``, and each resulting vector is written back under its
own key with TTL ``ttl_seconds`` (default 7 days per design §7.1).

Satisfies:
    - Req 5.6 — embedding cache with configurable default TTL of 7 days.

Design references:
    - §3.11 (Caches)
    - §4.3 (Redis key schemas)

Key shape
---------
``research:emb:{embedding_model}:{sha256(text)}``

* ``embedding_model`` is the inner provider's :attr:`~.EmbeddingsProvider.model_id`
  — switching models yields a disjoint keyspace so cached vectors of
  the old model can never surface under the new model.
* ``sha256(text)`` is the hex digest of ``text.encode("utf-8")``.

Stored value is a JSON-encoded ``list[float]``. JSON round-trips cleanly
for finite floats and is dependency-free; we deliberately do not use
Python ``pickle`` (unsafe cross-process) or ``msgpack`` (extra dep) at
this layer.

Batching
--------
``embed`` is called once upstream with a batch of ``texts``. The cache
preserves input order when returning results: every input position is
either filled from Redis or from a single batched call to
``inner.embed(missing_texts)``. Duplicate inputs within a single batch
are coalesced — we only call the inner provider once per unique hash —
and the resulting vector is written to Redis once.

Concurrency
-----------
There is no distributed lock around miss → fetch → set. Two workers
racing on the same ``(model, text)`` will both compute the embedding
and both write; the second write wins (overwrite), producing the same
value. No correctness issue; an avoidable but small cost.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from src.research.constants import EMBEDDING_CACHE_KEY_TEMPLATE
from src.research.providers.base import EmbeddingsProvider

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = ["EmbeddingCache"]


logger = logging.getLogger(__name__)


# Default TTL from design §7.1 / Req 5.6 — 7 days in seconds.
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def _sha256_hex(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8.

    The exact shape used in ``EMBEDDING_CACHE_KEY_TEMPLATE`` (design
    §3.11 / §4.3). Centralised so the key derivation and any future
    debug tooling stay in lockstep.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Redis-backed cache in front of any :class:`EmbeddingsProvider`.

    Structurally conforms to the :class:`EmbeddingsProvider` Protocol
    (design §3.1) — same ``embed`` signature, same ``model_id`` and
    ``dim`` properties — so it is a drop-in replacement for the inner
    provider. Call sites register an ``EmbeddingCache`` instance
    wherever they would have registered the raw provider and get
    transparent caching.

    Parameters
    ----------
    inner:
        The underlying provider. ``model_id`` and ``dim`` are delegated
        to it; ``embed`` is wrapped.
    redis_client:
        An async Redis client exposing ``get``/``set`` with ``ex=``.
        Typed loosely so tests can inject stubs without depending on
        :mod:`redis.asyncio`.
    ttl_seconds:
        Key expiry in seconds. Default 7 days per Req 5.6 / design §7.1.
        Must be positive.

    """

    def __init__(
        self,
        *,
        inner: EmbeddingsProvider,
        redis_client: Redis | Any,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        self._inner = inner
        self._redis = redis_client
        self._ttl = ttl_seconds

    # ------------------------------------------------------------------ #
    # EmbeddingsProvider protocol                                        #
    # ------------------------------------------------------------------ #

    @property
    def model_id(self) -> str:
        """Delegate to inner. Cache-key namespacing uses this value."""
        return self._inner.model_id

    @property
    def dim(self) -> int:
        """Delegate to inner. Cached vectors always match this length."""
        return self._inner.dim

    # ------------------------------------------------------------------ #
    # Cached embed                                                       #
    # ------------------------------------------------------------------ #

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` with read-through Redis caching.

        1. For each input, compute ``sha256(text)`` and the full Redis
           key. Issue ``GET`` per key (no pipelining at this layer —
           batches are small; Phase 8 operators can add an ``MGET``
           optimisation without changing this signature).
        2. Hits are decoded from JSON into ``list[float]`` and placed
           at the corresponding output index.
        3. Misses are batched into a single call to ``inner.embed``
           preserving their original order.
        4. Each newly-computed vector is written back with
           ``SET ... EX ttl_seconds`` and placed at its output index.

        Duplicate texts within ``texts`` are coalesced: we only
        compute the embedding once and reuse the result for every
        matching position.

        Returns
        -------
        list[list[float]]
            One vector per input, in input order. Length equals
            ``len(texts)``; every inner list has length ``self.dim``.

        """
        if not texts:
            return []

        model_id = self._inner.model_id

        # Pre-compute keys once so the GET and SET loops share them.
        hashes = [_sha256_hex(t) for t in texts]
        keys = [
            EMBEDDING_CACHE_KEY_TEMPLATE.format(
                embedding_model=model_id, text_sha256=h,
            )
            for h in hashes
        ]

        # Output slots, filled either from cache or from ``inner.embed``.
        out: list[list[float] | None] = [None] * len(texts)

        # ``miss_indices[hash]`` -> list of output positions sharing that
        # hash. Using a dict coalesces duplicates so each unique miss
        # text is sent to the inner provider exactly once.
        miss_positions: dict[str, list[int]] = {}
        miss_texts_by_hash: dict[str, str] = {}

        # ---- Pass 1: read-through ------------------------------------- #
        for idx, (text, h, key) in enumerate(zip(texts, hashes, keys)):
            try:
                raw = await self._redis.get(key)
            except Exception:  # noqa: BLE001 - cache is best-effort
                # Treat any Redis error as a miss; the caller still
                # gets a correct answer, just without the speedup.
                logger.warning(
                    "embedding_cache.get failed for key=%s; treating as miss",
                    key,
                    exc_info=True,
                )
                raw = None

            if raw is not None:
                vector = _decode_vector(raw)
                if vector is not None and len(vector) == self._inner.dim:
                    out[idx] = vector
                    continue
                # Malformed payload: treat as miss and let the rewrite
                # overwrite the bad key.
                logger.warning(
                    "embedding_cache.get: corrupt payload at key=%s; re-embedding",
                    key,
                )

            # Record the miss. Coalesce duplicate texts by hash so the
            # inner provider sees each unique text at most once.
            miss_positions.setdefault(h, []).append(idx)
            miss_texts_by_hash[h] = text

        # ---- Pass 2: batched miss fetch ------------------------------- #
        if miss_texts_by_hash:
            # Deterministic order (hash order) so property tests on the
            # cache observe stable behaviour when duplicates are present.
            ordered_hashes = list(miss_texts_by_hash.keys())
            ordered_texts = [miss_texts_by_hash[h] for h in ordered_hashes]

            vectors = await self._inner.embed(ordered_texts)
            if len(vectors) != len(ordered_texts):
                # Defensive: every shipped adapter returns 1:1. If a
                # future adapter violates this we fail loudly rather
                # than silently mis-caching.
                raise RuntimeError(
                    "inner embeddings provider returned "
                    f"{len(vectors)} vectors for {len(ordered_texts)} texts",
                )

            # ---- Pass 3: write-back + fan-out to shared positions ----- #
            for h, vector in zip(ordered_hashes, vectors):
                payload = json.dumps(vector)
                key = EMBEDDING_CACHE_KEY_TEMPLATE.format(
                    embedding_model=model_id, text_sha256=h,
                )
                try:
                    await self._redis.set(key, payload, ex=self._ttl)
                except Exception:  # noqa: BLE001 - cache is best-effort
                    logger.warning(
                        "embedding_cache.set failed for key=%s; continuing",
                        key,
                        exc_info=True,
                    )
                for pos in miss_positions[h]:
                    out[pos] = vector

        # Every slot must be filled now. ``None`` at this point is a bug.
        for idx, v in enumerate(out):
            if v is None:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"embedding_cache: unfilled output slot at index {idx}",
                )

        # mypy: the None check above narrows the element type.
        return [v for v in out if v is not None]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _decode_vector(raw: Any) -> list[float] | None:
    """Decode a Redis payload into ``list[float]`` or ``None`` on failure.

    Accepts both ``bytes`` (default :mod:`redis.asyncio` behaviour) and
    ``str`` (``decode_responses=True`` clients). Returns ``None`` for
    any payload that is not a JSON list of numbers, so the caller can
    treat it as a miss and overwrite.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(raw, str):
        text = raw
    else:
        return None

    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return None

    if not isinstance(decoded, list):
        return None
    # Accept ints-as-floats; ``list[float]`` tolerates numeric promotion.
    try:
        return [float(x) for x in decoded]
    except (TypeError, ValueError):
        return None
