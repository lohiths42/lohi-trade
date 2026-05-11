"""NVIDIA NIM embeddings adapter (Req 2.5, design §3.1).

NVIDIA NIM hosts OpenAI-compatible embeddings at
``https://integrate.api.nvidia.com/v1/embeddings`` alongside the
chat-completions endpoint wrapped by
``src.research.providers.llm.nvidia_nim``. The wire format follows the
same "OpenAI-compatible" body shape that the OpenAI embeddings adapter
(``src.research.providers.embeddings.openai``) speaks, **with one
NIM-specific addition**: every embeddings request must include an
``input_type`` field with either ``"query"`` or ``"passage"``. Sending
the request without it gets rejected upstream. Since the primary caller
is the ingestion pipeline (design §3.3), this adapter defaults
``input_type`` to ``"passage"``; operators can override via
``cfg["input_type"]`` when the same adapter instance is used for query-
side embedding instead.

This module implements the ``EmbeddingsProvider`` protocol declared in
``src.research.providers.base`` against NVIDIA NIM and nothing else. It
is registered lazily by ``registry.py`` via the
``"nvidia_nim": "src.research.providers.embeddings.nvidia_nim:build"``
entry, so importing this file does **not** require a configured API
key and does not trigger any network I/O (Req 2.12).

Contract highlights
-------------------
* ``embed`` — POST ``/v1/embeddings`` with ``{"input": texts,
  "model": …, "encoding_format": "float", "input_type": …}``. Returns
  one ``list[float]`` per input, re-ordered by the ``index`` field
  from the response so the output is aligned with ``texts`` even when
  the server returns items out of order.
* ``model_id`` — the configured model string.
* ``dim`` — returns ``cfg["dim"]`` when the operator pinned it up-
  front (recommended for ``VECTOR(dim)`` column provisioning, Req
  2.14); otherwise raises ``RuntimeError`` until ``embed()`` has been
  called at least once, at which point the cached length of the first
  returned vector is reused. This keeps the property synchronous
  (``EmbeddingsProvider.dim`` is a plain ``@property``, not an async
  coroutine).
* 401/403 → ``ProviderAuthError(provider="nvidia_nim", model=…,
  error_code="PROVIDER_AUTH_FAILED")`` so the gateway emits the
  envelope defined in design §5.3 and never falls back silently
  (Req 2.10).
* Other transport failures bubble up as ``httpx`` errors; the gateway
  error-mapping layer (Task 16.4) normalises them.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..base import EmbeddingsProvider
from ..errors import ProviderAuthError

# OpenAI-compatible NVIDIA NIM cloud endpoint (design §3.1, Req 2.5).
_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

# NIM requires ``input_type`` on every embeddings request; "passage" is
# the correct value for ingested corpus chunks which is the primary
# caller (design §3.3). Query-side callers override via cfg.
_DEFAULT_INPUT_TYPE = "passage"

# Embeddings are typically sub-second; 30s is generous enough to cover
# batched calls on a cold NIM instance but short enough to fail fast
# when the upstream is unreachable (design §3.4).
_DEFAULT_TIMEOUT_SECONDS = 30.0

_PROVIDER_NAME = "nvidia_nim"


class NvidiaNimEmbeddings:
    """Concrete ``EmbeddingsProvider`` hitting the NVIDIA NIM embeddings endpoint.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The only mutable state is the optional cached
    ``_dim`` captured from the first ``embed`` response; everything
    else is immutable after construction so a single instance is safe
    to share across agents (design §3.5).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        input_type: str,
        timeout_seconds: float,
        dim: int | None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        # Strip a single trailing slash so concatenation below is
        # predictable regardless of how the operator spells the URL.
        self._base_url = base_url.rstrip("/")
        self._input_type = input_type
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
        """Request headers used for ``embed``."""
        return {
            "Authorization": f"Bearer {self._api_key}",
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
        """Translate HTTP 401/403 to ``ProviderAuthError`` (Req 2.10)."""
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

        The response is sorted by the ``index`` field so the output
        order matches ``texts`` even if NIM returns the ``data`` array
        in a different order; this matches the OpenAI embeddings
        contract the rest of the codebase assumes.
        """
        payload: dict[str, Any] = {
            "input": list(texts),
            "model": self._model,
            "encoding_format": "float",
            "input_type": self._input_type,
        }
        url = f"{self._base_url}/embeddings"

        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        data = body.get("data") or []
        # Sort by the server-reported index so the output order is
        # aligned with ``texts``. Items without an ``index`` key fall
        # back to their position in ``data`` which preserves the
        # server's implicit order.
        ordered = sorted(
            data,
            key=lambda item: item.get("index", 0),
        )
        vectors: list[list[float]] = [
            [float(x) for x in (item.get("embedding") or [])]
            for item in ordered
        ]

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
                "nvidia_nim embeddings: dim is not yet known. Either "
                "set cfg['dim'] to the model's output width or call "
                "embed() at least once before reading .dim.",
            )
        return self._dim


def build(cfg: dict[str, Any]) -> EmbeddingsProvider:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the block under ``research.providers.embeddings`` in
    ``config/settings.yaml`` when ``provider == "nvidia_nim"``; it is
    forwarded verbatim by the registry.

    Required keys:
      * ``api_key`` — NIM bearer token (environment-interpolated).
      * ``model``   — NIM embeddings model id, e.g.
                      ``"nvidia/nv-embedqa-e5-v5"``.

    Optional keys:
      * ``base_url``   — override for self-hosted NIM microservices.
      * ``input_type`` — ``"passage"`` (default) or ``"query"``.
      * ``dim``        — pin the output width up-front so the ``dim``
                         property is available before the first
                         ``embed()`` call. Recommended for production
                         (see Req 2.14).
      * ``timeout_ms`` — per-call HTTP timeout (default 30000).

    This function performs **no** network I/O; the adapter is created
    eagerly but upstream calls only happen inside ``embed``.
    """
    try:
        api_key = cfg["api_key"]
        model = cfg["model"]
    except KeyError as exc:
        missing = exc.args[0]
        raise KeyError(
            f"nvidia_nim embeddings provider config is missing required "
            f"key {missing!r}; expected 'api_key' and 'model' "
            "(see design §7.1).",
        ) from exc

    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL
    input_type = cfg.get("input_type") or _DEFAULT_INPUT_TYPE

    timeout_ms = cfg.get("timeout_ms")
    timeout_seconds = (
        timeout_ms / 1000.0 if timeout_ms is not None else _DEFAULT_TIMEOUT_SECONDS
    )

    dim_cfg = cfg.get("dim")
    dim = int(dim_cfg) if dim_cfg is not None else None

    return NvidiaNimEmbeddings(
        api_key=api_key,
        model=model,
        base_url=base_url,
        input_type=input_type,
        timeout_seconds=timeout_seconds,
        dim=dim,
    )


__all__ = ["NvidiaNimEmbeddings", "build"]
