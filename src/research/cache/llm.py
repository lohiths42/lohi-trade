"""LLM response cache — Redis get/set wrapper around ``LLMProvider.complete``.

Caches non-streamed completions on the key template

    research:llm:{provider}:{model}:{sha256(prompt)}:{sha256(context)}

(see :data:`src.research.constants.LLM_RESPONSE_CACHE_KEY_TEMPLATE`).
Default TTL 30 minutes per design §7.1. Streaming is **not** supported
by this module: callers that want a streamed response call
``llm.stream(...)`` directly and bypass the cache entirely.

Satisfies:
    - Req 5.8 — LLM response cache keyed on
      ``(provider, model, hash(prompt), hash(context))`` with a
      configurable TTL defaulting to 30 minutes, bypassed when
      streaming is requested.

Design references:
    - §3.11 (Caches)
    - §4.3 (Redis key schemas)

Why an explicit helper, not a wrapper class
-------------------------------------------
:class:`~src.research.providers.base.LLMProvider` is a ``Protocol`` with
**no** ``provider`` or ``model`` attribute — those only surface on the
returned :class:`Completion`. Wrapping the provider as an object would
force every adapter to grow extra attributes to make the cache key
derivable. The function-level helper takes ``provider`` and ``model``
as explicit kwargs so the cache does not dictate adapter internals.
Every shipped adapter already knows its registry name and model id
(they come from ``research.providers.llm.*`` config), so the caller
supplies them once per call site.

Prompt hash
-----------
``prompt_sha256`` is computed over a **canonical JSON serialisation**
of ``(messages, params)``:

* ``messages`` — a list of ``{"role", "content"}`` dicts, order
  preserved.
* ``params``   — the :class:`LLMParams` fields *that affect output
  determinism*. We include ``temperature``, ``max_tokens``, ``top_p``,
  ``stop``, and the ``extra`` escape-hatch verbatim; ``timeout_ms`` and
  ``stream`` are excluded because they do not change the model's
  output distribution.

Canonical JSON uses sorted keys and no whitespace so semantically
identical inputs produce identical digests.

Context hash
------------
``context`` is a caller-supplied string (e.g., the concatenation of
retrieved chunks fed into the prompt). It is hashed separately so two
calls sharing the same prompt but different retrieved context do not
collide. Defaulting to ``""`` lets callers skip this field for
context-free prompts; the empty-string SHA-256 is well-defined and
stable across runs.

Value shape
-----------
The cached :class:`Completion` is stored via
:meth:`Completion.model_dump_json` and reloaded via
:meth:`Completion.model_validate_json`, so any field addition to the
model surfaces as a decode failure and we fall through to a fresh
call.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.research.constants import LLM_RESPONSE_CACHE_KEY_TEMPLATE
from src.research.providers.base import (
    Completion,
    LLMParams,
    LLMProvider,
    Message,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


__all__ = ["cached_complete"]


logger = logging.getLogger(__name__)


# Default TTL per Req 5.8 / design §7.1 — 30 minutes in seconds.
_DEFAULT_TTL_SECONDS = 30 * 60


def _canonical_prompt_bytes(
    messages: list[Message], params: LLMParams
) -> bytes:
    """Return canonical UTF-8 bytes for ``(messages, params)`` hashing.

    Shape::

        {
          "messages": [{"role": "...", "content": "..."}, ...],
          "params":   {"temperature": ..., "max_tokens": ..., ...}
        }

    Only determinism-affecting ``params`` fields are included; see the
    module docstring for the rationale. ``sort_keys=True`` + no
    separators gives a stable serialisation across Python versions
    and process restarts.
    """
    msg_dicts = [
        {"role": m.role, "content": m.content} for m in messages
    ]

    # Determinism-affecting fields only. ``timeout_ms`` and ``stream``
    # are intentionally excluded (see module docstring).
    param_dict = {
        "temperature": params.temperature,
        "max_tokens": params.max_tokens,
        "top_p": params.top_p,
        "stop": params.stop,
        "extra": params.extra,
    }

    canonical = {"messages": msg_dicts, "params": param_dict}
    return json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _build_key(
    *, provider: str, model: str, prompt_sha256: str, context_sha256: str
) -> str:
    """Assemble the ``research:llm:...`` cache key from its components."""
    return LLM_RESPONSE_CACHE_KEY_TEMPLATE.format(
        provider=provider,
        model=model,
        prompt_sha256=prompt_sha256,
        context_sha256=context_sha256,
    )


def _decode_completion(raw: Any) -> Completion | None:
    """Decode a Redis payload into a :class:`Completion` or ``None`` on failure.

    Accepts both ``bytes`` and ``str`` payloads so clients with
    ``decode_responses=True`` and default-byte clients both work.
    Any Pydantic validation failure collapses to ``None`` so the caller
    treats it as a miss and rewrites the key.
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
        return Completion.model_validate_json(text)
    except ValidationError:
        return None


async def cached_complete(
    llm: LLMProvider,
    messages: list[Message],
    params: LLMParams,
    *,
    redis_client: "Redis | Any",
    provider: str,
    model: str,
    context: str = "",
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> Completion:
    """Redis-cached wrapper for :meth:`LLMProvider.complete`.

    The cache is keyed on ``(provider, model, sha256(prompt_canonical),
    sha256(context))`` with TTL ``ttl_seconds``. On a hit the cached
    :class:`Completion` is returned without invoking ``llm``. On a
    miss the inner provider is called once and the result is written
    back with ``SET ... EX ttl_seconds``.

    Streaming is **not** supported here. Callers that request
    ``params.stream=True`` (a hint — :meth:`LLMProvider.stream` ignores
    it and always streams) should call ``llm.stream(...)`` directly
    and bypass this function. We still honour the hint defensively:
    if ``params.stream`` is ``True`` we skip the cache and call
    ``llm.complete`` pass-through, matching the Req 5.8 rule "except
    when streaming is requested".

    Parameters
    ----------
    llm:
        The inner :class:`LLMProvider`. Only ``complete`` is used.
    messages:
        Chat messages; shape defined by :class:`Message`.
    params:
        Generation parameters; shape defined by :class:`LLMParams`.
    redis_client:
        Async Redis client (``redis.asyncio.Redis``-compatible).
    provider:
        Registry name of the provider (e.g. ``"nvidia_nim"``). Used
        verbatim in the cache key. Supplied by the caller because the
        :class:`LLMProvider` Protocol does not expose this field.
    model:
        Provider-side model identifier. Used verbatim in the cache
        key. Same rationale as ``provider``.
    context:
        Arbitrary caller-supplied context string (e.g. joined
        retrieved chunks). Defaults to empty string.
    ttl_seconds:
        Cache entry expiry. Default 1800 s (30 min) per Req 5.8.

    Returns
    -------
    Completion
        The Provider_Contract shape (Req 2.11).
    """
    if ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")

    # Streaming path bypasses the cache entirely (Req 5.8).
    if params.stream:
        return await llm.complete(messages, params)

    prompt_sha = _sha256_hex(_canonical_prompt_bytes(messages, params))
    context_sha = _sha256_hex(context.encode("utf-8"))
    key = _build_key(
        provider=provider,
        model=model,
        prompt_sha256=prompt_sha,
        context_sha256=context_sha,
    )

    # ---- Read-through --------------------------------------------------- #
    try:
        raw = await redis_client.get(key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning(
            "llm_cache.get failed for key=%s; treating as miss",
            key,
            exc_info=True,
        )
        raw = None

    if raw is not None:
        cached = _decode_completion(raw)
        if cached is not None:
            return cached
        logger.warning(
            "llm_cache.get: corrupt payload at key=%s; re-calling provider",
            key,
        )

    # ---- Miss: call provider and write back ----------------------------- #
    completion = await llm.complete(messages, params)

    try:
        payload = completion.model_dump_json()
    except (TypeError, ValueError):  # pragma: no cover - Completion is pure data
        logger.warning(
            "llm_cache.set: failed to serialise completion for key=%s; "
            "returning uncached result",
            key,
            exc_info=True,
        )
        return completion

    try:
        await redis_client.set(key, payload, ex=ttl_seconds)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning(
            "llm_cache.set failed for key=%s; returning uncached result",
            key,
            exc_info=True,
        )

    return completion
