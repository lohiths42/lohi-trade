"""Ollama LLM adapter (Req 2.4, Req 7.5, design §3.1).

Ollama is the **default offline provider** for Lohi-Research (design
§3.1, design §18 Open Issue #3). It runs locally on
``http://localhost:11434`` by default, speaks its **own** chat wire
format at ``POST /api/chat``, and emits **newline-delimited JSON**
(NDJSON) rather than server-sent events when streaming — so this
adapter cannot reuse the OpenAI-compatible SSE parser that
``nvidia_nim.py`` / ``openai.py`` / ``groq.py`` / ``together.py`` /
``openrouter.py`` share. The framing is close enough to Anthropic's
custom adapter in shape but simpler: one JSON object per line, final
line carries ``"done": true``.

This module implements the ``LLMProvider`` protocol declared in
``src.research.providers.base`` against Ollama and nothing else. It is
registered lazily by ``registry.py`` via the
``"ollama": "src.research.providers.llm.ollama:build"`` entry, so
importing this file does **not** trigger network I/O and does not
require Ollama to be running (Req 2.12).

Offline default
---------------
Per design Open Issue #3, the out-of-the-box Ollama model is
``llama3.1:8b`` — an 8B-parameter weight class that fits the 16 GB
RAM budget called out in design §17 for the offline profile
(Req 7.5, Req 15.5). ``build(cfg)`` therefore treats ``model`` as
**optional** and falls back to ``llama3.1:8b`` when the operator does
not pin one in ``config/settings.yaml``. Operators can override with
e.g. ``qwen2.5:7b`` via config without code change (Req 2.12).

The offline-mode guard itself (``LOHI_RESEARCH_OFFLINE=true`` forcing
every role to ``ollama``) lives at the registry layer and is wired in
Task 19.1 — this adapter just works offline because every call is to
localhost.

Wire-format specifics
---------------------
* **Base URL** — ``http://localhost:11434`` by default; operators can
  override via ``cfg["base_url"]`` (e.g. when Ollama is reached
  through a reverse proxy or a named Docker service).
* **Endpoint** — ``POST /api/chat`` for both non-streamed and streamed
  calls; the ``stream`` field in the request body selects framing.
* **Auth** — none. Ollama runs locally. ``api_key`` is accepted in
  ``cfg`` for config-shape symmetry with every other adapter but is
  never sent over the wire. 401/403 are still mapped to
  ``ProviderAuthError`` because a reverse proxy in front of Ollama
  can legitimately return them; the gateway envelope in design §5.3
  therefore stays consistent (Req 2.10).
* **Messages** — Ollama accepts ``role: "system"`` inline (unlike
  Anthropic), so messages are forwarded 1:1. No system extraction is
  needed.
* **Sampling knobs** — live under a nested ``options`` object, with
  renames: ``temperature`` → ``options.temperature``, ``max_tokens``
  → ``options.num_predict``, ``top_p`` → ``options.top_p``, ``stop``
  → ``options.stop``. Only keys the caller set are forwarded, so
  unspecified knobs fall back to Ollama's defaults.
* **Non-streaming response** — single JSON object; ``content`` comes
  from ``message.content``, ``input_tokens`` from
  ``prompt_eval_count`` (default ``0``), ``output_tokens`` from
  ``eval_count`` (default ``0``).
* **Finish reason** — ``done_reason`` maps directly: ``"stop"`` →
  ``"stop"``, ``"length"`` → ``"length"``; anything else is coerced to
  ``"error"``. Ollama has no content-filter concept, so
  ``finish_reason == "refusal"`` is unreachable here.
* **Streaming response** — NDJSON: each line is a complete JSON
  object like ``{"message": {"content": "hello"}, "done": false}``,
  terminated by a line with ``"done": true``. We yield one
  ``CompletionChunk`` per non-empty ``message.content`` delta and
  return when ``done`` is seen.
* Other transport failures bubble up as ``httpx`` errors; the
  gateway error-mapping layer (Task 16.4) normalises them.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..base import (
    Completion,
    CompletionChunk,
    LLMParams,
    LLMProvider,
    Message,
)
from ..errors import ProviderAuthError

# Ollama's local daemon listens on 11434 by default (design §3.1, §16.2).
_DEFAULT_BASE_URL = "http://localhost:11434"

# Out-of-the-box offline model per design §18 Open Issue #3 / design §17.
# 8B fits the 16 GB offline RAM budget; operators can override via config.
_DEFAULT_MODEL = "llama3.1:8b"

_PROVIDER_NAME = "ollama"

# Upstream ``done_reason`` → normalised ``Completion.finish_reason``.
# Ollama has no content-filter equivalent, so ``"refusal"`` is
# unreachable here; keeping the map explicit documents that.
_DONE_REASON_MAP: dict[str, str] = {
    "stop": "stop",
    "length": "length",
}


class OllamaLLM:
    """Concrete ``LLMProvider`` hitting the local Ollama ``/api/chat``.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. State is limited to the cached model id and base
    URL — everything else comes from the per-call ``LLMParams`` so a
    single adapter instance is safe to share across agents
    (design §3.5).
    """

    def __init__(self, *, model: str, base_url: str) -> None:
        self._model = model
        # Strip a single trailing slash so concatenation below is
        # predictable regardless of how the operator spells the URL.
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, *, stream: bool) -> dict[str, str]:
        """Request headers used for both ``complete`` and ``stream``.

        Ollama does not require authentication (it runs locally). We
        still negotiate content types so a reverse proxy that enforces
        them sees a well-formed request.
        """
        # NDJSON framing has no registered media type; ``application/json``
        # is what Ollama itself advertises on both streamed and
        # non-streamed responses, so we accept it in both modes.
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _timeout(self, params: LLMParams) -> httpx.Timeout | None:
        """Translate ``params.timeout_ms`` to an ``httpx.Timeout``.

        Returns ``None`` when the caller did not set ``timeout_ms`` so
        ``httpx`` applies its own defaults. Local inference with 8B
        models can take tens of seconds on CPU — operators are
        expected to raise ``timeout_ms`` in settings.yaml under the
        offline profile (design §17).
        """
        if params.timeout_ms is None:
            return None
        return httpx.Timeout(params.timeout_ms / 1000.0)

    def _build_options(self, params: LLMParams) -> dict[str, Any]:
        """Translate ``LLMParams`` sampling knobs to Ollama's ``options`` block.

        Only keys the caller actually set are included so unspecified
        knobs fall back to Ollama's own defaults. Note the rename:
        Ollama's completion-length cap is ``num_predict``, not
        ``max_tokens``.
        """
        options: dict[str, Any] = {}
        if params.temperature is not None:
            options["temperature"] = params.temperature
        if params.max_tokens is not None:
            options["num_predict"] = params.max_tokens
        if params.top_p is not None:
            options["top_p"] = params.top_p
        if params.stop is not None:
            options["stop"] = params.stop
        return options

    def _build_payload(
        self,
        messages: list[Message],
        params: LLMParams,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Assemble the ``/api/chat`` request body.

        Differences from the OpenAI-compatible payload used by the
        NIM / OpenAI adapters:

        * Sampling knobs live under a nested ``options`` object with
          ``max_tokens`` renamed to ``num_predict``.
        * No ``Authorization`` header (handled in ``_headers``).
        * Unknown keys passed via ``params.extra`` are forwarded
          verbatim for provider-specific knobs (e.g. ``keep_alive``,
          ``format``) — Req 2.4 wants one-file-per-backend so there
          is no central allow-list to maintain.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
        }
        options = self._build_options(params)
        if options:
            payload["options"] = options
        if params.extra:
            # Explicit keys take precedence over ``extra`` — operators
            # can override without knowing our internal field list.
            for key, value in params.extra.items():
                payload.setdefault(key, value)
        return payload

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
    # LLMProvider API                                                    #
    # ------------------------------------------------------------------ #

    async def complete(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> Completion:
        """Single non-streamed ``/api/chat`` call (Req 2.11)."""
        payload = self._build_payload(messages, params, stream=False)
        url = f"{self._base_url}/api/chat"

        async with httpx.AsyncClient(timeout=self._timeout(params)) as client:
            response = await client.post(
                url,
                headers=self._headers(stream=False),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        message = body.get("message") or {}
        content = message.get("content") or ""

        raw_done = body.get("done_reason")
        finish_reason = _DONE_REASON_MAP.get(raw_done, "error")

        return Completion(
            provider=_PROVIDER_NAME,
            model=self._model,
            content=content,
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Async iterator over ``/api/chat`` NDJSON deltas (design §3.1).

        Ollama's streaming framing is **not** SSE: each line is a
        complete JSON object, with no ``data:`` prefix and no
        ``[DONE]`` sentinel. The final line carries ``"done": true``;
        every preceding line carries an incremental
        ``message.content`` delta that we surface as a
        ``CompletionChunk``.
        """
        payload = self._build_payload(messages, params, stream=True)
        url = f"{self._base_url}/api/chat"

        index = 0
        async with httpx.AsyncClient(timeout=self._timeout(params)) as client:
            async with client.stream(
                "POST",
                url,
                headers=self._headers(stream=True),
                json=payload,
            ) as response:
                self._raise_on_auth(response.status_code)
                response.raise_for_status()

                async for raw_line in response.aiter_lines():
                    if not raw_line:
                        # Blank lines are possible if a proxy inserts
                        # them; NDJSON itself requires no separators
                        # but we tolerate them.
                        continue

                    try:
                        event = json.loads(raw_line)
                    except json.JSONDecodeError:
                        # Skip malformed frames; a later chunk will
                        # carry the full completion or the server
                        # will close.
                        continue

                    # Terminal sentinel: Ollama closes the stream by
                    # sending a final frame with ``"done": true``. We
                    # return immediately so callers don't block on the
                    # underlying socket.
                    if event.get("done"):
                        return

                    message = event.get("message") or {}
                    delta = message.get("content")
                    if not delta:
                        # Non-text frames (e.g. pure metadata) carry
                        # no ``message.content`` — skip them silently.
                        continue

                    yield CompletionChunk(
                        provider=_PROVIDER_NAME,
                        model=self._model,
                        delta=delta,
                        index=index,
                    )
                    index += 1


def build(cfg: dict) -> LLMProvider:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the per-role block from ``research.providers.<role>`` in
    ``config/settings.yaml`` — the same shape every LLM adapter
    consumes. **All** keys are optional here, unlike cloud adapters:

    * ``model``    — defaults to ``llama3.1:8b`` (design §18 Open
                      Issue #3, Req 7.5) when missing or falsy.
    * ``base_url`` — defaults to ``http://localhost:11434``.
    * ``api_key``  — accepted for config-shape symmetry with every
                      other adapter but ignored (Ollama runs locally).

    This function performs **no** network I/O; the adapter is created
    eagerly but upstream calls only happen inside ``complete`` /
    ``stream``. In particular it does not verify that Ollama is
    actually running, so it is safe to import in offline test
    environments (Req 2.12).
    """
    # ``cfg.get("model")`` returns ``None`` for missing keys and
    # ``""`` for operators that accidentally leave the value blank;
    # both fall back to the documented default.
    model = cfg.get("model") or _DEFAULT_MODEL
    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL
    return OllamaLLM(model=model, base_url=base_url)


__all__ = ["OllamaLLM", "build"]
