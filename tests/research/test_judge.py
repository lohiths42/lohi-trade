"""Unit tests for the Judge_LLM invocation module (Task 12.1).

Exercises :func:`src.research.judge.invoke` against
:class:`FakeLLMProvider` so we never touch a real upstream. Covers:

* JSON parsing of the structured Judge response (design §3.7, §11.1).
* Merging of deterministic numeric-validator findings into the
  report's ``unsupported_claims`` list (design §11.1).
* The ``safe_to_display`` override rules (design §11.1: off-policy
  findings, sub-threshold scores, or numeric drift all force False).
* Fail-soft behaviour on provider errors, non-JSON output, malformed
  JSON, and schema mismatches.
* Re-export surface — ``JudgeReport`` and ``invoke`` reachable from
  the ``src.research.judge`` package.

Property tests for judge groundedness (Req 14.9) live in a separate
file and are not in scope here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.research.judge import JudgeReport as JudgeReportExported
from src.research.judge import invoke as invoke_exported
from src.research.judge.judge import JudgeReport, invoke
from src.research.validators.types import UnsupportedClaim
from tests.research.fakes import FakeLLMProvider

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeChunk:
    """Duck-typed chunk — only ``.chunk_id`` and ``.text`` are read."""

    chunk_id: str
    text: str


def _healthy_payload(*, min_score: float = 0.7) -> dict:
    """Canonical 'all good' Judge response — every section at ``min_score``."""
    return {
        "groundedness_score": {
            "summary": 0.9,
            "thesis": 0.85,
            "risks": 0.8,
            "financial_highlights": 0.9,
            "management_commentary": 0.75,
            "technical_view": 0.8,
            "peers": 0.85,
            "macro_context": 0.9,
        },
        "unsupported_claims": [],
        "safe_to_display": True,
        "contradiction_pairs": [],
        "off_policy_findings": [],
    }


def _unhealthy_payload() -> dict:
    """Judge says 'not safe' — one section below min_score + one claim."""
    return {
        "groundedness_score": {
            "summary": 0.9,
            "risks": 0.6,  # below default min_score 0.7
        },
        "unsupported_claims": [
            {
                "section": "risks",
                "claim_text": "A claim that is not grounded in the chunks.",
                "start_offset": 0,
                "end_offset": 42,
                "reason": "no_citation",
            },
        ],
        "safe_to_display": False,
        "contradiction_pairs": [],
        "off_policy_findings": [],
    }


# --------------------------------------------------------------------------- #
# Re-export surface                                                           #
# --------------------------------------------------------------------------- #


class TestReexports:
    """Package-level symbols resolve to the implementation module."""

    def test_judge_report_reexported(self) -> None:
        assert JudgeReportExported is JudgeReport

    def test_invoke_reexported(self) -> None:
        assert invoke_exported is invoke


# --------------------------------------------------------------------------- #
# JudgeReport model                                                            #
# --------------------------------------------------------------------------- #


class TestJudgeReportModel:
    """Structural tests for the :class:`JudgeReport` Pydantic model."""

    def test_constructs_with_minimal_fields(self) -> None:
        run_id = uuid4()
        report = JudgeReport(run_id=run_id, safe_to_display=True)
        assert report.run_id == run_id
        assert report.safe_to_display is True
        assert report.groundedness_score == {}
        assert report.unsupported_claims == []
        assert report.contradiction_pairs == []
        assert report.off_policy_findings == []
        assert report.retry_count == 0
        assert report.elapsed_ms == 0
        assert report.model_id == ""

    def test_min_score_empty_returns_zero(self) -> None:
        report = JudgeReport(run_id=uuid4(), safe_to_display=False)
        assert report.min_score() == 0.0

    def test_min_score_returns_minimum(self) -> None:
        report = JudgeReport(
            run_id=uuid4(),
            safe_to_display=True,
            groundedness_score={"a": 0.9, "b": 0.72, "c": 0.85},
        )
        assert report.min_score() == pytest.approx(0.72)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(Exception):  # ValidationError
            JudgeReport(
                run_id=uuid4(),
                safe_to_display=True,
                unknown_field="x",  # type: ignore[call-arg]
            )


# --------------------------------------------------------------------------- #
# invoke — happy path                                                          #
# --------------------------------------------------------------------------- #


class TestInvokeHappyPath:
    """The Judge returns a healthy JSON payload."""

    @pytest.mark.asyncio
    async def test_all_sections_above_min_score(self) -> None:
        run_id = uuid4()
        llm = FakeLLMProvider(
            provider="fake_judge",
            model="judge-v1",
            canned_completion=json.dumps(_healthy_payload()),
        )
        report = await invoke(
            run_id=run_id,
            brief={"summary": "Revenue of ₹1,234 Cr [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="Revenue was ₹1,234 Cr.")],
            llm=llm,
        )
        assert isinstance(report, JudgeReport)
        assert report.run_id == run_id
        assert report.safe_to_display is True
        assert report.min_score() >= 0.7
        assert report.unsupported_claims == []
        assert report.model_id == "fake_judge/judge-v1"
        assert report.retry_count == 0
        assert report.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_retry_count_passthrough(self) -> None:
        """Orchestrator-supplied ``retry_count`` is echoed back verbatim."""
        llm = FakeLLMProvider(canned_completion=json.dumps(_healthy_payload()))
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="ok")],
            llm=llm,
            retry_count=1,
        )
        assert report.retry_count == 1

    @pytest.mark.asyncio
    async def test_json_in_prose_is_extracted(self) -> None:
        """An LLM that wraps JSON in prose is still parseable."""
        payload = _healthy_payload()
        wrapped = (
            f"Here is the JudgeReport you asked for:\n```json\n"
            f"{json.dumps(payload)}\n```\nHope this helps."
        )
        llm = FakeLLMProvider(canned_completion=wrapped)
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "Ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="ok")],
            llm=llm,
        )
        assert report.safe_to_display is True


# --------------------------------------------------------------------------- #
# invoke — unhealthy / override rules                                          #
# --------------------------------------------------------------------------- #


class TestInvokeOverrideRules:
    """Design §11.1 override: ``safe_to_display`` is False under any of the
    three conditions (off-policy, sub-threshold score, numeric drift).
    """

    @pytest.mark.asyncio
    async def test_sub_threshold_score_forces_unsafe(self) -> None:
        llm = FakeLLMProvider(canned_completion=json.dumps(_unhealthy_payload()))
        report = await invoke(
            run_id=uuid4(),
            brief={"risks": "Risk claim [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="some chunk")],
            llm=llm,
            min_score=0.7,
        )
        assert report.safe_to_display is False
        assert report.min_score() == pytest.approx(0.6)
        assert len(report.unsupported_claims) == 1

    @pytest.mark.asyncio
    async def test_off_policy_forces_unsafe_even_with_high_scores(self) -> None:
        """Non-empty off_policy_findings → unsafe even if scores pass."""
        payload = _healthy_payload()
        payload["off_policy_findings"] = ["stock price prediction"]
        # The model may claim safe=True; the override must still flip it.
        payload["safe_to_display"] = True
        llm = FakeLLMProvider(canned_completion=json.dumps(payload))
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=llm,
        )
        assert report.safe_to_display is False
        assert report.off_policy_findings == ["stock price prediction"]

    @pytest.mark.asyncio
    async def test_numeric_drift_in_findings_forces_unsafe(self) -> None:
        """A numeric_drift claim in ``numeric_findings`` overrides safe=True."""
        payload = _healthy_payload()
        llm = FakeLLMProvider(canned_completion=json.dumps(payload))
        numeric_finding = UnsupportedClaim(
            section="financial_highlights",
            claim_text="₹5,678 Cr",
            start_offset=10,
            end_offset=19,
            reason="numeric_drift",
        )
        report = await invoke(
            run_id=uuid4(),
            brief={"financial_highlights": "Revenue was ₹5,678 Cr [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="Revenue was ₹1,234 Cr.")],
            numeric_findings=[numeric_finding],
            llm=llm,
        )
        assert report.safe_to_display is False
        # The numeric finding landed in the merged claim list.
        assert any(
            c.reason == "numeric_drift" and c.claim_text == "₹5,678 Cr"
            for c in report.unsupported_claims
        )

    @pytest.mark.asyncio
    async def test_contradiction_pairs_preserved(self) -> None:
        payload = _healthy_payload()
        payload["contradiction_pairs"] = [
            ["Revenue grew 10%", "Revenue fell 5%"],
        ]
        llm = FakeLLMProvider(canned_completion=json.dumps(payload))
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=llm,
        )
        assert report.contradiction_pairs == [
            ("Revenue grew 10%", "Revenue fell 5%"),
        ]


# --------------------------------------------------------------------------- #
# invoke — numeric findings merge                                              #
# --------------------------------------------------------------------------- #


class TestInvokeNumericFindingsMerge:
    """Deterministic numeric findings merge into ``unsupported_claims``."""

    @pytest.mark.asyncio
    async def test_findings_added_to_empty_judge_claims(self) -> None:
        llm = FakeLLMProvider(canned_completion=json.dumps(_healthy_payload()))
        finding = UnsupportedClaim(
            section="summary",
            claim_text="50%",
            start_offset=5,
            end_offset=8,
            reason="numeric_drift",
        )
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "Up 50% [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="Up 50%.")],
            numeric_findings=[finding],
            llm=llm,
        )
        # The numeric finding is in the merged list even though the
        # Judge itself returned no claims.
        assert finding in report.unsupported_claims

    @pytest.mark.asyncio
    async def test_duplicate_findings_deduplicated(self) -> None:
        """A finding present in both numeric_findings and the Judge output
        appears only once in the merged list.
        """
        claim_dict = {
            "section": "summary",
            "claim_text": "50%",
            "start_offset": 5,
            "end_offset": 8,
            "reason": "numeric_drift",
        }
        payload = _healthy_payload()
        payload["unsupported_claims"] = [claim_dict]
        llm = FakeLLMProvider(canned_completion=json.dumps(payload))
        finding = UnsupportedClaim(**claim_dict)
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "Up 50% [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="Up 50%.")],
            numeric_findings=[finding],
            llm=llm,
        )
        matching = [
            c
            for c in report.unsupported_claims
            if c.claim_text == "50%" and c.reason == "numeric_drift"
        ]
        assert len(matching) == 1


# --------------------------------------------------------------------------- #
# invoke — fail-soft paths                                                     #
# --------------------------------------------------------------------------- #


class TestInvokeFailSoft:
    """Every failure path reduces to ``safe_to_display=False``."""

    @pytest.mark.asyncio
    async def test_non_json_content_returns_unsafe(self) -> None:
        llm = FakeLLMProvider(canned_completion="Not JSON at all — sorry.")
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=llm,
        )
        assert report.safe_to_display is False
        assert len(report.unsupported_claims) == 1
        assert report.unsupported_claims[0].section == "<judge_error>"
        assert "json_parse_error" in report.off_policy_findings[0]

    @pytest.mark.asyncio
    async def test_malformed_json_returns_unsafe(self) -> None:
        llm = FakeLLMProvider(canned_completion='{"groundedness_score": {')
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=llm,
        )
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_schema_mismatch_returns_unsafe(self) -> None:
        """Wrong JSON *shape* (e.g. scores as list) reduces to unsafe."""
        bad = {
            "groundedness_score": ["not a dict"],
            "unsupported_claims": [],
            "safe_to_display": True,
            "contradiction_pairs": [],
            "off_policy_findings": [],
        }
        llm = FakeLLMProvider(canned_completion=json.dumps(bad))
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=llm,
        )
        assert report.safe_to_display is False
        assert any("schema_error" in f for f in report.off_policy_findings)

    @pytest.mark.asyncio
    async def test_provider_exception_returns_unsafe(self) -> None:
        """An LLMProvider that raises reduces to a fallback report."""

        class BoomLLM:
            async def complete(self, messages, params):
                raise RuntimeError("upstream exploded")

            async def stream(self, messages, params):  # pragma: no cover
                yield  # never called

        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "ok [cite:c1]."},
            chunks=[_FakeChunk(chunk_id="c1", text="x")],
            llm=BoomLLM(),
        )
        assert report.safe_to_display is False
        assert any("provider_error" in f for f in report.off_policy_findings)

    @pytest.mark.asyncio
    async def test_requires_llm_or_config(self) -> None:
        with pytest.raises(ValueError):
            await invoke(
                run_id=uuid4(),
                brief={"summary": "x"},
                chunks=[],
            )


# --------------------------------------------------------------------------- #
# invoke — brief + chunks coercion                                             #
# --------------------------------------------------------------------------- #


class TestInvokeInputCoercion:
    """Brief and chunks accept duck-typed shapes."""

    @pytest.mark.asyncio
    async def test_accepts_object_brief(self) -> None:
        """Any object exposing canonical section attributes works."""

        class BriefLike:
            summary = "Revenue ₹100 Cr [cite:c1]."
            thesis = ""
            risks = ""
            financial_highlights = ""
            management_commentary = ""
            technical_view = ""
            peers = ""
            macro_context = ""

        llm = FakeLLMProvider(canned_completion=json.dumps(_healthy_payload()))
        report = await invoke(
            run_id=uuid4(),
            brief=BriefLike(),
            chunks=[_FakeChunk(chunk_id="c1", text="Reported ₹100 Cr")],
            llm=llm,
        )
        assert report.safe_to_display is True

    @pytest.mark.asyncio
    async def test_empty_chunks_still_works(self) -> None:
        """No cited chunks — the prompt renders a sentinel; judge still runs."""
        llm = FakeLLMProvider(canned_completion=json.dumps(_healthy_payload()))
        report = await invoke(
            run_id=uuid4(),
            brief={"summary": "x"},
            chunks=[],
            llm=llm,
        )
        # The canned payload says safe=True, and with no numeric
        # findings and no off-policy hits, the override permits it.
        assert report.safe_to_display is True
