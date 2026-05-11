"""Anthropic LLM adapter (Req 2.4, design §3.1).

Anthropic's public Messages API lives at
``https://api.anthropic.com/v1/messages``. Unlike NVIDIA NIM, OpenAI,
Groq, Together, and OpenRouter — all of which speak the OpenAI
chat-completions wire format — Anthropic has its **own** request and
response shape, its own authentication header, and its own SSE event
taxonomy. This adapter therefore cannot reuse the OpenAI-compatible
body/stream parser used by ``nvidia_nim.py`` / ``openai.py``; it
speaks the Messages API directly.

This module implements the ``LLMProvider`` protocol declared in
``src.research.providers.base`` against the Anthropic Messages API and
nothing else. It is registered lazily by ``registry.py`` via the
``"anthropic": "src.research.providers.llm.anthropic:build"`` entry,
so importing this file does **not** require a configured API key and
does not trigger any network I/O (Req 2.12).

Wire-format specifics
---------------------
* **Auth header** — ``x-api-key: <api_key>`` (not ``Authorization:
  Bearer``).
* **Version header** — ``anthropic-version: 2023-06-01`` is required
  on every call.
* **``max_tokens``** — mandatory in the request body; Anthropic
  rejects requests without it, so this adapter defaults to ``1024``
  when the caller does not set ``params.max_tokens``.
* **System messages** — Anthropic does **not** accept ``role:
  "system"`` inside ``messages``. All ``role == "system"`` messages
  are concatenated with ``"\\n\\n"`` and passed as the top-level
  ``system`` field instead; only ``user`` / ``assistant`` messages
  are forwarded in ``messages``.
* **Stop sequences** — the request field is ``stop_sequences`` (not
  ``stop``).
* **Response shape** — ``content`` is a list of typed blocks; this
  adapter takes ``content[0].text`` for plain-text assistants.
  ``usage.input_tokens`` / ``usage.output_tokens`` map directly onto
  ``Completion.input_tokens`` / ``output_tokens``.
* **Finish reason** — ``end_turn`` and ``stop_sequence`` both map to
  ``"stop"``; ``max_tokens`` maps to ``"length"``; anything else is
  coerced to ``"error"``. The Messages API has no
  ``content_filter`` equivalent, so ``Completion.finish_reason ==
  "refusal"`` is never produced by this adapter.
* **SSE streaming** — events are typed (``message_start``,
  ``content_block_start``, ``content_block_delta``,
  ``content_block_stop``, ``message_delta``, ``message_stop``). Each
  event arrives as a pair of lines (``event: <name>`` then
  ``data: <json>``). The adapter dispatches on the ``event:`` name:
  it only yields a ``CompletionChunk`` for ``content_block_delta``
  events whose ``delta.type == "text_delta"``, and terminates on
  ``message_stop``.
* **Auth failure** — 401 / 403 map to
  ``ProviderAuthError(provider="anthropic", model=…,
  error_code="PROVIDER_AUTH_FAILED")`` so the gateway emits the
  envelope defined in design §5.3 and never falls back silently
  (Req 2.10).
* Other transport failures bubble up as ``httpx`` errors; the gateway
  error-mapping layer (Task 16.4) normalises them.
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

# Anthropic Messages API endpoint (design §3.1).
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

# Pinned API version header. Anthropic requires this on every call and
# guarantees wire stability per version string; bump deliberately when
# the adapter is updated for a newer response shape.
_ANTHROPIC_VERSION = "2023-06-01"

_PROVIDER_NAME = "anthropic"

# Anthropic ``max_tokens`` is mandatory. 1024 is a conservative default
# that keeps the adapter usable without the caller pre-populating the
# param block; per-agent configuration normally sets a tighter bound
# via ``LLMParams.max_tokens`` (design §3.5, Req 12.1).
_DEFAULT_MAX_TOKENS = 1024

# Upstream ``stop_reason`` → normalised ``Completion.finish_reason``.
# Anthropic has no ``content_filter`` equivalent, so "refusal" is
# unreachable here; keeping the map explicit documents that.
_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
}


def _split_system_and_turns(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, str]]]:
    """Extract Anthropic's top-level ``system`` from a mixed message list.

    The Messages API rejects ``role: "system"`` inside ``messages``.
    We pull every ``role == "system"`` message out, concatenate their
    contents with ``"\\n\\n"``, and return them as the top-level
    ``system`` string; the remaining user/assistant turns are returned
    in original order as the ``messages`` payload.

    Returns ``(None, turns)`` when the caller passed no system messages.
    """
    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        else:
            turns.append({"role": m.role, "content": m.content})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, turns


class AnthropicLLM:
    """Concrete ``LLMProvider`` hitting the Anthropic Messages API.

    Instantiated via ``build(cfg)``; operators never construct this
    class directly. State is limited to the cached API key, model id,
    and base URL — everything else comes from the per-call
    ``LLMParams`` so a single adapter instance is safe to share across
    agents (design §3.5).
    """

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        # Strip a single trailing slash so concatenation below is
        # predictable regardless of how the operator spells the URL.
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, *, stream: bool) -> dict[str, str]:
        """Request headers used for both ``complete`` and ``stream``.

        Anthropic uses ``x-api-key`` rather than
        ``Authorization: Bearer …`` and requires an explicit
        ``anthropic-version`` header on every call.
        """
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }

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
        """Assemble the Messages API request body.

        Differences from the OpenAI-compatible payload used by the NIM
        / OpenAI adapters:

        * ``max_tokens`` is always present (Anthropic rejects requests
          without it); we default to ``_DEFAULT_MAX_TOKENS`` when the
          caller omitted it.
        * System messages are pulled out into the top-level ``system``
          field rather than sent as a ``role: "system"`` turn.
        * Stop sequences ship as ``stop_sequences`` (not ``stop``).
        * Unknown keys passed via ``params.extra`` are forwarded
          verbatim for provider-specific knobs — Req 2.4 wants
          one-file-per-backend so there is no central allow-list to
          maintain.
        """
        system, turns = _split_system_and_turns(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": turns,
            "max_tokens": (
                params.max_tokens
                if params.max_tokens is not None
                else _DEFAULT_MAX_TOKENS
            ),
            "stream": stream,
        }
        if system is not None:
            payload["system"] = system
        if params.temperature is not None:
            payload["temperature"] = params.temperature
        if params.top_p is not None:
            payload["top_p"] = params.top_p
        if params.stop is not None:
            payload["stop_sequences"] = params.stop
        if params.extra:
            # Explicit keys take precedence over ``extra`` — operators
            # can override without knowing our internal field list.
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
        """Single non-streamed Messages API call (Req 2.11)."""
        payload = self._build_payload(messages, params, stream=False)
        url = f"{self._base_url}/messages"

        async with httpx.AsyncClient(timeout=self._timeout(params)) as client:
            response = await client.post(
                url,
                headers=self._headers(stream=False),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        # ``content`` is a list of typed blocks; for plain-text
        # assistants we take the first ``text`` block. If the list is
        # empty or the first block is not a ``text`` block we fall back
        # to the empty string rather than raising — the Guardrail_Layer
        # downstream treats empty output as a refusal-like event.
        content_blocks = body.get("content") or []
        first_text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                first_text = block.get("text") or ""
                break

        usage = body.get("usage") or {}
        raw_stop = body.get("stop_reason")
        finish_reason = _STOP_REASON_MAP.get(raw_stop, "error")

        return Completion(
            provider=_PROVIDER_NAME,
            model=self._model,
            content=first_text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            finish_reason=finish_reason,
        )

    async def stream(
        self, messages: list[Message], params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Async iterator over Messages API SSE deltas (design §3.1).

        Anthropic's SSE stream is event-typed: each event is a pair of
        lines — ``event: <name>`` followed by ``data: <json>`` —
        separated by a blank line from the next event. This loop
        tracks the most recently seen ``event:`` name and dispatches on
        it when the matching ``data:`` line arrives. We emit a
        ``CompletionChunk`` only for ``content_block_delta`` events
        whose ``delta.type == "text_delta"``, and we return on the
        first ``message_stop`` event.
        """
        payload = self._build_payload(messages, params, stream=True)
        url = f"{self._base_url}/messages"

        index = 0
        current_event: str | None = None
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
                        # Blank separator between SSE events; reset the
                        # event name so a stray ``data:`` without a
                        # preceding ``event:`` is ignored safely.
                        current_event = None
                        continue

                    if raw_line.startswith("event:"):
                        current_event = raw_line[len("event:") :].strip()
                        continue

                    if not raw_line.startswith("data:"):
                        # Anthropic occasionally prefixes comments with
                        # ``:`` or emits ``id:`` / ``retry:`` lines;
                        # none carry deltas.
                        continue

                    data = raw_line[len("data:") :].strip()
                    if not data:
                        continue

                    # Terminal sentinel: close the stream as soon as
                    # the server announces the end of the message.
                    if current_event == "message_stop":
                        return

                    # We only care about text deltas for streaming
                    # output; every other event type carries metadata
                    # (block start/stop, usage updates, etc.) that the
                    # ``LLMProvider`` contract does not surface.
                    if current_event != "content_block_delta":
                        continue

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        # Skip malformed frames; a later chunk will
                        # carry the full completion or the server will
                        # close.
                        continue

                    delta_obj = event.get("delta") or {}
                    if delta_obj.get("type") != "text_delta":
                        continue
                    text = delta_obj.get("text")
                    if not text:
                        continue

                    yield CompletionChunk(
                        provider=_PROVIDER_NAME,
                        model=self._model,
                        delta=text,
                        index=index,
                    )
                    index += 1


def build(cfg: dict) -> LLMProvider:
    """Factory entry point used by ``registry.py`` (Req 2.12).

    ``cfg`` is the per-role block from ``research.providers.<role>`` in
    ``config/settings.yaml`` — the same shape every LLM adapter
    consumes. Required keys: ``model``, ``api_key``. Optional:
    ``base_url`` (useful for pointing at a staging URL or a reverse
    proxy); defaults to ``https://api.anthropic.com/v1``.

    This function performs **no** network I/O; the adapter is created
    eagerly but upstream calls only happen inside
    ``complete`` / ``stream``.
    """
    try:
        model = cfg["model"]
        api_key = cfg["api_key"]
    except KeyError as exc:
        missing = exc.args[0]
        raise KeyError(
            f"anthropic provider config is missing required key {missing!r}; "
            "expected 'model' and 'api_key' (see design §7.1).",
        ) from exc

    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL
    return AnthropicLLM(api_key=api_key, model=model, base_url=base_url)


__all__ = ["AnthropicLLM", "build"]
