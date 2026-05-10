"""Unit tests for :class:`NewsSentimentAgent` (Task 13.4).

Unlike the retrieval-only Sub_Agents (Filings / Fundamentals /
Peer_Sector / Macro), this agent consumes the Commander's Redis streams
``news_clean`` / ``sentiment`` / ``bias`` (Req 8.3). The tests therefore
exercise the stream-pull → filter-by-symbol → (maybe) LLM contract,
not the retriever path.

Covers
------
* Happy path — stream reader returns canned events, the agent folds
  them into the prompt, the LLM is called, the resulting
  :class:`AgentResult` carries the expected identity + token counts.
* Symbol filtering — events for other tickers are dropped; a bias
  event published without a ``ticker`` field (i.e. a sharded stream
  where the stream name carries the ticker) is still kept.
* No-data paths — every stream empty → ``no_data`` + LLM never
  called; ``symbol is None`` → ``no_data`` without calling the reader
  or LLM.
* Error path — LLM exception propagates to the Orchestrator for
  Req 1.6 isolation.
* Prompt rendering — every shared-skeleton placeholder substituted
  and events rendered verbatim under ``# <event_id>``.
* SubAgent Protocol conformance + identity (name / section_name /
  prompt_name default).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.news_sentiment import NewsSentimentAgent
from src.research.agents.orchestrator import AgentContext, PlanOutput, SubAgent
from src.research.providers.base import LLMParams, Message
from tests.research.fakes import FakeLLMProvider

# --------------------------------------------------------------------------- #
# Stubs                                                                       #
# --------------------------------------------------------------------------- #


class _StubRedisReader:
    """Stream reader stub: returns canned entries keyed by stream name.

    Honours the :class:`RedisStreamReader` Protocol shape:
    ``xrevrange(name, count=N) -> list[(entry_id, fields)]``.
    """

    def __init__(
        self,
        per_stream: Mapping[str, list[tuple[str, dict[str, str]]]] | None = None,
    ) -> None:
        self._per_stream = dict(per_stream or {})
        self.calls: list[dict[str, Any]] = []

    async def xrevrange(
        self,
        name: str,
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        self.calls.append({"name": name, "count": count})
        entries = list(self._per_stream.get(name, []))
        if count is not None:
            entries = entries[:count]
        return entries


class _RaisingLLM(FakeLLMProvider):
    async def complete(self, messages: list[Message], params: LLMParams):
        raise RuntimeError("news_sentiment llm exploded")


class _RecordingLLM(FakeLLMProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[list[Message], LLMParams]] = []

    async def complete(self, messages: list[Message], params: LLMParams):
        self.calls.append(([m.model_copy() for m in messages], params))
        return await super().complete(messages, params)


def _build_context(
    *,
    user_id: UUID,
    symbol: str | None,
    user_prompt: str = "What's the news sentiment today?",
    retriever: Any = None,
) -> AgentContext:
    """Build a context; retriever is irrelevant for this agent."""
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever or object(),
        plan=PlanOutput(agents_requested=["news_sentiment"]),
    )


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #


class TestIdentity:
    def test_name_is_news_sentiment(self) -> None:
        agent = NewsSentimentAgent(
            llm=FakeLLMProvider(), redis_reader=_StubRedisReader(),
        )
        assert agent.name == "news_sentiment"

    def test_section_name_is_summary(self) -> None:
        agent = NewsSentimentAgent(
            llm=FakeLLMProvider(), redis_reader=_StubRedisReader(),
        )
        assert agent.section_name == "summary"

    def test_default_stream_names_match_req_8_3(self) -> None:
        """Req 8.3 enumerates ``news_clean``, ``sentiment``, ``bias``."""
        agent = NewsSentimentAgent(
            llm=FakeLLMProvider(), redis_reader=_StubRedisReader(),
        )
        assert agent.news_clean_stream == "news_clean"
        assert agent.sentiment_stream == "sentiment"
        assert agent.bias_stream == "bias"

    def test_conforms_to_subagent_protocol(self) -> None:
        agent = NewsSentimentAgent(
            llm=FakeLLMProvider(), redis_reader=_StubRedisReader(),
        )
        assert isinstance(agent, SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ok_and_calls_every_stream(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [
                    (
                        "1700000000000-0",
                        {
                            "article_id": "a1",
                            "ticker": "RELIANCE",
                            "title": "Reliance posts record quarterly profit",
                            "published_at": "2024-10-21T09:00:00Z",
                        },
                    ),
                ],
                "sentiment": [
                    (
                        "1700000001000-0",
                        {
                            "article_id": "a1",
                            "ticker": "RELIANCE",
                            "sentiment": "POSITIVE",
                            "confidence": "0.87",
                            "timestamp": "2024-10-21T09:05:00Z",
                        },
                    ),
                ],
                "bias": [
                    (
                        "1700000002000-0",
                        {
                            "ticker": "RELIANCE",
                            "bias": "BULLISH",
                            "score": "0.72",
                            "article_count": "5",
                            "timestamp": "2024-10-21T09:10:00Z",
                        },
                    ),
                ],
            },
        )
        llm = FakeLLMProvider(
            canned_completion='{"headlines":[{"text":"Reliance posts record quarterly profit [cite:1700000000000-0]","published_at":"2024-10-21T09:00:00Z","sentiment":"positive","chunk_id":"1700000000000-0"}],"themes":["earnings [cite:1700000001000-0]"],"sentiment_summary":"Bullish [cite:1700000002000-0]."}',
            canned_input_tokens=180,
            canned_output_tokens=55,
        )
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )

        assert result.kind == "ok"
        assert result.agent_name == "news_sentiment"
        assert result.section_name == "summary"
        assert result.input_tokens == 180
        assert result.output_tokens == 55
        # ``chunks`` stays empty — provenance is via event_ids embedded
        # in ``section_md``.
        assert result.chunks == []
        # All three streams consulted in order.
        assert [call["name"] for call in reader.calls] == [
            "news_clean",
            "sentiment",
            "bias",
        ]
        # Each call asks for the configured window.
        for call in reader.calls:
            assert call["count"] == agent.events_per_stream

    @pytest.mark.asyncio
    async def test_events_per_stream_override(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [
                    ("1-0", {"ticker": "RELIANCE", "title": "t"}),
                ],
            },
        )
        agent = NewsSentimentAgent(
            llm=FakeLLMProvider(), redis_reader=reader, events_per_stream=5,
        )
        await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )
        for call in reader.calls:
            assert call["count"] == 5


# --------------------------------------------------------------------------- #
# Symbol filtering                                                            #
# --------------------------------------------------------------------------- #


class TestSymbolFiltering:
    @pytest.mark.asyncio
    async def test_other_tickers_are_dropped(self) -> None:
        """Events whose ``ticker`` field doesn't match are dropped."""
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [
                    ("1-0", {"ticker": "RELIANCE", "title": "reliance news"}),
                    ("2-0", {"ticker": "TCS", "title": "tcs news"}),
                    ("3-0", {"ticker": "INFY", "title": "infy news"}),
                ],
            },
        )
        llm = _RecordingLLM()
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )
        assert result.kind == "ok"
        assert len(llm.calls) == 1
        system_prompt = llm.calls[0][0][0].content
        # Only the RELIANCE event shows up in the rendered prompt.
        assert "reliance news" in system_prompt
        assert "tcs news" not in system_prompt
        assert "infy news" not in system_prompt

    @pytest.mark.asyncio
    async def test_event_without_ticker_kept_for_sharded_stream(self) -> None:
        """A bias event with no ``ticker`` field still survives (sharded shape)."""
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "bias": [
                    (
                        "1-0",
                        {
                            # No ``ticker`` or ``symbol`` key — upstream
                            # sharded the stream by name (e.g.
                            # ``bias:RELIANCE``).
                            "bias": "BULLISH",
                            "score": "0.7",
                        },
                    ),
                ],
            },
        )
        llm = _RecordingLLM()
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )
        assert result.kind == "ok"
        assert len(llm.calls) == 1
        # The field-less bias event was folded into the prompt.
        system_prompt = llm.calls[0][0][0].content
        assert "BULLISH" in system_prompt


# --------------------------------------------------------------------------- #
# No-data paths                                                               #
# --------------------------------------------------------------------------- #


class TestNoData:
    @pytest.mark.asyncio
    async def test_missing_symbol_returns_no_data(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader()
        llm = _RecordingLLM()
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol=None),
        )
        assert result.kind == "no_data"
        assert "requires a symbol" in result.reason
        # Neither reader nor LLM is called.
        assert reader.calls == []
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_all_streams_empty_returns_no_data(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={"news_clean": [], "sentiment": [], "bias": []},
        )
        llm = _RecordingLLM()
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )
        assert result.kind == "no_data"
        # Reason surfaces the configured stream names.
        assert "no recent" in result.reason
        assert "RELIANCE" in result.reason
        # Reader was consulted for every stream.
        assert len(reader.calls) == 3
        # LLM was not called.
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_all_events_for_other_symbol_returns_no_data(self) -> None:
        """Events exist but none match the run's ticker → no_data."""
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [("1-0", {"ticker": "TCS", "title": "t"})],
                "sentiment": [("2-0", {"ticker": "TCS", "sentiment": "POSITIVE"})],
                "bias": [("3-0", {"ticker": "TCS", "bias": "BULLISH"})],
            },
        )
        llm = _RecordingLLM()
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE"),
        )
        assert result.kind == "no_data"
        assert llm.calls == []


# --------------------------------------------------------------------------- #
# Error path                                                                  #
# --------------------------------------------------------------------------- #


class TestErrorPath:
    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [("1-0", {"ticker": "RELIANCE", "title": "t"})],
            },
        )
        agent = NewsSentimentAgent(llm=_RaisingLLM(), redis_reader=reader)
        with pytest.raises(RuntimeError, match="news_sentiment llm exploded"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE"),
            )

    @pytest.mark.asyncio
    async def test_missing_reader_raises_value_error(self) -> None:
        user_id = uuid4()
        agent = NewsSentimentAgent(llm=FakeLLMProvider(), redis_reader=None)
        with pytest.raises(ValueError, match="RedisStreamReader"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE"),
            )

    @pytest.mark.asyncio
    async def test_missing_llm_raises_value_error(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [("1-0", {"ticker": "RELIANCE", "title": "t"})],
            },
        )
        agent = NewsSentimentAgent(llm=None, redis_reader=reader)
        with pytest.raises(ValueError, match="LLMProvider"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE"),
            )


# --------------------------------------------------------------------------- #
# Prompt rendering                                                            #
# --------------------------------------------------------------------------- #


class TestPromptRendering:
    @pytest.mark.asyncio
    async def test_every_placeholder_resolved(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "news_clean": [
                    (
                        "1700000000000-0",
                        {
                            "ticker": "TCS",
                            "title": "TCS wins large deal",
                            "published_at": "2024-10-21T09:00:00Z",
                        },
                    ),
                ],
            },
        )
        llm = _RecordingLLM(canned_completion='{"headlines":[]}')
        agent = NewsSentimentAgent(llm=llm, redis_reader=reader)

        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="TCS",
                user_prompt="Summarise today's news for TCS",
            ),
        )

        assert len(llm.calls) == 1
        system = llm.calls[0][0][0].content
        # No un-rendered placeholders survived.
        for placeholder in (
            "{{REFUSAL_POLICY_BLOCK}}",
            "{{REFUSAL_NO_CONTEXT}}",
            "{{RETRIEVED_CHUNKS_VERBATIM}}",
            "{{USER_PROMPT}}",
        ):
            assert placeholder not in system
        # Event id appears as a chunk-style fence the LLM can cite.
        assert "# 1700000000000-0" in system
        # Event fields are rendered verbatim.
        assert "TCS wins large deal" in system
        # User prompt embedded.
        assert "Summarise today's news for TCS" in system
