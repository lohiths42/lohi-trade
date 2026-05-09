"""Retrieval cache — Redis get/set wrapper around ``HybridRetriever.retrieve``.

Caches the output of
:meth:`src.research.index.retriever.HybridRetriever.retrieve` on the
key template

    research:ret:{symbol}:{query_template_hash}:{sha256(sorted_doc_hashes)}

(see :data:`src.research.constants.RETRIEVAL_CACHE_KEY_TEMPLATE`).
Default TTL 5 minutes per design §7.1.

Satisfies:
    - Req 5.7 — retrieval cache keyed on
      ``(symbol, query_template, sorted_doc_hashes)``, configurable TTL
      defaulting to 5 minutes.

Design references:
    - §3.11 (Caches)
    - §4.3 (Redis key schemas)

Key anatomy
-----------
* ``symbol`` — ticker scope already carried on every
  :class:`~src.research.providers.base.RetrievalFilter`. The cache is
  symbol-scoped rather than user-scoped because retrieval results for
  the same symbol/query/doc-set are identical across tenants; per-
  tenant isolation is enforced by ``RetrievalFilter.user_id`` at the
  underlying vector store (Req 3.10).
* ``query_template_hash`` — supplied by the caller. It represents the
  **rendered-prompt-family** the query belongs to, not the free-text
  query itself. Prompts v1 produce a bounded set of templates; the
  caller hashes the template id (or equivalent) once and passes it in.
  We do **not** derive it from the query string because two calls to
  the same template with different symbol substitutions should share a
  cache key prefix.
* ``sorted_doc_hashes_sha256`` — ``sha256`` of the comma-joined sorted
  document hashes that participate in retrieval. Caller-supplied so
  that when a symbol's corpus changes (new filing lands, old doc
  deleted) the key automatically differs — the cache is *invalidated
  implicitly* without any explicit ``DEL`` call. This is the contract
  from design §3.11.

Value shape
-----------
JSON list of
:meth:`src.research.providers.base.ChunkHit.model_dump` outputs, decoded
back via :meth:`ChunkHit.model_validate`. Pydantic v2's JSON mode
handles the ``UUID`` and numeric-float serialisation we need.

This helper is a **function** rather than a class because the retriever
itself is stateless across calls and the caller already holds both the
``HybridRetriever`` and the Redis client.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.research.constants import RETRIEVAL_CACHE_KEY_TEMPLATE
from src.research.index.retriever import HybridRetriever
from src.research.providers.base import ChunkHit, RetrievalFilter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = ["cached_retrieve", "compute_sorted_doc_hashes_sha256"]


logger = logging.getLogger(__name__)


# Default TTL per Req 5.7 / design §7.1 — 5 minutes in seconds.
_DEFAULT_TTL_SECONDS = 300


def compute_sorted_doc_hashes_sha256(sorted_doc_hashes: list[str]) -> str:
    """Return the SHA-256 hex digest of the sorted, comma-joined hashes.

    The exact transformation used to build the ``sorted_doc_hashes_sha256``
    field of :data:`RETRIEVAL_CACHE_KEY_TEMPLATE` (design §3.11). The
    caller may pass the hashes in any order — we sort here so callers
    don't have to repeat the invariant. Duplicates are preserved so the
    digest reflects the *exact* input (sorting plus de-dup would make
    otherwise-distinct inputs collide).

    Exposed publicly so callers that need to compute the same value
    ahead of time (e.g., for logging or snapshot-invalidation logic)
    share one canonical implementation.
    """
    joined = ",".join(sorted(sorted_doc_hashes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _build_key(
    *, symbol: str, query_template_hash: str, sorted_doc_hashes: list[str]
) -> str:
    """Assemble the ``research:ret:...`` cache key from caller inputs."""
    return RETRIEVAL_CACHE_KEY_TEMPLATE.format(
        symbol=symbol,
        query_template_hash=query_template_hash,
        sorted_doc_hashes_sha256=compute_sorted_doc_hashes_sha256(
            sorted_doc_hashes
        ),
    )


def _decode_hits(raw: Any) -> list[ChunkHit] | None:
    """Decode a Redis payload into ``list[ChunkHit]`` or ``None`` on failure.

    ``None`` is interpreted by the caller as "treat as miss and
    overwrite". We validate through Pydantic so any schema drift in
    :class:`ChunkHit` surfaces as a miss rather than a silent load of
    stale-shaped data.
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

    out: list[ChunkHit] = []
    for entry in decoded:
        try:
            out.append(ChunkHit.model_validate(entry))
        except ValidationError:
            # Any individual bad entry invalidates the cached list —
            # otherwise we'd return a partial result shorter than the
            # one the underlying retriever would produce.
            return None
    return out


async def cached_retrieve(
    retriever: HybridRetriever,
    query: str,
    filter: RetrievalFilter,
    *,
    redis_client: "Redis | Any",
    query_template_hash: str,
    sorted_doc_hashes: list[str],
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    k: int | None = None,
) -> list[ChunkHit]:
    """Redis-cached wrapper for :meth:`HybridRetriever.retrieve`.

    On a hit, returns the cached ``list[ChunkHit]`` without touching the
    retriever, the vector store, or the embeddings provider. On a miss,
    delegates to ``retriever.retrieve(query, filter, k=k)`` and writes
    the result back with TTL ``ttl_seconds``.

    The cache is scoped by ``symbol`` — which must be present on
    ``filter`` — so cross-symbol reuse is structurally impossible. If
    ``filter.symbol`` is ``None`` the cache is **bypassed** (we don't
    have a stable symbol scope to key on); the retriever is called
    directly and the result is not written back. This matches the
    spec's intent: the retrieval cache exists for symbol-scoped panel
    queries, not for cross-corpus exploration.

    Parameters
    ----------
    retriever:
        The hybrid retriever to wrap. Structural protocol — any object
        exposing ``retrieve(query, filter, *, k=...)`` works, so test
        fakes can stand in.
    query:
        Free-text query. Not part of the cache key — the caller
        commits to a ``query_template_hash`` that characterises the
        prompt family instead. If two calls share template + symbol +
        doc-set they share a cache key even if the surface query
        differs (expected behaviour: the template is the invariant,
        symbol substitution is the varying part).
    filter:
        Retrieval filter; must carry ``user_id`` (mandatory) and
        ``symbol`` (required to use the cache).
    redis_client:
        Async Redis client (``redis.asyncio.Redis``-compatible).
    query_template_hash:
        Caller-supplied hash of the rendered prompt template; see
        module docstring.
    sorted_doc_hashes:
        Document hashes of the docs participating in retrieval.
        The function sorts them internally — caller can pass any order.
    ttl_seconds:
        Cache entry expiry. Default 300 s (5 min) per Req 5.7.
    k:
        Forwarded to ``retriever.retrieve``. Does not participate in
        the cache key: callers that ask for different ``k``s against
        the same symbol/template/docs will share an entry. The Phase 8
        retriever returns rank-ordered hits so a larger ``k`` is a
        prefix of a smaller ``k`` — but note the returned list is
        truncated to the ``k`` of the *first* request to land, which
        is a known, acceptable simplification for the cache layer.

    Returns
    -------
    list[ChunkHit]
        Hits as produced by :meth:`HybridRetriever.retrieve`.
    """
    if ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")

    # Symbol-less calls bypass the cache entirely (see docstring).
    if filter.symbol is None:
        return await retriever.retrieve(query, filter, k=k)

    key = _build_key(
        symbol=filter.symbol,
        query_template_hash=query_template_hash,
        sorted_doc_hashes=sorted_doc_hashes,
    )

    # ---- Read-through --------------------------------------------------- #
    try:
        raw = await redis_client.get(key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning(
            "retrieval_cache.get failed for key=%s; treating as miss",
            key,
            exc_info=True,
        )
        raw = None

    if raw is not None:
        cached = _decode_hits(raw)
        if cached is not None:
            return cached
        logger.warning(
            "retrieval_cache.get: corrupt payload at key=%s; re-retrieving",
            key,
        )

    # ---- Miss: compute and write back ----------------------------------- #
    hits = await retriever.retrieve(query, filter, k=k)

    try:
        # ``mode='json'`` coerces ``UUID`` → str and is the only shape
        # ``ChunkHit.model_validate`` can reconstruct reliably on read.
        payload = json.dumps([h.model_dump(mode="json") for h in hits])
    except (TypeError, ValueError):
        logger.warning(
            "retrieval_cache.set: failed to serialise hits for key=%s; "
            "returning uncached result",
            key,
            exc_info=True,
        )
        return hits

    try:
        await redis_client.set(key, payload, ex=ttl_seconds)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning(
            "retrieval_cache.set failed for key=%s; returning uncached result",
            key,
            exc_info=True,
        )

    return hits
