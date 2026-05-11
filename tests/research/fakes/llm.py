"""In-memory ``LLMProvider`` fake for Phase 6–12 tests (design §17.2).

The real LLM adapters in ``src/research/providers/llm/`` each require a
live upstream (NVIDIA NIM / OpenAI / Anthropic / …). Correctness
properties — latency SLO (Req 14.6), provider-swap invariance (Req 14.2),
Judge groundedness (Req 14.9) — need a deterministic, dependency-free
stand-in that still satisfies the ``LLMProvider`` Protocol from
``src/research/providers/base.py``.

``FakeLLMProvider`` provides exactly that. It is configurable along the
axes the property tests care about:

* ``latency_ms``          — controllable ``asyncio.sleep`` so the latency
                            SLO property can exercise budget boundaries
                            (Req 14.6 / design §17.1 row 6).
* ``canned_completion``   — fixed text returned from ``complete`` and
                            word-split across chunks in ``stream``. The
                            provider-swap property asserts the
                            ``Completion`` shape is stable regardless of
                            this content (Req 14.2).
* ``canned_input_tokens`` / ``canned_output_tokens`` — returned verbatim
                            so ``Completion`` validates with the exact
                            token counts tests want to assert on.
* ``finish_reason``       — one of the four values normalised by the real
                            adapters (``stop|length|refusal|error``).
* ``chunks``              — optional override for streaming deltas; if
                            ``None``, the canned completion is split on
                            whitespace (one chunk per word).

Used by:

* ``tests/research/test_prop_provider_swap.py`` (Task 2.20, Req 14.2).
* ``tests/research/test_prop_latency_slo.py``   (Task 13.x, Req 14.6).
* ``tests/research/test_prop_judge_groundedness.py`` (Req 14.9).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from src.research.providers.base import (
    Completion,
    CompletionChunk,
    LLMParams,
    LLMProvider,
    Message,
)

__all__ = ["FakeLLMProvider"]


class FakeLLMProvider(LLMProvider):
    """Deterministic, dependency-free ``LLMProvider`` implementation.

    The class inherits from the ``LLMProvider`` Protocol (runtime-checkable
    in ``base.py``) so that ``isinstance(FakeLLMProvider(), LLMProvider)``
    holds in every test — this is what the provider-swap property in
    Task 2.20 leans on.
    """

    def __init__(
        self,
        *,
        provider: str = "fake",
        model: str = "fake-model",
        canned_completion: str = "fake completion",
        canned_input_tokens: int = 10,
        canned_output_tokens: int = 20,
        finish_reason: str = "stop",
        latency_ms: int = 0,
        chunks: list[str] | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._canned_completion = canned_completion
        self._canned_input_tokens = canned_input_tokens
        self._canned_output_tokens = canned_output_tokens
        self._finish_reason = finish_reason
        self._latency_ms = latency_ms
        self._chunks = chunks

    # ------------------------------------------------------------------ #
    # LLMProvider contract                                               #
    # ------------------------------------------------------------------ #

    async def complete(
        self, messages: list[Message], params: LLMParams,
    ) -> Completion:
        """Return a canned ``Completion`` after the configured latency.

        ``messages`` and ``params`` are accepted but not inspected —
        tests drive behaviour via the constructor kwargs. The shape of
        the returned ``Completion`` must match what every real adapter
        returns (Req 2.11, Req 14.2).
        """
        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000)
        return Completion(
            provider=self._provider,
            model=self._model,
            content=self._canned_completion,
            input_tokens=self._canned_input_tokens,
            output_tokens=self._canned_output_tokens,
            finish_reason=self._finish_reason,  # type: ignore[arg-type]
        )

    async def stream(
        self, messages: list[Message], params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:
        """Yield ``CompletionChunk`` deltas word-by-word.

        If ``chunks`` was supplied at construction time, iterate over it
        verbatim; otherwise split the canned completion on whitespace so
        the streamed concatenation equals ``canned_completion`` (modulo
        spaces). Between yields, sleep ``latency_ms`` so the latency SLO
        property can exercise streaming budgets too.
        """
        deltas = self._chunks if self._chunks is not None else self._canned_completion.split()
        for index, delta in enumerate(deltas):
            if self._latency_ms > 0:
                await asyncio.sleep(self._latency_ms / 1000)
            yield CompletionChunk(
                provider=self._provider,
                model=self._model,
                delta=delta,
                index=index,
            )
