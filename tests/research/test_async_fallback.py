"""Unit tests for the async-Judge fallback (Task 12.3).

Covers the two public responsibilities of
:mod:`src.research.judge.async_fallback`:

* :func:`should_run_async` — boundary conditions of the budget decision
  (elapsed + expected vs budget, equality, negatives).
* :func:`schedule_background_judge` — the "optimistic return +
  background completion" flow: the scheduler returns immediately, the
  Judge runs on the event loop, and the result arrives on the
  configured publisher when the Judge completes.

Plus the observability guarantees:

* Failures inside the background Judge (exceptions, malformed
  reports) are swallowed so the event loop stays healthy.
* Publisher failures are swallowed for the same reason — the brief
  is already in the user's hands with ``judge_pending=true``.

Design references
-----------------
* §11.3 — async Judge fallback workflow.
* §5.2  — ``research:judge_report`` Socket.IO event contract.
* §13.1 — full-brief latency budget default (15 000 ms).

Satisfies
---------
* Req 15.7 — budget decision.
* Req 15.8 — background execution + channel emission.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.research.constants import RESEARCH_JUDGE_REPORT_CHANNEL
from src.research.judge import (
    JudgeReport,
    JudgeReportPublisher,
    publish_judge_report,
    redis_publisher_for,
    schedule_background_judge,
    should_run_async,
)
from src.research.judge.async_fallback import _run_and_publish

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _report(run_id: UUID | None = None, *, safe: bool = True) -> JudgeReport:
    """Build a minimal :class:`JudgeReport` for publisher-round-trip tests."""
    return JudgeReport(
        run_id=run_id or uuid4(),
        groundedness_score={"summary": 0.9, "risks": 0.85},
        unsupported_claims=[],
        safe_to_display=safe,
        contradiction_pairs=[],
        off_policy_findings=[],
        retry_count=0,
        elapsed_ms=1234,
        model_id="fake/test",
    )


class _RecordingPublisher:
    """In-memory :data:`JudgeReportPublisher` stub."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, channel: str, payload: dict) -> None:
        self.calls.append((channel, payload))


class _FailingPublisher:
    """Publisher that always raises — used to exercise error-swallowing."""

    def __init__(self) -> None:
        self.calls: int = 0

    async def __call__(self, channel: str, payload: dict) -> None:
        self.calls += 1
        raise RuntimeError("publisher down")


class _FakeRedis:
    """In-memory stand-in for ``redis.asyncio.Redis.publish``."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class _FailingRedis:
    """Redis stand-in that raises on publish — error-swallowing check."""

    def __init__(self) -> None:
        self.attempts: int = 0

    async def publish(self, channel: str, message: str) -> int:
        self.attempts += 1
        raise ConnectionError("redis down")


# --------------------------------------------------------------------------- #
# should_run_async                                                            #
# --------------------------------------------------------------------------- #


class TestShouldRunAsync:
    """Req 15.7 — budget decision for the sync/async Judge path."""

    def test_well_within_budget_returns_false(self) -> None:
        # Reference config: 15 000 ms full-brief, 2 000 ms Judge.
        assert should_run_async(
            elapsed_ms=5_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        ) is False

    def test_sum_equal_to_budget_returns_false(self) -> None:
        """Equal fits — the budget is not exceeded on a tie."""
        assert should_run_async(
            elapsed_ms=13_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        ) is False

    def test_sum_exceeds_budget_by_one_ms_returns_true(self) -> None:
        """Strictly greater — one ms over the budget flips the decision."""
        assert should_run_async(
            elapsed_ms=13_001,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        ) is True

    def test_sum_well_over_budget_returns_true(self) -> None:
        assert should_run_async(
            elapsed_ms=20_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        ) is True

    def test_zero_values_are_allowed(self) -> None:
        """Zero on every axis is a legitimate caller state (no elapsed time,
        no expected Judge cost, zero budget) — treated as "0 <= 0" which
        fits by the tie rule.
        """
        assert should_run_async(
            elapsed_ms=0,
            expected_judge_ms=0,
            full_brief_ms_budget=0,
        ) is False

    def test_offline_budget_applied(self) -> None:
        """Offline budget is 60 000 ms — what the Orchestrator substitutes
        when ``LOHI_RESEARCH_OFFLINE=true`` (design §13.1).
        """
        assert should_run_async(
            elapsed_ms=30_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=60_000,
        ) is False
        assert should_run_async(
            elapsed_ms=58_001,
            expected_judge_ms=2_000,
            full_brief_ms_budget=60_000,
        ) is True

    @pytest.mark.parametrize(
        "elapsed_ms,expected_judge_ms,full_brief_ms_budget",
        [
            (-1, 2_000, 15_000),
            (5_000, -1, 15_000),
            (5_000, 2_000, -1),
        ],
    )
    def test_negative_values_raise(
        self,
        elapsed_ms: int,
        expected_judge_ms: int,
        full_brief_ms_budget: int,
    ) -> None:
        with pytest.raises(ValueError):
            should_run_async(
                elapsed_ms=elapsed_ms,
                expected_judge_ms=expected_judge_ms,
                full_brief_ms_budget=full_brief_ms_budget,
            )


# --------------------------------------------------------------------------- #
# schedule_background_judge — happy path                                      #
# --------------------------------------------------------------------------- #


class TestScheduleBackgroundJudge:
    """Req 15.8 — Judge runs in background, report arrives on the channel."""

    @pytest.mark.asyncio
    async def test_returns_task_immediately(self) -> None:
        """The scheduler returns a :class:`asyncio.Task`, not the report."""
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(_judge(), publisher=publisher)

        assert isinstance(task, asyncio.Task)
        # Not done yet — the coroutine hasn't been awaited.
        # (It may be done by the time we read because asyncio's scheduling
        # is implementation-defined; we only assert the return type.)
        await task
        assert task.done()

    @pytest.mark.asyncio
    async def test_publishes_report_on_default_channel(self) -> None:
        """The default channel is :data:`RESEARCH_JUDGE_REPORT_CHANNEL`."""
        publisher = _RecordingPublisher()
        run_id = uuid4()

        async def _judge() -> JudgeReport:
            return _report(run_id=run_id)

        task = schedule_background_judge(_judge(), publisher=publisher)
        await task

        assert len(publisher.calls) == 1
        channel, payload = publisher.calls[0]
        assert channel == RESEARCH_JUDGE_REPORT_CHANNEL
        # UUIDs serialise to strings under ``mode='json'``.
        assert payload["run_id"] == str(run_id)
        assert payload["safe_to_display"] is True
        assert payload["groundedness_score"] == {"summary": 0.9, "risks": 0.85}

    @pytest.mark.asyncio
    async def test_custom_channel_is_honoured(self) -> None:
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(
            _judge(),
            publisher=publisher,
            channel="custom:test_channel",
        )
        await task

        assert publisher.calls[0][0] == "custom:test_channel"

    @pytest.mark.asyncio
    async def test_payload_is_json_serialisable(self) -> None:
        """``model_dump(mode='json')`` output must round-trip through
        :func:`json.dumps` without raising — otherwise the default Redis
        publisher would fail.
        """
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(_judge(), publisher=publisher)
        await task

        _, payload = publisher.calls[0]
        # Must not raise.
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded["safe_to_display"] is True

    @pytest.mark.asyncio
    async def test_task_has_configured_name(self) -> None:
        """Custom ``task_name`` flows through to :meth:`asyncio.Task.get_name`."""
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(
            _judge(),
            publisher=publisher,
            task_name="my-custom-task",
        )
        assert task.get_name() == "my-custom-task"
        await task

    @pytest.mark.asyncio
    async def test_default_task_name(self) -> None:
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(_judge(), publisher=publisher)
        assert task.get_name() == "research-async-judge"
        await task


# --------------------------------------------------------------------------- #
# schedule_background_judge — error paths                                     #
# --------------------------------------------------------------------------- #


class TestBackgroundJudgeErrorPaths:
    """A background Judge failure must not crash the event loop."""

    @pytest.mark.asyncio
    async def test_judge_exception_is_swallowed(self) -> None:
        publisher = _RecordingPublisher()

        async def _boom() -> JudgeReport:
            raise RuntimeError("llm provider exploded")

        task = schedule_background_judge(_boom(), publisher=publisher)
        # Awaiting must not raise — the wrapper swallows the error.
        await task

        # The publisher was never called because the Judge failed.
        assert publisher.calls == []
        # The task completed successfully (error swallowed).
        assert task.done()
        assert task.exception() is None

    @pytest.mark.asyncio
    async def test_publisher_exception_is_swallowed(self) -> None:
        publisher = _FailingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(_judge(), publisher=publisher)
        await task

        # Publisher was invoked and raised, but the task still completes.
        assert publisher.calls == 1
        assert task.done()
        assert task.exception() is None

    @pytest.mark.asyncio
    async def test_run_and_publish_direct_happy_path(self) -> None:
        """The extracted helper is independently testable."""
        publisher = _RecordingPublisher()

        async def _judge() -> JudgeReport:
            return _report()

        await _run_and_publish(
            _judge(),
            publisher=publisher,
            channel="direct:test",
        )

        assert len(publisher.calls) == 1
        assert publisher.calls[0][0] == "direct:test"

    @pytest.mark.asyncio
    async def test_run_and_publish_direct_error(self) -> None:
        """Directly exercise the error branch — must not raise."""
        publisher = _RecordingPublisher()

        async def _boom() -> JudgeReport:
            raise ValueError("bad")

        # Must not raise — the wrapper swallows.
        await _run_and_publish(
            _boom(),
            publisher=publisher,
            channel="direct:test",
        )
        assert publisher.calls == []


# --------------------------------------------------------------------------- #
# End-to-end — optimistic return + background completion                      #
# --------------------------------------------------------------------------- #


class TestOptimisticReturnFlow:
    """Design §11.3 full flow: decide → schedule → receive on channel.

    The Orchestrator's behaviour is modelled as:

    1. Compute the budget decision.
    2. If async, emit the brief with ``judge_pending=true`` and kick
       off the background Judge.
    3. Return to the caller immediately (here: record the emit).
    4. When the Judge completes, the publisher fires the channel event.

    These tests stitch 1–4 together with a tiny Orchestrator stand-in
    so we can assert on the ordering that matters: the "brief emit"
    happens before the publisher call, regardless of Judge latency.
    """

    @pytest.mark.asyncio
    async def test_emit_happens_before_publish_even_with_slow_judge(self) -> None:
        events: list[str] = []
        publisher_started = asyncio.Event()

        async def _slow_judge() -> JudgeReport:
            # Simulate a Judge that takes non-trivial time.
            await asyncio.sleep(0.02)
            return _report()

        async def _publisher(channel: str, payload: dict) -> None:
            publisher_started.set()
            events.append(f"publish:{channel}")

        # Orchestrator-side:
        should_async = should_run_async(
            elapsed_ms=14_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        )
        assert should_async is True

        # Emit the brief optimistically.
        events.append("emit:brief_with_judge_pending")
        task = schedule_background_judge(_slow_judge(), publisher=_publisher)

        # The caller has already returned — the publisher has not fired yet.
        assert not publisher_started.is_set()
        assert events == ["emit:brief_with_judge_pending"]

        # Now let the background work complete.
        await task

        # The publisher fired after the emit.
        assert events == [
            "emit:brief_with_judge_pending",
            f"publish:{RESEARCH_JUDGE_REPORT_CHANNEL}",
        ]

    @pytest.mark.asyncio
    async def test_synchronous_path_skips_scheduling(self) -> None:
        """When the budget fits, the Orchestrator calls the Judge inline —
        the scheduler is never invoked. Sanity check of the decision.
        """
        should_async = should_run_async(
            elapsed_ms=5_000,
            expected_judge_ms=2_000,
            full_brief_ms_budget=15_000,
        )
        assert should_async is False


# --------------------------------------------------------------------------- #
# publish_judge_report — Redis round-trip                                     #
# --------------------------------------------------------------------------- #


class TestPublishJudgeReport:
    """Low-level Redis publisher — single ``PUBLISH`` + best-effort errors."""

    @pytest.mark.asyncio
    async def test_publishes_serialised_payload(self) -> None:
        redis = _FakeRedis()
        payload = _report().model_dump(mode="json")

        await publish_judge_report(redis, "research:judge_report", payload)

        assert len(redis.published) == 1
        channel, message = redis.published[0]
        assert channel == "research:judge_report"
        # The message is JSON — parsing round-trips to the input payload.
        decoded = json.loads(message)
        assert decoded["safe_to_display"] == payload["safe_to_display"]
        assert decoded["groundedness_score"] == payload["groundedness_score"]

    @pytest.mark.asyncio
    async def test_redis_failure_is_swallowed(self) -> None:
        redis = _FailingRedis()
        payload = _report().model_dump(mode="json")

        # Must not raise.
        await publish_judge_report(redis, "research:judge_report", payload)
        assert redis.attempts == 1

    @pytest.mark.asyncio
    async def test_non_serialisable_payload_is_swallowed(self) -> None:
        """A payload containing a non-JSON-serialisable value never
        reaches Redis; the helper logs + returns quietly.
        """
        redis = _FakeRedis()
        bad_payload: dict[str, Any] = {"thing": object()}

        await publish_judge_report(redis, "research:judge_report", bad_payload)
        # No publish attempt was made.
        assert redis.published == []


# --------------------------------------------------------------------------- #
# redis_publisher_for — factory                                               #
# --------------------------------------------------------------------------- #


class TestRedisPublisherFor:
    """Factory wires the Redis client into a :data:`JudgeReportPublisher`."""

    @pytest.mark.asyncio
    async def test_factory_returns_callable_that_publishes(self) -> None:
        redis = _FakeRedis()
        publisher: JudgeReportPublisher = redis_publisher_for(redis)

        payload = _report().model_dump(mode="json")
        await publisher("research:judge_report", payload)

        assert len(redis.published) == 1
        channel, message = redis.published[0]
        assert channel == "research:judge_report"
        assert json.loads(message)["safe_to_display"] is True

    @pytest.mark.asyncio
    async def test_factory_integrates_with_scheduler(self) -> None:
        """End-to-end wiring: scheduler → factory → Redis."""
        redis = _FakeRedis()
        publisher = redis_publisher_for(redis)

        async def _judge() -> JudgeReport:
            return _report()

        task = schedule_background_judge(_judge(), publisher=publisher)
        await task

        assert len(redis.published) == 1
        channel, message = redis.published[0]
        assert channel == RESEARCH_JUDGE_REPORT_CHANNEL
        # The serialised JSON decodes to a JudgeReport-shaped dict.
        decoded = json.loads(message)
        assert "run_id" in decoded
        assert decoded["safe_to_display"] is True
