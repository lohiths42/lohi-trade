"""Unit tests for the partials streaming helpers (Task 13.10).

Covers the four responsibilities of :mod:`src.research.agents.partials`:

* :func:`format_agent_partial` / :func:`format_done` — canonical
  serialisation of an :class:`AgentResult` (and an end-of-run marker)
  into the Redis-stream entry shape.
* :class:`RedisPartialsPublisher` — round-trip wiring that wraps a
  Redis async client's ``xadd`` method and writes to
  :data:`RESEARCH_PARTIALS_STREAM`.
* :class:`NoopPartialsPublisher` — an in-memory publisher that records
  calls for unit tests.
* Error-swallowing on publish failure — a broken Redis must not take
  down the calling code (design §3.12, §5.2).

Design references
-----------------
* §2.1 — top-down diagram (partials flow through ``research:partials``).
* §3.5 — Orchestrator graph shape.
* §3.11, §4.3 — Redis stream contracts.
* §5.2 — gateway re-emits partials as ``research:<run_id>`` Socket.IO
  events.

Satisfies
---------
* Req 1.7 — partials stream to the caller per Sub_Agent completion.
* Req 5.1 / Req 5.2 — first token / first agent latency budgets are
  enabled by the stream contract this module implements.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.orchestrator import AgentResult
from src.research.agents.partials import (
    EVENT_AGENT_DONE,
    EVENT_DONE,
    EVENT_TOKEN,
    NoopPartialsPublisher,
    PartialsPublisher,
    RedisPartialsPublisher,
    format_agent_partial,
    format_done,
    make_redis_partials_publisher,
)
from src.research.constants import RESEARCH_PARTIALS_STREAM
from src.research.providers.base import ChunkHit, ChunkRecord

# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #


class _FakeRedis:
    """In-memory stand-in for ``redis.asyncio.Redis.xadd``.

    Mirrors the ``_FakeRedis`` pattern in
    :mod:`tests.research.test_async_fallback` so the two Redis-round-trip
    publisher tests are uniform. Captures every call so tests can
    assert on the forwarded stream name, the fields dict, and the
    maxlen kwarg.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self._next_id = 1

    async def xadd(
        self,
        name: str,
        fields: Mapping[str, Any],
        **kwargs: Any,
    ) -> str:
        self.calls.append((name, dict(fields), dict(kwargs)))
        stream_id = f"{self._next_id}-0"
        self._next_id += 1
        return stream_id


class _FailingRedis:
    """Redis stand-in whose ``xadd`` always raises."""

    def __init__(self) -> None:
        self.attempts: int = 0

    async def xadd(self, name: str, fields: Mapping[str, Any], **_: Any) -> str:
        self.attempts += 1
        raise ConnectionError("redis down")


def _build_chunk_hit(chunk_id: str, *, user_id: UUID, symbol: str) -> ChunkHit:
    """Construct a minimal :class:`ChunkHit` for ``AgentResult.chunks``."""
    return ChunkHit(
        chunk=ChunkRecord(
            chunk_id=chunk_id,
            document_id=uuid4(),
            user_id=user_id,
            symbol=symbol,
            position=0,
            token_count=5,
            text="some chunk text",
            embedding=[0.1, 0.2, 0.3, 0.4],
            embedding_model="fake",
            embedding_dim=4,
        ),
        score=0.9,
    )


def _build_agent_result(
    *,
    agent_name: str = "filings",
    kind: str = "ok",
    section_name: str = "summary",
    section_md: str = "stub body",
    chunk_ids: list[str] | None = None,
    reason: str = "",
) -> AgentResult:
    chunks: list[ChunkHit] = []
    if chunk_ids:
        user_id = uuid4()
        for cid in chunk_ids:
            chunks.append(_build_chunk_hit(cid, user_id=user_id, symbol="X"))
    return AgentResult(
        agent_name=agent_name,
        kind=kind,
        section_name=section_name,
        section_md=section_md,
        chunks=chunks,
        wall_time_ms=42,
        input_tokens=10,
        output_tokens=20,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# Event-type constants                                                        #
# --------------------------------------------------------------------------- #


class TestEventConstants:
    """Event names match the Socket.IO event names the frontend listens for."""

    def test_agent_done_value(self) -> None:
        assert EVENT_AGENT_DONE == "agent_done"

    def test_done_value(self) -> None:
        assert EVENT_DONE == "done"

    def test_token_value(self) -> None:
        """``token`` is reserved for future token-level streaming (design §5.2)."""
        assert EVENT_TOKEN == "token"


# --------------------------------------------------------------------------- #
# Payload format helpers                                                      #
# --------------------------------------------------------------------------- #


class TestFormatAgentPartial:
    """:func:`format_agent_partial` produces the canonical stream entry."""

    def test_returns_three_canonical_fields(self) -> None:
        run_id = uuid4()
        result = _build_agent_result()

        entry = format_agent_partial(run_id, result)

        assert set(entry.keys()) == {"run_id", "event", "payload"}

    def test_run_id_is_stringified(self) -> None:
        run_id = uuid4()
        result = _build_agent_result()

        entry = format_agent_partial(run_id, result)

        assert entry["run_id"] == str(run_id)
        assert isinstance(entry["run_id"], str)

    def test_event_field_is_agent_done(self) -> None:
        entry = format_agent_partial(uuid4(), _build_agent_result())
        assert entry["event"] == EVENT_AGENT_DONE

    def test_payload_is_json_decodable(self) -> None:
        """The payload field is JSON-encoded so nested structures survive."""
        result = _build_agent_result(chunk_ids=["c1", "c2"])
        entry = format_agent_partial(uuid4(), result)

        payload = json.loads(entry["payload"])

        assert payload["agent_name"] == "filings"
        assert payload["kind"] == "ok"
        assert payload["section_name"] == "summary"
        assert payload["section_md"] == "stub body"
        assert payload["chunk_ids"] == ["c1", "c2"]
        assert payload["wall_time_ms"] == 42
        assert payload["input_tokens"] == 10
        assert payload["output_tokens"] == 20
        assert payload["reason"] == ""

    def test_no_data_result_round_trips(self) -> None:
        """``no_data`` / ``error`` kinds preserve the reason field."""
        result = _build_agent_result(
            kind="no_data",
            section_md="",
            reason="no filings for RELIANCE",
        )
        entry = format_agent_partial(uuid4(), result)
        payload = json.loads(entry["payload"])

        assert payload["kind"] == "no_data"
        assert payload["reason"] == "no filings for RELIANCE"

    def test_payload_is_compact_json(self) -> None:
        """JSON output uses ``separators=(",", ":")`` (no spaces)."""
        entry = format_agent_partial(uuid4(), _build_agent_result())
        assert ", " not in entry["payload"]
        assert ": " not in entry["payload"]

    def test_all_values_are_strings(self) -> None:
        """Redis Stream fields are string-typed — every value must be ``str``."""
        entry = format_agent_partial(uuid4(), _build_agent_result())
        for value in entry.values():
            assert isinstance(value, str)


class TestFormatDone:
    """:func:`format_done` produces the end-of-run marker."""

    def test_returns_three_canonical_fields(self) -> None:
        entry = format_done(uuid4(), quality="high")
        assert set(entry.keys()) == {"run_id", "event", "quality"}

    def test_run_id_is_stringified(self) -> None:
        run_id = uuid4()
        entry = format_done(run_id, quality="high")
        assert entry["run_id"] == str(run_id)

    def test_event_field_is_done(self) -> None:
        entry = format_done(uuid4(), quality="high")
        assert entry["event"] == EVENT_DONE

    @pytest.mark.parametrize("quality", ["high", "medium", "low"])
    def test_all_quality_labels_pass_through(self, quality: str) -> None:
        entry = format_done(uuid4(), quality=quality)
        assert entry["quality"] == quality

    def test_all_values_are_strings(self) -> None:
        entry = format_done(uuid4(), quality="medium")
        for value in entry.values():
            assert isinstance(value, str)


# --------------------------------------------------------------------------- #
# RedisPartialsPublisher — happy path + error swallowing                      #
# --------------------------------------------------------------------------- #


class TestRedisPartialsPublisher:
    """Round-trip wiring against a fake Redis ``xadd``."""

    @pytest.mark.asyncio
    async def test_xadd_called_with_stream_and_fields(self) -> None:
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)

        fields = format_agent_partial(uuid4(), _build_agent_result())
        result = await publisher(RESEARCH_PARTIALS_STREAM, fields)

        # ``xadd`` returns the new stream id on success.
        assert result == "1-0"
        assert len(redis.calls) == 1
        stream_name, forwarded_fields, kwargs = redis.calls[0]
        assert stream_name == RESEARCH_PARTIALS_STREAM
        # Every field was forwarded verbatim.
        for k, v in fields.items():
            assert forwarded_fields[k] == v
        # No maxlen kwarg by default.
        assert kwargs == {}

    @pytest.mark.asyncio
    async def test_default_stream_property(self) -> None:
        publisher = RedisPartialsPublisher(_FakeRedis())
        assert publisher.stream == RESEARCH_PARTIALS_STREAM

    @pytest.mark.asyncio
    async def test_custom_stream_name_is_honoured(self) -> None:
        """The publisher forwards the caller-supplied stream name verbatim."""
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)

        await publisher("custom:test_stream", {"event": "done", "run_id": "x"})

        assert redis.calls[0][0] == "custom:test_stream"

    @pytest.mark.asyncio
    async def test_maxlen_is_forwarded_when_set(self) -> None:
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis, maxlen=10_000)

        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done", "run_id": "x"})

        _, _, kwargs = redis.calls[0]
        assert kwargs == {"maxlen": 10_000}

    @pytest.mark.asyncio
    async def test_none_values_become_empty_strings(self) -> None:
        """Stream clients that require string fields reject stray ``None``s."""
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)

        await publisher(
            RESEARCH_PARTIALS_STREAM,
            {"run_id": "abc", "event": "done", "extra": None},
        )

        _, forwarded, _ = redis.calls[0]
        assert forwarded["extra"] == ""

    @pytest.mark.asyncio
    async def test_non_string_values_are_coerced(self) -> None:
        """Integers / floats are coerced so ``decode_responses=True`` clients accept them."""
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)

        await publisher(
            RESEARCH_PARTIALS_STREAM,
            {"run_id": "abc", "event": "done", "retry_count": 1},
        )

        _, forwarded, _ = redis.calls[0]
        assert forwarded["retry_count"] == "1"

    @pytest.mark.asyncio
    async def test_xadd_exception_is_swallowed(self) -> None:
        """A broken Redis must not raise from the publisher contract."""
        redis = _FailingRedis()
        publisher = RedisPartialsPublisher(redis)

        # Must not raise.
        result = await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done"})

        assert result is None
        assert redis.attempts == 1

    @pytest.mark.asyncio
    async def test_satisfies_partials_publisher_protocol(self) -> None:
        """The concrete class is a :data:`PartialsPublisher` callable."""
        redis = _FakeRedis()
        publisher: PartialsPublisher = RedisPartialsPublisher(redis)

        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done", "run_id": "x"})

        assert len(redis.calls) == 1


class TestMakeRedisPartialsPublisher:
    """Factory wires the client into a :data:`PartialsPublisher`."""

    @pytest.mark.asyncio
    async def test_factory_returns_callable_that_publishes(self) -> None:
        redis = _FakeRedis()
        publisher = make_redis_partials_publisher(redis)

        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done", "run_id": "x"})

        assert len(redis.calls) == 1
        assert redis.calls[0][0] == RESEARCH_PARTIALS_STREAM

    @pytest.mark.asyncio
    async def test_factory_passes_maxlen_through(self) -> None:
        redis = _FakeRedis()
        publisher = make_redis_partials_publisher(redis, maxlen=500)

        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done", "run_id": "x"})

        _, _, kwargs = redis.calls[0]
        assert kwargs == {"maxlen": 500}


# --------------------------------------------------------------------------- #
# NoopPartialsPublisher — in-memory recording                                 #
# --------------------------------------------------------------------------- #


class TestNoopPartialsPublisher:
    """:class:`NoopPartialsPublisher` records calls without raising."""

    @pytest.mark.asyncio
    async def test_records_calls(self) -> None:
        publisher = NoopPartialsPublisher()

        await publisher(RESEARCH_PARTIALS_STREAM, {"run_id": "x", "event": "done"})
        await publisher(RESEARCH_PARTIALS_STREAM, {"run_id": "y", "event": "done"})

        assert len(publisher.calls) == 2
        assert publisher.calls[0].stream == RESEARCH_PARTIALS_STREAM
        assert publisher.calls[0].fields == {"run_id": "x", "event": "done"}
        assert publisher.calls[1].fields == {"run_id": "y", "event": "done"}

    @pytest.mark.asyncio
    async def test_fields_are_copied_not_aliased(self) -> None:
        """Mutating the caller's dict after publishing must not affect records."""
        publisher = NoopPartialsPublisher()
        shared = {"run_id": "x", "event": "done"}

        await publisher(RESEARCH_PARTIALS_STREAM, shared)
        shared["event"] = "mutated"

        assert publisher.calls[0].fields == {"run_id": "x", "event": "done"}

    @pytest.mark.asyncio
    async def test_clear_resets_records(self) -> None:
        publisher = NoopPartialsPublisher()
        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done"})
        assert publisher.calls

        publisher.clear()
        assert publisher.calls == []

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        """Even on weird inputs the noop publisher must stay quiet."""
        publisher = NoopPartialsPublisher()
        # No error on unusual types.
        await publisher("whatever", {})
        await publisher(RESEARCH_PARTIALS_STREAM, {"k": None})
        assert len(publisher.calls) == 2

    @pytest.mark.asyncio
    async def test_satisfies_partials_publisher_protocol(self) -> None:
        """The class is usable wherever :data:`PartialsPublisher` is expected."""
        publisher: PartialsPublisher = NoopPartialsPublisher()
        await publisher(RESEARCH_PARTIALS_STREAM, {"event": "done", "run_id": "x"})
        # Type narrowing — we know it's a NoopPartialsPublisher so we can inspect .calls.
        assert isinstance(publisher, NoopPartialsPublisher)
        assert len(publisher.calls) == 1


# --------------------------------------------------------------------------- #
# End-to-end — format + publish against fake Redis                            #
# --------------------------------------------------------------------------- #


class TestEndToEnd:
    """``format_*`` + :class:`RedisPartialsPublisher` integrate cleanly."""

    @pytest.mark.asyncio
    async def test_agent_partial_round_trip(self) -> None:
        """Format an ``AgentResult``, publish it, and decode the captured fields."""
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)
        run_id = uuid4()
        result = _build_agent_result(
            agent_name="fundamentals",
            kind="ok",
            section_name="thesis",
            chunk_ids=["c1", "c2"],
        )

        entry = format_agent_partial(run_id, result)
        await publisher(RESEARCH_PARTIALS_STREAM, entry)

        _, forwarded, _ = redis.calls[0]
        assert forwarded["run_id"] == str(run_id)
        assert forwarded["event"] == "agent_done"
        payload = json.loads(forwarded["payload"])
        assert payload["agent_name"] == "fundamentals"
        assert payload["section_name"] == "thesis"
        assert payload["chunk_ids"] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_done_round_trip(self) -> None:
        redis = _FakeRedis()
        publisher = RedisPartialsPublisher(redis)
        run_id = uuid4()

        entry = format_done(run_id, quality="medium")
        await publisher(RESEARCH_PARTIALS_STREAM, entry)

        _, forwarded, _ = redis.calls[0]
        assert forwarded == {
            "run_id": str(run_id),
            "event": "done",
            "quality": "medium",
        }
