"""Unit tests for the single re-synthesis loop (Task 12.2).

Exercises :func:`src.research.judge.resynthesis.run_resynthesis_loop`
against stub ``synthesize_fn`` callbacks and a :class:`FakeLLMProvider`
so we never touch a real upstream. Covers the three terminal states
defined in design §11.2:

* First pass passes → ``quality="high"``, no re-synthesis, no redaction.
* First pass fails, second pass passes → ``quality="medium"`` on the
  re-synthesised brief, ``synthesize_fn`` called exactly once.
* First pass fails, second pass fails → ``quality="low"``, unsupported
  sections redacted to :data:`INSUFFICIENT_EVIDENCE`.

Plus the guardrails around the loop:

* Exactly one re-synthesis (Req 16.18) — ``synthesize_fn`` never
  called twice, even under repeated-failure scenarios.
* ``max_retries=0`` disables re-synthesis and short-circuits to
  ``quality="low"`` on the first failure.
* Negative ``max_retries`` raises :class:`ValueError`.
* Mapping and object-attribute briefs both round-trip through the
  loop without shape changes.
* Fallback report sections (``"<judge_error>"``) are not redacted
  on the brief.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.judge import (
    INSUFFICIENT_EVIDENCE,
    JudgeReport,
    ResynthesisOutcome,
    run_resynthesis_loop,
)
from src.research.judge.resynthesis import _is_passing, _redact_unsupported_sections
from src.research.validators.types import UnsupportedClaim

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _healthy_report(run_id: UUID, *, retry_count: int = 0) -> JudgeReport:
    """Build a passing :class:`JudgeReport` — every section at 0.9."""
    return JudgeReport(
        run_id=run_id,
        groundedness_score={
            "summary": 0.9,
            "thesis": 0.85,
            "risks": 0.8,
        },
        unsupported_claims=[],
        safe_to_display=True,
        retry_count=retry_count,
    )


def _failing_report(
    run_id: UUID,
    *,
    retry_count: int = 0,
    sections: tuple[str, ...] = ("risks",),
) -> JudgeReport:
    """Build a failing report with one unsupported claim per section."""
    claims = [
        UnsupportedClaim(
            section=section,
            claim_text=f"unsupported in {section}",
            start_offset=0,
            end_offset=10,
            reason="no_citation",
        )
        for section in sections
    ]
    scores = dict.fromkeys(sections, 0.5)
    # Include one healthy section so ``min_score`` has something to
    # compare — ``0.5 < 0.7`` still trips the gate.
    scores.setdefault("summary", 0.9)
    return JudgeReport(
        run_id=run_id,
        groundedness_score=scores,
        unsupported_claims=claims,
        safe_to_display=False,
        retry_count=retry_count,
    )


@dataclass
class _JudgeRecorder:
    """Records every call to the judge and returns canned reports in order."""

    run_id: UUID
    reports: list[JudgeReport]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, *, brief: Any, retry_count: int) -> JudgeReport:
        if not self.reports:
            raise AssertionError(
                "Judge called more times than the test configured; "
                f"no canned reports left. Received retry_count={retry_count}.",
            )
        self.calls.append({"brief": brief, "retry_count": retry_count})
        return self.reports.pop(0)


@dataclass
class _SynthesizeRecorder:
    """Records every re-synthesis call and returns the canned new brief."""

    new_brief: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(
        self,
        *,
        prior_brief: Any,
        unsupported_claims: tuple[UnsupportedClaim, ...],
        numeric_findings: tuple[UnsupportedClaim, ...],
    ) -> Any:
        self.calls.append(
            {
                "prior_brief": prior_brief,
                "unsupported_claims": unsupported_claims,
                "numeric_findings": numeric_findings,
            },
        )
        return self.new_brief


# --------------------------------------------------------------------------- #
# Happy path — first pass passes                                              #
# --------------------------------------------------------------------------- #


class TestFirstPassPasses:
    """First-pass success → quality='high', no re-synthesis."""

    @pytest.mark.asyncio
    async def test_returns_high_quality(self) -> None:
        run_id = uuid4()
        judge = _JudgeRecorder(run_id=run_id, reports=[_healthy_report(run_id)])
        synth = _SynthesizeRecorder(new_brief={})
        brief = {"summary": "Good [cite:c1].", "risks": "Known [cite:c2]."}

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=brief,
        )

        assert isinstance(outcome, ResynthesisOutcome)
        assert outcome.quality == "high"
        assert outcome.brief is brief
        assert outcome.unsupported_sections == frozenset()
        # Judge called exactly once (no re-synthesis).
        assert len(judge.calls) == 1
        assert judge.calls[0]["retry_count"] == 0
        # synthesize_fn never called on the happy path.
        assert synth.calls == []

    @pytest.mark.asyncio
    async def test_passes_brief_and_retry_count_through(self) -> None:
        run_id = uuid4()
        judge = _JudgeRecorder(run_id=run_id, reports=[_healthy_report(run_id)])
        brief = {"summary": "ok [cite:c1]."}

        await run_resynthesis_loop(
            synthesize_fn=_SynthesizeRecorder(new_brief={}),
            judge_fn=judge,
            brief=brief,
        )

        call = judge.calls[0]
        assert call["brief"] is brief
        assert call["retry_count"] == 0


# --------------------------------------------------------------------------- #
# Recovery path — first fails, re-synthesis passes                            #
# --------------------------------------------------------------------------- #


class TestResynthesisRecovers:
    """Design §11.2 recovery path → quality='medium'."""

    @pytest.mark.asyncio
    async def test_returns_medium_quality_and_new_brief(self) -> None:
        run_id = uuid4()
        first = _failing_report(run_id, retry_count=0)
        second = _healthy_report(run_id, retry_count=1)
        judge = _JudgeRecorder(run_id=run_id, reports=[first, second])
        new_brief = {"summary": "Revised [cite:c1].", "risks": "Known [cite:c2]."}
        synth = _SynthesizeRecorder(new_brief=new_brief)

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "Old [cite:c1].", "risks": "Vague."},
        )

        assert outcome.quality == "medium"
        assert outcome.brief is new_brief
        assert outcome.judge_report.retry_count == 1
        assert outcome.unsupported_sections == frozenset()

    @pytest.mark.asyncio
    async def test_synthesize_called_exactly_once(self) -> None:
        """Req 16.18 — exactly one re-synthesis pass."""
        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id, retry_count=0),
                _healthy_report(run_id, retry_count=1),
            ],
        )
        synth = _SynthesizeRecorder(new_brief={"summary": "revised"})

        await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "old"},
        )

        assert len(synth.calls) == 1
        assert len(judge.calls) == 2
        assert judge.calls[0]["retry_count"] == 0
        assert judge.calls[1]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_synthesize_receives_feedback(self) -> None:
        """Judge unsupported_claims + numeric_findings feed into synthesize_fn.

        Design §11.2: ``feedback = {unsupported_claims,
        numeric_validator_findings}``.
        """
        run_id = uuid4()
        first = _failing_report(run_id, sections=("risks", "thesis"))
        second = _healthy_report(run_id, retry_count=1)
        judge = _JudgeRecorder(run_id=run_id, reports=[first, second])
        synth = _SynthesizeRecorder(new_brief={"summary": "revised"})

        numeric = [
            UnsupportedClaim(
                section="financial_highlights",
                claim_text="₹5,678 Cr",
                start_offset=10,
                end_offset=19,
                reason="numeric_drift",
            ),
        ]
        brief = {"summary": "old", "risks": "vague"}

        await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=brief,
            numeric_findings=numeric,
        )

        assert len(synth.calls) == 1
        call = synth.calls[0]
        assert call["prior_brief"] is brief
        # All Judge-flagged claims are forwarded verbatim.
        forwarded_sections = {c.section for c in call["unsupported_claims"]}
        assert forwarded_sections == {"risks", "thesis"}
        # Numeric findings forwarded as a tuple for stable ordering.
        assert isinstance(call["numeric_findings"], tuple)
        assert len(call["numeric_findings"]) == 1
        assert call["numeric_findings"][0].reason == "numeric_drift"

    @pytest.mark.asyncio
    async def test_numeric_findings_generator_is_materialised(self) -> None:
        """A generator input is safe even though the loop only iterates once."""
        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id),
                _healthy_report(run_id, retry_count=1),
            ],
        )
        synth = _SynthesizeRecorder(new_brief={"summary": "revised"})

        def _gen() -> Iterable[UnsupportedClaim]:
            yield UnsupportedClaim(
                section="summary",
                claim_text="50%",
                start_offset=0,
                end_offset=3,
                reason="numeric_drift",
            )

        await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "ok"},
            numeric_findings=_gen(),
        )

        assert len(synth.calls[0]["numeric_findings"]) == 1


# --------------------------------------------------------------------------- #
# Failure path — both passes fail, redaction kicks in                         #
# --------------------------------------------------------------------------- #


class TestBothPassesFail:
    """Req 16.19 — quality='low' with unsupported sections redacted."""

    @pytest.mark.asyncio
    async def test_returns_low_quality(self) -> None:
        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id, sections=("risks",)),
                _failing_report(run_id, sections=("risks",), retry_count=1),
            ],
        )
        new_brief = {
            "summary": "Revised [cite:c1].",
            "risks": "Still vague, no citation.",
        }
        synth = _SynthesizeRecorder(new_brief=new_brief)

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "Old [cite:c1].", "risks": "Vague."},
        )

        assert outcome.quality == "low"
        assert outcome.judge_report.retry_count == 1
        # The second (re-synthesised) brief is what gets redacted —
        # it is the most recent best-effort output.
        assert outcome.brief["summary"] == "Revised [cite:c1]."
        assert outcome.brief["risks"] == INSUFFICIENT_EVIDENCE
        assert outcome.unsupported_sections == frozenset({"risks"})

    @pytest.mark.asyncio
    async def test_multiple_sections_redacted(self) -> None:
        run_id = uuid4()
        sections = ("risks", "thesis", "management_commentary")
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id, sections=sections),
                _failing_report(run_id, sections=sections, retry_count=1),
            ],
        )
        brief = {
            "summary": "Healthy [cite:c1].",
            "thesis": "Weak thesis.",
            "risks": "Weak risks.",
            "management_commentary": "Weak commentary.",
        }
        synth = _SynthesizeRecorder(new_brief=dict(brief))

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=brief,
        )

        assert outcome.quality == "low"
        assert outcome.brief["summary"] == "Healthy [cite:c1]."
        for section in sections:
            assert outcome.brief[section] == INSUFFICIENT_EVIDENCE
        assert outcome.unsupported_sections == frozenset(sections)

    @pytest.mark.asyncio
    async def test_synthesize_still_called_exactly_once(self) -> None:
        """Even when the second pass fails, synthesize_fn runs only once."""
        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id),
                _failing_report(run_id, retry_count=1),
            ],
        )
        synth = _SynthesizeRecorder(new_brief={"summary": "revised"})

        await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "ok"},
        )

        assert len(synth.calls) == 1


# --------------------------------------------------------------------------- #
# min_score cross-check                                                       #
# --------------------------------------------------------------------------- #


class TestMinScoreGate:
    """A Judge that claims safe=True but is below the loop's min_score triggers re-synthesis."""

    @pytest.mark.asyncio
    async def test_sub_threshold_score_triggers_resynthesis(self) -> None:
        """If the Judge's min score is below the loop's threshold, we re-synth.

        This guards against a Judge configured with a laxer
        ``min_score`` than the Orchestrator's; the loop's own
        threshold is authoritative (design §11.2 pass predicate).
        """
        run_id = uuid4()
        # Judge claims safe=True but min score is 0.65 — below our 0.7 gate.
        first = JudgeReport(
            run_id=run_id,
            groundedness_score={"summary": 0.9, "risks": 0.65},
            unsupported_claims=[
                UnsupportedClaim(
                    section="risks",
                    claim_text="weak claim",
                    start_offset=0,
                    end_offset=10,
                    reason="no_citation",
                ),
            ],
            safe_to_display=True,
        )
        second = _healthy_report(run_id, retry_count=1)
        judge = _JudgeRecorder(run_id=run_id, reports=[first, second])
        synth = _SynthesizeRecorder(new_brief={"summary": "revised", "risks": "ok"})

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief={"summary": "ok", "risks": "weak"},
            min_score=0.7,
        )

        # Re-synthesis ran and recovered.
        assert outcome.quality == "medium"
        assert len(synth.calls) == 1


# --------------------------------------------------------------------------- #
# max_retries knob                                                            #
# --------------------------------------------------------------------------- #


class TestMaxRetries:
    """``max_retries=0`` disables re-synthesis; negative values are a bug."""

    @pytest.mark.asyncio
    async def test_max_retries_zero_short_circuits_to_low(self) -> None:
        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[_failing_report(run_id, sections=("risks",))],
        )
        synth = _SynthesizeRecorder(new_brief={"summary": "unused"})
        brief = {"summary": "ok", "risks": "weak"}

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=brief,
            max_retries=0,
        )

        assert outcome.quality == "low"
        # Only the original brief was scored — no re-synthesis.
        assert len(judge.calls) == 1
        assert synth.calls == []
        # Redaction still runs on the failing sections.
        assert outcome.brief["risks"] == INSUFFICIENT_EVIDENCE
        assert outcome.unsupported_sections == frozenset({"risks"})

    @pytest.mark.asyncio
    async def test_negative_max_retries_raises(self) -> None:
        run_id = uuid4()
        judge = _JudgeRecorder(run_id=run_id, reports=[])

        with pytest.raises(ValueError):
            await run_resynthesis_loop(
                synthesize_fn=_SynthesizeRecorder(new_brief={}),
                judge_fn=judge,
                brief={"summary": "x"},
                max_retries=-1,
            )


# --------------------------------------------------------------------------- #
# Object-attribute briefs                                                     #
# --------------------------------------------------------------------------- #


class TestObjectBrief:
    """The loop also accepts a brief exposed as attributes, not a Mapping."""

    @pytest.mark.asyncio
    async def test_object_brief_redacted_in_place(self) -> None:
        @dataclass
        class BriefLike:
            summary: str = "Healthy [cite:c1]."
            thesis: str = ""
            risks: str = "Weak risks."
            financial_highlights: str = ""
            management_commentary: str = ""
            technical_view: str = ""
            peers: str = ""
            macro_context: str = ""

        run_id = uuid4()
        judge = _JudgeRecorder(
            run_id=run_id,
            reports=[
                _failing_report(run_id, sections=("risks",)),
                _failing_report(run_id, sections=("risks",), retry_count=1),
            ],
        )
        new_brief = BriefLike(summary="Revised [cite:c1].", risks="Still weak.")
        synth = _SynthesizeRecorder(new_brief=new_brief)

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=BriefLike(),
        )

        assert outcome.quality == "low"
        assert outcome.brief is new_brief
        assert new_brief.risks == INSUFFICIENT_EVIDENCE
        assert new_brief.summary == "Revised [cite:c1]."
        assert outcome.unsupported_sections == frozenset({"risks"})

    @pytest.mark.asyncio
    async def test_object_brief_happy_path_unchanged(self) -> None:
        @dataclass
        class BriefLike:
            summary: str = "Healthy [cite:c1]."

        run_id = uuid4()
        judge = _JudgeRecorder(run_id=run_id, reports=[_healthy_report(run_id)])
        synth = _SynthesizeRecorder(new_brief=None)
        brief = BriefLike()

        outcome = await run_resynthesis_loop(
            synthesize_fn=synth,
            judge_fn=judge,
            brief=brief,
        )

        assert outcome.quality == "high"
        assert outcome.brief is brief
        assert brief.summary == "Healthy [cite:c1]."


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


class TestIsPassing:
    """``_is_passing`` implements the design §11.2 pass predicate."""

    def test_safe_plus_scores_pass(self) -> None:
        report = JudgeReport(
            run_id=uuid4(),
            groundedness_score={"summary": 0.9, "risks": 0.8},
            safe_to_display=True,
        )
        assert _is_passing(report, min_score=0.7) is True

    def test_unsafe_fails(self) -> None:
        report = JudgeReport(
            run_id=uuid4(),
            groundedness_score={"summary": 0.9},
            safe_to_display=False,
        )
        assert _is_passing(report, min_score=0.7) is False

    def test_sub_threshold_fails_even_when_safe(self) -> None:
        """Operator's min_score cuts off even if the Judge says safe=True."""
        report = JudgeReport(
            run_id=uuid4(),
            groundedness_score={"summary": 0.9, "risks": 0.5},
            safe_to_display=True,
        )
        assert _is_passing(report, min_score=0.7) is False

    def test_empty_scores_fails(self) -> None:
        """An empty score dict → min_score()=0.0 → never passes."""
        report = JudgeReport(
            run_id=uuid4(),
            groundedness_score={},
            safe_to_display=True,
        )
        assert _is_passing(report, min_score=0.7) is False


class TestRedactUnsupportedSections:
    """``_redact_unsupported_sections`` preserves healthy sections."""

    def test_mapping_preserves_untouched_sections(self) -> None:
        run_id = uuid4()
        report = _failing_report(run_id, sections=("risks",))
        brief = {
            "summary": "Healthy.",
            "risks": "Unhealthy.",
            "thesis": "Also healthy.",
        }
        redacted, sections = _redact_unsupported_sections(brief, report)
        assert redacted["summary"] == "Healthy."
        assert redacted["thesis"] == "Also healthy."
        assert redacted["risks"] == INSUFFICIENT_EVIDENCE
        assert sections == frozenset({"risks"})
        # The caller's dict must not be mutated.
        assert brief["risks"] == "Unhealthy."

    def test_fallback_sentinel_section_is_ignored(self) -> None:
        """``<judge_error>`` from the fallback report is not redacted."""
        report = JudgeReport(
            run_id=uuid4(),
            safe_to_display=False,
            groundedness_score={"summary": 0.0},
            unsupported_claims=[
                UnsupportedClaim(
                    section="<judge_error>",
                    claim_text="provider boom",
                    start_offset=0,
                    end_offset=12,
                    reason="off_policy",
                ),
            ],
        )
        brief = {"summary": "Healthy."}
        redacted, sections = _redact_unsupported_sections(brief, report)
        assert redacted == {"summary": "Healthy."}
        assert sections == frozenset()

    def test_section_missing_from_brief_is_skipped(self) -> None:
        """Judge flags a section the brief does not expose → no-op redaction."""
        run_id = uuid4()
        report = _failing_report(run_id, sections=("risks",))
        brief = {"summary": "Healthy."}
        redacted, sections = _redact_unsupported_sections(brief, report)
        assert redacted == {"summary": "Healthy."}
        # `applied` only contains sections that exist on the brief.
        assert sections == frozenset()
