"""Unit tests for :class:`PeerSectorAgent` (Task 13.6)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.orchestrator import AgentContext, PlanOutput, SubAgent
from src.research.agents.peer_sector import PeerSectorAgent
from src.research.providers.base import (
    ChunkHit,
    ChunkRecord,
    LLMParams,
    Message,
    RetrievalFilter,
)
from tests.research.fakes import FakeLLMProvider


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
        raise RuntimeError("peer_sector llm exploded")


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
    user_prompt: str = "Who are the peers?",
    retrieval_plan: dict[str, str] | None = None,
) -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever,
        plan=PlanOutput(
            agents_requested=["peer_sector"],
            retrieval_plan=retrieval_plan or {},
        ),
    )


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #


class TestIdentity:
    def test_name_is_peer_sector(self) -> None:
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        assert agent.name == "peer_sector"

    def test_section_name_is_peers(self) -> None:
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        assert agent.section_name == "peers"

    def test_prompt_name_matches_template(self) -> None:
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        assert agent.prompt_name == "peer_sector_agent"

    def test_conforms_to_subagent_protocol(self) -> None:
        assert isinstance(PeerSectorAgent(llm=FakeLLMProvider()), SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ok_with_chunks(self) -> None:
        user_id = uuid4()
        chunks = [
            _build_hit(
                chunk_id="c_peers_1",
                user_id=user_id,
                symbol="TCS",
                text="TCS competes with INFY, WIPRO, and HCLTECH in IT services.",
            ),
        ]
        retriever = _RecordingRetriever(canned=chunks)
        llm = FakeLLMProvider(
            canned_completion='{"sector":"IT services [cite:c_peers_1]","peers":[{"symbol":"INFY","relation":"competitor","chunk_id":"c_peers_1"}]}',
            canned_input_tokens=55,
            canned_output_tokens=30,
        )
        agent = PeerSectorAgent(llm=llm)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="TCS", retriever=retriever),
        )
        assert result.kind == "ok"
        assert result.agent_name == "peer_sector"
        assert result.section_name == "peers"
        assert result.input_tokens == 55


# --------------------------------------------------------------------------- #
# Retrieval shape                                                             #
# --------------------------------------------------------------------------- #


class TestRetrievalShape:
    @pytest.mark.asyncio
    async def test_filter_does_not_narrow_document_type(self) -> None:
        """Peer/sector evidence spans every doc type — no narrowing."""
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="TCS",
                    text="t",
                ),
            ],
        )
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(user_id=user_id, symbol="TCS", retriever=retriever),
        )
        filter_used: RetrievalFilter = retriever.calls[0]["filter"]
        assert filter_used.document_type is None
        assert filter_used.user_id == user_id
        assert filter_used.symbol == "TCS"

    @pytest.mark.asyncio
    async def test_query_has_peer_sector_bias(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="TCS",
                    text="t",
                ),
            ],
        )
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="TCS",
                retriever=retriever,
                user_prompt="Why invest in TCS?",
            ),
        )
        query = retriever.calls[0]["query"]
        assert "Why invest in TCS?" in query
        for token in ("peers", "competitors", "sector", "industry"):
            assert token in query

    @pytest.mark.asyncio
    async def test_plan_retrieval_intent_wins(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="TCS",
                    text="t",
                ),
            ],
        )
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="TCS",
                retriever=retriever,
                retrieval_plan={"peer_sector": "compare TCS to INFY"},
            ),
        )
        assert retriever.calls[0]["query"] == "compare TCS to INFY"


# --------------------------------------------------------------------------- #
# Failure modes                                                               #
# --------------------------------------------------------------------------- #


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="TCS", retriever=retriever),
        )
        assert result.kind == "no_data"
        assert "no peer_sector chunks" in result.reason

    @pytest.mark.asyncio
    async def test_no_symbol_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = PeerSectorAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol=None, retriever=retriever),
        )
        assert result.kind == "no_data"

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(
            canned=[
                _build_hit(
                    chunk_id="c",
                    user_id=user_id,
                    symbol="TCS",
                    text="t",
                ),
            ],
        )
        agent = PeerSectorAgent(llm=_RaisingLLM())
        with pytest.raises(RuntimeError, match="peer_sector llm exploded"):
            await agent.invoke(
                _build_context(
                    user_id=user_id,
                    symbol="TCS",
                    retriever=retriever,
                ),
            )
