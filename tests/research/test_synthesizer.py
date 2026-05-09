"""Unit tests for :class:`Synthesizer` (Task 13.8).

The Report_Synthesizer is unusual among the Sub_Agents: it consumes
only the outputs of the other Sub_Agents (Req 1.4) and issues no
retrieval calls of its own. These tests therefore drive the agent
with pre-built :class:`AgentResult` lists and a
:class:`FakeLLMProvider` primed to return canned JSON — no retriever,
no vector store, no Redis.

Covers
------
* **Happy path** — multiple ok ``AgentResult``s → LLM is called →
  returned mapping has every canonical section plus ``citations``.
* **Re-synthesis path** — ``prior_brief`` + ``unsupported_claims`` +
  ``numeric_findings`` are packed into the prompt so the LLM can
  rewrite the flagged sections.
* **Missing sections default to empty strings** — a Sub_Agent set
  that only covers a subset of sections still yields a full brief
  shape.
* **No-data results don't crash synthesis** — every Sub_Agent
  returning ``kind="no_data"`` still produces a structurally valid
  brief; the LLM is still called (no_data is information, not an
  empty context).
* **LLM error propagates** — synthesizer does NOT swallow provider
  exceptions (design decision explained in the module docstring).
* **Canonical section enforcement** — unknown section names in the
  LLM response are dropped; the fallback stitch respects
  ``section_name``.
* **Citations derived from Sub_Agent chunks** — the authoritative
  source (Req 3.11).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.orchestrator import AgentResult
from src.research.agents.synthesizer import Synthesizer, build
from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    LLMParams,
    Message,
)
from src.research.validators.types import UnsupportedClaim
from tests.research.fakes import FakeLLMProvider


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


CANONICAL_SECTIONS = (
    "summary",
    "thesis",
    "risks",
    "financial_highlights",
    "management_commentary",
    "technical_view",
    "peers",
    "macro_context",
)


def _build_hit(
    *,
    chunk_id: str,
    user_id: UUID | None = None,
    symbol: str = "RELIANCE",
    text: str = "cited content",
) -> ChunkHit:
    """Construct a minimal :class:`ChunkHit` for synthesizer inputs."""
    return ChunkHit(
        chunk=ChunkRecord(
            chunk_id=chunk_id,
            document_id=uuid4(),
            user_id=user_id or uuid4(),
            symbol=symbol,
            position=0,
            token_count=10,
            text=text,
            embedding=[0.1] * 4,
            embedding_model="fake",
            embedding_dim=4,
        ),
        score=0.9,
    )


def _ok_result(
    *,
    agent_name: str,
    section_name: str,
    section_md: str,
    chunk_ids: list[str] | None = None,
) -> AgentResult:
    """Construct an ``ok`` :class:`AgentResult` with optional cited chunks."""
    chunks = [
        _build_hit(chunk_id=cid)
        for cid in (chunk_ids or [])
    ]
    return AgentResult(
        agent_name=agent_name,
        kind="ok",
        section_name=section_name,
        section_md=section_md,
        chunks=chunks,
        input_tokens=100,
        output_tokens=50,
        wall_time_ms=120,
    )


def _no_data_result(*, agent_name: str, section_name: str) -> AgentResult:
    """Construct a ``no_data`` :class:`AgentResult`."""
    return AgentResult(
        agent_name=agent_name,
        kind="no_data",
        section_name=section_name,
        reason=f"no_data: no {agent_name} chunks found",
        wall_time_ms=10,
    )


def _error_result(*, agent_name: str, section_name: str) -> AgentResult:
    """Construct an ``error`` :class:`AgentResult`."""
    return AgentResult(
        agent_name=agent_name,
        kind="error",
        section_name=section_name,
        reason="RuntimeError: boom",
        wall_time_ms=5,
    )


class _RecordingLLM(FakeLLMProvider):
    """FakeLLMProvider that records every ``complete`` call's messages."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[list[Message], LLMParams]] = []

    async def complete(
        self, messages: list[Message], params: LLMParams
    ):
        self.calls.append(([m.model_copy() for m in messages], params))
        return await super().complete(messages, params)


class _RaisingLLM(FakeLLMProvider):
    """FakeLLMProvider that raises on ``complete``."""

    async def complete(self, messages: list[Message], params: LLMParams):
        raise RuntimeError("llm provider exploded")


# Canned JSON shape matching the v1 prompt's "sections" array.
def _canned_sections_json(
    *,
    summary: str = "Overall summary. [cite:c1]",
    thesis: str = "Core thesis. [cite:c2]",
    risks: str = "Downside risks. [cite:c3]",
    financial_highlights: str = "FY results. [cite:c4]",
    management_commentary: str = "Mgmt said. [cite:c5]",
    technical_view: str = "Uptrend noted. [cite:c6]",
    peers: str = "Peer comparison. [cite:c7]",
    macro_context: str = "Macro backdrop. [cite:c8]",
) -> str:
    payload = {
        "sections": [
            {"name": "summary", "content_markdown": summary, "citations": ["c1"]},
            {"name": "thesis", "content_markdown": thesis, "citations": ["c2"]},
            {"name": "risks", "content_markdown": risks, "citations": ["c3"]},
            {
                "name": "financial_highlights",
                "content_markdown": financial_highlights,
                "citations": ["c4"],
            },
            {
                "name": "management_commentary",
                "content_markdown": management_commentary,
                "citations": ["c5"],
            },
            {
                "name": "technical_view",
                "content_markdown": technical_view,
                "citations": ["c6"],
            },
            {"name": "peers", "content_markdown": peers, "citations": ["c7"]},
            {
                "name": "macro_context",
                "content_markdown": macro_context,
                "citations": ["c8"],
            },
        ],
        "executive_summary": summary,
    }
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# Identity + construction                                                     #
# --------------------------------------------------------------------------- #


class TestConstruction:
    """The class constructs cleanly and refuses without an LLM."""

    def test_builds_with_llm(self) -> None:
        synth = Synthesizer(llm=FakeLLMProvider())
        assert synth.llm is not None
        assert synth.prompt_version == "v1"

    def test_build_factory_constructs_instance(self) -> None:
        """The registry-style ``build`` factory returns a Synthesizer."""
        llm = FakeLLMProvider()
        synth = build(llm)
        assert isinstance(synth, Synthesizer)
        assert synth.llm is llm

    @pytest.mark.asyncio
    async def test_no_llm_raises_value_error(self) -> None:
        synth = Synthesizer(llm=None)
        with pytest.raises(ValueError, match="LLMProvider"):
            await synth(
                agent_results=[],
                symbol="RELIANCE",
                user_prompt="What's the brief?",
            )


# --------------------------------------------------------------------------- #
# Happy path — first pass                                                     #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    """Multiple AgentResults → LLM → merged brief."""

    @pytest.mark.asyncio
    async def test_returns_every_canonical_section(self) -> None:
        """Every key in the canonical set plus ``citations`` is present."""
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        results = [
            _ok_result(
                agent_name="filings",
                section_name="management_commentary",
                section_md="Filings body. [cite:c_f1]",
                chunk_ids=["c_f1"],
            ),
            _ok_result(
                agent_name="fundamentals",
                section_name="financial_highlights",
                section_md="Fundamentals body. [cite:c_n1]",
                chunk_ids=["c_n1"],
            ),
        ]
        brief = await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="Brief RELIANCE.",
        )

        # Every canonical section present.
        for section in CANONICAL_SECTIONS:
            assert section in brief
            assert isinstance(brief[section], str)

        # Citations key is present and parseable as a JSON list.
        assert "citations" in brief
        citations = json.loads(brief["citations"])
        assert citations == ["c_f1", "c_n1"]

    @pytest.mark.asyncio
    async def test_llm_is_called_once(self) -> None:
        llm = _RecordingLLM(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        results = [
            _ok_result(
                agent_name="filings",
                section_name="management_commentary",
                section_md="body",
                chunk_ids=["c1"],
            )
        ]
        await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="What's the brief?",
        )
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_sub_agent_section_md_included_in_prompt(self) -> None:
        """Sub_Agent outputs are rendered into the ``<|CONTEXT|>`` block."""
        llm = _RecordingLLM(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        results = [
            _ok_result(
                agent_name="filings",
                section_name="management_commentary",
                section_md="Mgmt commentary body with [cite:c_unique_id_42].",
                chunk_ids=["c_unique_id_42"],
            ),
            _ok_result(
                agent_name="fundamentals",
                section_name="financial_highlights",
                section_md="Financials body [cite:c_xyz].",
                chunk_ids=["c_xyz"],
            ),
        ]
        await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="Brief.",
        )

        system = llm.calls[0][0][0].content
        # Every agent's section_md appears verbatim in the prompt.
        assert "Mgmt commentary body with [cite:c_unique_id_42]." in system
        assert "Financials body [cite:c_xyz]." in system
        # Agent identity is also embedded for attribution.
        assert "agent=filings" in system
        assert "agent=fundamentals" in system
        # No un-rendered placeholders leaked through.
        assert "{{REFUSAL_POLICY_BLOCK}}" not in system
        assert "{{USER_PROMPT}}" not in system
        assert "{{RETRIEVED_CHUNKS_VERBATIM}}" not in system

    @pytest.mark.asyncio
    async def test_citations_derived_from_agent_chunks(self) -> None:
        """``citations`` reflects the Sub_Agents' actual cited chunks (Req 3.11)."""
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        # Two agents cite one overlapping chunk and one unique each.
        results = [
            _ok_result(
                agent_name="filings",
                section_name="management_commentary",
                section_md="x",
                chunk_ids=["c_shared", "c_a"],
            ),
            _ok_result(
                agent_name="fundamentals",
                section_name="financial_highlights",
                section_md="y",
                chunk_ids=["c_shared", "c_b"],
            ),
        ]
        brief = await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="Brief.",
        )
        citations = json.loads(brief["citations"])
        # Deduplicated, but order preserved.
        assert citations == ["c_shared", "c_a", "c_b"]


# --------------------------------------------------------------------------- #
# Missing sections                                                            #
# --------------------------------------------------------------------------- #


class TestMissingSections:
    """Sections no Sub_Agent contributed to default to empty strings."""

    @pytest.mark.asyncio
    async def test_partial_coverage_fills_empty_strings(self) -> None:
        """LLM returns only a subset — absent sections are ``""``."""
        partial_json = json.dumps(
            {
                "sections": [
                    {
                        "name": "summary",
                        "content_markdown": "Summary only.",
                        "citations": [],
                    },
                    {
                        "name": "thesis",
                        "content_markdown": "Thesis only.",
                        "citations": [],
                    },
                ],
                "executive_summary": "Summary only.",
            }
        )
        llm = FakeLLMProvider(canned_completion=partial_json)
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[
                _ok_result(
                    agent_name="filings",
                    section_name="management_commentary",
                    section_md="x",
                )
            ],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )

        assert brief["summary"] == "Summary only."
        assert brief["thesis"] == "Thesis only."
        # Sections the LLM didn't return default to empty.
        for absent in (
            "risks",
            "financial_highlights",
            "management_commentary",
            "technical_view",
            "peers",
            "macro_context",
        ):
            assert brief[absent] == ""

    @pytest.mark.asyncio
    async def test_flat_mapping_response_accepted(self) -> None:
        """LLM returning a flat ``{section: content}`` mapping is accepted."""
        flat_json = json.dumps(
            {
                "summary": "Flat summary.",
                "thesis": "Flat thesis.",
                "risks": "Flat risks.",
                # Other sections absent; should default to "".
            }
        )
        llm = FakeLLMProvider(canned_completion=flat_json)
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )

        assert brief["summary"] == "Flat summary."
        assert brief["thesis"] == "Flat thesis."
        assert brief["risks"] == "Flat risks."
        assert brief["financial_highlights"] == ""

    @pytest.mark.asyncio
    async def test_unknown_section_names_dropped(self) -> None:
        """LLM-invented section names never appear in the returned brief."""
        rogue_json = json.dumps(
            {
                "sections": [
                    {
                        "name": "summary",
                        "content_markdown": "legit",
                        "citations": [],
                    },
                    {
                        "name": "fabricated_section",
                        "content_markdown": "impostor",
                        "citations": [],
                    },
                ]
            }
        )
        llm = FakeLLMProvider(canned_completion=rogue_json)
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[],
            symbol=None,
            user_prompt="Brief.",
        )

        assert brief["summary"] == "legit"
        assert "fabricated_section" not in brief


# --------------------------------------------------------------------------- #
# No-data / error results                                                     #
# --------------------------------------------------------------------------- #


class TestNoDataAndErrorResults:
    """``no_data`` / ``error`` Sub_Agents don't crash synthesis (Req 1.3, Req 1.6)."""

    @pytest.mark.asyncio
    async def test_all_no_data_produces_structurally_valid_brief(self) -> None:
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        results = [
            _no_data_result(
                agent_name="filings", section_name="management_commentary"
            ),
            _no_data_result(agent_name="fundamentals", section_name="financial_highlights"),
            _no_data_result(agent_name="macro", section_name="macro_context"),
        ]
        brief = await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="Brief.",
        )

        # Every canonical section present.
        for section in CANONICAL_SECTIONS:
            assert section in brief
        # Citations list is empty JSON array (no chunks cited).
        assert json.loads(brief["citations"]) == []

    @pytest.mark.asyncio
    async def test_mixed_ok_no_data_error_does_not_raise(self) -> None:
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        results = [
            _ok_result(
                agent_name="filings",
                section_name="management_commentary",
                section_md="Mgmt body.",
                chunk_ids=["c_filings"],
            ),
            _no_data_result(agent_name="macro", section_name="macro_context"),
            _error_result(
                agent_name="peer_sector", section_name="peers"
            ),
        ]
        # Does not raise.
        brief = await synth(
            agent_results=results,
            symbol="RELIANCE",
            user_prompt="Brief.",
        )
        assert "summary" in brief
        # Citations only drawn from the ok agent.
        assert json.loads(brief["citations"]) == ["c_filings"]

    @pytest.mark.asyncio
    async def test_no_data_is_visible_in_prompt(self) -> None:
        """``no_data`` results appear in the context so the LLM knows about gaps."""
        llm = _RecordingLLM(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        await synth(
            agent_results=[
                _no_data_result(agent_name="macro", section_name="macro_context"),
            ],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )
        system = llm.calls[0][0][0].content
        assert "agent=macro" in system
        assert "kind=no_data" in system


# --------------------------------------------------------------------------- #
# Re-synthesis                                                                #
# --------------------------------------------------------------------------- #


class TestResynthesisPath:
    """``prior_brief`` + feedback → LLM produces a revised brief (Req 16.18)."""

    @pytest.mark.asyncio
    async def test_prior_brief_included_in_prompt(self) -> None:
        llm = _RecordingLLM(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        prior_brief = {
            "summary": "Draft summary with problems.",
            "thesis": "Thesis draft.",
        }
        unsupported = (
            UnsupportedClaim(
                section="summary",
                claim_text="revenue grew 99 percent",
                start_offset=0,
                end_offset=25,
                reason="numeric_drift",
            ),
        )
        numeric = (
            UnsupportedClaim(
                section="financial_highlights",
                claim_text="Rs 500 Cr",
                start_offset=0,
                end_offset=9,
                reason="numeric_drift",
            ),
        )
        await synth(
            agent_results=[
                _ok_result(
                    agent_name="filings",
                    section_name="management_commentary",
                    section_md="body",
                    chunk_ids=["c1"],
                )
            ],
            symbol="RELIANCE",
            user_prompt="Brief.",
            prior_brief=prior_brief,
            unsupported_claims=unsupported,
            numeric_findings=numeric,
        )

        system = llm.calls[0][0][0].content
        # Prior brief visible.
        assert "Draft summary with problems." in system
        assert "<prior_brief>" in system
        # Unsupported claims visible.
        assert "<unsupported_claims>" in system
        assert "revenue grew 99 percent" in system
        assert "numeric_drift" in system
        # Numeric findings visible.
        assert "<numeric_findings>" in system
        assert "Rs 500 Cr" in system

    @pytest.mark.asyncio
    async def test_resynth_returns_revised_brief(self) -> None:
        """The revised LLM response replaces the prior brief sections."""
        revised_json = json.dumps(
            {
                "sections": [
                    {
                        "name": "summary",
                        "content_markdown": "Revised summary (revenue +5%). [cite:c1]",
                        "citations": ["c1"],
                    },
                    {
                        "name": "financial_highlights",
                        "content_markdown": "Revenue Rs 600 Cr. [cite:c1]",
                        "citations": ["c1"],
                    },
                ]
            }
        )
        llm = FakeLLMProvider(canned_completion=revised_json)
        synth = Synthesizer(llm=llm)

        prior_brief = {"summary": "Old summary (revenue +99%).",
                       "financial_highlights": "Old highlights."}
        brief = await synth(
            agent_results=[
                _ok_result(
                    agent_name="fundamentals",
                    section_name="financial_highlights",
                    section_md="fund body",
                    chunk_ids=["c1"],
                )
            ],
            symbol="RELIANCE",
            user_prompt="Brief.",
            prior_brief=prior_brief,
            unsupported_claims=(
                UnsupportedClaim(
                    section="summary",
                    claim_text="+99%",
                    start_offset=0,
                    end_offset=4,
                    reason="numeric_drift",
                ),
            ),
        )

        assert brief["summary"] == "Revised summary (revenue +5%). [cite:c1]"
        assert brief["financial_highlights"] == "Revenue Rs 600 Cr. [cite:c1]"
        # Old draft is not leaked through.
        assert "99%" not in brief["summary"]

    @pytest.mark.asyncio
    async def test_first_pass_omits_resynth_blocks(self) -> None:
        """First-pass prompts do not contain prior_brief / feedback fences."""
        llm = _RecordingLLM(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        await synth(
            agent_results=[],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )
        system = llm.calls[0][0][0].content
        assert "<prior_brief>" not in system
        assert "<unsupported_claims>" not in system
        assert "<numeric_findings>" not in system


# --------------------------------------------------------------------------- #
# Error propagation                                                           #
# --------------------------------------------------------------------------- #


class TestErrorPropagation:
    """LLM exceptions propagate to the Orchestrator (Req 1.6)."""

    @pytest.mark.asyncio
    async def test_llm_exception_propagates(self) -> None:
        synth = Synthesizer(llm=_RaisingLLM())

        with pytest.raises(RuntimeError, match="llm provider exploded"):
            await synth(
                agent_results=[
                    _ok_result(
                        agent_name="filings",
                        section_name="management_commentary",
                        section_md="body",
                    )
                ],
                symbol="RELIANCE",
                user_prompt="Brief.",
            )


# --------------------------------------------------------------------------- #
# JSON parsing fallback                                                       #
# --------------------------------------------------------------------------- #


class TestJsonParsingFallback:
    """Non-JSON LLM output falls back to stitching Sub_Agent section_md."""

    @pytest.mark.asyncio
    async def test_non_json_response_stitches_from_agents(self) -> None:
        """The fallback threads each ``ok`` agent's content into its section."""
        llm = FakeLLMProvider(canned_completion="I am just prose, no JSON here.")
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[
                _ok_result(
                    agent_name="filings",
                    section_name="management_commentary",
                    section_md="Filings content.",
                ),
                _ok_result(
                    agent_name="fundamentals",
                    section_name="financial_highlights",
                    section_md="Fundamentals content.",
                ),
            ],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )

        assert brief["management_commentary"] == "Filings content."
        assert brief["financial_highlights"] == "Fundamentals content."
        # Other sections still exist as empty strings.
        assert brief["thesis"] == ""

    @pytest.mark.asyncio
    async def test_json_wrapped_in_prose_still_parses(self) -> None:
        """Code-fence / prose-wrapped JSON is still extracted."""
        content = (
            "Sure, here is the brief:\n\n"
            "```json\n"
            + _canned_sections_json()
            + "\n```\n"
            "Hope this helps."
        )
        llm = FakeLLMProvider(canned_completion=content)
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[],
            symbol=None,
            user_prompt="Brief.",
        )
        # The canned JSON's summary is "Overall summary. [cite:c1]".
        assert brief["summary"] == "Overall summary. [cite:c1]"


# --------------------------------------------------------------------------- #
# Empty inputs                                                                #
# --------------------------------------------------------------------------- #


class TestEmptyInputs:
    """Synthesizer still produces a well-shaped brief with no agents."""

    @pytest.mark.asyncio
    async def test_empty_agent_results_does_not_crash(self) -> None:
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[],
            symbol="RELIANCE",
            user_prompt="Brief.",
        )
        # Canonical shape still enforced.
        for section in CANONICAL_SECTIONS:
            assert section in brief
        # No chunks, no citations.
        assert json.loads(brief["citations"]) == []

    @pytest.mark.asyncio
    async def test_missing_symbol_still_produces_brief(self) -> None:
        """``symbol=None`` (Req 1.5 generic queries) does not block synthesis."""
        llm = FakeLLMProvider(canned_completion=_canned_sections_json())
        synth = Synthesizer(llm=llm)

        brief = await synth(
            agent_results=[],
            symbol=None,
            user_prompt="General macro question.",
        )
        for section in CANONICAL_SECTIONS:
            assert section in brief
