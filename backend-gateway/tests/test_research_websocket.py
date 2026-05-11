"""Unit tests for the Lohi-Research Socket.IO event bridge (Task 16.3).

Exercises :func:`app.websocket._dispatch_partial` and
:func:`app.websocket._dispatch_pubsub` with a fake ``sio`` to pin:

* the stream-entry ``event`` → Socket.IO event name mapping,
* the ``research:<run_id>`` room derivation,
* JSON-decoding of stream fields,
* silent-skip behaviour on unknown events.

Full stream consumption (xreadgroup / pubsub subscribe) is out of
scope — that path requires a live Redis. The dispatcher helpers are
the pure-function heart of the bridge and cover the contract per
design §5.2.

Requirements: 5.1, 5.2, 5.9, 6.4, 16.11, 16.17
Design: §5.2, §13.4
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.websocket import (
    _channel_for,
    _decode_field,
    _decode_payload,
    _dispatch_partial,
    _dispatch_pubsub,
)
from src.research.constants import (
    RESEARCH_JUDGE_REPORT_CHANNEL,
    RESEARCH_LATENCY_BUDGET_CHANNEL,
)


# --------------------------------------------------------------------------- #
# Fake Socket.IO server                                                       #
# --------------------------------------------------------------------------- #


class _FakeSio:
    """Minimal ``AsyncServer`` stand-in capturing ``emit`` calls."""

    def __init__(self) -> None:
        self.emits: list[tuple[str, dict, str | None]] = []

    async def emit(self, event: str, data=None, *, room=None, **_) -> None:
        self.emits.append((event, data, room))


# --------------------------------------------------------------------------- #
# _channel_for                                                                 #
# --------------------------------------------------------------------------- #


class TestChannelFor:
    def test_uuid_run_id(self) -> None:
        run_id = uuid4()
        assert _channel_for(run_id) == f"research:{run_id}"

    def test_string_run_id(self) -> None:
        assert _channel_for("abc-123") == "research:abc-123"


# --------------------------------------------------------------------------- #
# _decode_field / _decode_payload                                              #
# --------------------------------------------------------------------------- #


class TestDecodeField:
    def test_decodes_bytes(self) -> None:
        assert _decode_field(b"hello") == "hello"

    def test_passes_str_through(self) -> None:
        assert _decode_field("world") == "world"

    def test_none_becomes_empty_string(self) -> None:
        assert _decode_field(None) == ""


class TestDecodePayload:
    def test_parses_json_payload_field(self) -> None:
        payload = _decode_payload(
            {
                "event": "agent_done",
                "payload": json.dumps({"agent_name": "filings", "chunk_ids": ["c1"]}),
            }
        )
        assert payload["event"] == "agent_done"
        assert payload["payload"] == {"agent_name": "filings", "chunk_ids": ["c1"]}

    def test_non_json_stays_string(self) -> None:
        payload = _decode_payload({"event": "done", "quality": "high"})
        assert payload["quality"] == "high"

    def test_numeric_string_parsed_as_int(self) -> None:
        payload = _decode_payload({"retry_count": "1"})
        assert payload["retry_count"] == 1


# --------------------------------------------------------------------------- #
# _dispatch_partial                                                           #
# --------------------------------------------------------------------------- #


class TestDispatchPartial:
    @pytest.mark.asyncio
    async def test_agent_done_emits_on_research_run_channel(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {
                "run_id": str(run_id),
                "event": "agent_done",
                "payload": json.dumps({"agent_name": "filings"}),
            },
        )
        assert len(sio.emits) == 1
        event_name, payload, room = sio.emits[0]
        assert event_name == "research:agent_done"
        assert room == f"research:{run_id}"
        assert payload["payload"] == {"agent_name": "filings"}

    @pytest.mark.asyncio
    async def test_done_maps_to_research_done(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {"run_id": str(run_id), "event": "done", "quality": "high"},
        )
        assert sio.emits[0][0] == "research:done"
        assert sio.emits[0][2] == f"research:{run_id}"

    @pytest.mark.asyncio
    async def test_token_maps_to_research_token(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {"run_id": str(run_id), "event": "token", "delta": "Hello"},
        )
        assert sio.emits[0][0] == "research:token"

    @pytest.mark.asyncio
    async def test_guardrail_decision_maps(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {"run_id": str(run_id), "event": "guardrail_decision", "rule_id": "JB-001"},
        )
        assert sio.emits[0][0] == "research:guardrail_decision"

    @pytest.mark.asyncio
    async def test_judge_report_maps(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {"run_id": str(run_id), "event": "judge_report", "safe_to_display": "true"},
        )
        assert sio.emits[0][0] == "research:judge_report"

    @pytest.mark.asyncio
    async def test_error_maps(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {"run_id": str(run_id), "event": "error", "message": "boom"},
        )
        assert sio.emits[0][0] == "research:error"

    @pytest.mark.asyncio
    async def test_latency_budget_exceeded_maps(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {
                "run_id": str(run_id),
                "event": "latency_budget_exceeded",
                "phase": "first_token",
                "observed_ms": "900",
                "budget_ms": "800",
            },
        )
        assert sio.emits[0][0] == "research:latency_budget_exceeded"

    @pytest.mark.asyncio
    async def test_unknown_event_silently_skipped(self) -> None:
        sio = _FakeSio()
        await _dispatch_partial(
            sio,
            {"run_id": str(uuid4()), "event": "unknown_event_never_defined"},
        )
        assert sio.emits == []

    @pytest.mark.asyncio
    async def test_missing_run_id_skipped(self) -> None:
        sio = _FakeSio()
        await _dispatch_partial(sio, {"event": "done", "quality": "high"})
        assert sio.emits == []

    @pytest.mark.asyncio
    async def test_bytes_fields_decoded(self) -> None:
        """redis-py returns ``bytes`` by default; bridge must decode."""
        sio = _FakeSio()
        run_id = uuid4()
        await _dispatch_partial(
            sio,
            {
                b"run_id": str(run_id).encode("utf-8"),
                b"event": b"done",
                b"quality": b"high",
            },
        )
        assert sio.emits[0][0] == "research:done"
        assert sio.emits[0][2] == f"research:{run_id}"


# --------------------------------------------------------------------------- #
# _dispatch_pubsub                                                            #
# --------------------------------------------------------------------------- #


class TestDispatchPubsub:
    @pytest.mark.asyncio
    async def test_latency_budget_channel_scoped_to_run(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        inner = {"run_id": str(run_id), "phase": "first_token", "observed_ms": 900}
        await _dispatch_pubsub(
            sio,
            {
                "channel": RESEARCH_LATENCY_BUDGET_CHANNEL,
                "data": json.dumps(inner),
            },
        )
        assert len(sio.emits) == 1
        event, payload, room = sio.emits[0]
        assert event == "research:latency_budget_exceeded"
        assert room == f"research:{run_id}"
        assert payload["phase"] == "first_token"

    @pytest.mark.asyncio
    async def test_judge_report_channel_scoped_to_run(self) -> None:
        sio = _FakeSio()
        run_id = uuid4()
        inner = {"run_id": str(run_id), "safe_to_display": True}
        await _dispatch_pubsub(
            sio,
            {
                "channel": RESEARCH_JUDGE_REPORT_CHANNEL,
                "data": json.dumps(inner),
            },
        )
        assert len(sio.emits) == 1
        event, payload, room = sio.emits[0]
        assert event == "research:judge_report"
        assert room == f"research:{run_id}"

    @pytest.mark.asyncio
    async def test_unscoped_latency_budget_broadcasts(self) -> None:
        """No ``run_id`` in payload → unscoped broadcast (operator dashboard)."""
        sio = _FakeSio()
        await _dispatch_pubsub(
            sio,
            {
                "channel": RESEARCH_LATENCY_BUDGET_CHANNEL,
                "data": json.dumps({"phase": "startup"}),
            },
        )
        assert sio.emits[0][0] == "research:latency_budget_exceeded"
        # No room on unscoped broadcast.
        assert sio.emits[0][2] is None

    @pytest.mark.asyncio
    async def test_unknown_channel_skipped(self) -> None:
        sio = _FakeSio()
        await _dispatch_pubsub(
            sio,
            {"channel": "research:unknown", "data": "{}"},
        )
        assert sio.emits == []
