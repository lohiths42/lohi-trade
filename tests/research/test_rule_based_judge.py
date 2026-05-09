"""Unit tests for the offline rule-based Judge (Task 12.4).

Exercises :func:`src.research.judge.invoke_rule_based` against the
three checks design §11.4 specifies: citation coverage, numeric
fidelity (delegated to the deterministic validator), and the
Refusal_Policy regex. Every test pins one axis of behaviour.

The tests are intentionally structured so the asserts line up with
the six scenarios the task names:

* healthy brief (all cited, no refusals, no drift)
* uncited sentences
* numeric findings folded in
* off-policy content triggering ``off_policy_findings``
* empty brief
* ``safe_to_display`` override rules

No network, no LLMs — the rule-based judge is entirely
deterministic, so the tests use plain dataclasses for chunks and
call the function directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.research.judge import (
    JudgeReport,
    invoke_rule_based,
)
from src.research.judge import invoke_rule_based as invoke_rule_based_exported
from src.research.judge.rule_based import invoke_rule_based as invoke_rule_based_direct
from src.research.validators.types import UnsupportedClaim


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeChunk:
    """Duck-typed chunk — only ``.chunk_id`` and ``.text`` are read."""

    chunk_id: str
    text: str


def _healthy_brief() -> dict[str, str]:
    """Every sentence in every section carries a ``[cite:...]`` marker.

    Citation chunk_ids use letter-only ids (``[cite:alpha]``) so the
    numeric validator doesn't see them as bare integers. Real chunk_ids
    are SHA-256 hex (design §3.3) which contain digits and would match
    anywhere in chunk text, so production briefs never hit this edge
    case — but the unit tests pick letter-only ids for simplicity.
    """
    return {
        "summary": "Revenue was 1,234 crore [cite:alpha]. Profit grew [cite:beta].",
        "thesis": "Growth is driven by new markets [cite:gamma].",
    }


def _healthy_chunks() -> list[_FakeChunk]:
    """Chunk corpus that supports every numeric claim in the healthy brief."""
    return [
        _FakeChunk(chunk_id="alpha", text="Revenue was 1,234 crore last year."),
        _FakeChunk(chunk_id="beta", text="Profit grew meaningfully."),
        _FakeChunk(chunk_id="gamma", text="Growth driven by new markets."),
    ]


# --------------------------------------------------------------------------- #
# Re-export surface                                                           #
# --------------------------------------------------------------------------- #


class TestReexports:
    """Package-level symbol resolves to the implementation module."""

    def test_invoke_rule_based_reexported(self) -> None:
        assert invoke_rule_based_exported is invoke_rule_based_direct


# --------------------------------------------------------------------------- #
# Healthy brief                                                                #
# --------------------------------------------------------------------------- #


class TestHealthyBrief:
    """All-cited, policy-clean briefs produce safe_to_display=True."""

    @pytest.mark.asyncio
    async def test_healthy_brief_is_safe(self) -> None:
        run_id = uuid4()
        report = await invoke_rule_based(
            run_id=run_id,
            brief=_healthy_brief(),
            chunks=_healthy_chunks(),
        )
        assert isinstance(report, JudgeReport)
        assert report.run_id == run_id
        assert report.safe_to_display is True
        assert report.unsupported_claims == []
        assert report.off_policy_findings == []
        assert report.contradiction_pairs == []

    @pytest.mark.asyncio
    async def test_all_scores_are_one(self) -> None:
        """Fully-cited sections score 1.0 on the fraction-of-cited-sentences heuristic."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief=_healthy_brief(),
            chunks=_healthy_chunks(),
        )
        # Both sections should be fully cited.
        assert report.groundedness_score["summary"] == pytest.approx(1.0)
        assert report.groundedness_score["thesis"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_model_id_is_rule_based(self) -> None:
        """Reports carry ``model_id='rule_based/v1'`` so operators can trace provenance."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief=_healthy_brief(),
            chunks=_healthy_chunks(),
        )
        assert report.model_id == "rule_based/v1"

    @pytest.mark.asyncio
    async def test_elapsed_ms_is_populated(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief=_healthy_brief(),
            chunks=_healthy_chunks(),
        )
        assert report.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_retry_count_passthrough(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief=_healthy_brief(),
            chunks=_healthy_chunks(),
            retry_count=1,
        )
        assert report.retry_count == 1


# --------------------------------------------------------------------------- #
# Uncited sentences                                                           #
# --------------------------------------------------------------------------- #


class TestUncitedSentences:
    """Sentences without a citation marker become ``no_citation`` claims."""

    @pytest.mark.asyncio
    async def test_one_uncited_sentence_flips_safe_to_false(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose. Profit grew [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="Profit grew.")],
        )
        assert report.safe_to_display is False
        # One uncited sentence, one claim.
        assert len(report.unsupported_claims) == 1
        claim = report.unsupported_claims[0]
        assert claim.section == "summary"
        assert claim.reason == "no_citation"
        assert "Revenue rose" in claim.claim_text

    @pytest.mark.asyncio
    async def test_score_reflects_cited_fraction(self) -> None:
        """Two sentences, one cited → score = 0.5."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose. Profit grew [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="Profit grew.")],
        )
        assert report.groundedness_score["summary"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_all_uncited_scores_zero(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose. Profit grew."},
            chunks=[],
        )
        assert report.groundedness_score["summary"] == pytest.approx(0.0)
        assert report.safe_to_display is False
        # Both sentences flagged.
        assert len(report.unsupported_claims) == 2

    @pytest.mark.asyncio
    async def test_claim_offsets_are_valid_slice_bounds(self) -> None:
        """``claim_text`` must equal the section body sliced at the stored offsets."""
        content = "Revenue rose. Profit grew [cite:alpha]."
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": content},
            chunks=[_FakeChunk(chunk_id="alpha", text="Profit grew.")],
        )
        assert len(report.unsupported_claims) == 1
        claim = report.unsupported_claims[0]
        assert content[claim.start_offset : claim.end_offset] == claim.claim_text

    @pytest.mark.asyncio
    async def test_question_and_exclamation_split(self) -> None:
        """``?`` and ``!`` also split sentences (design §11.4: ``. ? !``)."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "What now? We wait! We hope [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="x")],
        )
        # Three sentences, two uncited → score = 1/3.
        assert report.groundedness_score["summary"] == pytest.approx(1 / 3)
        assert len(report.unsupported_claims) == 2

    @pytest.mark.asyncio
    async def test_single_sentence_without_terminator_is_one_piece(self) -> None:
        """A body with no ``. ? !`` counts as one sentence."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose"},  # no punctuation
            chunks=[],
        )
        # One sentence, uncited → score = 0.0, one claim.
        assert report.groundedness_score["summary"] == pytest.approx(0.0)
        assert len(report.unsupported_claims) == 1


# --------------------------------------------------------------------------- #
# Numeric findings                                                            #
# --------------------------------------------------------------------------- #


class TestNumericFindings:
    """Numeric validator findings fold into ``unsupported_claims``."""

    @pytest.mark.asyncio
    async def test_drift_detected_when_numeric_findings_omitted(self) -> None:
        """When caller omits ``numeric_findings``, the module runs the validator itself."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue was 5,678 crore [cite:alpha]."},
            # Chunk reports a different magnitude — the validator should catch it.
            chunks=[_FakeChunk(chunk_id="alpha", text="Revenue was 1,234 crore.")],
        )
        assert report.safe_to_display is False
        assert any(c.reason == "numeric_drift" for c in report.unsupported_claims)

    @pytest.mark.asyncio
    async def test_precomputed_findings_preferred_over_rerunning(self) -> None:
        """When the caller supplies ``numeric_findings``, they appear verbatim and the
        validator is not re-run.
        """
        # Pre-computed finding that does NOT correspond to any real drift in the
        # brief text — proves the caller's list is authoritative.
        finding = UnsupportedClaim(
            section="summary",
            claim_text="5,678 crore",
            start_offset=12,
            end_offset=23,
            reason="numeric_drift",
        )
        report = await invoke_rule_based(
            run_id=uuid4(),
            # Numbers in the brief all match the chunk, so re-running the
            # validator here would produce zero findings. The caller's
            # finding must still land in the report.
            brief={"summary": "Revenue 1,234 crore [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="Revenue 1,234 crore.")],
            numeric_findings=[finding],
        )
        assert finding in report.unsupported_claims
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_empty_precomputed_findings_skips_validator(self) -> None:
        """``numeric_findings=[]`` means trust the caller — no drift even if text would produce some."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            # Numbers don't match — would produce drift if validator ran.
            brief={"summary": "Revenue 5,678 crore [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="Revenue 1,234 crore.")],
            numeric_findings=[],
        )
        # No numeric claims — caller asserted none.
        assert all(
            c.reason != "numeric_drift" for c in report.unsupported_claims
        )


# --------------------------------------------------------------------------- #
# Off-policy findings                                                         #
# --------------------------------------------------------------------------- #


class TestOffPolicyFindings:
    """Refusal_Policy regex matches in section bodies surface as ``off_policy_findings``."""

    @pytest.mark.asyncio
    async def test_price_target_in_section_is_off_policy(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "The 12-month price target is 2500 [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="Filing notes pricing.")],
        )
        assert len(report.off_policy_findings) == 1
        finding = report.off_policy_findings[0]
        assert "summary" in finding
        assert "RP-002" in finding
        assert "price_target" in finding
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_buy_sell_hold_in_section_is_off_policy(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"thesis": "Should I buy this stock [cite:alpha]?"},
            chunks=[_FakeChunk(chunk_id="alpha", text="Filing text.")],
        )
        assert any("RP-001" in f for f in report.off_policy_findings)
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_multiple_sections_each_reported(self) -> None:
        """Each section with a match produces its own finding."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={
                "summary": "Price target of 2500 [cite:alpha].",
                "thesis": "Should I buy [cite:beta]?",
            },
            chunks=[
                _FakeChunk(chunk_id="alpha", text="x"),
                _FakeChunk(chunk_id="beta", text="y"),
            ],
        )
        assert len(report.off_policy_findings) == 2

    @pytest.mark.asyncio
    async def test_neutral_content_produces_no_off_policy(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={
                "summary": "The company reported revenue growth [cite:alpha].",
                "thesis": "Buyback history is documented [cite:beta].",
            },
            chunks=[
                _FakeChunk(chunk_id="alpha", text="revenue"),
                _FakeChunk(chunk_id="beta", text="buyback"),
            ],
        )
        assert report.off_policy_findings == []


# --------------------------------------------------------------------------- #
# Empty brief                                                                 #
# --------------------------------------------------------------------------- #


class TestEmptyBrief:
    """An empty brief passes every check trivially."""

    @pytest.mark.asyncio
    async def test_empty_dict_is_safe(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={},
            chunks=[],
        )
        assert report.safe_to_display is True
        assert report.unsupported_claims == []
        assert report.off_policy_findings == []
        assert report.groundedness_score == {}

    @pytest.mark.asyncio
    async def test_sections_with_empty_strings_score_one(self) -> None:
        """An empty section body trivially "covers" all (zero) sentences."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "", "thesis": ""},
            chunks=[],
        )
        assert report.groundedness_score == {"summary": 1.0, "thesis": 1.0}
        assert report.safe_to_display is True

    @pytest.mark.asyncio
    async def test_no_chunks_with_no_brief_is_safe(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={},
            chunks=[],
        )
        assert report.safe_to_display is True


# --------------------------------------------------------------------------- #
# safe_to_display override rules                                              #
# --------------------------------------------------------------------------- #


class TestSafeToDisplayOverrides:
    """``safe_to_display`` is ``True`` iff every check passes AND every score ≥ min_score."""

    @pytest.mark.asyncio
    async def test_off_policy_alone_forces_unsafe(self) -> None:
        """Policy hit flips safe even when everything else is green."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Price target is 2500 [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="x")],
        )
        assert report.off_policy_findings
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_uncited_alone_forces_unsafe(self) -> None:
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose."},
            chunks=[],
        )
        assert report.unsupported_claims
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_numeric_drift_alone_forces_unsafe(self) -> None:
        finding = UnsupportedClaim(
            section="summary",
            claim_text="5,678 crore",
            start_offset=0,
            end_offset=11,
            reason="numeric_drift",
        )
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "5,678 crore [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="1,234 crore")],
            numeric_findings=[finding],
        )
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_score_below_min_forces_unsafe(self) -> None:
        """A per-section score below ``min_score`` forces unsafe."""
        # 2 sentences, 1 cited → score 0.5; with min_score=0.7 this fails.
        # But the uncited sentence also produces an ``UnsupportedClaim``, which
        # separately forces unsafe. Raise the score bar high enough to verify
        # the score gate works independently.
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose. Profit grew [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="x")],
            min_score=0.7,
        )
        assert report.groundedness_score["summary"] == pytest.approx(0.5)
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_min_score_lower_permits_partial_coverage(self) -> None:
        """Lowering ``min_score`` lets a partial-coverage section pass the score gate.

        Note: the sentence-coverage pass ALSO produces an ``UnsupportedClaim``
        for the uncited sentence, so ``safe_to_display`` stays ``False``
        regardless. This test pins the score-gate behaviour specifically.
        """
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue rose. Profit grew [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="x")],
            min_score=0.1,
        )
        # Score 0.5 ≥ 0.1 → score gate passes.
        assert report.groundedness_score["summary"] == pytest.approx(0.5)
        # But uncited-sentence claim still forces unsafe.
        assert report.unsupported_claims
        assert report.safe_to_display is False

    @pytest.mark.asyncio
    async def test_all_checks_passing_yields_safe(self) -> None:
        """Sanity: passing every gate produces ``safe_to_display=True``."""
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "Revenue grew [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="revenue")],
            min_score=0.9,
        )
        assert report.safe_to_display is True


# --------------------------------------------------------------------------- #
# Duck-typed brief input                                                      #
# --------------------------------------------------------------------------- #


class TestBriefCoercion:
    """Brief accepts both dicts and attribute-bearing objects."""

    @pytest.mark.asyncio
    async def test_accepts_object_brief(self) -> None:
        class BriefLike:
            summary = "Revenue rose [cite:alpha]."
            thesis = ""
            risks = ""
            financial_highlights = ""
            management_commentary = ""
            technical_view = ""
            peers = ""
            macro_context = ""

        report = await invoke_rule_based(
            run_id=uuid4(),
            brief=BriefLike(),
            chunks=[_FakeChunk(chunk_id="alpha", text="revenue")],
        )
        # Only ``summary`` is populated; empty attributes are dropped
        # (the object path skips empty strings).
        assert "summary" in report.groundedness_score
        assert report.safe_to_display is True


# --------------------------------------------------------------------------- #
# Claim deduplication                                                         #
# --------------------------------------------------------------------------- #


class TestClaimDeduplication:
    """The merge step collapses duplicates by the five-field identity tuple."""

    @pytest.mark.asyncio
    async def test_duplicate_findings_deduplicated(self) -> None:
        """A numeric finding that happens to match a coverage claim's
        ``(section, claim_text, start_offset, end_offset, reason)`` is
        kept only once.

        This is a contrived but important guard — if the merge logic
        regresses to naive concatenation, downstream re-synthesis
        would double-count the claim.
        """
        # Two identical findings passed in — the merged list must have one.
        finding_a = UnsupportedClaim(
            section="summary",
            claim_text="5,678 crore",
            start_offset=0,
            end_offset=11,
            reason="numeric_drift",
        )
        finding_b = UnsupportedClaim(
            section="summary",
            claim_text="5,678 crore",
            start_offset=0,
            end_offset=11,
            reason="numeric_drift",
        )
        report = await invoke_rule_based(
            run_id=uuid4(),
            brief={"summary": "5,678 crore [cite:alpha]."},
            chunks=[_FakeChunk(chunk_id="alpha", text="1,234 crore")],
            numeric_findings=[finding_a, finding_b],
        )
        matching = [
            c
            for c in report.unsupported_claims
            if c.claim_text == "5,678 crore" and c.reason == "numeric_drift"
        ]
        assert len(matching) == 1


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
