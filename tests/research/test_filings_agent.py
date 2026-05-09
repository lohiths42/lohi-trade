"""Unit tests for :class:`FilingsAgent` (Task 13.2).

Every retrieval-only Sub_Agent shares
:class:`~src.research.agents._base.BaseRetrievalAgent` so most of the
assertions in this file apply identically to the fundamentals /
peer_sector / macro tests. Keeping the duplication intentionally —
the tests are small, the invariants are worth asserting per-agent
(prompt name, section name, retrieval-filter narrowing), and a shared
parametrised harness would obscure the per-agent intent.

Covers
------

* **Happy path** — retriever returns chunks, LLM is called, the
  resulting :class:`AgentResult` carries the expected kind / section
  name / section_md / token counts / citations (Req 1.8).
* **No-data path** — retriever returns ``[]`` → ``kind="no_data"``
  and the LLM is **never** called (Req 1.3).
* **No-symbol path** — ``context.symbol is None`` → ``kind="no_data"``
  without invoking the retriever or the LLM.
* **Error path** — LLM raises → the base re-raises so the
  Orchestrator's per-agent ``try/except`` in
  :meth:`ResearchOrchestrator._invoke_agent` can convert it to
  ``kind="error"`` (Req 1.6).
* **Retrieval-filter shape** — the :class:`RetrievalFilter` carries
  ``document_type`` narrowing so the run trace makes the filings
  intent visible.
* **SubAgent Protocol conformance** — ``isinstance(agent, SubAgent)``
  holds and ``name`` is the canonical value.
* **Prompt rendering** — the rendered system message carries every
  shared-skeleton placeholder substituted (no un-rendered
  ``{{…}}`` markers) and embeds the chunks verbatim.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents._base import AgentConfig
from src.research.agents.filings import FilingsAgent
from src.research.agents.orchestrator import AgentContext, PlanOutput, SubAgent
from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    LLMParams,
    Message,
    RetrievalFilter,
)
from tests.research.fakes import FakeLLMProvider


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


class _RecordingRetriever:
    """In-memory stub implementing the retriever contract.

    Exposes ``retrieve(query, filter, k=...)`` and records every call
    so tests can assert on the query the agent built and the filter
    shape (including ``document_type`` narrowing).
    """

    def __init__(self, canned: list[ChunkHit]) -> None:
        self._canned = canned
        self.calls: list[dict[str, Any]] = []

    async def retrieve(
        self,
        query: str,
        filter: RetrievalFilter,
        *,
        k: int | None = None,
    ) -> list[ChunkHit]:
        self.calls.append({"query": query, "filter": filter, "k": k})
        return list(self._canned)


class _RaisingLLM(FakeLLMProvider):
    """FakeLLMProvider that raises on ``complete`` — exercises the error path."""

    async def complete(self, messages: list[Message], params: LLMParams):
        raise RuntimeError("llm provider exploded")


class _RecordingLLM(FakeLLMProvider):
    """FakeLLMProvider that records the exact messages it was called with."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[list[Message], LLMParams]] = []

    async def complete(self, messages: list[Message], params: LLMParams):
        # Store a shallow copy so tests can inspect the rendered
        # system prompt without fear of later mutation.
        self.calls.append(([m.model_copy() for m in messages], params))
        return await super().complete(messages, params)


def _build_hit(
    *,
    chunk_id: str,
    user_id: UUID,
    symbol: str,
    text: str,
) -> ChunkHit:
    """Construct a minimal :class:`ChunkHit` for retriever stubs."""
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


def _build_context(
    *,
    user_id: UUID,
    symbol: str | None,
    retriever: Any,
    user_prompt: str = "How did RELIANCE do this quarter?",
    retrieval_plan: dict[str, str] | None = None,
) -> AgentContext:
    """Construct an :class:`AgentContext` with the given retriever."""
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever,
        plan=PlanOutput(
            agents_requested=["filings"],
            retrieval_plan=retrieval_plan or {},
        ),
    )


# --------------------------------------------------------------------------- #
# Identity + protocol conformance                                             #
# --------------------------------------------------------------------------- #


class TestIdentity:
    """The agent exposes the identity fields the Orchestrator expects."""

    def test_name_is_filings(self) -> None:
        agent = FilingsAgent(llm=FakeLLMProvider())
        assert agent.name == "filings"

    def test_section_name_is_management_commentary(self) -> None:
        """Filings Agent contributes to ``management_commentary`` (design §3.5)."""
        agent = FilingsAgent(llm=FakeLLMProvider())
        assert agent.section_name == "management_commentary"

    def test_prompt_name_matches_template_file(self) -> None:
        """The prompt name resolves to ``prompts/v1/filings_agent.md``."""
        agent = FilingsAgent(llm=FakeLLMProvider())
        assert agent.prompt_name == "filings_agent"

    def test_conforms_to_subagent_protocol(self) -> None:
        """Runtime-check the Orchestrator's SubAgent Protocol."""
        agent = FilingsAgent(llm=FakeLLMProvider())
        assert isinstance(agent, SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    """Chunks returned → LLM called → AgentResult populated."""

    @pytest.mark.asyncio
    async def test_returns_ok_result_with_llm_content(self) -> None:
        user_id = uuid4()
        chunks = [
            _build_hit(
                chunk_id="c_filing_1",
                user_id=user_id,
                symbol="RELIANCE",
                text="Announcement: Q2 results released.",
            ),
            _build_hit(
                chunk_id="c_filing_2",
                user_id=user_id,
                symbol="RELIANCE",
                text="Board approved dividend of Rs 9 per share.",
            ),
        ]
        retriever = _RecordingRetriever(canned=chunks)
        llm = FakeLLMProvider(
            canned_completion='{"findings":[{"claim":"Q2 results released [cite:c_filing_1]","document_type":"announcement","chunk_ids":["c_filing_1"]}]}',
            canned_input_tokens=123,
            canned_output_tokens=45,
        )
        agent = FilingsAgent(llm=llm)

        context = _build_context(
            user_id=user_id, symbol="RELIANCE", retriever=retriever
        )
        result = await agent.invoke(context)

        assert result.kind == "ok"
        assert result.agent_name == "filings"
        assert result.section_name == "management_commentary"
        assert result.section_md.startswith('{"findings"')
        assert result.input_tokens == 123
        assert result.output_tokens == 45
        assert len(result.chunks) == 2
        assert {hit.chunk.chunk_id for hit in result.chunks} == {
            "c_filing_1",
            "c_filing_2",
        }
        # Wall time always populated (Req 1.8).
        assert result.wall_time_ms >= 0

    @pytest.mark.asyncio
    async def test_final_k_truncation(self) -> None:
        """``config.final_k`` caps the chunk list before prompt rendering."""
        user_id = uuid4()
        chunks = [
            _build_hit(
                chunk_id=f"c{i}",
                user_id=user_id,
                symbol="RELIANCE",
                text=f"chunk {i}",
            )
            for i in range(5)
        ]
        retriever = _RecordingRetriever(canned=chunks)
        llm = FakeLLMProvider()
        agent = FilingsAgent(
            llm=llm, config=AgentConfig(final_k=2)
        )

        context = _build_context(
            user_id=user_id, symbol="RELIANCE", retriever=retriever
        )
        result = await agent.invoke(context)
        assert len(result.chunks) == 2

    @pytest.mark.asyncio
    async def test_retrieval_k_forwarded_to_retriever(self) -> None:
        """Base passes ``config.retrieval_k`` to the retriever."""
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="X",
                    text="t",
                )
            ]
        )
        agent = FilingsAgent(
            llm=FakeLLMProvider(), config=AgentConfig(retrieval_k=17)
        )
        await agent.invoke(
            _build_context(user_id=user_id, symbol="X", retriever=retriever)
        )
        assert retriever.calls[0]["k"] == 17


# --------------------------------------------------------------------------- #
# Retrieval filter narrowing                                                  #
# --------------------------------------------------------------------------- #


class TestRetrievalFilter:
    """The filter carries ``document_type`` narrowing for filings."""

    @pytest.mark.asyncio
    async def test_filter_includes_document_type(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="RELIANCE",
                    text="t",
                )
            ]
        )
        agent = FilingsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id, symbol="RELIANCE", retriever=retriever
            )
        )
        filter_used: RetrievalFilter = retriever.calls[0]["filter"]
        assert filter_used.user_id == user_id
        assert filter_used.symbol == "RELIANCE"
        # Filings Agent narrows by the ``announcement`` document type.
        assert filter_used.document_type == "announcement"


# --------------------------------------------------------------------------- #
# No-data paths                                                               #
# --------------------------------------------------------------------------- #


class TestNoData:
    """Empty retrieval / no symbol → ``no_data`` without calling the LLM."""

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        llm = _RecordingLLM()
        agent = FilingsAgent(llm=llm)

        result = await agent.invoke(
            _build_context(
                user_id=user_id, symbol="RELIANCE", retriever=retriever
            )
        )
        assert result.kind == "no_data"
        assert result.agent_name == "filings"
        assert result.section_name == "management_commentary"
        assert "no filings chunks" in result.reason
        # Retriever was consulted; LLM was not.
        assert len(retriever.calls) == 1
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_missing_symbol_returns_no_data_without_retrieval(
        self,
    ) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        llm = _RecordingLLM()
        agent = FilingsAgent(llm=llm)

        result = await agent.invoke(
            _build_context(
                user_id=user_id, symbol=None, retriever=retriever
            )
        )
        assert result.kind == "no_data"
        assert "requires a symbol" in result.reason
        # Neither the retriever nor the LLM is called.
        assert retriever.calls == []
        assert llm.calls == []


# --------------------------------------------------------------------------- #
# Error path                                                                  #
# --------------------------------------------------------------------------- #


class TestErrorPath:
    """LLM exceptions propagate for Orchestrator-side isolation (Req 1.6)."""

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="RELIANCE",
                    text="t",
                )
            ]
        )
        agent = FilingsAgent(llm=_RaisingLLM())
        with pytest.raises(RuntimeError, match="llm provider exploded"):
            await agent.invoke(
                _build_context(
                    user_id=user_id, symbol="RELIANCE", retriever=retriever
                )
            )

    @pytest.mark.asyncio
    async def test_no_llm_raises_value_error(self) -> None:
        """Agent constructed without an LLM surfaces a clear error."""
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="X",
                    text="t",
                )
            ]
        )
        agent = FilingsAgent(llm=None)
        with pytest.raises(ValueError, match="LLMProvider"):
            await agent.invoke(
                _build_context(
                    user_id=user_id, symbol="X", retriever=retriever
                )
            )


# --------------------------------------------------------------------------- #
# Prompt rendering                                                            #
# --------------------------------------------------------------------------- #


class TestPromptRendering:
    """The rendered system prompt carries substituted placeholders + chunks."""

    @pytest.mark.asyncio
    async def test_system_prompt_has_every_placeholder_resolved(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c_filing",
                    user_id=user_id,
                    symbol="TCS",
                    text="TCS Q2 revenue grew 12 percent YoY.",
                )
            ]
        )
        llm = _RecordingLLM(canned_completion='{"findings":[]}')
        agent = FilingsAgent(llm=llm)

        await agent.invoke(
            _build_context(
                user_id=user_id, symbol="TCS", retriever=retriever
            )
        )

        assert len(llm.calls) == 1
        messages, _params = llm.calls[0]
        system = messages[0].content

        # No un-rendered placeholders survived.
        assert "{{REFUSAL_POLICY_BLOCK}}" not in system
        assert "{{REFUSAL_NO_CONTEXT}}" not in system
        assert "{{RETRIEVED_CHUNKS_VERBATIM}}" not in system
        assert "{{USER_PROMPT}}" not in system

        # The chunk was embedded verbatim with its id as a fence.
        assert "# c_filing" in system
        assert "TCS Q2 revenue grew 12 percent YoY." in system

        # User prompt shows up inside the <user_prompt> section.
        assert "How did RELIANCE do this quarter?" in system

    @pytest.mark.asyncio
    async def test_plan_retrieval_intent_overrides_user_prompt(self) -> None:
        """Planner's per-agent retrieval intent wins when present."""
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="TCS",
                    text="t",
                )
            ]
        )
        agent = FilingsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="TCS",
                retriever=retriever,
                retrieval_plan={"filings": "board meeting outcomes"},
            )
        )
        assert retriever.calls[0]["query"] == "board meeting outcomes"
