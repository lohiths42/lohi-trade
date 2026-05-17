"""Unit tests for :class:`BiasInvalidationListener` (Task 15.2).

The listener translates Commander ``stream:bias:<TICKER>`` events into
per-user snapshot invalidations on
:data:`RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM`. The tests use

* a :class:`_FakeStreamReader` matching the
  :class:`RedisStreamReader` Protocol;
* a :class:`_RecordingPublisher` that captures every published entry;
* a :class:`_InMemoryWatchlist` resolver returning static mappings.

No Redis, no Postgres — just the translation logic.

Covers
------
* Happy path — bias event on ``stream:bias:RELIANCE`` carrying a
  ``ticker`` field fans out one invalidation per user watching
  ``RELIANCE``.
* Sharded streams — an event with no ``ticker`` field but published
  on ``stream:bias:TCS`` still resolves to ``TCS``.
* Empty-watchlist skip — no users watching the symbol → no
  invalidations published.
* Dedup — the same ``(stream, entry_id)`` pair is not translated
  twice across successive polls.
* Explicit vs scan-based stream discovery.
* Resolver failure is swallowed; the listener keeps running.
* Publish failure is swallowed; subsequent users are still processed.
* ``invalidation_fields`` carry the canonical field set.

Satisfies: Req 8.3, Req 11.3, design §3.10.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents._stream import StreamEvent
from src.research.constants import RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM
from src.research.snapshot.bias_listener import (
    BiasInvalidationListener,
    build_invalidation_fields,
)

# --------------------------------------------------------------------------- #
# Stubs                                                                       #
# --------------------------------------------------------------------------- #


class _FakeStreamReader:
    """Return canned ``xrevrange`` results per stream name."""

    def __init__(
        self,
        per_stream: Mapping[str, list[tuple[str, dict[str, str]]]] | None = None,
    ) -> None:
        self._per_stream: dict[str, list[tuple[str, dict[str, str]]]] = {
            k: list(v) for k, v in (per_stream or {}).items()
        }
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


class _RecordingPublisher:
    """Async callable that captures every (stream, fields) call."""

    def __init__(self, *, raise_on_calls: list[int] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._raise_on_calls = list(raise_on_calls or [])

    async def __call__(self, stream: str, fields: Mapping[str, Any]) -> Any:
        idx = len(self.calls)
        self.calls.append((stream, dict(fields)))
        if idx in self._raise_on_calls:
            raise RuntimeError("simulated publish failure")
        return f"entry-{idx}"


class _InMemoryWatchlist:
    """Static ``symbol -> list[user_id]`` mapping."""

    def __init__(
        self,
        mapping: Mapping[str, list[UUID]] | None = None,
        *,
        raise_on: str | None = None,
    ) -> None:
        self._mapping: dict[str, list[UUID]] = {
            k.upper(): list(v) for k, v in (mapping or {}).items()
        }
        self._raise_on = raise_on.upper() if raise_on else None
        self.calls: list[str] = []

    async def users_watching(self, symbol: str) -> list[UUID]:
        self.calls.append(symbol)
        if self._raise_on and symbol.upper() == self._raise_on:
            raise RuntimeError("simulated watchlist failure")
        return list(self._mapping.get(symbol.upper(), []))


# --------------------------------------------------------------------------- #
# Constructor validation                                                      #
# --------------------------------------------------------------------------- #


class TestConstructor:
    def test_requires_streams_or_scan(self) -> None:
        with pytest.raises(ValueError, match="streams"):
            BiasInvalidationListener(
                redis_reader=_FakeStreamReader(),
                invalidation_publisher=_RecordingPublisher(),
                watchlist_resolver=_InMemoryWatchlist(),
            )

    def test_explicit_streams_accepted(self) -> None:
        # Does not raise.
        BiasInvalidationListener(
            redis_reader=_FakeStreamReader(),
            invalidation_publisher=_RecordingPublisher(),
            watchlist_resolver=_InMemoryWatchlist(),
            streams=["stream:bias:RELIANCE"],
        )


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_fans_out_to_every_user_watching_the_symbol(self) -> None:
        user_a, user_b = uuid4(), uuid4()
        reader = _FakeStreamReader(
            {
                "stream:bias:RELIANCE": [
                    (
                        "1704067200000-0",
                        {
                            "ticker": "RELIANCE",
                            "bias": "BULLISH",
                            "timestamp": "2024-01-01T00:00:00+00:00",
                        },
                    ),
                ],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({"RELIANCE": [user_a, user_b]})

        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:RELIANCE"],
        )

        published = await listener.poll_once()
        assert published == 2

        # One entry per user; all on the snapshot-invalidation stream.
        assert len(publisher.calls) == 2
        streams = {s for s, _ in publisher.calls}
        assert streams == {RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM}

        # Field shape is canonical.
        published_users = {c[1]["user_id"] for c in publisher.calls}
        assert published_users == {str(user_a), str(user_b)}
        for _, fields in publisher.calls:
            assert fields["symbol"] == "RELIANCE"
            assert fields["trigger"] == "bias"
            assert fields["source_event_id"] == "1704067200000-0"

    @pytest.mark.asyncio
    async def test_sharded_stream_resolves_ticker_from_name(self) -> None:
        """An event without a ``ticker`` field is still translated
        when the stream name carries the ticker suffix.
        """
        user_c = uuid4()
        reader = _FakeStreamReader(
            {
                "stream:bias:TCS": [
                    # No ``ticker`` field; only timestamp + bias.
                    (
                        "1-0",
                        {"bias": "BEARISH", "timestamp": "2024-02-01T00:00:00+00:00"},
                    ),
                ],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({"TCS": [user_c]})

        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:TCS"],
        )

        published = await listener.poll_once()
        assert published == 1
        assert publisher.calls[0][1]["symbol"] == "TCS"

    @pytest.mark.asyncio
    async def test_empty_watchlist_yields_no_invalidations(self) -> None:
        reader = _FakeStreamReader(
            {
                "stream:bias:INFY": [
                    ("1-0", {"ticker": "INFY", "bias": "NEUTRAL"}),
                ],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({})  # no users watching anything

        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:INFY"],
        )

        assert await listener.poll_once() == 0
        assert publisher.calls == []


# --------------------------------------------------------------------------- #
# Dedup                                                                       #
# --------------------------------------------------------------------------- #


class TestDedup:
    @pytest.mark.asyncio
    async def test_same_entry_id_not_translated_twice(self) -> None:
        user = uuid4()
        entry = ("1-0", {"ticker": "HDFC", "bias": "BULLISH"})
        reader = _FakeStreamReader({"stream:bias:HDFC": [entry]})
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({"HDFC": [user]})
        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:HDFC"],
        )

        first = await listener.poll_once()
        second = await listener.poll_once()

        assert first == 1
        assert second == 0
        assert len(publisher.calls) == 1

    @pytest.mark.asyncio
    async def test_new_entry_id_translated_on_subsequent_poll(self) -> None:
        user = uuid4()
        reader = _FakeStreamReader(
            {
                "stream:bias:HDFC": [
                    ("1-0", {"ticker": "HDFC", "bias": "BULLISH"}),
                ],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({"HDFC": [user]})
        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:HDFC"],
        )

        await listener.poll_once()

        # A fresh bias event on the same stream.
        reader._per_stream["stream:bias:HDFC"].insert(
            0,
            ("2-0", {"ticker": "HDFC", "bias": "BEARISH"}),
        )
        assert await listener.poll_once() == 1
        assert len(publisher.calls) == 2


# --------------------------------------------------------------------------- #
# Discovery                                                                   #
# --------------------------------------------------------------------------- #


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_scan_based_discovery_invokes_scan_each_poll(self) -> None:
        user = uuid4()
        reader = _FakeStreamReader(
            {
                "stream:bias:WIPRO": [
                    ("1-0", {"ticker": "WIPRO", "bias": "BULLISH"}),
                ],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist({"WIPRO": [user]})

        scan_calls: list[str] = []

        async def fake_scan(pattern: str) -> list[str]:
            scan_calls.append(pattern)
            return ["stream:bias:WIPRO"]

        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            redis_scan=fake_scan,
        )

        await listener.poll_once()
        assert scan_calls == ["stream:bias:*"]

        # A new stream pops up between polls.
        reader._per_stream["stream:bias:SBIN"] = [
            ("1-0", {"ticker": "SBIN", "bias": "BEARISH"}),
        ]
        resolver._mapping["SBIN"] = [user]

        async def fake_scan_2(pattern: str) -> list[str]:
            scan_calls.append(pattern)
            return ["stream:bias:WIPRO", "stream:bias:SBIN"]

        listener._discovery.scan = fake_scan_2  # type: ignore[assignment]
        published = await listener.poll_once()
        assert published == 1
        assert publisher.calls[-1][1]["symbol"] == "SBIN"

    @pytest.mark.asyncio
    async def test_scan_failure_is_swallowed(self) -> None:
        reader = _FakeStreamReader()
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist()

        async def failing_scan(pattern: str) -> list[str]:
            raise RuntimeError("redis unreachable")

        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            redis_scan=failing_scan,
        )
        # Must not raise.
        assert await listener.poll_once() == 0


# --------------------------------------------------------------------------- #
# Resilience                                                                  #
# --------------------------------------------------------------------------- #


class TestResilience:
    @pytest.mark.asyncio
    async def test_resolver_failure_does_not_break_listener(self) -> None:
        reader = _FakeStreamReader(
            {
                "stream:bias:X": [("1-0", {"ticker": "X", "bias": "B"})],
            },
        )
        publisher = _RecordingPublisher()
        resolver = _InMemoryWatchlist(raise_on="X")
        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:X"],
        )

        # No crash, no publishes.
        assert await listener.poll_once() == 0
        assert publisher.calls == []

    @pytest.mark.asyncio
    async def test_publisher_failure_for_one_user_does_not_block_next(
        self,
    ) -> None:
        user_a, user_b = uuid4(), uuid4()
        reader = _FakeStreamReader(
            {
                "stream:bias:TATA": [
                    ("1-0", {"ticker": "TATA", "bias": "BULLISH"}),
                ],
            },
        )
        publisher = _RecordingPublisher(raise_on_calls=[0])  # first call raises
        resolver = _InMemoryWatchlist({"TATA": [user_a, user_b]})
        listener = BiasInvalidationListener(
            redis_reader=reader,
            invalidation_publisher=publisher,
            watchlist_resolver=resolver,
            streams=["stream:bias:TATA"],
        )

        published = await listener.poll_once()
        # Only the second publish succeeded.
        assert published == 1
        assert len(publisher.calls) == 2  # both were attempted


# --------------------------------------------------------------------------- #
# process_event                                                               #
# --------------------------------------------------------------------------- #


class TestProcessEvent:
    @pytest.mark.asyncio
    async def test_accepts_stream_event_directly(self) -> None:
        """Tests can drive one event at a time without the poll loop."""
        user = uuid4()
        publisher = _RecordingPublisher()
        listener = BiasInvalidationListener(
            redis_reader=_FakeStreamReader(),
            invalidation_publisher=publisher,
            watchlist_resolver=_InMemoryWatchlist({"ACC": [user]}),
            streams=["stream:bias:ACC"],
        )
        event = StreamEvent(
            event_id="10-0",
            stream="stream:bias:ACC",
            fields={"ticker": "ACC", "bias": "NEUTRAL"},
            symbol="ACC",
        )

        published = await listener.process_event(event)
        assert published == 1
        assert publisher.calls[0][1]["symbol"] == "ACC"
        assert publisher.calls[0][1]["user_id"] == str(user)


# --------------------------------------------------------------------------- #
# build_invalidation_fields                                                   #
# --------------------------------------------------------------------------- #


class TestBuildInvalidationFields:
    def test_canonical_field_set(self) -> None:
        user = uuid4()
        fields = build_invalidation_fields(
            user_id=user,
            symbol="reliance",
            trigger="bias",
            source_event_id="123-0",
        )
        assert fields == {
            "user_id": str(user),
            "symbol": "RELIANCE",
            "trigger": "bias",
            "source_event_id": "123-0",
        }

    def test_source_event_id_optional(self) -> None:
        user = uuid4()
        fields = build_invalidation_fields(
            user_id=user,
            symbol="X",
            trigger="bias",
        )
        assert "source_event_id" not in fields
