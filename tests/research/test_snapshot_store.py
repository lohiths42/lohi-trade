"""Unit tests for :class:`SnapshotStore` (Task 15.3).

Uses a lightweight ``asyncpg.Connection``-shaped fake so the store can
be exercised without pulling in a real Postgres. The fake records every
``execute`` / ``fetchrow`` call so assertions can pin the exact SQL +
parameter tuple (design §4.1 column order).

Covers
------
* :meth:`save_snapshot` — upserts a row with ``stale=false``, sorted
  ``input_document_hashes``, and a ``generated_at`` default pulled
  from the injected clock.
* :meth:`mark_stale` — returns ``True`` when a row was flipped and
  ``False`` when no row matched; the UPDATE only touches ``stale``
  (Req 11.6).
* :meth:`get_fresh_snapshot` — returns ``SnapshotRecord`` for fresh
  rows, ``None`` when stale, missing, or outside the staleness
  window. Clock is deterministic via the injected ``clock`` hook.
* Edge cases — empty hash list, tz-naive ``generated_at`` normalised
  to UTC, ``staleness_window_sec<=0`` short-circuits to ``None``,
  future ``generated_at`` treated as fresh (no clock-skew failure
  mode).

Satisfies: Req 5.5, Req 11.4, Req 11.5, Req 11.6, design §3.10, §13.3.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import pytest

from src.research.snapshot.store import (
    DEFAULT_STALENESS_WINDOW_SEC,
    SnapshotRecord,
    SnapshotStore,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class _FakeConn:
    """Minimal asyncpg.Connection stand-in.

    ``execute`` returns the configured command tag; ``fetchrow``
    returns the configured row (one per pending return value, popped
    FIFO). Every call is recorded for assertion.
    """

    def __init__(
        self,
        *,
        execute_return: str = "INSERT 0 1",
        fetchrow_returns: list[dict | None] | None = None,
    ) -> None:
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self._execute_return = execute_return
        self._fetchrow_returns = list(fetchrow_returns or [])

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return self._execute_return

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        self.fetchrow_calls.append((sql, args))
        if not self._fetchrow_returns:
            return None
        return self._fetchrow_returns.pop(0)


def _factory_for(conn: _FakeConn) -> Any:
    """Build an ``(user_id) -> AsyncContextManager[conn]`` factory.

    Records each ``user_id`` it was called with so tests can verify
    RLS engagement (the factory is expected to set ``app.user_id`` for
    the yielded connection).
    """
    calls: list[UUID] = []

    @asynccontextmanager
    async def factory(user_id: UUID) -> AsyncIterator[_FakeConn]:
        calls.append(user_id)
        yield conn

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


# --------------------------------------------------------------------------- #
# save_snapshot                                                               #
# --------------------------------------------------------------------------- #


class TestSaveSnapshot:
    @pytest.mark.asyncio
    async def test_upsert_row_with_expected_parameters(self) -> None:
        conn = _FakeConn()
        factory = _factory_for(conn)
        pinned_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        store = SnapshotStore(
            connection_factory=factory, clock=lambda: pinned_now
        )

        user_id = uuid4()
        brief = {"summary": "Strong Q3 results", "citations": ["abc123"]}
        hashes = ["z_hash", "a_hash", "m_hash"]

        await store.save_snapshot(user_id, "reliance", brief, hashes)

        assert len(conn.execute_calls) == 1
        sql, args = conn.execute_calls[0]
        assert "INSERT INTO research_snapshots" in sql
        assert "ON CONFLICT" in sql

        # Column order per the migration:
        # (user_id, symbol, brief_json, generated_at,
        #  input_document_hashes, stale)
        assert args[0] == user_id
        assert args[1] == "RELIANCE"  # normalised
        assert json.loads(args[2]) == brief  # jsonb-safe encoding
        assert args[3] == pinned_now
        # Hashes are sorted before persistence.
        assert args[4] == ["a_hash", "m_hash", "z_hash"]
        assert args[5] is False  # fresh upsert always clears stale

        # RLS engaged for the right tenant.
        assert factory.calls == [user_id]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_explicit_generated_at_is_used(self) -> None:
        conn = _FakeConn()
        clock_calls: list[None] = []

        def clock() -> datetime:
            clock_calls.append(None)
            return datetime(2030, 1, 1, tzinfo=timezone.utc)

        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=clock
        )
        fixed = datetime(2024, 6, 1, 9, 30, tzinfo=timezone.utc)
        await store.save_snapshot(
            uuid4(), "TCS", {}, [], generated_at=fixed
        )
        _, args = conn.execute_calls[0]
        assert args[3] == fixed
        # Clock wasn't consulted.
        assert clock_calls == []

    @pytest.mark.asyncio
    async def test_empty_hashes_persist_as_empty_list(self) -> None:
        conn = _FakeConn()
        store = SnapshotStore(connection_factory=_factory_for(conn))
        await store.save_snapshot(uuid4(), "ACC", {"summary": "x"}, [])
        _, args = conn.execute_calls[0]
        assert args[4] == []

    @pytest.mark.asyncio
    async def test_falsy_hashes_dropped(self) -> None:
        """Empty-string hashes are skipped — the column is NOT NULL
        in the migration and carrying empty entries would silently
        change the sort order."""
        conn = _FakeConn()
        store = SnapshotStore(connection_factory=_factory_for(conn))
        await store.save_snapshot(uuid4(), "X", {}, ["a", "", "b", ""])
        _, args = conn.execute_calls[0]
        assert args[4] == ["a", "b"]


# --------------------------------------------------------------------------- #
# mark_stale                                                                  #
# --------------------------------------------------------------------------- #


class TestMarkStale:
    @pytest.mark.asyncio
    async def test_returns_true_when_row_flipped(self) -> None:
        conn = _FakeConn(execute_return="UPDATE 1")
        store = SnapshotStore(connection_factory=_factory_for(conn))

        flipped = await store.mark_stale(uuid4(), "infy")
        assert flipped is True

        sql, args = conn.execute_calls[0]
        assert "UPDATE research_snapshots" in sql
        assert "SET stale = TRUE" in sql
        assert args[1] == "INFY"

    @pytest.mark.asyncio
    async def test_returns_false_when_no_row(self) -> None:
        conn = _FakeConn(execute_return="UPDATE 0")
        store = SnapshotStore(connection_factory=_factory_for(conn))

        flipped = await store.mark_stale(uuid4(), "UNKNOWN")
        assert flipped is False

    @pytest.mark.asyncio
    async def test_unexpected_command_tag_collapses_to_false(self) -> None:
        conn = _FakeConn(execute_return="WEIRD")
        store = SnapshotStore(connection_factory=_factory_for(conn))
        flipped = await store.mark_stale(uuid4(), "X")
        assert flipped is False


# --------------------------------------------------------------------------- #
# get_fresh_snapshot                                                          #
# --------------------------------------------------------------------------- #


class TestGetFreshSnapshot:
    @pytest.mark.asyncio
    async def test_returns_record_for_fresh_row(self) -> None:
        user_id = uuid4()
        generated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = generated_at + timedelta(minutes=10)  # well within 15-min default

        brief = {"summary": "Cited summary"}
        row = {
            "user_id": user_id,
            "symbol": "HDFC",
            "brief_json": json.dumps(brief),
            "generated_at": generated_at,
            "input_document_hashes": ["h1", "h2"],
            "stale": False,
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=lambda: now
        )

        record = await store.get_fresh_snapshot(user_id, "hdfc")
        assert record is not None
        assert isinstance(record, SnapshotRecord)
        assert record.user_id == user_id
        assert record.symbol == "HDFC"
        assert record.brief == brief
        assert record.input_document_hashes == ["h1", "h2"]
        assert record.stale is False

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self) -> None:
        conn = _FakeConn(fetchrow_returns=[None])
        store = SnapshotStore(connection_factory=_factory_for(conn))
        assert await store.get_fresh_snapshot(uuid4(), "X") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_row_is_stale(self) -> None:
        user_id = uuid4()
        generated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        row = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": "{}",
            "generated_at": generated_at,
            "input_document_hashes": [],
            "stale": True,  # stale
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn),
            clock=lambda: generated_at + timedelta(seconds=1),
        )
        assert await store.get_fresh_snapshot(user_id, "X") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_outside_staleness_window(self) -> None:
        user_id = uuid4()
        generated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # 16 minutes later — default window is 15 min (900s).
        now = generated_at + timedelta(minutes=16)
        row = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": "{}",
            "generated_at": generated_at,
            "input_document_hashes": [],
            "stale": False,
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=lambda: now
        )
        assert await store.get_fresh_snapshot(user_id, "X") is None

    @pytest.mark.asyncio
    async def test_custom_staleness_window_honoured(self) -> None:
        user_id = uuid4()
        generated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = generated_at + timedelta(seconds=30)
        row = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": "{}",
            "generated_at": generated_at,
            "input_document_hashes": [],
            "stale": False,
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=lambda: now
        )
        # 30 seconds is outside a 15s window.
        assert (
            await store.get_fresh_snapshot(
                user_id, "X", staleness_window_sec=15
            )
            is None
        )
        # But inside a 60s window (new row per call).
        conn2 = _FakeConn(fetchrow_returns=[row])
        store2 = SnapshotStore(
            connection_factory=_factory_for(conn2), clock=lambda: now
        )
        assert (
            await store2.get_fresh_snapshot(
                user_id, "X", staleness_window_sec=60
            )
            is not None
        )

    @pytest.mark.asyncio
    async def test_nonpositive_staleness_window_returns_none(self) -> None:
        """Operator short-circuit: force every run through fan-out."""
        conn = _FakeConn()
        store = SnapshotStore(connection_factory=_factory_for(conn))
        assert (
            await store.get_fresh_snapshot(
                uuid4(), "X", staleness_window_sec=0
            )
            is None
        )
        assert (
            await store.get_fresh_snapshot(
                uuid4(), "X", staleness_window_sec=-1
            )
            is None
        )
        # Neither call should have hit the DB.
        assert conn.fetchrow_calls == []

    @pytest.mark.asyncio
    async def test_tz_naive_generated_at_normalised_to_utc(self) -> None:
        """A naive timestamp from a test fixture still works."""
        user_id = uuid4()
        naive_generated_at = datetime(2024, 1, 1, 12, 0, 0)  # no tz
        aware_now = datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
        row = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": "{}",
            "generated_at": naive_generated_at,
            "input_document_hashes": [],
            "stale": False,
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=lambda: aware_now
        )
        record = await store.get_fresh_snapshot(user_id, "X")
        assert record is not None
        # The record normalises the naive stamp so callers never see
        # tz-naive datetimes.
        assert record.generated_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_future_generated_at_treated_as_fresh(self) -> None:
        """No clock-skew failure mode."""
        user_id = uuid4()
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Row stamped 5 seconds in the future.
        row = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": "{}",
            "generated_at": now + timedelta(seconds=5),
            "input_document_hashes": [],
            "stale": False,
        }
        conn = _FakeConn(fetchrow_returns=[row])
        store = SnapshotStore(
            connection_factory=_factory_for(conn), clock=lambda: now
        )
        record = await store.get_fresh_snapshot(user_id, "X")
        assert record is not None

    @pytest.mark.asyncio
    async def test_brief_json_accepts_dict_or_bytes(self) -> None:
        """Some drivers/tests return the jsonb already-decoded."""
        user_id = uuid4()
        generated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = generated_at + timedelta(seconds=1)

        # dict shape
        row_dict = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": {"already": "decoded"},
            "generated_at": generated_at,
            "input_document_hashes": [],
            "stale": False,
        }
        conn_dict = _FakeConn(fetchrow_returns=[row_dict])
        store_dict = SnapshotStore(
            connection_factory=_factory_for(conn_dict), clock=lambda: now
        )
        record_dict = await store_dict.get_fresh_snapshot(user_id, "X")
        assert record_dict is not None
        assert record_dict.brief == {"already": "decoded"}

        # bytes shape
        row_bytes = {
            "user_id": user_id,
            "symbol": "X",
            "brief_json": b'{"bytes": "ok"}',
            "generated_at": generated_at,
            "input_document_hashes": [],
            "stale": False,
        }
        conn_bytes = _FakeConn(fetchrow_returns=[row_bytes])
        store_bytes = SnapshotStore(
            connection_factory=_factory_for(conn_bytes), clock=lambda: now
        )
        record_bytes = await store_bytes.get_fresh_snapshot(user_id, "X")
        assert record_bytes is not None
        assert record_bytes.brief == {"bytes": "ok"}


# --------------------------------------------------------------------------- #
# Defaults                                                                    #
# --------------------------------------------------------------------------- #


class TestDefaults:
    def test_default_staleness_window_is_15_minutes(self) -> None:
        """Per Req 11.4 default staleness window is 15 minutes."""
        assert DEFAULT_STALENESS_WINDOW_SEC == 900
