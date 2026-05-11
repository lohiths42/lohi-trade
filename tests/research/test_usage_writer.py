"""Unit tests for :class:`UsageWriter` and :class:`NoopUsageWriter` (Task 13.9).

Uses a lightweight ``asyncpg.Connection``-shaped fake so the writer
can be exercised without pulling in a real Postgres. The fake records
every ``execute`` call so the tests can assert on the exact SQL and
parameter tuple the writer emitted (Req 12.5, design §4.1).

Covers
------
* Happy path — one ``execute`` per ``write()``, parameters match
  the column order in the migration.
* Best-effort semantics — raising during ``execute`` or during the
  factory's context manager ``__aenter__`` / ``__aexit__`` is
  swallowed; the caller's ``await`` returns normally.
* Cost normalisation — ``None`` → ``Decimal('0')``, ``float`` →
  ``Decimal(str(float))`` (precision-safe), ``Decimal`` passes
  through unchanged.
* Negative token guards.
* ``NoopUsageWriter`` records the last call so tests that don't want
  a DB can still assert on what the Orchestrator would have
  written.
* The protocol is satisfied by both classes at runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.agents.usage_writer import (
    NoopUsageWriter,
    UsageWriter,
    UsageWriterProtocol,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


class _FakeConnection:
    """Minimal asyncpg.Connection stand-in.

    Records every ``execute`` call as ``(sql, args)`` tuples so tests
    can assert on the exact parameter order. ``raise_on_execute``
    lets tests force a failure inside the INSERT path.
    """

    def __init__(
        self,
        *,
        raise_on_execute: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._raise_on_execute = raise_on_execute

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append((sql, args))
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        return "INSERT 0 1"


def _factory_for(
    conn: _FakeConnection,
    *,
    raise_on_enter: Exception | None = None,
    raise_on_exit: Exception | None = None,
) -> Any:
    """Build an ``(user_id) -> AsyncContextManager[conn]`` factory.

    The factory records each ``user_id`` it was called with on its
    ``calls`` list so tests can verify RLS engagement (the factory is
    expected to set ``app.user_id`` for the yielded connection).
    """
    calls: list[UUID] = []

    @asynccontextmanager
    async def factory(user_id: UUID) -> AsyncIterator[_FakeConnection]:
        calls.append(user_id)
        if raise_on_enter is not None:
            raise raise_on_enter
        try:
            yield conn
        finally:
            if raise_on_exit is not None:
                raise raise_on_exit

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


# --------------------------------------------------------------------------- #
# UsageWriter — happy path                                                    #
# --------------------------------------------------------------------------- #


class TestUsageWriterHappyPath:
    @pytest.mark.asyncio
    async def test_inserts_one_row_with_expected_parameters(self) -> None:
        conn = _FakeConnection()
        factory = _factory_for(conn)
        writer = UsageWriter(connection_factory=factory)

        run_id = uuid4()
        user_id = uuid4()
        await writer.write(
            run_id=run_id,
            user_id=user_id,
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
            input_tokens=250,
            output_tokens=75,
            purpose="filings_agent",
            latency_ms=312,
            cost_estimate_usd=Decimal("0.001234"),
        )

        assert len(conn.calls) == 1
        sql, args = conn.calls[0]
        assert "INSERT INTO llm_usage" in sql
        # Column order per the migration:
        # (user_id, research_run_id, provider, model,
        #  input_tokens, output_tokens, cost_estimate_usd)
        assert args == (
            user_id,
            run_id,
            "nvidia_nim",
            "meta/llama-3.1-70b-instruct",
            250,
            75,
            Decimal("0.001234"),
        )
        # Factory was called with the user's id so RLS engages for
        # the right tenant.
        assert factory.calls == [user_id]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_null_run_id_is_preserved(self) -> None:
        """Pre-run plan / post-run async Judge writes a row with run_id=None."""
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))

        await writer.write(
            run_id=None,
            user_id=uuid4(),
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=10,
            output_tokens=5,
            purpose="plan",
            latency_ms=50,
        )
        sql, args = conn.calls[0]
        # args[1] is research_run_id.
        assert args[1] is None

    @pytest.mark.asyncio
    async def test_default_cost_is_decimal_zero(self) -> None:
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))

        await writer.write(
            run_id=uuid4(),
            user_id=uuid4(),
            provider="ollama",
            model="llama3.1:8b",
            input_tokens=0,
            output_tokens=0,
            purpose="test",
            latency_ms=0,
        )
        _, args = conn.calls[0]
        assert args[-1] == Decimal(0)
        assert isinstance(args[-1], Decimal)

    @pytest.mark.asyncio
    async def test_float_cost_is_normalised_via_str(self) -> None:
        """``float`` → ``Decimal(str(x))`` avoids binary-float drift."""
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))

        await writer.write(
            run_id=uuid4(),
            user_id=uuid4(),
            provider="nvidia_nim",
            model="m",
            input_tokens=1,
            output_tokens=1,
            purpose="x",
            latency_ms=1,
            cost_estimate_usd=0.1,
        )
        _, args = conn.calls[0]
        # ``Decimal(0.1)`` would be the lossy 0.1000000000000000055...
        # ``Decimal(str(0.1))`` is the clean 0.1.
        assert args[-1] == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_decimal_cost_passes_through(self) -> None:
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))

        cost = Decimal("0.987654")
        await writer.write(
            run_id=uuid4(),
            user_id=uuid4(),
            provider="p",
            model="m",
            input_tokens=1,
            output_tokens=1,
            purpose="x",
            latency_ms=1,
            cost_estimate_usd=cost,
        )
        _, args = conn.calls[0]
        assert args[-1] is cost


# --------------------------------------------------------------------------- #
# UsageWriter — error swallowing                                              #
# --------------------------------------------------------------------------- #


class TestUsageWriterSwallowsErrors:
    @pytest.mark.asyncio
    async def test_execute_failure_is_swallowed(self) -> None:
        conn = _FakeConnection(raise_on_execute=RuntimeError("db down"))
        writer = UsageWriter(connection_factory=_factory_for(conn))

        # Must not raise.
        await writer.write(
            run_id=uuid4(),
            user_id=uuid4(),
            provider="p",
            model="m",
            input_tokens=1,
            output_tokens=1,
            purpose="x",
            latency_ms=1,
        )
        # And the execute was still attempted.
        assert len(conn.calls) == 1

    @pytest.mark.asyncio
    async def test_factory_acquire_failure_is_swallowed(self) -> None:
        """Connection-acquire failure (pool exhausted, etc.) is survivable."""
        conn = _FakeConnection()
        factory = _factory_for(
            conn,
            raise_on_enter=ConnectionError("no free connections"),
        )
        writer = UsageWriter(connection_factory=factory)

        # Must not raise.
        await writer.write(
            run_id=uuid4(),
            user_id=uuid4(),
            provider="p",
            model="m",
            input_tokens=1,
            output_tokens=1,
            purpose="x",
            latency_ms=1,
        )
        # Execute was never reached because __aenter__ failed.
        assert conn.calls == []


# --------------------------------------------------------------------------- #
# UsageWriter — input validation                                              #
# --------------------------------------------------------------------------- #


class TestUsageWriterValidation:
    @pytest.mark.asyncio
    async def test_negative_input_tokens_rejected(self) -> None:
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))
        with pytest.raises(ValueError, match="input_tokens"):
            await writer.write(
                run_id=uuid4(),
                user_id=uuid4(),
                provider="p",
                model="m",
                input_tokens=-1,
                output_tokens=0,
                purpose="x",
                latency_ms=0,
            )
        assert conn.calls == []

    @pytest.mark.asyncio
    async def test_negative_output_tokens_rejected(self) -> None:
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))
        with pytest.raises(ValueError, match="output_tokens"):
            await writer.write(
                run_id=uuid4(),
                user_id=uuid4(),
                provider="p",
                model="m",
                input_tokens=0,
                output_tokens=-1,
                purpose="x",
                latency_ms=0,
            )
        assert conn.calls == []


# --------------------------------------------------------------------------- #
# NoopUsageWriter                                                             #
# --------------------------------------------------------------------------- #


class TestNoopUsageWriter:
    @pytest.mark.asyncio
    async def test_records_last_call(self) -> None:
        writer = NoopUsageWriter()
        assert writer.last_call is None
        assert writer.call_count == 0

        run_id = uuid4()
        user_id = uuid4()
        await writer.write(
            run_id=run_id,
            user_id=user_id,
            provider="nvidia_nim",
            model="m",
            input_tokens=10,
            output_tokens=5,
            purpose="filings",
            latency_ms=100,
        )

        assert writer.call_count == 1
        assert writer.last_call is not None
        assert writer.last_call["run_id"] == run_id
        assert writer.last_call["user_id"] == user_id
        assert writer.last_call["provider"] == "nvidia_nim"
        assert writer.last_call["input_tokens"] == 10
        assert writer.last_call["output_tokens"] == 5
        assert writer.last_call["purpose"] == "filings"
        assert writer.last_call["latency_ms"] == 100

    @pytest.mark.asyncio
    async def test_last_call_is_the_most_recent(self) -> None:
        writer = NoopUsageWriter()
        await writer.write(
            run_id=None,
            user_id=uuid4(),
            provider="a",
            model="m",
            input_tokens=1,
            output_tokens=1,
            purpose="first",
            latency_ms=1,
        )
        await writer.write(
            run_id=None,
            user_id=uuid4(),
            provider="b",
            model="m",
            input_tokens=2,
            output_tokens=2,
            purpose="second",
            latency_ms=2,
        )
        assert writer.call_count == 2
        assert writer.last_call is not None
        assert writer.last_call["purpose"] == "second"

    @pytest.mark.asyncio
    async def test_noop_never_raises(self) -> None:
        """Zero tokens and missing cost are all acceptable — it's a no-op."""
        writer = NoopUsageWriter()
        await writer.write(
            run_id=None,
            user_id=uuid4(),
            provider="",
            model="",
            input_tokens=0,
            output_tokens=0,
            purpose="",
            latency_ms=0,
        )


# --------------------------------------------------------------------------- #
# Protocol conformance                                                        #
# --------------------------------------------------------------------------- #


class TestProtocolConformance:
    def test_concrete_writer_implements_protocol(self) -> None:
        conn = _FakeConnection()
        writer = UsageWriter(connection_factory=_factory_for(conn))
        assert isinstance(writer, UsageWriterProtocol)

    def test_noop_writer_implements_protocol(self) -> None:
        assert isinstance(NoopUsageWriter(), UsageWriterProtocol)


# --------------------------------------------------------------------------- #
# Re-exports                                                                  #
# --------------------------------------------------------------------------- #


class TestReExports:
    def test_budget_and_usage_writer_available_from_agents_package(
        self,
    ) -> None:
        # Task 13.9 asks for the collaborators to be re-exported from
        # ``src.research.agents`` so the Orchestrator can find them
        # at a single import site without importing the
        # implementation modules directly.
        from src.research import agents

        assert hasattr(agents, "TokenBudget")
        assert hasattr(agents, "BudgetTotals")
        assert hasattr(agents, "UsageWriter")
        assert hasattr(agents, "NoopUsageWriter")
        assert hasattr(agents, "UsageWriterProtocol")
        assert hasattr(agents, "DEFAULT_INPUT_LIMIT")
        assert hasattr(agents, "DEFAULT_OUTPUT_LIMIT")
