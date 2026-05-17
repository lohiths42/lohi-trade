"""Ollama embeddings adapter (Req 2.5, Req 7.5, design §3.1).

Ollama is the **default offline embeddings provider** for Lohi-Research
when the operator prefers a locally-served model over the bundled
``sentence-transformers`` path (design §3.1, §17). It runs locally on
``http://localhost:11434`` by default and exposes a batched embeddings
endpoint at ``POST /api/embed`` with body
``{"model": "<model>", "input": ["text1", ...]}`` and response
``{"embeddings": [[...], ...], "model": "..."}``.

The **older** single-text endpoint ``POST /api/embeddings`` with body
``{"model": ..., "prompt": "..."}`` still works on current Ollama
builds but takes a single string at a time; since
``EmbeddingsProvider.embed`` accepts a ``list[str]`` this adapter uses
the newer batched ``/api/embed`` endpoint — one HTTP round trip per
batch instead of one per text. On an Ollama version that predates
``/api/embed`` the caller will get a 404, which is acceptable: the
gateway error-mapping layer in Task 16.4 normalises the response.

This module implements the ``EmbeddingsProvider`` protocol declared in
``src.research.providers.base`` against Ollama and nothing else. It is
registered lazily by ``registry.py`` via the
``"ollama": "src.research.providers.embeddings.ollama:build"`` entry,
so importing this file does **not** require Ollama to be running and
does not trigger network I/O (Req 2.12).

Offline default
---------------
Per Req 7.5, Lohi-Research must be able to run fully offline. When the
operator wires this adapter in they typically pair it with a local
embeddings model that Ollama can serve from disk. The documented
default here is ``nomic-embed-text`` — a widely-available 768-dim
embedding model that is well-represented in the Ollama library. The
``sentence-transformers`` adapter (Task 2.11, Req 2.5) remains the
zero-config default; operators who prefer Ollama embeddings override
by flipping ``research.providers.embeddings.provider`` to ``ollama``.

Contract highlights
-------------------
* ``embed`` — POST ``/api/embed`` with ``{"model": …, "input": texts}``.
  Returns one ``list[float]`` per input in the same order as ``texts``
  (Ollama preserves order: there is no ``index`` field in the response
  and the ``embeddings`` array aligns with ``input`` positionally).
* ``model_id`` — the configured model string.
* ``dim`` — returns ``cfg["dim"]`` when the operator pinned it up-
  front (recommended for ``VECTOR(dim)`` column provisioning, Req
  2.14); otherwise raises ``RuntimeError`` until ``embed()`` has been
  called at least once, at which point the cached length of the first
  returned vector is reused. This keeps the property synchronous
  (``EmbeddingsProvider.dim`` is a plain ``@property``, not an async
  coroutine).
* 401/403 → ``ProviderAuthError(provider="ollama", model=…,
  error_code="PROVIDER_AUTH_FAILED")`` for consistency with every
  other adapter. Ollama itself does not authenticate, but a reverse
  proxy in front of it may (design §5.3, Req 2.10).
* Other transport failures bubble up as ``httpx`` errors; the gateway
  error-mapping layer (Task 16.4) normalises them.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..base import EmbeddingsProvider
from ..errors import ProviderAuthError

# Ollama's local daemon listens on 11434 by default (design §3.1, §16.2).
_DEFAULT_BASE_URL = "http://localhost:11434"

# Widely-available 768-dim local embedding model. Operators can override
# via cfg; the sentence_transformers adapter remains the zero-config
# default for Lohi-Research.
_DEFAULT_MODEL = "nomic-embed-text"

# Local inference with a small embedding model is sub-second on CPU,
# but a cold model pull can take longer; 30s is the same default the
# other two embeddings adapters use so the three are interchangeable
# from a timeout perspective.
_DEFAULT_TIMEOUT_SECONDS = 30.0

_PROVIDER_NAME = "ollama"


class OllamaEmbeddings:
    """Concrete ``EmbeddingsProvider`` hitting local Ollama ``/api/embed``.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The only mutable state is the optional cached
    ``_dim`` captured from the first ``embed`` response; everything
    else is immutable after construction so a single instance is safe
    to share across agents (design §3.5).
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
        dim: int | None,
    ) -> None:
        self._model = model
        # Strip a single trailing slash so concatenation below is
        # predictable regardless of how the operator spells the URL.
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # ``_dim`` is populated either from cfg (preferred — callers
        # provisioning ``VECTOR(dim)`` must know the width before they
        # ever call ``embed``) or lazily from the first successful
        # response. ``dim`` the property raises ``RuntimeError`` until
        # one of the two has happened.
        self._dim: int | None = dim

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self) -> dict[str, str]:
        """Request headers used for ``embed``.

        Ollama does not require authentication (it runs locally), so
        no ``Authorization`` header is sent. We still negotiate
        content types so a reverse proxy that enforces them sees a
        well-formed request.
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _timeout(self) -> httpx.Timeout:
        """Fixed per-call timeout.

        Embeddings have no per-call ``LLMParams`` to draw ``timeout_ms``
        from, so the factory picks one at construction time and it
        applies uniformly to every ``embed`` call. 30s is the documented
        default; operators can override via ``cfg['timeout_ms']``.
        """
        return httpx.Timeout(self._timeout_seconds)

    def _raise_on_auth(self, status_code: int) -> None:
        """Translate HTTP 401/403 to ``ProviderAuthError`` (Req 2.10).

        Ollama itself never returns these, but a reverse proxy in
        front of it may. Mapping them keeps the structured error
        envelope in design §5.3 consistent across every adapter.
        """
        if status_code in (401, 403):
            raise ProviderAuthError(
                provider=_PROVIDER_NAME,
                model=self._model,
                error_code="PROVIDER_AUTH_FAILED",
            )

    # ------------------------------------------------------------------ #
    # EmbeddingsProvider API                                             #
    # ------------------------------------------------------------------ #

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` and return one float vector per input.

        Ollama's ``/api/embed`` returns the ``embeddings`` array in the
        same positional order as ``input``; there is no ``index``
        field to sort by. We preserve the server's order directly.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "input": list(texts),
        }
        url = f"{self._base_url}/api/embed"

        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        raw_vectors = body.get("embeddings") or []
        vectors: list[list[float]] = [[float(x) for x in (vec or [])] for vec in raw_vectors]

        # Cache the dim on first successful call so the ``dim`` property
        # can return synchronously after that. We deliberately check
        # truthy-length rather than ``> 0`` so an empty ``vectors`` list
        # (e.g. ``texts == []``) does not clobber a previous value.
        if vectors and self._dim is None:
            self._dim = len(vectors[0])

        return vectors

    @property
    def model_id(self) -> str:
        """Stable identifier used in cache keys (design §3.11, Req 5.6)."""
        return self._model

    @property
    def dim(self) -> int:
        """Embedding dimensionality; wired into ``VECTOR(dim)`` (Req 2.14).

        Returns ``cfg["dim"]`` when the operator pinned it up-front
        (the recommended configuration for production because the
        ``VECTOR(dim)`` column width must be known before the first
        upsert). Otherwise raises ``RuntimeError`` until ``embed()``
        has been called at least once, at which point the cached
        length of the first returned vector is reused. Keeping this
        property synchronous matches the ``EmbeddingsProvider``
        protocol contract in ``base.py``.
        """
        if self._dim is None:
            raise RuntimeError(
                "ollama embeddings: dim is not yet known. Either set "
                "cfg['dim'] to the model's output width or call "
                "embed() at least once before reading .dim.",
            )
        return self._dim


def build(cfg: dict[str, Any]) -> EmbeddingsProvider:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the block under ``research.providers.embeddings`` in
    ``config/settings.yaml`` when ``provider == "ollama"``; it is
    forwarded verbatim by the registry. **All** keys are optional here,
    unlike cloud adapters:

    * ``model``      — defaults to ``nomic-embed-text`` when missing
                        or falsy.
    * ``base_url``   — defaults to ``http://localhost:11434``.
    * ``dim``        — pin the output width up-front so the ``dim``
                        property is available before the first
                        ``embed()`` call. Recommended for production
                        (see Req 2.14).
    * ``timeout_ms`` — per-call HTTP timeout (default 30000).

    This function performs **no** network I/O; the adapter is created
    eagerly but upstream calls only happen inside ``embed``. In
    particular it does not verify that Ollama is actually running, so
    it is safe to import in offline test environments (Req 2.12).
    """
    # ``cfg.get("model")`` returns ``None`` for missing keys and
    # ``""`` for operators that accidentally leave the value blank;
    # both fall back to the documented default.
    model = cfg.get("model") or _DEFAULT_MODEL
    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL

    timeout_ms = cfg.get("timeout_ms")
    timeout_seconds = timeout_ms / 1000.0 if timeout_ms is not None else _DEFAULT_TIMEOUT_SECONDS

    dim_cfg = cfg.get("dim")
    dim = int(dim_cfg) if dim_cfg is not None else None

    return OllamaEmbeddings(
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        dim=dim,
    )


__all__ = ["OllamaEmbeddings", "build"]
