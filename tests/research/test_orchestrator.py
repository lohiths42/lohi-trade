"""Unit tests for the Research Orchestrator graph (Task 13.1).

Covers the structural contract of :class:`ResearchOrchestrator`:

* Plan runs (even with no chat LLM), and the plan's ``agents_requested``
  drives which Sub_Agents the Orchestrator fans out to.
* Every Sub_Agent is invoked exactly once per run.
* Concurrency cap is respected — more Sub_Agents than the cap are
  queued, not run in parallel (Req 5.4).
* A partial is published for every Sub_Agent completion
  (Req 1.7, design §3.5).
* The final brief stamps the quality label from the re-synthesis
  outcome (design §11.2, Req 16.19).
* Sub_Agent exceptions do not kill the run — they become
  ``AgentResult(kind="error")`` and set ``partial=true`` (Req 1.6).
* ``no_data`` results also set ``partial=true`` (Req 1.3).
* The brief's section keys are always the canonical design-§3.5 set
  (Req 1.5).

Design references
-----------------
* §2.1 — top-down diagram.
* §3.5 — Orchestrator graph shape.
* §11.2 — re-synthesis loop (covered end-to-end here; per-pass
  semantics are tested in :mod:`tests.research.test_resynthesis`).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.orchestrator import (
    AgentContext,
    AgentResult,
    PlanOutput,
    ResearchOrchestrator,
    SubAgent,
)
from src.research.constants import RESEARCH_PARTIALS_STREAM
from src.research.judge.judge import JudgeReport
from src.research.providers.base import ChunkHit, ChunkRecord
from src.research.validators.types import UnsupportedClaim


# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class _StubAgent(SubAgent):
    """Deterministic Sub_Agent stub.

    ``latency_sec`` lets the concurrency-cap test observe overlapping
    execution windows without a real LLM.
    ``raises`` / ``no_data`` force the error / no-data branches.
    ``chunks`` seeds the retriever contract in the final brief.
    """

    name: str
    section_name: str = "summary"
    latency_sec: float = 0.0
    raises: bool = False
    no_data: bool = False
    section_md: str = "stub section"
    chunks: list[ChunkHit] = field(default_factory=list)
    calls: list[AgentContext] = field(default_factory=list)
    enter_events: list[tuple[str, float]] = field(default_factory=list)
    exit_events: list[tuple[str, float]] = field(default_factory=list)
    # Shared clock so two agents can observe each other's windows.
    clock: list[float] | None = None

    async def invoke(self, context: AgentContext) -> AgentResult:
        self.calls.append(context)
        now = asyncio.get_event_loop().time()
        self.enter_events.append((self.name, now))
        if self.latency_sec > 0:
            await asyncio.sleep(self.latency_sec)
        exit_now = asyncio.get_event_loop().time()
        self.exit_events.append((self.name, exit_now))

        if self.raises:
            raise RuntimeError(f"stub agent {self.name} boom")
        if self.no_data:
            return AgentResult(
                agent_name=self.name,
                kind="no_data",
                section_name=self.section_name,
                reason="no data",
            )
        return AgentResult(
            agent_name=self.name,
            kind="ok",
            section_name=self.section_name,
            section_md=self.section_md,
            chunks=list(self.chunks),
            input_tokens=10,
            output_tokens=20,
        )


class _RecordingPublisher:
    """In-memory partials-stream publisher.

    The Orchestrator calls ``publisher(stream_name, fields_dict)`` —
    we record every call so tests can inspect the partials that would
    have been XADD'd onto Redis.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, stream: str, fields: dict[str, Any]) -> None:
        self.calls.append((stream, dict(fields)))


def _canned_synthesizer(
    *,
    brief: dict[str, str] | None = None,
    resynth_brief: dict[str, str] | None = None,
) -> Any:
    """Build a synthesiser stub with distinct first-pass + resynth outputs."""

    first = brief if brief is not None else {
        "summary": "First pass summary [cite:c1].",
        "thesis": "First pass thesis [cite:c1].",
        "risks": "First pass risks [cite:c1].",
    }
    second = resynth_brief if resynth_brief is not None else {
        "summary": "Second pass summary [cite:c1].",
        "thesis": "Second pass thesis [cite:c1].",
        "risks": "Second pass risks [cite:c1].",
    }

    async def _synth(**kwargs: Any) -> dict[str, str]:
        if "prior_brief" in kwargs:
            return second
        return first

    return _synth


def _canned_judge(reports: list[JudgeReport]) -> Any:
    """Judge stub returning canned reports in order."""

    queue = list(reports)

    async def _judge(*, brief: Any, retry_count: int) -> JudgeReport:
        if not queue:
            raise AssertionError("Judge called more times than canned reports supplied")
        return queue.pop(0)

    return _judge


def _healthy_report(run_id: UUID, *, retry_count: int = 0) -> JudgeReport:
    return JudgeReport(
        run_id=run_id,
        groundedness_score={"summary": 0.9, "thesis": 0.9, "risks": 0.85},
        unsupported_claims=[],
        safe_to_display=True,
        retry_count=retry_count,
    )


def _failing_report(run_id: UUID, *, retry_count: int = 0) -> JudgeReport:
    return JudgeReport(
        run_id=run_id,
        groundedness_score={"summary": 0.9, "thesis": 0.5, "risks": 0.5},
        unsupported_claims=[
            UnsupportedClaim(
                section="risks",
                claim_text="unsupported risk",
                start_offset=0,
                end_offset=15,
                reason="no_citation",
            )
        ],
        safe_to_display=False,
        retry_count=retry_count,
    )


def _build_chunk(chunk_id: str, *, user_id: UUID, symbol: str, text: str) -> ChunkHit:
    """Build a minimal ``ChunkHit`` for Sub_Agent provenance."""
    return ChunkHit(
        chunk=ChunkRecord(
            chunk_id=chunk_id,
            document_id=uuid4(),
            user_id=user_id,
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


# --------------------------------------------------------------------------- #
# Plan + fan-out                                                              #
# --------------------------------------------------------------------------- #


class TestPlanAndFanOut:
    """Plan runs and fan-out invokes every Sub_Agent (Req 1.1, 1.2)."""

    @pytest.mark.asyncio
    async def test_plan_runs_without_chat_llm(self) -> None:
        """The default plan returns a PlanOutput even with no LLM."""
        run_id = uuid4()
        user_id = uuid4()
        agents = [_StubAgent(name="filings", section_name="summary")]
        publisher = _RecordingPublisher()

        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=publisher,
            chat_llm=None,
        )

        brief = await orchestrator.run(
            run_id=run_id,
            user_id=user_id,
            symbol="RELIANCE",
            user_prompt="How did RELIANCE do this quarter?",
        )

        # The plan ran and selected the one available agent.
        assert len(agents[0].calls) == 1
        assert agents[0].calls[0].plan.agents_requested == ["filings"]
        assert brief["quality"] == "high"

    @pytest.mark.asyncio
    async def test_custom_plan_fn_is_respected(self) -> None:
        """A custom plan_fn drives agent selection."""
        run_id = uuid4()
        agent_a = _StubAgent(name="a", section_name="summary")
        agent_b = _StubAgent(name="b", section_name="thesis")

        async def _plan_only_b(**_: Any) -> PlanOutput:
            return PlanOutput(agents_requested=["b"])

        orchestrator = ResearchOrchestrator(
            sub_agents=[agent_a, agent_b],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            plan_fn=_plan_only_b,
        )

        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        assert agent_a.calls == []
        assert len(agent_b.calls) == 1

    @pytest.mark.asyncio
    async def test_unknown_agent_in_plan_is_skipped(self) -> None:
        """A plan referencing an unknown agent name is dropped silently."""
        run_id = uuid4()
        agent_a = _StubAgent(name="a")

        async def _plan_with_ghost(**_: Any) -> PlanOutput:
            return PlanOutput(agents_requested=["a", "ghost"])

        orchestrator = ResearchOrchestrator(
            sub_agents=[agent_a],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            plan_fn=_plan_with_ghost,
        )

        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        assert len(agent_a.calls) == 1
        assert brief["quality"] == "high"

    @pytest.mark.asyncio
    async def test_every_subagent_invoked(self) -> None:
        """Every injected Sub_Agent is invoked exactly once (Req 1.2)."""
        run_id = uuid4()
        agents = [
            _StubAgent(name="filings", section_name="summary"),
            _StubAgent(name="fundamentals", section_name="thesis"),
            _StubAgent(name="news_sentiment", section_name="risks"),
            _StubAgent(name="technicals", section_name="technical_view"),
            _StubAgent(name="peer_sector", section_name="peers"),
            _StubAgent(name="macro", section_name="macro_context"),
        ]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )

        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        for agent in agents:
            assert len(agent.calls) == 1, f"{agent.name} invoked {len(agent.calls)} times"


# --------------------------------------------------------------------------- #
# Concurrency cap                                                             #
# --------------------------------------------------------------------------- #


class TestConcurrencyCap:
    """Req 5.4 — concurrent Sub_Agents are capped."""

    @pytest.mark.asyncio
    async def test_more_agents_than_cap_respects_semaphore(self) -> None:
        """With cap=2 and 4 agents each sleeping 50ms, elapsed ≥ 2 * 50ms."""
        run_id = uuid4()
        latency = 0.05  # 50ms per agent
        agents = [
            _StubAgent(name=f"a{i}", latency_sec=latency, section_name="summary")
            for i in range(4)
        ]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            concurrency_cap=2,
        )

        loop = asyncio.get_event_loop()
        started = loop.time()
        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        elapsed = loop.time() - started

        # 4 agents, cap=2, 50ms each → 2 waves → ≥ 100ms
        assert elapsed >= 2 * latency * 0.9  # 10% slack for scheduling jitter

        # Concurrency inspection: at most 2 agents running at once.
        # Build a sorted event list of (time, kind), count concurrency.
        events: list[tuple[float, str]] = []
        for agent in agents:
            events.append((agent.enter_events[0][1], "enter"))
            events.append((agent.exit_events[0][1], "exit"))
        events.sort()
        active = 0
        peak = 0
        for _, kind in events:
            if kind == "enter":
                active += 1
                peak = max(peak, active)
            else:
                active -= 1
        assert peak <= 2, f"peak concurrency {peak} exceeded cap 2"

    @pytest.mark.asyncio
    async def test_cap_of_six_allows_six_in_flight(self) -> None:
        """Default cap=6 must allow six in-flight agents."""
        run_id = uuid4()
        agents = [
            _StubAgent(name=f"a{i}", latency_sec=0.03, section_name="summary")
            for i in range(6)
        ]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            concurrency_cap=6,
        )

        loop = asyncio.get_event_loop()
        started = loop.time()
        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        elapsed = loop.time() - started

        # All six can run concurrently → elapsed ≈ one agent's latency,
        # not 6 * latency.
        assert elapsed < 6 * 0.03 * 0.8

    @pytest.mark.asyncio
    async def test_invalid_cap_raises(self) -> None:
        """concurrency_cap < 1 is rejected at construction."""
        with pytest.raises(ValueError):
            ResearchOrchestrator(
                sub_agents=[],
                synthesizer=_canned_synthesizer(),
                judge_fn=_canned_judge([]),
                retriever=None,
                concurrency_cap=0,
            )


# --------------------------------------------------------------------------- #
# Partials publishing                                                         #
# --------------------------------------------------------------------------- #


class TestPartialsPublishing:
    """Req 1.7 — partials published per Sub_Agent, plus an end-of-run marker."""

    @pytest.mark.asyncio
    async def test_one_partial_per_agent_plus_done_event(self) -> None:
        run_id = uuid4()
        agents = [
            _StubAgent(name="filings"),
            _StubAgent(name="fundamentals"),
        ]
        publisher = _RecordingPublisher()
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=publisher,
        )

        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        # All publishes target the canonical stream.
        for stream, _ in publisher.calls:
            assert stream == RESEARCH_PARTIALS_STREAM

        events = [call[1]["event"] for call in publisher.calls]
        assert events.count("agent_done") == 2
        assert events.count("done") == 1
        # The "done" marker is the final event.
        assert events[-1] == "done"

    @pytest.mark.asyncio
    async def test_partial_payload_carries_run_id_and_agent_name(self) -> None:
        run_id = uuid4()
        agents = [_StubAgent(name="filings", section_name="summary")]
        publisher = _RecordingPublisher()
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=publisher,
        )

        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        agent_partials = [c for c in publisher.calls if c[1]["event"] == "agent_done"]
        assert len(agent_partials) == 1
        fields = agent_partials[0][1]
        assert fields["run_id"] == str(run_id)
        # The payload JSON contains the agent name.
        import json as _json
        payload = _json.loads(fields["payload"])
        assert payload["agent_name"] == "filings"

    @pytest.mark.asyncio
    async def test_publisher_exception_does_not_break_run(self) -> None:
        run_id = uuid4()

        class _BadPublisher:
            def __init__(self) -> None:
                self.calls = 0

            async def __call__(self, stream: str, fields: dict[str, Any]) -> None:
                self.calls += 1
                raise ConnectionError("redis down")

        publisher = _BadPublisher()
        agents = [_StubAgent(name="filings")]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=publisher,
        )

        # Must not raise — the partial failures are swallowed.
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert publisher.calls >= 1
        assert brief["quality"] == "high"

    @pytest.mark.asyncio
    async def test_publisher_none_is_allowed(self) -> None:
        """No publisher injected → Orchestrator runs silently."""
        run_id = uuid4()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert brief["quality"] == "high"


# --------------------------------------------------------------------------- #
# Quality label from re-synthesis outcome                                     #
# --------------------------------------------------------------------------- #


class TestQualityLabel:
    """Design §11.2 — final brief stamps the resynthesis outcome's quality."""

    @pytest.mark.asyncio
    async def test_first_pass_passes_yields_high(self) -> None:
        run_id = uuid4()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert brief["quality"] == "high"

    @pytest.mark.asyncio
    async def test_first_fails_second_passes_yields_medium(self) -> None:
        run_id = uuid4()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge(
                [_failing_report(run_id), _healthy_report(run_id, retry_count=1)]
            ),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert brief["quality"] == "medium"
        assert brief["summary"] == "Second pass summary [cite:c1]."

    @pytest.mark.asyncio
    async def test_both_passes_fail_yields_low(self) -> None:
        run_id = uuid4()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge(
                [_failing_report(run_id), _failing_report(run_id, retry_count=1)]
            ),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert brief["quality"] == "low"
        # Unsupported sections were redacted.
        assert brief["risks"] == "insufficient evidence"
        assert "risks" in brief["unsupported_sections"]

    @pytest.mark.asyncio
    async def test_done_event_carries_quality(self) -> None:
        """The end-of-run marker stamps the quality label."""
        run_id = uuid4()
        publisher = _RecordingPublisher()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
            partials_publisher=publisher,
        )
        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        done_events = [c for c in publisher.calls if c[1].get("event") == "done"]
        assert len(done_events) == 1
        assert done_events[0][1]["quality"] == "high"


# --------------------------------------------------------------------------- #
# Error isolation + partial flag                                              #
# --------------------------------------------------------------------------- #


class TestErrorIsolation:
    """Req 1.3, 1.6 — bad Sub_Agents don't kill the run; partial=true."""

    @pytest.mark.asyncio
    async def test_raising_agent_becomes_error_result(self) -> None:
        run_id = uuid4()
        good = _StubAgent(name="filings", section_name="summary")
        bad = _StubAgent(name="fundamentals", section_name="thesis", raises=True)
        orchestrator = ResearchOrchestrator(
            sub_agents=[good, bad],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )

        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )

        # Run completed despite the raising agent.
        assert brief["quality"] == "high"
        # partial=true because one agent errored.
        assert brief["partial"] is True
        # Both agents appear in provenance.
        names = [p["agent_name"] for p in brief["provenance"]]
        assert set(names) == {"filings", "fundamentals"}
        kinds = {p["agent_name"]: p["kind"] for p in brief["provenance"]}
        assert kinds["filings"] == "ok"
        assert kinds["fundamentals"] == "error"

    @pytest.mark.asyncio
    async def test_no_data_result_marks_run_partial(self) -> None:
        run_id = uuid4()
        agents = [
            _StubAgent(name="filings"),
            _StubAgent(name="fundamentals", no_data=True),
        ]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert brief["partial"] is True
        kinds = {p["agent_name"]: p["kind"] for p in brief["provenance"]}
        assert kinds["fundamentals"] == "no_data"


# --------------------------------------------------------------------------- #
# Canonical brief shape                                                       #
# --------------------------------------------------------------------------- #


class TestBriefShape:
    """Req 1.5 — the returned brief always has every canonical section key."""

    @pytest.mark.asyncio
    async def test_all_canonical_sections_present_even_if_empty(self) -> None:
        run_id = uuid4()
        # Synthesiser only returns summary + thesis; the others must
        # still be present (empty strings) in the final brief.
        synth = _canned_synthesizer(
            brief={"summary": "s", "thesis": "t"},
        )
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=synth,
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        for section in (
            "summary",
            "thesis",
            "risks",
            "financial_highlights",
            "management_commentary",
            "technical_view",
            "peers",
            "macro_context",
        ):
            assert section in brief

        assert brief["summary"] == "s"
        assert brief["thesis"] == "t"
        assert brief["risks"] == ""

    @pytest.mark.asyncio
    async def test_citations_collected_from_subagents(self) -> None:
        """Every cited chunk from a Sub_Agent appears in brief['citations']."""
        run_id = uuid4()
        user_id = uuid4()
        chunk_a = _build_chunk("c_a", user_id=user_id, symbol="X", text="alpha")
        chunk_b = _build_chunk("c_b", user_id=user_id, symbol="X", text="beta")
        agents = [
            _StubAgent(name="filings", chunks=[chunk_a]),
            _StubAgent(name="fundamentals", chunks=[chunk_b]),
        ]
        orchestrator = ResearchOrchestrator(
            sub_agents=agents,
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=user_id,
            symbol="X",
            user_prompt="",
        )
        assert set(brief["citations"]) == {"c_a", "c_b"}

    @pytest.mark.asyncio
    async def test_run_id_and_symbol_preserved(self) -> None:
        run_id = uuid4()
        orchestrator = ResearchOrchestrator(
            sub_agents=[_StubAgent(name="filings")],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=None,
        )
        brief = await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="RELIANCE",
            user_prompt="",
        )
        assert brief["run_id"] == str(run_id)
        assert brief["symbol"] == "RELIANCE"


# --------------------------------------------------------------------------- #
# Retriever in context                                                        #
# --------------------------------------------------------------------------- #


class TestContextWiring:
    """Sub_Agents receive the injected retriever via AgentContext."""

    @pytest.mark.asyncio
    async def test_retriever_threaded_through(self) -> None:
        run_id = uuid4()
        sentinel = object()
        agent = _StubAgent(name="filings")
        orchestrator = ResearchOrchestrator(
            sub_agents=[agent],
            synthesizer=_canned_synthesizer(),
            judge_fn=_canned_judge([_healthy_report(run_id)]),
            retriever=sentinel,
        )
        await orchestrator.run(
            run_id=run_id,
            user_id=uuid4(),
            symbol="X",
            user_prompt="",
        )
        assert agent.calls[0].retriever is sentinel
