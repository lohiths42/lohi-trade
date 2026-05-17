"""Unit tests for :class:`FundamentalsAgent` (Task 13.3).

Mirrors :mod:`tests.research.test_filings_agent` in structure — the
two agents share :class:`BaseRetrievalAgent` so the invariants
overlap heavily. Per-agent assertions (name / section_name /
prompt_name / query-bias / document_type narrowing) are tested here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.fundamentals import FundamentalsAgent
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
# Helpers (identical shape to test_filings_agent; tiny duplication is fine)   #
# --------------------------------------------------------------------------- #


class _RecordingRetriever:
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
    async def complete(self, messages: list[Message], params: LLMParams):
        raise RuntimeError("fundamentals llm exploded")


def _build_hit(
    *,
    chunk_id: str,
    user_id: UUID,
    symbol: str,
    text: str,
) -> ChunkHit:
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
    user_prompt: str = "Summarise the fundamentals",
    retrieval_plan: dict[str, str] | None = None,
) -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever,
        plan=PlanOutput(
            agents_requested=["fundamentals"],
            retrieval_plan=retrieval_plan or {},
        ),
    )


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #


class TestIdentity:
    def test_name_is_fundamentals(self) -> None:
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        assert agent.name == "fundamentals"

    def test_section_name_is_financial_highlights(self) -> None:
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        assert agent.section_name == "financial_highlights"

    def test_prompt_name_matches_template(self) -> None:
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        assert agent.prompt_name == "fundamentals_agent"

    def test_conforms_to_subagent_protocol(self) -> None:
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        assert isinstance(agent, SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ok_with_chunks(self) -> None:
        user_id = uuid4()
        chunks = [
            _build_hit(
                chunk_id="c_ar_1",
                user_id=user_id,
                symbol="INFY",
                text="Revenue for FY24 was INR 1,53,670 crore.",
            ),
        ]
        retriever = _RecordingRetriever(canned=chunks)
        llm = FakeLLMProvider(
            canned_completion='{"metrics":[{"name":"revenue","value":"1,53,670 Cr","period":"FY24","chunk_id":"c_ar_1"}]}',
            canned_input_tokens=200,
            canned_output_tokens=60,
        )
        agent = FundamentalsAgent(llm=llm)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="INFY", retriever=retriever),
        )
        assert result.kind == "ok"
        assert result.section_name == "financial_highlights"
        assert result.input_tokens == 200
        assert result.output_tokens == 60
        assert len(result.chunks) == 1


# --------------------------------------------------------------------------- #
# Retrieval filter + query bias                                               #
# --------------------------------------------------------------------------- #


class TestRetrievalShape:
    @pytest.mark.asyncio
    async def test_filter_narrows_to_annual_report(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="INFY",
                    text="t",
                ),
            ],
        )
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(user_id=user_id, symbol="INFY", retriever=retriever),
        )
        filter_used: RetrievalFilter = retriever.calls[0]["filter"]
        assert filter_used.document_type == "annual_report"

    @pytest.mark.asyncio
    async def test_query_has_fundamentals_bias_tokens(self) -> None:
        """Default query appends bias tokens for BM25."""
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="INFY",
                    text="t",
                ),
            ],
        )
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="INFY",
                retriever=retriever,
                user_prompt="How strong is INFY?",
            ),
        )
        query = retriever.calls[0]["query"]
        assert "How strong is INFY?" in query
        # Bias tokens from the module.
        for token in ("revenue", "EBITDA", "margin", "EPS"):
            assert token in query

    @pytest.mark.asyncio
    async def test_plan_retrieval_intent_wins(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="INFY",
                    text="t",
                ),
            ],
        )
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="INFY",
                retriever=retriever,
                retrieval_plan={"fundamentals": "FY24 margins walkthrough"},
            ),
        )
        assert retriever.calls[0]["query"] == "FY24 margins walkthrough"

    @pytest.mark.asyncio
    async def test_empty_user_prompt_still_yields_bias_query(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="INFY",
                    text="t",
                ),
            ],
        )
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="INFY",
                retriever=retriever,
                user_prompt="",
            ),
        )
        query = retriever.calls[0]["query"]
        assert "revenue" in query


# --------------------------------------------------------------------------- #
# No-data + error                                                             #
# --------------------------------------------------------------------------- #


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="INFY", retriever=retriever),
        )
        assert result.kind == "no_data"
        assert "no fundamentals chunks" in result.reason

    @pytest.mark.asyncio
    async def test_no_symbol_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = FundamentalsAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol=None, retriever=retriever),
        )
        assert result.kind == "no_data"
        assert retriever.calls == []

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="INFY",
                    text="t",
                ),
            ],
        )
        agent = FundamentalsAgent(llm=_RaisingLLM())
        with pytest.raises(RuntimeError, match="fundamentals llm exploded"):
            await agent.invoke(
                _build_context(
                    user_id=user_id,
                    symbol="INFY",
                    retriever=retriever,
                ),
            )
