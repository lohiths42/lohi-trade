"""Redis-stream consumption primitives shared by News_Sentiment + Technicals.

The News_Sentiment Agent (Task 13.4) and the Technicals Agent (Task 13.5)
both consume existing Redis streams produced by the Commander and Soldier
(Req 8.3, Req 8.4, design §2.1) instead of going through the
retriever/embeddings path that every other Sub_Agent uses. This module
hosts the tiny bit of shared machinery those two agents need:

* :class:`StreamEvent` — a Pydantic-free, JSON-friendly dataclass that
  wraps one Redis Stream entry with just enough structure for the
  agents to filter by symbol and format into prompt context.
* :class:`RedisStreamReader` — the Protocol the agents inject. Production
  wiring hands in an adapter over ``redis.asyncio.Redis``; tests hand in
  an in-memory stub that returns canned entries.
* :func:`parse_stream_entry` / :func:`filter_events_by_symbol` — small
  helpers that parse the ``(entry_id, fields)`` tuples returned by
  ``xrevrange`` and keep only the entries for a given symbol. The
  helpers are split out from the agents themselves so the two agents
  stay in lock-step on event parsing semantics without a cross-import.

Why a reader Protocol and not a concrete ``redis.asyncio.Redis`` type?
---------------------------------------------------------------------
Unit tests for the two agents should not require a live Redis. Neither
should they depend on ``redis.asyncio`` being importable — several
trimmed test environments in this repo do not install the async Redis
extra. By expressing the contract as a :class:`typing.Protocol` the
agents accept any object with an ``xrevrange(stream_name, count=N)``
coroutine; the production wiring (gateway / worker) constructs a
small adapter around the real client in exactly one place, and tests
pass a plain Python class.

Symbol normalisation
--------------------
Upstream publishers use slightly different keys to carry the symbol:

* :mod:`src.commander.sentiment_analyzer` publishes ``ticker`` onto
  ``stream:sentiment`` (see ``SENTIMENT_STREAM_NAME``).
* :mod:`src.commander.bias_scheduler` publishes ``ticker`` onto
  ``stream:bias:{ticker}`` (sharded per ticker).
* :mod:`src.commander.news_publisher` publishes articles onto
  ``stream:news`` with a ``ticker`` field (see ``NEWS_STREAM_NAME``).
* :mod:`src.soldier.indicator_publisher` publishes indicator sets onto
  ``stream:indicators:{symbol}`` (sharded per symbol, field ``symbol``).

The helpers in this module accept any of the keys listed in
:data:`_SYMBOL_FIELD_CANDIDATES` so the agents do not need to know
which upstream wrote the event.

Design references
-----------------
* §2.1 — top-down diagram shows News_Sentiment and Technicals hanging
  off the Commander / Soldier streams.
* §3.5 — Sub_Agent graph and per-agent configurability.
* Req 8.3 / Req 8.4 — reuse of existing Commander/Soldier streams.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

__all__ = [
    "RedisStreamReader",
    "StreamEvent",
    "filter_events_by_symbol",
    "parse_stream_entry",
]


# Ordered list of field names we look at when extracting the symbol /
# ticker from an event's ``fields`` dict. ``ticker`` is the Commander
# convention; ``symbol`` is the Soldier / LOHI-TRADE convention. The
# order matters only when both are present — in practice at most one
# is, and returning the first match keeps parsing deterministic.
_SYMBOL_FIELD_CANDIDATES: Final[tuple[str, ...]] = ("ticker", "symbol")

# Timestamp field names the two upstreams use — both emit ISO-8601
# strings on the ``timestamp`` field, but we tolerate ``published_at``
# (news) and ``created_at`` for robustness against other Commander
# publishers that may be added later.
_TIMESTAMP_FIELD_CANDIDATES: Final[tuple[str, ...]] = (
    "timestamp",
    "published_at",
    "created_at",
)


@dataclass(frozen=True)
class StreamEvent:
    """One Redis Stream entry, normalised for agent consumption.

    Attributes
    ----------
    event_id:
        The Redis Stream entry id returned alongside the fields dict
        (e.g. ``"1704067200000-0"``). Forwarded verbatim into the
        prompt context so the LLM can cite a stable identifier in its
        ``[cite:<event_id>]`` markers.
    stream:
        The stream name this entry came from. The agents render it
        next to each event so the LLM knows whether a line is a news
        headline, a sentiment score, a bias classification, or a
        technical indicator snapshot.
    fields:
        The flat ``{field: value}`` dict Redis Streams carries for the
        entry. Values are strings as returned by the client (see
        :mod:`src.state.redis_client` and the
        ``decode_responses=True`` setting) — we don't coerce them
        because the LLM works better on verbatim text than on
        reformatted numbers (cf. the numeric validator which checks
        verbatim tokens, design §12).
    symbol:
        Extracted from ``fields`` via the
        :data:`_SYMBOL_FIELD_CANDIDATES` lookup so the two agents
        can filter without re-implementing the lookup per site. May
        be ``None`` when the event has no symbol context (e.g. a
        bias entry that is sharded by stream name alone); the
        Technicals Agent handles that case by passing the ticker at
        the stream-name level.
    timestamp:
        Verbatim timestamp string extracted from ``fields`` via the
        :data:`_TIMESTAMP_FIELD_CANDIDATES` lookup. Forwarded into
        the prompt context so the LLM can cite an ISO-8601 stamp.
        ``None`` when no candidate field is present — the prompt
        then renders the entry without a trailing ``@ <ts>`` marker.

    """

    event_id: str
    stream: str
    fields: Mapping[str, str] = field(default_factory=dict)
    symbol: str | None = None
    timestamp: str | None = None

    def render_prompt_line(self) -> str:
        """Render one ``# <event_id>`` block for the prompt context.

        Mirrors the ``# <chunk_id>\\n<text>`` layout that
        :func:`src.research.agents._base._format_chunks` produces so
        the Judge's ``[cite:<id>]`` grammar sees identical fences
        across retrieval-backed and stream-backed Sub_Agents. Fields
        are rendered as ``key: value`` lines in stable sorted order
        so the same event always renders identically (important for
        the retrieval cache and the Judge's claim-extraction).
        """
        header = f"# {self.event_id}"
        subheader_parts: list[str] = [f"stream: {self.stream}"]
        if self.symbol:
            subheader_parts.append(f"symbol: {self.symbol}")
        if self.timestamp:
            subheader_parts.append(f"timestamp: {self.timestamp}")
        body_lines = [
            f"{k}: {self.fields[k]}"
            for k in sorted(self.fields)
            # Skip the keys we already surfaced as subheaders so the
            # LLM doesn't see them twice.
            if k not in {"symbol", "ticker", "timestamp", "published_at", "created_at"}
        ]
        lines = [header, ", ".join(subheader_parts)]
        lines.extend(body_lines)
        return "\n".join(lines)


@runtime_checkable
class RedisStreamReader(Protocol):
    """Minimal async contract the agents need from a Redis client.

    Production wiring: a thin adapter over ``redis.asyncio.Redis`` whose
    ``xrevrange(name, count=count)`` returns a list of
    ``(entry_id, {field: value})`` tuples with ``decode_responses=True``.

    Tests: an in-memory stub that returns canned tuples per stream.

    The Protocol is deliberately narrow — we only need the most recent
    N events per stream, not streaming consumption. That matches the
    "fold recent events into context" contract from Req 8.3 / Req 8.4
    and keeps the agents insulated from the difference between
    ``xread`` (blocking consumer-group semantics) and ``xrevrange``
    (snapshot-style read).
    """

    async def xrevrange(
        self,
        name: str,
        count: int | None = None,
    ) -> list[tuple[str, Mapping[str, Any]]]:
        """Return up to ``count`` entries from ``name``, newest first."""
        ...


def parse_stream_entry(
    *,
    stream: str,
    entry: tuple[str, Mapping[str, Any]],
) -> StreamEvent:
    """Turn one ``(entry_id, fields)`` tuple into a :class:`StreamEvent`.

    Field values are coerced to ``str`` so downstream prompt rendering
    is uniform regardless of whether the client returned ``bytes``
    (``decode_responses=False``) or ``str`` (``decode_responses=True``).
    """
    entry_id, raw_fields = entry
    # ``raw_fields`` is Mapping[str, Any]; coerce values to str and
    # decode any bytes the caller may hand in. Key values are assumed
    # to already be str (the Redis client decodes them when
    # ``decode_responses=True``); tolerate bytes keys for the same
    # reason we tolerate bytes values.
    decoded_fields: dict[str, str] = {}
    for raw_k, raw_v in raw_fields.items():
        key = raw_k.decode("utf-8") if isinstance(raw_k, (bytes, bytearray)) else str(raw_k)
        if isinstance(raw_v, (bytes, bytearray)):
            value = raw_v.decode("utf-8", errors="replace")
        else:
            value = str(raw_v)
        decoded_fields[key] = value

    symbol: str | None = None
    for candidate in _SYMBOL_FIELD_CANDIDATES:
        if candidate in decoded_fields:
            symbol = decoded_fields[candidate]
            break

    timestamp: str | None = None
    for candidate in _TIMESTAMP_FIELD_CANDIDATES:
        if candidate in decoded_fields:
            timestamp = decoded_fields[candidate]
            break

    entry_id_str = (
        entry_id.decode("utf-8")
        if isinstance(entry_id, (bytes, bytearray))
        else str(entry_id)
    )

    return StreamEvent(
        event_id=entry_id_str,
        stream=stream,
        fields=decoded_fields,
        symbol=symbol,
        timestamp=timestamp,
    )


def filter_events_by_symbol(
    events: Iterable[StreamEvent],
    *,
    symbol: str,
    sharded_by_stream: bool = False,
) -> list[StreamEvent]:
    """Keep only the events that belong to ``symbol``.

    Parameters
    ----------
    events:
        The iterable of parsed :class:`StreamEvent`\\s to filter.
    symbol:
        The run's ticker scope (case-sensitive; upstream publishers
        all emit upper-case Indian-market tickers so a case-sensitive
        compare is safe).
    sharded_by_stream:
        When ``True``, events that lack a ``symbol`` / ``ticker`` in
        their fields are kept — the reader is expected to have
        scoped them via the stream name itself (e.g.
        ``stream:indicators:{symbol}``). When ``False`` (the default),
        events without a symbol field are dropped since we have no
        way to confirm they belong to the requested ticker.

    """
    kept: list[StreamEvent] = []
    for event in events:
        if event.symbol == symbol:
            kept.append(event)
            continue
        if sharded_by_stream and event.symbol is None:
            kept.append(event)
    return kept
