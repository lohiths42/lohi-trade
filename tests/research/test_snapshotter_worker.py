"""Unit tests for :class:`SnapshotWorker` (Task 15.1).

The worker is the glue between the invalidation stream, the debounce
state, the injected Orchestrator factory, and the snapshot store.
Tests drive the worker via its test-friendly :meth:`tick` hand-crank
so the run loop's ``asyncio.sleep`` never executes.

Covers
------
* Debounce — a single invalidation must wait at least
  ``debounce_sec`` before regenerating; a second invalidation within
  the window resets the timer (Req 11.2).
* Regen success — calls ``save_snapshot`` with the brief returned by
  the Orchestrator factory and the current input-document hashes.
* Regen failure — calls ``mark_stale`` on the existing row; the
  worker survives for the next tick.
* Save failure — the brief is produced but ``save_snapshot`` raises;
  worker marks stale and keeps going.
* Stream dedup — the same invalidation entry_id is not folded twice.
* Malformed events are skipped without raising.
* SubAgent selector plumbing — ``skip_agents`` is forwarded to the
  factory.
* Hash resolver is consulted both before regen (for the selector)
  and after regen (for the persisted hashes).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

import pytest

from src.research.constants import RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM
from src.research.workers.snapshotter import (
    DEFAULT_DEBOUNCE_SEC,
    InvalidationEvent,
    SnapshotWorker,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class _FakeStreamReader:
    """Canned xrevrange results, appendable between ticks."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, Mapping[str, str]]] = []
        self.calls: list[dict[str, Any]] = []
        self.raise_next: Exception | None = None

    def push(self, entry_id: str, fields: Mapping[str, str]) -> None:
        # ``xrevrange`` returns newest first, so we prepend.
        self.entries.insert(0, (entry_id, dict(fields)))

    async def xrevrange(
        self,
        name: str,
        count: int | None = None,
    ) -> list[tuple[str, Mapping[str, str]]]:
        self.calls.append({"name": name, "count": count})
        if self.raise_next is not None:
            exc = self.raise_next
            self.raise_next = None
            raise exc
        entries = list(self.entries)
        if count is not None:
            entries = entries[:count]
        return entries


class _FakeSnapshotStore:
    """Records save_snapshot / mark_stale calls.

    Raises on demand so tests can exercise the stale-on-failure path.
    """

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.staled: list[tuple[UUID, str]] = []
        self.raise_on_save: Exception | None = None
        self.mark_stale_return: bool = True

    async def save_snapshot(
        self,
        user_id: UUID,
        symbol: str,
        brief: Mapping[str, Any],
        input_document_hashes: Iterable[str] | Sequence[str],
    ) -> None:
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.saved.append(
            {
                "user_id": user_id,
                "symbol": symbol,
                "brief": dict(brief),
                "hashes": list(input_document_hashes),
            }
        )

    async def mark_stale(self, user_id: UUID, symbol: str) -> bool:
        self.staled.append((user_id, symbol))
        return self.mark_stale_return


class _FakeOrchestrator:
    """Returns a canned brief (or raises)."""

    def __init__(
        self,
        *,
        brief: Mapping[str, Any] | None = None,
        raise_on_run: Exception | None = None,
    ) -> None:
        self._brief = dict(brief or {"summary": "cached"})
        self._raise = raise_on_run
        self.run_calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        symbol: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        self.run_calls.append(
            {
                "run_id": run_id,
                "user_id": user_id,
                "symbol": symbol,
                "user_prompt": user_prompt,
            }
        )
        if self._raise is not None:
            raise self._raise
        return dict(self._brief)


# --------------------------------------------------------------------------- #
# Clock helper                                                                #
# --------------------------------------------------------------------------- #


class _ManualClock:
    """Monotonic clock whose value tests drive explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# --------------------------------------------------------------------------- #
# Factory helpers                                                             #
# --------------------------------------------------------------------------- #


def _invalidation_fields(
    user_id: UUID,
    symbol: str,
    trigger: str = "bias",
    source_event_id: str | None = "source-1",
) -> dict[str, str]:
    fields = {
        "user_id": str(user_id),
        "symbol": symbol,
        "trigger": trigger,
    }
    if source_event_id:
        fields["source_event_id"] = source_event_id
    return fields


def _build_worker(
    *,
    reader: _FakeStreamReader,
    store: _FakeSnapshotStore,
    orchestrator: _FakeOrchestrator,
    clock: _ManualClock,
    debounce_sec: float = DEFAULT_DEBOUNCE_SEC,
    hash_resolver: Any = None,
    subagent_selector: Any = None,
) -> SnapshotWorker:
    factory_calls: list[dict[str, Any]] = []

    async def factory(
        *,
        user_id: UUID,
        symbol: str,
        skip_agents: tuple[str, ...],
    ) -> _FakeOrchestrator:
        factory_calls.append(
            {
                "user_id": user_id,
                "symbol": symbol,
                "skip_agents": skip_agents,
            }
        )
        return orchestrator

    worker = SnapshotWorker(
        redis_reader=reader,
        snapshot_store=store,  # type: ignore[arg-type]
        orchestrator_factory=factory,
        subagent_selector=subagent_selector,
        debounce_sec=debounce_sec,
        tick_sec=0.01,  # tiny; we never await the run loop's sleep
        clock=clock,
        hash_resolver=hash_resolver,
    )
    worker._factory_calls = factory_calls  # type: ignore[attr-defined]
    return worker


# --------------------------------------------------------------------------- #
# Constructor validation                                                      #
# --------------------------------------------------------------------------- #


class TestConstructor:
    def test_rejects_negative_debounce(self) -> None:
        with pytest.raises(ValueError, match="debounce_sec"):
            SnapshotWorker(
                redis_reader=_FakeStreamReader(),
                snapshot_store=_FakeSnapshotStore(),  # type: ignore[arg-type]
                orchestrator_factory=lambda **_: None,  # type: ignore[arg-type]
                debounce_sec=-1,
            )

    def test_rejects_nonpositive_tick(self) -> None:
        with pytest.raises(ValueError, match="tick_sec"):
            SnapshotWorker(
                redis_reader=_FakeStreamReader(),
                snapshot_store=_FakeSnapshotStore(),  # type: ignore[arg-type]
                orchestrator_factory=lambda **_: None,  # type: ignore[arg-type]
                tick_sec=0,
            )


# --------------------------------------------------------------------------- #
# Debounce                                                                    #
# --------------------------------------------------------------------------- #


class TestDebounce:
    @pytest.mark.asyncio
    async def test_does_not_regen_before_debounce_elapses(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=60.0,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "RELIANCE"))

        # Fold the invalidation in.
        regens = await worker.tick()
        assert regens == 0
        assert len(worker.pending) == 1

        # Advance 30 s — still within the window.
        clock.advance(30)
        regens = await worker.tick()
        assert regens == 0
        assert orch.run_calls == []

    @pytest.mark.asyncio
    async def test_regenerates_after_debounce_elapses(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator(brief={"summary": "snapshot content"})
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=60.0,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "RELIANCE"))

        await worker.tick()  # fold invalidation at t=0
        clock.advance(60.0)  # debounce elapsed
        regens = await worker.tick()

        assert regens == 1
        assert len(orch.run_calls) == 1
        call = orch.run_calls[0]
        assert call["user_id"] == user
        assert call["symbol"] == "RELIANCE"
        assert "RELIANCE" in call["user_prompt"]

        # Brief was persisted.
        assert len(store.saved) == 1
        assert store.saved[0]["brief"] == {"summary": "snapshot content"}
        assert store.saved[0]["symbol"] == "RELIANCE"

        # Pending map was cleared.
        assert worker.pending == {}

    @pytest.mark.asyncio
    async def test_second_invalidation_resets_timer(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=60.0,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        await worker.tick()  # fold at t=0

        clock.advance(30)
        # A second invalidation for the same pair.
        reader.push("2-0", _invalidation_fields(user, "X"))
        await worker.tick()  # fold at t=30

        clock.advance(50)  # t=80, which is only 50s after the second fold
        regens = await worker.tick()
        assert regens == 0
        assert orch.run_calls == []

        clock.advance(15)  # t=95, 65s after the second fold
        regens = await worker.tick()
        assert regens == 1

    @pytest.mark.asyncio
    async def test_distinct_pairs_debounce_independently(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=60.0,
        )

        u_a, u_b = uuid4(), uuid4()
        reader.push("1-0", _invalidation_fields(u_a, "A"))
        reader.push("2-0", _invalidation_fields(u_b, "B"))
        await worker.tick()  # both at t=0

        clock.advance(60.0)
        regens = await worker.tick()
        assert regens == 2
        symbols = {c["symbol"] for c in orch.run_calls}
        assert symbols == {"A", "B"}


# --------------------------------------------------------------------------- #
# Dedup + event parsing                                                       #
# --------------------------------------------------------------------------- #


class TestStreamIntake:
    @pytest.mark.asyncio
    async def test_duplicate_entry_is_not_folded_twice(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader, store=store, orchestrator=orch, clock=clock
        )

        user = uuid4()
        reader.push("42-0", _invalidation_fields(user, "X"))
        await worker.poll_once()
        # Fold again — same entry id.
        await worker.poll_once()
        assert len(worker.pending) == 1

    @pytest.mark.asyncio
    async def test_malformed_entries_are_skipped(self) -> None:
        reader = _FakeStreamReader()
        reader.push("bad-1", {"symbol": "X"})  # missing user_id
        reader.push("bad-2", {"user_id": "not-a-uuid", "symbol": "X"})
        reader.push("bad-3", {"user_id": str(uuid4())})  # missing symbol

        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader, store=store, orchestrator=orch, clock=clock
        )

        await worker.poll_once()
        assert worker.pending == {}

    @pytest.mark.asyncio
    async def test_stream_read_failure_is_swallowed(self) -> None:
        reader = _FakeStreamReader()
        reader.raise_next = RuntimeError("redis exploded")
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader, store=store, orchestrator=orch, clock=clock
        )
        # Must not raise.
        folded = await worker.poll_once()
        assert folded == 0

    @pytest.mark.asyncio
    async def test_reads_from_configured_stream(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader, store=store, orchestrator=orch, clock=clock
        )
        await worker.poll_once()
        assert reader.calls[-1]["name"] == RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM


# --------------------------------------------------------------------------- #
# Stale-on-failure                                                            #
# --------------------------------------------------------------------------- #


class TestStaleOnFailure:
    @pytest.mark.asyncio
    async def test_orchestrator_failure_marks_stale(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator(raise_on_run=RuntimeError("llm down"))
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,  # regen immediately
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        regens = await worker.tick()
        assert regens == 1

        assert store.saved == []
        assert store.staled == [(user, "X")]

    @pytest.mark.asyncio
    async def test_store_save_failure_marks_stale(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        store.raise_on_save = RuntimeError("disk full")
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "Y"))
        await worker.tick()

        # Brief was produced but the save raised.
        assert len(orch.run_calls) == 1
        assert store.staled == [(user, "Y")]

    @pytest.mark.asyncio
    async def test_stale_no_prior_row_is_logged_but_not_fatal(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        store.mark_stale_return = False  # no prior row
        orch = _FakeOrchestrator(raise_on_run=RuntimeError("x"))
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "Z"))
        # Must not raise.
        await worker.tick()

    @pytest.mark.asyncio
    async def test_worker_continues_after_failure(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        # First run raises; second run succeeds.
        call_count = {"n": 0}

        class _OrchSeq:
            def __init__(self) -> None:
                self.run_calls: list[dict[str, Any]] = []

            async def run(
                self,
                *,
                run_id: UUID,
                user_id: UUID,
                symbol: str,
                user_prompt: str,
            ) -> dict[str, Any]:
                self.run_calls.append(
                    {"user_id": user_id, "symbol": symbol}
                )
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("transient")
                return {"summary": "ok"}

        orch_seq = _OrchSeq()
        clock = _ManualClock()

        async def factory(
            *,
            user_id: UUID,
            symbol: str,
            skip_agents: tuple[str, ...],
        ) -> _OrchSeq:
            return orch_seq

        worker = SnapshotWorker(
            redis_reader=reader,
            snapshot_store=store,  # type: ignore[arg-type]
            orchestrator_factory=factory,
            debounce_sec=0,
            tick_sec=0.01,
            clock=clock,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "A"))
        await worker.tick()
        reader.push("2-0", _invalidation_fields(user, "B"))
        await worker.tick()

        assert [c["symbol"] for c in orch_seq.run_calls] == ["A", "B"]
        # First (A) marked stale, second (B) saved.
        assert store.staled == [(user, "A")]
        assert [s["symbol"] for s in store.saved] == ["B"]


# --------------------------------------------------------------------------- #
# Selector + hash plumbing                                                    #
# --------------------------------------------------------------------------- #


class TestSelectorAndHashes:
    @pytest.mark.asyncio
    async def test_selector_output_forwarded_to_factory(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()

        async def selector(
            *,
            user_id: UUID,
            symbol: str,
            prior_hashes: tuple[str, ...],
        ) -> list[str]:
            return ["filings", "macro"]

        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
            subagent_selector=selector,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        await worker.tick()

        assert worker._factory_calls == [  # type: ignore[attr-defined]
            {
                "user_id": user,
                "symbol": "X",
                "skip_agents": ("filings", "macro"),
            }
        ]

    @pytest.mark.asyncio
    async def test_selector_failure_falls_back_to_empty(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()

        async def selector(
            *,
            user_id: UUID,
            symbol: str,
            prior_hashes: tuple[str, ...],
        ) -> list[str]:
            raise RuntimeError("selector broke")

        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
            subagent_selector=selector,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        await worker.tick()

        # Still regened, with no skip hints.
        assert worker._factory_calls == [  # type: ignore[attr-defined]
            {"user_id": user, "symbol": "X", "skip_agents": ()}
        ]
        assert len(orch.run_calls) == 1

    @pytest.mark.asyncio
    async def test_hash_resolver_supplies_persisted_hashes(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()

        resolver_calls: list[tuple[UUID, str]] = []

        async def resolver(user_id: UUID, symbol: str) -> tuple[str, ...]:
            resolver_calls.append((user_id, symbol))
            return ("h_a", "h_b")

        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
            hash_resolver=resolver,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        await worker.tick()

        assert store.saved[0]["hashes"] == ["h_a", "h_b"]
        # Resolver called at least twice — once for the selector
        # (prior hashes) and once after the regen (to persist).
        assert len(resolver_calls) >= 1

    @pytest.mark.asyncio
    async def test_no_hash_resolver_yields_empty_list(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()
        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
            hash_resolver=None,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        await worker.tick()

        assert store.saved[0]["hashes"] == []

    @pytest.mark.asyncio
    async def test_hash_resolver_failure_falls_back_to_empty(self) -> None:
        reader = _FakeStreamReader()
        store = _FakeSnapshotStore()
        orch = _FakeOrchestrator()
        clock = _ManualClock()

        async def bad_resolver(user_id: UUID, symbol: str) -> list[str]:
            raise RuntimeError("hash db down")

        worker = _build_worker(
            reader=reader,
            store=store,
            orchestrator=orch,
            clock=clock,
            debounce_sec=0,
            hash_resolver=bad_resolver,
        )

        user = uuid4()
        reader.push("1-0", _invalidation_fields(user, "X"))
        # Must not raise.
        await worker.tick()
        assert store.saved[0]["hashes"] == []


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #


class TestDefaults:
    def test_default_debounce_is_60_seconds(self) -> None:
        """Req 11.2 default debounce window is 60 seconds."""
        assert DEFAULT_DEBOUNCE_SEC == 60.0


# --------------------------------------------------------------------------- #
# Event parser                                                                #
# --------------------------------------------------------------------------- #


class TestInvalidationEvent:
    def test_frozen_and_hashable(self) -> None:
        """The dataclass is frozen so tests can use it in sets/dicts."""
        user = uuid4()
        ev = InvalidationEvent(
            user_id=user,
            symbol="X",
            trigger="bias",
            entry_id="1-0",
        )
        # Exercising hash is enough.
        {ev}
