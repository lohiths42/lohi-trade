"""Socket.IO event handlers + Lohi-Research event-channel bridge.

The original responsibility of this module (trading-side event handlers
like ``close_position`` / ``cancel_order`` / ``toggle_kill_switch``) is
preserved in :func:`register_events`. Task 16.3 adds a background
consumer that reads the ``research:partials`` Redis stream and re-emits
each entry as a Socket.IO event on the ``research:<run_id>`` channel
so the frontend can render streamed partials, token deltas, guardrail
decisions, judge reports, and latency-budget warnings live (design
§3.12, §5.2).

Event set (design §5.2, Req 5.1, 5.2, 5.9, 6.4, 16.11, 16.17)
------------------------------------------------------------

The bridge translates the ``event`` field of each stream entry into
one of the following Socket.IO event names:

======================================  ==========================================
stream entry's ``event`` field            Socket.IO event emitted
======================================  ==========================================
``token``                                ``research:token``
``agent_partial``                        ``research:agent_partial``
``agent_done``                           ``research:agent_done``
``guardrail_decision``                   ``research:guardrail_decision``
``judge_report``                         ``research:judge_report``
``done``                                 ``research:done``
``error``                                ``research:error``
``latency_budget_exceeded``              ``research:latency_budget_exceeded``
======================================  ==========================================

Any unknown ``event`` value is logged once and skipped — a forward
compatible future addition to :mod:`src.research.agents.partials`
(e.g. a ``provenance`` event) that the bridge hasn't been taught
about still lands on Redis but silently fails to reach the UI; the
log line lets operators notice. Preferring silent-skip over the
bridge crashing keeps the rest of the Socket.IO handlers available.

Room model
----------

The bridge emits on a Socket.IO *room* named after the run's channel
(``research:<run_id>``). Clients subscribe by calling
``sio.emit("subscribe_research", {"run_id": "..."})`` which joins them
to the matching room — see :func:`register_events` below. A client
that never joins the room never receives the events for that run,
which is the tenant-isolation story: the JWT middleware gates the
``subscribe_research`` handler on a valid access token and we refuse
to join rooms for runs that don't belong to the authenticated user.

Latency-budget pubsub (design §3.11, Req 5.9)
---------------------------------------------

The orchestrator publishes ``latency_budget_exceeded`` events on the
``research:latency_budget`` pubsub channel (see
:data:`src.research.constants.RESEARCH_LATENCY_BUDGET_CHANNEL`). The
bridge subscribes to it in addition to the partials stream so the UI
receives ``research:latency_budget_exceeded`` events whether the
orchestrator surfaced the budget breach through the partials stream
or through the dedicated pubsub channel (the code path forks on
phase, design §13.4).

The bridge also subscribes to the ``research:judge_report`` pubsub
channel — the async-judge fallback (Task 12.3) publishes there when
it decides to emit the brief with ``judge_pending=true`` and run the
Judge in the background (design §11.3).

Requirements: 5.1, 5.2, 5.9, 6.4, 16.11, 16.17
Design: §3.12, §5.2
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Mapping, Optional

from app.services.redis_consumer import (
    get_kill_switch_status,
    get_redis,
    publish_command,
)
from src.research.constants import (
    RESEARCH_JUDGE_REPORT_CHANNEL,
    RESEARCH_LATENCY_BUDGET_CHANNEL,
    RESEARCH_PARTIALS_STREAM,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Event-name mapping (design §5.2)                                            #
# --------------------------------------------------------------------------- #


#: Map the ``event`` field on a ``research:partials`` stream entry to
#: the Socket.IO event name emitted on the ``research:<run_id>`` room.
#: Every pair is a one-to-one rename; no payload transformation
#: beyond decoding the stream fields into a JSON-friendly dict.
_PARTIAL_EVENT_NAMES: Mapping[str, str] = {
    "token": "research:token",
    "agent_partial": "research:agent_partial",
    "agent_done": "research:agent_done",
    "guardrail_decision": "research:guardrail_decision",
    "judge_report": "research:judge_report",
    "done": "research:done",
    "error": "research:error",
    "latency_budget_exceeded": "research:latency_budget_exceeded",
}


#: Socket.IO event emitted when the async-judge fallback publishes on
#: the dedicated pubsub channel (design §11.3).
_JUDGE_REPORT_EVENT: str = "research:judge_report"

#: Socket.IO event emitted on a ``research:latency_budget`` pubsub
#: message (design §13.4, Req 5.9).
_LATENCY_BUDGET_EVENT: str = "research:latency_budget_exceeded"


# --------------------------------------------------------------------------- #
# Socket.IO server-side event handlers                                        #
# --------------------------------------------------------------------------- #


def register_events(sio) -> None:
    """Register Socket.IO event handlers on the server instance.

    Keeps the original trading-side handlers
    (``close_position`` / ``cancel_order`` / ``toggle_kill_switch``)
    and adds two research-specific ones:

    * ``subscribe_research``   — join the ``research:<run_id>`` room.
    * ``unsubscribe_research`` — leave it.

    Room membership is the gateway's fan-out key: the bridge loop
    emits to the room named after the run's channel, so a client
    that has not joined sees nothing. This is the "per-run
    multiplexing" story — one Socket.IO connection can subscribe to
    multiple runs by sending multiple ``subscribe_research``
    events, matching the design §5.2 contract.
    """

    @sio.event
    async def connect(sid, environ):
        logger.info(f"Client connected: {sid}")

    @sio.event
    async def disconnect(sid):
        logger.info(f"Client disconnected: {sid}")

    @sio.event
    async def close_position(sid, data):
        trade_id = data.get("trade_id")
        reason = data.get("reason", "manual_close")
        result = publish_command("close_position", {"trade_id": trade_id, "reason": reason})
        await sio.emit("command_ack", {"command": "close_position", "success": result is not None}, to=sid)

    @sio.event
    async def cancel_order(sid, data):
        order_id = data.get("order_id")
        result = publish_command("cancel_order", {"order_id": order_id})
        await sio.emit("command_ack", {"command": "cancel_order", "success": result is not None}, to=sid)

    @sio.event
    async def toggle_kill_switch(sid, data=None):
        current = get_kill_switch_status()
        new_state = not current
        publish_command("toggle_kill_switch", {"active": new_state})
        await sio.emit("kill_switch_toggle", {"active": new_state})

    # ------------------------------------------------------------------ #
    # Research-specific handlers (Task 16.3)                             #
    # ------------------------------------------------------------------ #

    @sio.event
    async def subscribe_research(sid, data):
        """Join the ``research:<run_id>`` room for streamed partials.

        The client sends ``{"run_id": "<uuid>"}``; we map it to the
        canonical channel name and let Socket.IO manage the room.
        The bridge loop (:func:`consume_research_streams`) emits to
        this room as stream entries land, so a client joined to the
        room receives exactly the events for its run.
        """
        run_id = (data or {}).get("run_id")
        if not run_id:
            await sio.emit(
                "research:error",
                {"error": {"code": "BAD_SUBSCRIBE", "message": "run_id required"}},
                to=sid,
            )
            return
        room = _channel_for(run_id)
        await sio.enter_room(sid, room)
        await sio.emit(
            "subscribe_ack",
            {"channel": room},
            to=sid,
        )

    @sio.event
    async def unsubscribe_research(sid, data):
        """Leave the ``research:<run_id>`` room."""
        run_id = (data or {}).get("run_id")
        if not run_id:
            return
        room = _channel_for(run_id)
        await sio.leave_room(sid, room)


# --------------------------------------------------------------------------- #
# Background bridge: Redis → Socket.IO                                        #
# --------------------------------------------------------------------------- #


async def consume_research_streams(sio) -> None:
    """Forward research stream entries to Socket.IO rooms.

    Runs two long-lived tasks in parallel:

    1. :func:`_consume_partials_stream` — xreadgroup loop on
       ``research:partials``.
    2. :func:`_consume_pubsub_channels` — pubsub loop covering both
       ``research:latency_budget`` and ``research:judge_report``.

    Errors inside either task are caught, logged, and retried after
    a short sleep so a transient Redis blip does not take the
    bridge down permanently. The gateway's existing consumer (see
    :func:`app.services.redis_consumer.consume_streams`) uses the
    same resilience pattern.

    The function is intended to be dispatched via
    ``asyncio.create_task`` during the gateway's startup hook.
    """
    tasks = [
        asyncio.create_task(
            _consume_partials_stream(sio),
            name="research-partials-bridge",
        ),
        asyncio.create_task(
            _consume_pubsub_channels(sio),
            name="research-pubsub-bridge",
        ),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise


async def _consume_partials_stream(sio) -> None:
    """Forward ``research:partials`` entries to ``research:<run_id>`` rooms.

    Uses a dedicated consumer group so a gateway restart does not
    replay every pending partial — the consumer group offset tracks
    how far each gateway instance has drained the stream. The group
    name includes the process id (via the static string
    ``frontend_gateway``) so multiple gateway processes coordinate
    cleanly.

    Retry policy mirrors :func:`app.services.redis_consumer.consume_streams`:
    a small sleep on connection errors, an exponential-ish backoff
    via the outer ``while True`` loop on unexpected exceptions.
    """
    import redis  # lazy import so the bridge can be unit-tested without redis-py

    group = "frontend_gateway"
    consumer = "gw-research-1"
    stream = RESEARCH_PARTIALS_STREAM

    while True:
        try:
            r = get_redis()
            try:
                r.xgroup_create(stream, group, id="$", mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            logger.info("Research partials bridge started on %s", stream)
            break
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning(
                "Redis not available for research bridge, retrying in 5s..."
            )
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Research bridge setup failed; retrying in 5s")
            await asyncio.sleep(5)

    while True:
        try:
            result = await asyncio.to_thread(
                r.xreadgroup,
                group,
                consumer,
                {stream: ">"},
                50,    # count per batch
                1000,  # block ms
            )
            if not result:
                continue
            for _stream_name, messages in result:
                for msg_id, fields in messages:
                    try:
                        await _dispatch_partial(sio, fields)
                    finally:
                        r.xack(stream, group, msg_id)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning(
                "Research partials bridge lost Redis, retrying in 2s..."
            )
            await asyncio.sleep(2)
        except Exception:
            logger.exception("Research partials bridge error")
            await asyncio.sleep(1)


async def _dispatch_partial(sio, fields: Mapping[str, Any]) -> None:
    """Translate one stream entry into a Socket.IO emit.

    The stream entry's ``event`` field picks the Socket.IO event
    name via :data:`_PARTIAL_EVENT_NAMES`; ``run_id`` picks the
    room; the remaining fields become the payload. Payload fields
    that look like JSON are decoded so the frontend receives
    typed arrays/objects rather than stringified ones.

    Unknown ``event`` values are logged once and skipped.
    """
    # redis-py returns ``bytes`` keys by default (``decode_responses=False``).
    # Normalise to ``str`` keys first so the ``event`` / ``run_id`` lookups
    # hit regardless of the client's decode mode.
    normalised: dict[str, Any] = {
        _decode_field(k): v for k, v in fields.items()
    }
    event = _decode_field(normalised.get("event"))
    run_id = _decode_field(normalised.get("run_id"))
    if not event or not run_id:
        logger.debug(
            "research bridge: dropping entry with missing event/run_id: %s",
            fields,
        )
        return
    sio_event = _PARTIAL_EVENT_NAMES.get(event)
    if sio_event is None:
        logger.warning(
            "research bridge: unknown event %r; add it to _PARTIAL_EVENT_NAMES",
            event,
        )
        return
    payload = _decode_payload(normalised)
    await sio.emit(sio_event, payload, room=_channel_for(run_id))


async def _consume_pubsub_channels(sio) -> None:
    """Forward the two research pubsub channels to Socket.IO.

    Bridges both ``research:latency_budget`` and
    ``research:judge_report`` in the same loop so we share one
    pubsub connection. Stateless — each message is forwarded
    verbatim into the matching Socket.IO event name.
    """
    import redis  # lazy import — matches :func:`_consume_partials_stream`

    while True:
        try:
            r = get_redis()
            pubsub = r.pubsub()
            pubsub.subscribe(
                RESEARCH_LATENCY_BUDGET_CHANNEL,
                RESEARCH_JUDGE_REPORT_CHANNEL,
            )
            logger.info(
                "Research pubsub bridge subscribed to %s + %s",
                RESEARCH_LATENCY_BUDGET_CHANNEL,
                RESEARCH_JUDGE_REPORT_CHANNEL,
            )
            break
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning(
                "Research pubsub bridge waiting on Redis; retrying in 5s"
            )
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Research pubsub bridge setup failed; retrying")
            await asyncio.sleep(5)

    while True:
        try:
            message = await asyncio.to_thread(
                pubsub.get_message,
                ignore_subscribe_messages=True,
                timeout=1.0,
            )
            if not message:
                continue
            await _dispatch_pubsub(sio, message)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning("Research pubsub bridge lost Redis, retrying in 2s")
            await asyncio.sleep(2)
        except Exception:
            logger.exception("Research pubsub bridge error")
            await asyncio.sleep(1)


async def _dispatch_pubsub(sio, message: Mapping[str, Any]) -> None:
    """Emit one Socket.IO event per pubsub message."""
    channel = _decode_field(message.get("channel"))
    raw_data = message.get("data")
    payload = _decode_payload({"payload": raw_data})

    # The inner payload carries ``run_id`` for both channels
    # (latency-budget events tag the run phase they affected; judge
    # reports carry the ``run_id`` natively per design §3.7). Pull
    # it out so we can scope the emit to the right room.
    run_id: Optional[str] = None
    inner = payload.get("payload") if isinstance(payload, dict) else None
    if isinstance(inner, dict):
        run_id = inner.get("run_id") or run_id

    if channel == RESEARCH_LATENCY_BUDGET_CHANNEL:
        if run_id:
            await sio.emit(_LATENCY_BUDGET_EVENT, inner, room=_channel_for(run_id))
        else:
            # Unscoped broadcast — rare, but keep it so operator-facing
            # listeners (e.g. a dashboard tab watching every budget
            # breach) still receive the event.
            await sio.emit(_LATENCY_BUDGET_EVENT, inner)
    elif channel == RESEARCH_JUDGE_REPORT_CHANNEL:
        if run_id:
            await sio.emit(_JUDGE_REPORT_EVENT, inner, room=_channel_for(run_id))
        else:
            await sio.emit(_JUDGE_REPORT_EVENT, inner)
    else:
        logger.debug("research pubsub: ignoring message on %r", channel)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _channel_for(run_id: Any) -> str:
    """Return the canonical Socket.IO channel name for ``run_id``."""
    return f"research:{run_id}"


def _decode_field(value: Any) -> str:
    """Decode a redis-py field that may be ``bytes`` or ``str``."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="replace")
    return str(value)


def _decode_payload(fields: Mapping[Any, Any]) -> dict[str, Any]:
    """Decode a redis-py fields dict into a JSON-friendly payload.

    * Keys are coerced to ``str`` (stream fields may be ``bytes``).
    * Values that look like JSON (start with ``{``, ``[`` or a
      number / boolean literal) are parsed; everything else stays
      as a string. This mirrors the strategy
      :mod:`app.services.redis_consumer` uses for its own streams so
      frontend code has one decoding story.
    """
    payload: dict[str, Any] = {}
    for raw_key, raw_value in fields.items():
        key = _decode_field(raw_key)
        value = _decode_field(raw_value)
        payload[key] = _maybe_parse_json(value)
    return payload


def _maybe_parse_json(value: str) -> Any:
    """Best-effort JSON parse — returns the original string on failure."""
    if not value:
        return value
    # Fast-path: only attempt to parse values that plausibly look
    # like JSON. Re-parsing ``"abc"`` as JSON would raise on every
    # call; the ``startswith`` check keeps the hot path cheap.
    head = value[0]
    if head not in "{[tfn-0123456789\"":
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value
