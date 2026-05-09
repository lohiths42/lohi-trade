"""Unit tests for :class:`MacroAgent` (Task 13.7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.macro import MacroAgent
from src.research.agents.orchestrator import AgentContext, PlanOutput, SubAgent
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
        raise RuntimeError("macro llm exploded")


def _build_hit(
    *, chunk_id: str, user_id: UUID, symbol: str, text: str
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
    user_prompt: str = "What's the macro backdrop?",
    retrieval_plan: dict[str, str] | None = None,
) -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever,
        plan=PlanOutput(
            agents_requested=["macro"],
            retrieval_plan=retrieval_plan or {},
        ),
    )


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #


class TestIdentity:
    def test_name_is_macro(self) -> None:
        agent = MacroAgent(llm=FakeLLMProvider())
        assert agent.name == "macro"

    def test_section_name_is_macro_context(self) -> None:
        agent = MacroAgent(llm=FakeLLMProvider())
        assert agent.section_name == "macro_context"

    def test_prompt_name_matches_template(self) -> None:
        agent = MacroAgent(llm=FakeLLMProvider())
        assert agent.prompt_name == "macro_agent"

    def test_conforms_to_subagent_protocol(self) -> None:
        assert isinstance(MacroAgent(llm=FakeLLMProvider()), SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ok_with_chunks(self) -> None:
        user_id = uuid4()
        chunks = [
            _build_hit(
                chunk_id="c_macro_1",
                user_id=user_id,
                symbol="RELIANCE",
                text="Brent crude averaged USD 85/bbl during the quarter.",
            ),
        ]
        retriever = _RecordingRetriever(canned=chunks)
        llm = FakeLLMProvider(
            canned_completion='{"factors":[{"name":"commodity","observation":"Brent at USD 85/bbl [cite:c_macro_1]","chunk_id":"c_macro_1"}]}',
            canned_input_tokens=40,
            canned_output_tokens=25,
        )
        agent = MacroAgent(llm=llm)

        result = await agent.invoke(
            _build_context(
                user_id=user_id, symbol="RELIANCE", retriever=retriever
            )
        )
        assert result.kind == "ok"
        assert result.section_name == "macro_context"
        assert result.input_tokens == 40


# --------------------------------------------------------------------------- #
# Retrieval shape                                                             #
# --------------------------------------------------------------------------- #


class TestRetrievalShape:
    @pytest.mark.asyncio
    async def test_filter_does_not_narrow_document_type(self) -> None:
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
        agent = MacroAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id, symbol="RELIANCE", retriever=retriever
            )
        )
        filter_used: RetrievalFilter = retriever.calls[0]["filter"]
        assert filter_used.document_type is None

    @pytest.mark.asyncio
    async def test_query_has_macro_bias(self) -> None:
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
        agent = MacroAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="RELIANCE",
                retriever=retriever,
                user_prompt="Macro outlook?",
            )
        )
        query = retriever.calls[0]["query"]
        assert "Macro outlook?" in query
        for token in ("inflation", "rates", "FX", "commodity", "policy"):
            assert token in query

    @pytest.mark.asyncio
    async def test_plan_retrieval_intent_wins(self) -> None:
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
        agent = MacroAgent(llm=FakeLLMProvider())
        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="RELIANCE",
                retriever=retriever,
                retrieval_plan={"macro": "crude price trajectory"},
            )
        )
        assert retriever.calls[0]["query"] == "crude price trajectory"


# --------------------------------------------------------------------------- #
# Failure modes                                                               #
# --------------------------------------------------------------------------- #


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = MacroAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(
                user_id=user_id, symbol="RELIANCE", retriever=retriever
            )
        )
        assert result.kind == "no_data"
        assert "no macro chunks" in result.reason

    @pytest.mark.asyncio
    async def test_no_symbol_returns_no_data(self) -> None:
        user_id = uuid4()
        retriever = _RecordingRetriever(canned=[])
        agent = MacroAgent(llm=FakeLLMProvider())
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol=None, retriever=retriever)
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
                    symbol="RELIANCE",
                    text="t",
                )
            ]
        )
        agent = MacroAgent(llm=_RaisingLLM())
        with pytest.raises(RuntimeError, match="macro llm exploded"):
            await agent.invoke(
                _build_context(
                    user_id=user_id, symbol="RELIANCE", retriever=retriever
                )
            )
