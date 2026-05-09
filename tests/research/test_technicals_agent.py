"""Unit tests for :class:`TechnicalsAgent` (Task 13.5).

The Technicals Agent consumes the Soldier's ``indicators`` stream
(Req 8.4) — sharded per symbol as ``indicators:{symbol}``. Tests
exercise the stream-pull → filter → (maybe) LLM contract, the
per-symbol stream-name resolution, and every failure mode.
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID, uuid4

import pytest

from src.research.agents.orchestrator import AgentContext, PlanOutput, SubAgent
from src.research.agents.technicals import TechnicalsAgent
from src.research.providers.base import LLMParams, Message
from tests.research.fakes import FakeLLMProvider


# --------------------------------------------------------------------------- #
# Stubs                                                                       #
# --------------------------------------------------------------------------- #


class _StubRedisReader:
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
        raise RuntimeError("technicals llm exploded")


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
    user_prompt: str = "Read the latest technicals",
    retriever: Any = None,
) -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        user_id=user_id,
        symbol=symbol,
        user_prompt=user_prompt,
        retriever=retriever or object(),
        plan=PlanOutput(agents_requested=["technicals"]),
    )


def _indicator_entry(
    *,
    entry_id: str,
    symbol: str | None,
    rsi: str = "52.0",
    macd: str = "0.31",
    timestamp: str = "2024-10-21T09:15:00Z",
) -> tuple[str, dict[str, str]]:
    """Shape matches :mod:`src.soldier.indicator_publisher`'s serialisation."""
    fields: dict[str, str] = {
        "rsi": rsi,
        "macd": macd,
        "timestamp": timestamp,
    }
    if symbol is not None:
        fields["symbol"] = symbol
    return (entry_id, fields)


# --------------------------------------------------------------------------- #
# Identity                                                                    #
# --------------------------------------------------------------------------- #


class TestIdentity:
    def test_name_is_technicals(self) -> None:
        agent = TechnicalsAgent(llm=FakeLLMProvider(), redis_reader=_StubRedisReader())
        assert agent.name == "technicals"

    def test_section_name_is_technical_view(self) -> None:
        agent = TechnicalsAgent(llm=FakeLLMProvider(), redis_reader=_StubRedisReader())
        assert agent.section_name == "technical_view"

    def test_default_stream_template_matches_req_8_4(self) -> None:
        agent = TechnicalsAgent(llm=FakeLLMProvider(), redis_reader=_StubRedisReader())
        assert "{symbol}" in agent.stream_name_template
        assert agent.stream_name_template == "indicators:{symbol}"

    def test_conforms_to_subagent_protocol(self) -> None:
        agent = TechnicalsAgent(llm=FakeLLMProvider(), redis_reader=_StubRedisReader())
        assert isinstance(agent, SubAgent)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ok_with_canned_events(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "indicators:RELIANCE": [
                    _indicator_entry(
                        entry_id="1700000000000-0",
                        symbol="RELIANCE",
                        rsi="48.5",
                    ),
                    _indicator_entry(
                        entry_id="1700000060000-0",
                        symbol="RELIANCE",
                        rsi="51.2",
                    ),
                ],
            }
        )
        llm = FakeLLMProvider(
            canned_completion='{"indicators":[{"name":"rsi","value":"51.2","window":"14d","chunk_id":"1700000060000-0"}],"observations":["RSI is neutral [cite:1700000060000-0]."]}',
            canned_input_tokens=140,
            canned_output_tokens=42,
        )
        agent = TechnicalsAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE")
        )

        assert result.kind == "ok"
        assert result.agent_name == "technicals"
        assert result.section_name == "technical_view"
        assert result.input_tokens == 140
        assert result.output_tokens == 42
        assert result.chunks == []
        # The per-symbol stream was consulted exactly once.
        assert reader.calls == [
            {"name": "indicators:RELIANCE", "count": agent.events_count}
        ]

    @pytest.mark.asyncio
    async def test_stream_name_template_override(self) -> None:
        """Operators pointing at the raw Soldier stream can override."""
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "stream:indicators:TCS": [
                    _indicator_entry(entry_id="1-0", symbol="TCS"),
                ],
            }
        )
        agent = TechnicalsAgent(
            llm=FakeLLMProvider(),
            redis_reader=reader,
            stream_name_template="stream:indicators:{symbol}",
        )
        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="TCS")
        )
        assert result.kind == "ok"
        assert reader.calls[0]["name"] == "stream:indicators:TCS"

    @pytest.mark.asyncio
    async def test_keeps_events_without_symbol_field(self) -> None:
        """Event without a ``symbol`` field but on a sharded stream is kept."""
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "indicators:RELIANCE": [
                    _indicator_entry(entry_id="1-0", symbol=None, rsi="60.0"),
                ],
            }
        )
        llm = _RecordingLLM()
        agent = TechnicalsAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE")
        )
        assert result.kind == "ok"
        # Event was folded into the prompt.
        system_prompt = llm.calls[0][0][0].content
        assert "60.0" in system_prompt


# --------------------------------------------------------------------------- #
# No-data                                                                     #
# --------------------------------------------------------------------------- #


class TestNoData:
    @pytest.mark.asyncio
    async def test_missing_symbol_returns_no_data(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader()
        llm = _RecordingLLM()
        agent = TechnicalsAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol=None)
        )
        assert result.kind == "no_data"
        assert "requires a symbol" in result.reason
        assert reader.calls == []
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_empty_stream_returns_no_data(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={"indicators:RELIANCE": []}
        )
        llm = _RecordingLLM()
        agent = TechnicalsAgent(llm=llm, redis_reader=reader)

        result = await agent.invoke(
            _build_context(user_id=user_id, symbol="RELIANCE")
        )
        assert result.kind == "no_data"
        assert "no recent indicators events" in result.reason
        assert "RELIANCE" in result.reason
        # Reader consulted, LLM not called.
        assert len(reader.calls) == 1
        assert llm.calls == []


# --------------------------------------------------------------------------- #
# Error paths                                                                 #
# --------------------------------------------------------------------------- #


class TestErrorPath:
    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        user_id = uuid4()
        reader = _StubRedisReader(
            per_stream={
                "indicators:RELIANCE": [
                    _indicator_entry(entry_id="1-0", symbol="RELIANCE"),
                ],
            }
        )
        agent = TechnicalsAgent(llm=_RaisingLLM(), redis_reader=reader)
        with pytest.raises(RuntimeError, match="technicals llm exploded"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE")
            )

    @pytest.mark.asyncio
    async def test_missing_reader_raises_value_error(self) -> None:
        user_id = uuid4()
        agent = TechnicalsAgent(llm=FakeLLMProvider(), redis_reader=None)
        with pytest.raises(ValueError, match="RedisStreamReader"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE")
            )

    @pytest.mark.asyncio
    async def test_template_without_symbol_placeholder_raises(self) -> None:
        """A template missing the ``{symbol}`` placeholder fails loud."""
        user_id = uuid4()
        reader = _StubRedisReader()
        agent = TechnicalsAgent(
            llm=FakeLLMProvider(),
            redis_reader=reader,
            stream_name_template="indicators",
        )
        with pytest.raises(ValueError, match=r"\{symbol\}"):
            await agent.invoke(
                _build_context(user_id=user_id, symbol="RELIANCE")
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
                "indicators:TCS": [
                    _indicator_entry(
                        entry_id="1700000000000-0",
                        symbol="TCS",
                        rsi="58.1",
                    ),
                ],
            }
        )
        llm = _RecordingLLM(canned_completion='{"indicators":[]}')
        agent = TechnicalsAgent(llm=llm, redis_reader=reader)

        await agent.invoke(
            _build_context(
                user_id=user_id,
                symbol="TCS",
                user_prompt="What do the indicators say for TCS?",
            )
        )

        assert len(llm.calls) == 1
        system = llm.calls[0][0][0].content
        for placeholder in (
            "{{REFUSAL_POLICY_BLOCK}}",
            "{{REFUSAL_NO_CONTEXT}}",
            "{{RETRIEVED_CHUNKS_VERBATIM}}",
            "{{USER_PROMPT}}",
        ):
            assert placeholder not in system
        # Event id appears as a chunk-style fence.
        assert "# 1700000000000-0" in system
        # Indicator value present verbatim.
        assert "58.1" in system
        # User prompt embedded.
        assert "What do the indicators say for TCS?" in system
