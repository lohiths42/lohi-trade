"""Unit tests for offline-mode Judge dispatch (Task 19.3).

When ``LOHI_RESEARCH_OFFLINE=true``, :func:`src.research.judge.invoke`
MUST dispatch to the deterministic rule-based judge
(:func:`src.research.judge.rule_based.invoke_rule_based`) rather than
invoking any LLM. The rule-based report carries
``model_id="rule_based/v1"`` so operators inspecting
``research_judge_reports`` can tell the two paths apart (Req 16.22,
design §11.4).

Assertions:

* Offline mode dispatches to the rule-based judge and the provided
  LLM is **never** called.
* Online mode (env unset) still calls the LLM and the returned
  ``model_id`` reflects the provider/model combination.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.research.judge.judge import JudgeReport, invoke
from src.research.providers.base import (
    Completion,
    CompletionChunk,
    LLMParams,
    LLMProvider,
    Message,
)

# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeChunk:
    """Minimal duck-typed chunk — only ``.chunk_id`` and ``.text`` read."""

    chunk_id: str
    text: str


class _RaisingLLM(LLMProvider):
    """Fake LLM that records calls and raises if anybody touches ``complete``.

    The offline dispatch test asserts that :func:`invoke` never touches
    the LLM — having ``complete`` raise on entry turns "the LLM was
    called" into a test failure even if the assertion on
    :attr:`complete_called` is omitted.
    """

    def __init__(self) -> None:
        self.complete_called = False
        self.stream_called = False

    async def complete(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> Completion:  # pragma: no cover - should never fire in these tests
        self.complete_called = True
        raise AssertionError(
            "LLMProvider.complete() must not be called when "
            "LOHI_RESEARCH_OFFLINE=true — the offline dispatch rule "
            "requires the rule-based judge instead (Req 16.22).",
        )

    async def stream(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:  # pragma: no cover - unused here
        self.stream_called = True
        if False:
            yield  # type: ignore[unreachable]


class _CannedJSONLLM(LLMProvider):
    """Fake LLM returning a canned healthy Judge-JSON response.

    Used by the online-mode test: we assert the LLM path ran by
    checking :attr:`complete_called` and by reading
    :attr:`JudgeReport.model_id`, which the real :func:`invoke`
    derives from the completion's ``provider`` / ``model``.
    """

    def __init__(self, provider: str = "fake", model: str = "fake-model") -> None:
        self._provider = provider
        self._model = model
        self.complete_called = False

    async def complete(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> Completion:
        self.complete_called = True
        payload = {
            "groundedness_score": {"summary": 0.95},
            "unsupported_claims": [],
            "safe_to_display": True,
            "contradiction_pairs": [],
            "off_policy_findings": [],
        }
        return Completion(
            provider=self._provider,
            model=self._model,
            content=json.dumps(payload),
            input_tokens=10,
            output_tokens=20,
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[Message],
        params: LLMParams,
    ) -> AsyncIterator[CompletionChunk]:  # pragma: no cover - unused here
        if False:
            yield  # type: ignore[unreachable]


# --------------------------------------------------------------------------- #
# Offline dispatch                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_judge_offline_dispatches_to_rule_based(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline mode must route to the rule-based judge (Req 16.22).

    Uses a :class:`_RaisingLLM` so any accidental LLM invocation fails
    the test loudly. Asserts:

    * The returned report's ``model_id`` is ``"rule_based/v1"``,
      the canonical identifier stamped by
      :mod:`src.research.judge.rule_based`.
    * The LLM was never called.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    llm = _RaisingLLM()

    report = await invoke(
        run_id=uuid4(),
        brief={"summary": "X [cite:c1]."},
        chunks=[_FakeChunk(chunk_id="c1", text="X is a placeholder sentence.")],
        llm=llm,
    )

    assert isinstance(report, JudgeReport)
    assert report.model_id == "rule_based/v1"
    assert not llm.complete_called
    assert not llm.stream_called


@pytest.mark.asyncio
async def test_judge_offline_dispatch_ignores_llm_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline mode must not resolve the registry factory either.

    Passing a cloud ``llm_config`` would normally resolve through the
    registry and raise :class:`CloudProviderForbiddenError` (Task 19.1).
    With the offline dispatch in place, the rule-based judge runs
    **before** any factory resolution happens — so no guardrail error
    fires and we get a rule-based report.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")

    report = await invoke(
        run_id=uuid4(),
        brief={"summary": "Revenue rose [cite:c1]."},
        chunks=[_FakeChunk(chunk_id="c1", text="Revenue rose by a lot.")],
        llm_config={"provider": "openai", "model": "gpt-4o"},
    )

    assert report.model_id == "rule_based/v1"


@pytest.mark.asyncio
async def test_judge_offline_rule_based_respects_min_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule-based judge honours the caller's ``min_score`` floor.

    An uncited section drops the groundedness fraction to 0 and
    forces ``safe_to_display=False``. This test mainly confirms the
    dispatch forwards the ``min_score`` and ``retry_count`` kwargs
    through untouched.
    """
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "true")
    llm = _RaisingLLM()

    report = await invoke(
        run_id=uuid4(),
        brief={"summary": "An uncited sentence with no citation marker."},
        chunks=[],
        llm=llm,
        min_score=0.7,
        retry_count=1,
    )

    assert report.model_id == "rule_based/v1"
    assert report.retry_count == 1
    # Uncited sentence must produce an unsupported_claim (design §11.4).
    assert any(claim.reason == "no_citation" for claim in report.unsupported_claims)
    assert report.safe_to_display is False
    assert not llm.complete_called


# --------------------------------------------------------------------------- #
# Online dispatch                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_judge_online_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Online mode continues to invoke the LLM-backed judge.

    Asserts that:

    * The LLM's ``complete`` method was called.
    * The returned report's ``model_id`` reflects the fake provider /
      model, not ``"rule_based/v1"``.
    """
    monkeypatch.delenv("LOHI_RESEARCH_OFFLINE", raising=False)
    llm = _CannedJSONLLM(provider="fake", model="fake-model")

    report = await invoke(
        run_id=uuid4(),
        brief={"summary": "Revenue rose 10% [cite:c1]."},
        chunks=[_FakeChunk(chunk_id="c1", text="Revenue rose 10% year on year.")],
        llm=llm,
    )

    assert llm.complete_called is True
    assert report.model_id == "fake/fake-model"
    assert report.model_id != "rule_based/v1"


@pytest.mark.asyncio
async def test_judge_online_with_falsy_env_value_still_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any non-truthy env value keeps the online path in force."""
    monkeypatch.setenv("LOHI_RESEARCH_OFFLINE", "false")
    llm = _CannedJSONLLM()

    report = await invoke(
        run_id=uuid4(),
        brief={"summary": "A cited sentence [cite:c1]."},
        chunks=[_FakeChunk(chunk_id="c1", text="Source text for citation.")],
        llm=llm,
    )

    assert llm.complete_called is True
    assert report.model_id.startswith("fake/")
