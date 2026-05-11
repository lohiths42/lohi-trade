"""OpenRouter LLM adapter (Req 2.4, design §3.1).

OpenRouter's chat-completions endpoint
(``https://openrouter.ai/api/v1/chat/completions``) is OpenAI-wire
compatible, so this adapter mirrors
``src.research.providers.llm.openai`` verbatim — same request payload,
same SSE parsing, same ``ProviderAuthError`` mapping — and differs only
in the default base URL, the ``provider`` tag stamped onto returned
envelopes, and two optional attribution headers (``HTTP-Referer`` and
``X-Title``) that OpenRouter recommends but does not require. That is
the deliberate outcome of Req 2.4 (one file per backend, minimal
surface area) and design §3.1 (shared OpenAI-compatible contract).

This module implements the ``LLMProvider`` protocol declared in
``src.research.providers.base`` against OpenRouter and nothing else.
It is registered lazily by ``registry.py`` via the
``"openrouter": "src.research.providers.llm.openrouter:build"`` entry,
so importing this file does **not** require a configured API key and
does not trigger any network I/O (Req 2.12).

Contract highlights
-------------------
* ``complete`` — single non-streamed call returning the Pydantic
  ``Completion`` (the Provider_Contract, Req 2.11).
* ``stream`` — async iterator of ``CompletionChunk`` deltas parsed from
  the OpenAI-compatible SSE stream (``data: {…}\\n\\n`` lines,
  terminated by ``data: [DONE]``).
* 401/403 → ``ProviderAuthError(provider="openrouter", model=…,
  error_code="PROVIDER_AUTH_FAILED")`` so the gateway emits the
  envelope defined in design §5.3 and never falls back silently
  (Req 2.10).
* Optional ``referer`` / ``title`` cfg keys populate OpenRouter's
  ``HTTP-Referer`` and ``X-Title`` attribution headers when set; both
  are fully optional and absent by default.
* Other transport failures are left to bubble up as ``httpx`` errors;
  the gateway error-mapping layer (Task 16.4) normalises them.
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

# OpenRouter's OpenAI-compatible chat-completions endpoint (design §3.1).
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_PROVIDER_NAME = "openrouter"

# Upstream ``finish_reason`` values → normalised ``Completion.finish_reason``
# (design §3.1). ``content_filter`` is surfaced as ``refusal`` because the
# Guardrail_Layer (design §3.6) treats upstream safety blocks the same as
# our own refusals. Anything else is coerced to ``"error"``.
_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "refusal",
}


class OpenRouterLLM:
    """Concrete ``LLMProvider`` hitting the OpenRouter chat-completions endpoint.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. The only mutable state is the cached per-call
    auth headers, base URL, and the optional attribution headers —
    everything else comes from the per-call ``LLMParams`` so the same
    adapter instance is safe to share across agents (design §3.5).

    Attribution headers
    -------------------
    OpenRouter recommends — but does not require — that clients send
    ``HTTP-Referer`` (an opaque identifier for your app, typically a
    URL) and ``X-Title`` (a human-readable app name) so usage appears
    under your project in their dashboard. Both are optional; when
    left unset at construction time, neither header is sent.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        referer: str | None = None,
        title: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        # Strip a single trailing slash so concatenation below is
        # predictable regardless of how the operator spells the URL.
        self._base_url = base_url.rstrip("/")
        self._referer = referer
        self._title = title

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, *, stream: bool) -> dict[str, str]:
        """Request headers used for both ``complete`` and ``stream``.

        Includes OpenRouter's optional ``HTTP-Referer`` / ``X-Title``
        attribution headers only when the corresponding cfg values
        were supplied at construction time.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }
        if self._referer is not None:
            headers["HTTP-Referer"] = self._referer
        if self._title is not None:
            headers["X-Title"] = self._title
        return headers

    def _timeout(self, params: LLMParams) -> httpx.Timeout | None:
        """Translate ``params.timeout_ms`` to an ``httpx.Timeout``.

        Returns ``None`` when the caller did not set ``timeout_ms`` so
        ``httpx`` applies its own defaults.
        """
        if params.timeout_ms is None:
            return None
        return httpx.Timeout(params.timeout_ms / 1000.0)

    def _build_payload(
        self,
        messages: list[Message],
        params: LLMParams,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Assemble the OpenAI-compatible request body.

        Only fields the caller actually set are included so we send a
        minimal payload and let OpenRouter fall back to its own
        defaults for unspecified knobs. Unknown keys passed via
        ``params.extra`` are forwarded verbatim for provider-specific
        knobs (e.g. OpenRouter's ``route`` / ``provider`` routing
        hints) — Req 2.4 wants one-file-per-backend so there is no
        central allow-list to maintain.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
        }
        if params.temperature is not None:
            payload["temperature"] = params.temperature
        if params.max_tokens is not None:
            payload["max_tokens"] = params.max_tokens
        if params.top_p is not None:
            payload["top_p"] = params.top_p
        if params.stop is not None:
            payload["stop"] = params.stop
        if params.extra:
            # Explicit keys take precedence over ``extra`` — operators can
            # override without knowing our internal field list.
            for key, value in params.extra.items():
                payload.setdefault(key, value)
        return payload

    def _raise_on_auth(self, status_code: int) -> None:
        """Translate HTTP 401/403 to ``ProviderAuthError`` (Req 2.10)."""
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
        self, messages: list[Message], params: LLMParams,
    ) -> Completion:
        """Single non-streamed chat completion (Req 2.11)."""
        payload = self._build_payload(messages, params, stream=False)
        url = f"{self._base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self._timeout(params)) as client:
            response = await client.post(
                url,
                headers=self._headers(stream=False),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        choice = body["choices"][0]
        message = choice["message"]
        usage = body.get("usage") or {}
        raw_finish = choice.get("finish_reason")
        finish_reason = _FINISH_REASON_MAP.get(raw_finish, "error")

        return Completion(
            provider=_PROVIDER_NAME,
            model=self._model,
            content=message.get("content") or "",
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            finish_reason=finish_reason,
        )

    async def stream(
        self, messages: list[Message], params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Async iterator over server-sent deltas (design §3.1)."""
        payload = self._build_payload(messages, params, stream=True)
        url = f"{self._base_url}/chat/completions"

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
                        # Blank separator between SSE events.
                        continue
                    if not raw_line.startswith("data:"):
                        # OpenRouter occasionally emits ``event:`` / ``id:`` frames.
                        continue
                    data = raw_line[len("data:") :].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        return

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        # Skip malformed frames; a later chunk will carry
                        # the full completion or the server will close.
                        continue

                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if not delta:
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
    ``config/settings.yaml`` — the same shape every LLM adapter consumes.

    Required keys
    -------------
    * ``model``   — OpenRouter model slug (e.g. ``"anthropic/claude-3.5-sonnet"``).
    * ``api_key`` — OpenRouter API key.

    Optional keys
    -------------
    * ``base_url`` — override of the default endpoint.
    * ``referer`` — populates the ``HTTP-Referer`` attribution header
      when set; omitted from requests when ``None`` / unset.
    * ``title``   — populates the ``X-Title`` attribution header when
      set; omitted from requests when ``None`` / unset.

    This function performs **no** network I/O; the adapter is created
    eagerly but upstream calls only happen inside ``complete`` /
    ``stream``.
    """
    try:
        model = cfg["model"]
        api_key = cfg["api_key"]
    except KeyError as exc:
        missing = exc.args[0]
        raise KeyError(
            f"openrouter provider config is missing required key {missing!r}; "
            "expected 'model' and 'api_key' (see design §7.1).",
        ) from exc

    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL
    referer = cfg.get("referer")
    title = cfg.get("title")
    return OpenRouterLLM(
        api_key=api_key,
        model=model,
        base_url=base_url,
        referer=referer,
        title=title,
    )


__all__ = ["OpenRouterLLM", "build"]
