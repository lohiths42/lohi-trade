"""Unit tests for the :class:`ResearchService` (Task 16.1).

Exercises the service with a fake Redis, a fake orchestrator, and a
fake snapshot store / memory stack. No network, no Postgres, no
subprocess — the goal is to pin the run-lifecycle behaviour and the
structured error envelope for operator-configurable failures.

Requirements: 8.1, 8.2, 13.3
Design: §3.12, §5.1, §5.2
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.middleware.errors import ConfigMissingError
from app.services.research_service import ResearchService

# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #


class _FakeRedis:
    """In-memory async Redis stand-in capturing ``xadd`` calls."""

    def __init__(self) -> None:
        self.xadd_calls: list[tuple[str, dict[str, Any]]] = []

    async def xadd(self, stream: str, fields: dict[str, Any], **_: Any) -> str:
        self.xadd_calls.append((stream, dict(fields)))
        return "0-0"


class _FakeOrchestrator:
    """Deterministic orchestrator returning a canned brief."""

    def __init__(self, brief: dict[str, Any] | Exception | None = None) -> None:
        # ``None`` defaults to a minimal successful brief; passing an
        # Exception causes ``run`` to raise (tests assert the service's
        # error-handling path).
        self._brief: dict[str, Any] | Exception = (
            brief
            if brief is not None
            else {
                "run_id": "",
                "summary": "ok",
                "partial": False,
                "quality": "normal",
                "budget_exhausted": False,
                "trace": {"plan_md": "go"},
            }
        )
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        symbol: str | None,
        user_prompt: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "run_id": run_id,
                "user_id": user_id,
                "symbol": symbol,
                "user_prompt": user_prompt,
            }
        )
        if isinstance(self._brief, Exception):
            raise self._brief
        brief = dict(self._brief)
        brief["run_id"] = str(run_id)
        return brief


class _FakeSnapshotStore:
    """Snapshot store with a single canned record."""

    def __init__(self, record: Any = None) -> None:
        self._record = record

    async def get_fresh_snapshot(self, user_id: UUID, symbol: str) -> Any:
        return self._record


# --------------------------------------------------------------------------- #
# start_run                                                                    #
# --------------------------------------------------------------------------- #


class TestStartRun:
    @pytest.mark.asyncio
    async def test_returns_record_with_channel_and_status(self) -> None:
        orch = _FakeOrchestrator()
        svc = ResearchService(
            redis=_FakeRedis(),
            orchestrator_factory=lambda: orch,
        )

        record = await svc.start_run(uuid4(), "RELIANCE", "Analyse the filings.")

        # Channel format per design §5.2.
        assert record.channel == f"research:{record.run_id}"
        # ``status`` is ``"running"`` once the task has been dispatched.
        assert record.status == "running"

    @pytest.mark.asyncio
    async def test_publishes_run_request_onto_research_runs_stream(self) -> None:
        redis = _FakeRedis()
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=redis, orchestrator_factory=lambda: orch)

        user_id = uuid4()
        record = await svc.start_run(user_id, "RELIANCE", "What's the thesis?")
        # Let the background task run so downstream assertions see the
        # final state even if they don't await explicitly.
        await asyncio.sleep(0)

        # At least the ``research:runs`` request was published.
        stream_names = [c[0] for c in redis.xadd_calls]
        assert "research:runs" in stream_names

        # And the request carried the tenant + prompt verbatim.
        runs_fields = next(fields for name, fields in redis.xadd_calls if name == "research:runs")
        assert runs_fields["run_id"] == str(record.run_id)
        assert runs_fields["user_id"] == str(user_id)
        assert runs_fields["symbol"] == "RELIANCE"
        assert runs_fields["prompt"] == "What's the thesis?"

    @pytest.mark.asyncio
    async def test_dispatches_orchestrator_background_task(self) -> None:
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        record = await svc.start_run(uuid4(), "RELIANCE", "go")
        # Let the background task finish.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(orch.calls) == 1
        assert orch.calls[0]["run_id"] == record.run_id

    @pytest.mark.asyncio
    async def test_empty_prompt_raises_config_missing(self) -> None:
        svc = ResearchService(
            redis=_FakeRedis(),
            orchestrator_factory=lambda: _FakeOrchestrator(),
        )
        with pytest.raises(ConfigMissingError) as excinfo:
            await svc.start_run(uuid4(), "RELIANCE", "   ")
        assert excinfo.value.config_key == "research.run.prompt"

    @pytest.mark.asyncio
    async def test_missing_factory_raises_config_missing(self) -> None:
        svc = ResearchService(redis=_FakeRedis())
        with pytest.raises(ConfigMissingError) as excinfo:
            await svc.start_run(uuid4(), "RELIANCE", "go")
        assert excinfo.value.config_key == "research.orchestrator_factory"


# --------------------------------------------------------------------------- #
# Run lifecycle — state transitions                                           #
# --------------------------------------------------------------------------- #


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_successful_run_transitions_to_done(self) -> None:
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        record = await svc.start_run(uuid4(), "RELIANCE", "go")
        # Wait for background task to complete.
        task = svc._run_tasks[record.run_id]  # type: ignore[attr-defined]
        await task

        assert record.status == "done"
        assert record.brief is not None
        assert record.finished_at is not None

    @pytest.mark.asyncio
    async def test_partial_brief_transitions_to_partial(self) -> None:
        brief = {
            "run_id": "",
            "summary": "ok",
            "partial": True,
            "quality": "normal",
            "budget_exhausted": False,
        }
        orch = _FakeOrchestrator(brief=brief)
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        record = await svc.start_run(uuid4(), "RELIANCE", "go")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]
        assert record.status == "partial"

    @pytest.mark.asyncio
    async def test_low_quality_transitions_to_partial(self) -> None:
        brief = {
            "run_id": "",
            "summary": "insufficient evidence",
            "partial": False,
            "quality": "low",
            "budget_exhausted": False,
        }
        orch = _FakeOrchestrator(brief=brief)
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        record = await svc.start_run(uuid4(), "RELIANCE", "go")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]
        assert record.status == "partial"

    @pytest.mark.asyncio
    async def test_orchestrator_exception_transitions_to_error(self) -> None:
        orch = _FakeOrchestrator(brief=RuntimeError("downstream on fire"))
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        record = await svc.start_run(uuid4(), "RELIANCE", "go")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]

        assert record.status == "error"
        assert record.brief is None
        assert record.trace["error"]["type"] == "RuntimeError"
        assert "downstream on fire" in record.trace["error"]["message"]


# --------------------------------------------------------------------------- #
# get_run / get_run_trace                                                     #
# --------------------------------------------------------------------------- #


class TestGetRun:
    @pytest.mark.asyncio
    async def test_get_run_returns_brief_after_completion(self) -> None:
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        user_id = uuid4()
        record = await svc.start_run(user_id, "RELIANCE", "go")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]

        payload = await svc.get_run(user_id, record.run_id)
        assert payload["run_id"] == str(record.run_id)
        assert payload["status"] == "done"
        assert payload["brief"] is not None

    @pytest.mark.asyncio
    async def test_get_run_missing_raises_key_error(self) -> None:
        svc = ResearchService(orchestrator_factory=lambda: _FakeOrchestrator())
        with pytest.raises(KeyError):
            await svc.get_run(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_run_cross_tenant_raises_key_error(self) -> None:
        """Foreign run must not be distinguishable from a missing run."""
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        owner = uuid4()
        other = uuid4()
        record = await svc.start_run(owner, "RELIANCE", "go")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]

        with pytest.raises(KeyError):
            await svc.get_run(other, record.run_id)

    @pytest.mark.asyncio
    async def test_get_run_trace_includes_prompt_and_symbol(self) -> None:
        orch = _FakeOrchestrator()
        svc = ResearchService(redis=_FakeRedis(), orchestrator_factory=lambda: orch)

        user_id = uuid4()
        record = await svc.start_run(user_id, "RELIANCE", "analyse filings")
        await svc._run_tasks[record.run_id]  # type: ignore[attr-defined]

        trace = await svc.get_run_trace(user_id, record.run_id)
        assert trace["prompt"] == "analyse filings"
        assert trace["symbol"] == "RELIANCE"
        assert trace["status"] == "done"


# --------------------------------------------------------------------------- #
# Snapshot                                                                    #
# --------------------------------------------------------------------------- #


class TestGetSnapshot:
    @pytest.mark.asyncio
    async def test_no_store_returns_none(self) -> None:
        svc = ResearchService()
        result = await svc.get_snapshot(uuid4(), "RELIANCE")
        assert result is None

    @pytest.mark.asyncio
    async def test_store_forwarded(self) -> None:
        class _Rec:
            brief = {"summary": "x"}
            symbol = "RELIANCE"
            stale = False
            from datetime import datetime, timezone

            generated_at = datetime.now(timezone.utc)
            input_document_hashes: list[str] = []
            user_id = uuid4()

        svc = ResearchService(snapshot_store=_FakeSnapshotStore(_Rec()))
        result = await svc.get_snapshot(uuid4(), "RELIANCE")
        assert result is _Rec or result.symbol == "RELIANCE"


# --------------------------------------------------------------------------- #
# Reindex                                                                     #
# --------------------------------------------------------------------------- #


class TestReindex:
    @pytest.mark.asyncio
    async def test_reindex_publishes_index_event(self) -> None:
        redis = _FakeRedis()
        svc = ResearchService(redis=redis)

        payload = await svc.reindex(uuid4(), "reliance")
        assert payload["status"] == "queued"
        assert payload["symbol"] == "RELIANCE"

        streams = [c[0] for c in redis.xadd_calls]
        assert "research:index_events" in streams

    @pytest.mark.asyncio
    async def test_reindex_without_redis_still_returns_payload(self) -> None:
        """A broken Redis must not block the reindex handshake."""
        svc = ResearchService()
        payload = await svc.reindex(uuid4(), "RELIANCE")
        assert payload["status"] == "queued"


# --------------------------------------------------------------------------- #
# forget_memory                                                               #
# --------------------------------------------------------------------------- #


class TestForgetMemory:
    @pytest.mark.asyncio
    async def test_missing_stack_raises_config_missing(self) -> None:
        svc = ResearchService()
        with pytest.raises(ConfigMissingError) as excinfo:
            await svc.forget_memory(uuid4(), "all")
        assert excinfo.value.config_key == "research.memory_stack"


# --------------------------------------------------------------------------- #
# Health                                                                      #
# --------------------------------------------------------------------------- #


class TestHealth:
    @pytest.mark.asyncio
    async def test_defaults_report_pending(self) -> None:
        svc = ResearchService()
        report = await svc.health()
        assert report["status"] == "pending"
        components = report["components"]
        # The five always-present components from Phase 1.
        for key in (
            "vector_store",
            "embeddings_provider",
            "llm_provider",
            "redis",
            "postgres",
        ):
            assert key in components

    @pytest.mark.asyncio
    async def test_orchestrator_configured_when_factory_supplied(self) -> None:
        svc = ResearchService(orchestrator_factory=lambda: _FakeOrchestrator())
        report = await svc.health()
        assert report["components"]["orchestrator"] == "configured"
