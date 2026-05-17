"""Gemini LLM adapter (Req 2.4, design §3.1).

Google's public Generative Language API lives at
``https://generativelanguage.googleapis.com/v1beta`` and, unlike NVIDIA
NIM / OpenAI / Groq / Together / OpenRouter, it does **not** speak the
OpenAI chat-completions wire format. It has its own request shape
(``contents`` / ``systemInstruction`` / ``generationConfig``), its own
response shape (``candidates[].content.parts[].text``), and — unusually
— it authenticates via a ``?key=<api_key>`` **URL query parameter**
rather than an ``Authorization`` header. This adapter therefore cannot
reuse the OpenAI-compatible payload/stream parser in ``nvidia_nim.py``
/ ``openai.py``; it speaks the Generative Language API directly.

This module targets the public Generative Language API only. Vertex AI
exposes broadly similar Gemini models behind a different endpoint
(``*-aiplatform.googleapis.com``) with bearer-token auth; that is a
separate backend and is out of scope here.

The adapter is registered lazily by ``registry.py`` via the
``"gemini": "src.research.providers.llm.gemini:build"`` entry, so
importing this file does **not** require a configured API key and does
not trigger any network I/O (Req 2.12).

Wire-format specifics
---------------------
* **Base URL** — ``https://generativelanguage.googleapis.com/v1beta``.
* **Endpoints** —
    * Non-streaming: ``POST /models/{model}:generateContent?key=<api_key>``.
    * Streaming:     ``POST /models/{model}:streamGenerateContent?alt=sse&key=<api_key>``.
* **Auth** — the API key is a URL query parameter. No ``Authorization``
  header is sent. The key is treated as a secret regardless — it must
  never appear in log records or error messages emitted by this module.
* **Role mapping** — Gemini uses ``"user"`` and ``"model"`` (not
  ``"assistant"``). Input ``Message.role == "assistant"`` is sent as
  ``"model"``; ``"user"`` is passed through unchanged. ``"system"`` is
  **not** a valid role inside ``contents``; all ``role == "system"``
  messages are concatenated with ``"\\n\\n"`` and sent via the top-level
  ``systemInstruction: {"parts": [{"text": ...}]}`` field. No reverse
  mapping is needed because ``Completion.content`` is a plain string.
* **``generationConfig``** — only the knobs the caller actually set are
  forwarded: ``temperature``, ``maxOutputTokens``, ``topP``,
  ``stopSequences``. Everything else falls back to Gemini's own
  defaults.
* **Response shape** — ``candidates[0].content.parts`` is a list of
  typed parts; we concatenate the ``text`` of every part so multi-part
  text responses collapse cleanly into ``Completion.content``.
* **Finish reason** — ``candidates[0].finishReason`` values map as:
  ``STOP`` → ``"stop"``, ``MAX_TOKENS`` → ``"length"``,
  ``SAFETY`` / ``RECITATION`` → ``"refusal"``, anything else →
  ``"error"``.
* **Usage** — ``usageMetadata.promptTokenCount`` and
  ``usageMetadata.candidatesTokenCount`` map onto
  ``Completion.input_tokens`` / ``output_tokens``.
* **SSE streaming** — with ``alt=sse`` Gemini emits ``data: {...}\\n\\n``
  frames whose JSON payload has the same shape as a single non-streaming
  response (one text delta per event in ``candidates[0].content.parts[0].text``).
  There is no ``[DONE]`` sentinel; the stream closes naturally when the
  server ends the connection.
* **Auth failure** — 401/403 map to
  ``ProviderAuthError(provider="gemini", model=…,
  error_code="PROVIDER_AUTH_FAILED")`` (Req 2.10). Gemini also returns
  400 with an ``"API key not valid"`` body for invalid keys; per the
  registry contract this adapter maps only 401/403 here, and the
  gateway error-mapping layer (Task 16.4) can inspect 400 bodies later
  if required.
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

# Public Generative Language API root (design §3.1). Vertex AI is a
# separate backend and is intentionally not covered here.
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_PROVIDER_NAME = "gemini"

# Upstream ``finishReason`` → normalised ``Completion.finish_reason``
# (design §3.1). ``SAFETY`` and ``RECITATION`` are both surfaced as
# ``"refusal"`` because the Guardrail_Layer (design §3.6) treats upstream
# safety / recitation blocks the same as our own refusals. Anything not
# listed (including ``OTHER`` and missing values) is coerced to
# ``"error"``.
_FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "refusal",
    "RECITATION": "refusal",
}


def _split_system_and_contents(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Extract Gemini's top-level ``systemInstruction`` text and ``contents``.

    Gemini rejects ``role: "system"`` inside ``contents``. We pull every
    ``role == "system"`` message out, concatenate their contents with
    ``"\\n\\n"``, and return that as the ``systemInstruction`` text; the
    remaining user/assistant turns are returned in original order as the
    ``contents`` payload with ``"assistant"`` rewritten to ``"model"``
    (the role name Gemini expects).

    Returns ``(None, contents)`` when the caller passed no system
    messages.
    """
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        # Gemini uses "model" for assistant turns; "user" passes through.
        gemini_role = "model" if m.role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": m.content}]})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, contents


class GeminiLLM:
    """Concrete ``LLMProvider`` hitting the Gemini Generative Language API.

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

        Gemini authenticates via a ``?key=`` URL query parameter, so no
        ``Authorization`` header is set here. ``Accept`` is switched to
        ``text/event-stream`` for streaming so the server honours the
        ``alt=sse`` response framing.
        """
        return {
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

    def _build_url(self, *, stream: bool) -> str:
        """Assemble the endpoint URL including the ``?key=`` query param.

        Streaming adds the additional ``alt=sse`` query parameter so
        the server emits SSE frames (``data: {...}\\n\\n``) instead of
        Gemini's default JSON-array streaming format, which this
        adapter does not parse.
        """
        if stream:
            method = "streamGenerateContent"
            query = f"?alt=sse&key={self._api_key}"
        else:
            method = "generateContent"
            query = f"?key={self._api_key}"
        return f"{self._base_url}/models/{self._model}:{method}{query}"

    def _build_payload(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> dict[str, Any]:
        """Assemble the Generative Language API request body.

        Differences from the OpenAI-compatible payload used by the NIM
        / OpenAI adapters:

        * System messages are pulled out into ``systemInstruction``
          rather than sent as a ``role: "system"`` turn.
        * Sampling knobs live under ``generationConfig`` with Gemini's
          own names (``maxOutputTokens`` / ``topP`` / ``stopSequences``).
        * No ``stream`` field is needed — streaming is selected by the
          ``:streamGenerateContent`` endpoint and ``alt=sse`` query
          parameter, not by a body flag.
        * Unknown keys passed via ``params.extra`` are forwarded
          verbatim for provider-specific knobs — Req 2.4 wants
          one-file-per-backend so there is no central allow-list to
          maintain.
        """
        system, contents = _split_system_and_contents(messages)

        payload: dict[str, Any] = {"contents": contents}
        if system is not None:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        generation_config: dict[str, Any] = {}
        if params.temperature is not None:
            generation_config["temperature"] = params.temperature
        if params.max_tokens is not None:
            generation_config["maxOutputTokens"] = params.max_tokens
        if params.top_p is not None:
            generation_config["topP"] = params.top_p
        if params.stop is not None:
            generation_config["stopSequences"] = params.stop
        if generation_config:
            payload["generationConfig"] = generation_config

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

    @staticmethod
    def _extract_text(candidate: dict[str, Any]) -> str:
        """Concatenate every ``text`` part from a candidate's content.

        Gemini may split a single assistant turn across multiple
        ``parts``; we stitch them back together so
        ``Completion.content`` is always a single plain string. Parts
        without a ``text`` field (e.g. future inline-data parts) are
        ignored — the Provider_Contract (Req 2.11) surfaces plain
        assistant text only.
        """
        parts = (candidate.get("content") or {}).get("parts") or []
        chunks: list[str] = []
        for part in parts:
            text = part.get("text")
            if text:
                chunks.append(text)
        return "".join(chunks)

    # ------------------------------------------------------------------ #
    # LLMProvider API                                                    #
    # ------------------------------------------------------------------ #

    async def complete(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> Completion:
        """Single non-streamed ``generateContent`` call (Req 2.11)."""
        payload = self._build_payload(messages, params)
        url = self._build_url(stream=False)

        async with httpx.AsyncClient(timeout=self._timeout(params)) as client:
            response = await client.post(
                url,
                headers=self._headers(stream=False),
                json=payload,
            )
            self._raise_on_auth(response.status_code)
            response.raise_for_status()
            body = response.json()

        candidates = body.get("candidates") or []
        # If Gemini returned no candidates (e.g. all filtered) we fall
        # back to empty content rather than raising; the Guardrail_Layer
        # downstream treats empty output as a refusal-like event.
        if candidates:
            candidate = candidates[0]
            content = self._extract_text(candidate)
            raw_finish = candidate.get("finishReason")
        else:
            content = ""
            raw_finish = None

        usage = body.get("usageMetadata") or {}
        finish_reason = _FINISH_REASON_MAP.get(raw_finish or "", "error")

        return Completion(
            provider=_PROVIDER_NAME,
            model=self._model,
            content=content,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Async iterator over ``:streamGenerateContent`` SSE deltas (design §3.1).

        With ``alt=sse`` Gemini frames each update as ``data: {...}\\n\\n``
        where the JSON payload has the same shape as a single
        non-streaming response. For each event we emit one
        ``CompletionChunk`` carrying the concatenated text of every
        ``candidates[0].content.parts[].text`` entry in that frame.
        Empty deltas are skipped so the chunk ``index`` counter advances
        in lock-step with visible output. There is no ``[DONE]``
        sentinel; the loop terminates naturally when the server closes
        the connection.
        """
        payload = self._build_payload(messages, params)
        url = self._build_url(stream=True)

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
                        # Gemini may emit comment lines (``:``) or other
                        # SSE framing fields that do not carry deltas.
                        continue
                    data = raw_line[len("data:") :].strip()
                    if not data:
                        continue

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        # Skip malformed frames; a later chunk will
                        # carry the full completion or the server will
                        # close.
                        continue

                    candidates = event.get("candidates") or []
                    if not candidates:
                        continue
                    delta = self._extract_text(candidates[0])
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
    ``config/settings.yaml`` — the same shape every LLM adapter
    consumes. Required keys: ``model``, ``api_key``. Optional:
    ``base_url`` (useful for pointing at a staging URL or a reverse
    proxy); defaults to ``https://generativelanguage.googleapis.com/v1beta``.

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
            f"gemini provider config is missing required key {missing!r}; "
            "expected 'model' and 'api_key' (see design §7.1).",
        ) from exc

    base_url = cfg.get("base_url") or _DEFAULT_BASE_URL
    return GeminiLLM(api_key=api_key, model=model, base_url=base_url)


__all__ = ["GeminiLLM", "build"]
