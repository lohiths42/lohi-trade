"""Unit tests for Phase 18 Task 20.3 — per-run trace endpoint shape.

Verifies that ``GET /api/v2/research/runs/{run_id}/trace`` returns the
replayable trace shape documented in design §15:

* Run metadata (status, prompt, symbol, timestamps).
* ``trace.provenance`` — per-agent ``AgentResult`` payloads.
* ``trace.guardrail_decisions`` — Guardrail_Layer decisions.
* ``trace.judge_reports`` — Judge_LLM verdicts (first-pass +
  re-synthesis pass if any).

The tests exercise :meth:`ResearchService.get_run_trace` directly
against a seeded in-memory :class:`RunRecord` and also smoke-test the
HTTP surface via FastAPI's :class:`TestClient`. Seeding the DB would
exercise the persistence layer (migration 002) — out of scope for
Task 20.3 which is a read-through enrichment pass; Phase 19 will add a
DB-backed integration test.

Requirements: 13.3, 13.4
Design: §15
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# Backend-gateway is not on sys.path when ``tests/research`` is invoked
# from the project root; insert it lazily so the same test file runs
# identically from either directory.
_gateway_root = str(Path(__file__).resolve().parents[2] / "backend-gateway")
if _gateway_root not in sys.path:
    sys.path.insert(0, _gateway_root)


from app.routers.auth_v2 import get_current_user_id  # noqa: E402
from app.routers.research import get_research_service, router  # noqa: E402
from app.services.research_service import ResearchService, RunRecord  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


_USER_ID = str(uuid4())


def _seed_run(
    svc: ResearchService,
    *,
    user_id: UUID | None = None,
    brief: dict | None = None,
) -> RunRecord:
    """Seed a completed run on ``svc`` and return its :class:`RunRecord`."""
    user_uuid = user_id or UUID(_USER_ID)
    run_id = uuid4()
    now = time.time()
    record = RunRecord(
        run_id=run_id,
        user_id=user_uuid,
        symbol="RELIANCE",
        prompt="analyse RELIANCE",
        status="done",
        created_at=now - 10.0,
        finished_at=now,
        brief=brief,
        trace={"plan_md": "one-line plan"},
        channel=f"research:{run_id}",
    )
    # ``ResearchService._runs`` is the canonical in-memory run cache
    # (``app/services/research_service.py``); seeding it directly is
    # the supported test seam until Phase 19 wires the DB-backed
    # read path.
    svc._runs[run_id] = record
    return record


def _brief_with_provenance_and_judge() -> dict:
    """Canonical brief payload used by the endpoint tests."""
    return {
        "run_id": "placeholder",
        "symbol": "RELIANCE",
        "summary": "Summary markdown.",
        "thesis": "Thesis markdown.",
        "risks": "Risks markdown.",
        "financial_highlights": "",
        "management_commentary": "",
        "technical_view": "",
        "peers": "",
        "macro_context": "",
        "citations": ["abc123"],
        "provenance": [
            {
                "agent_name": "filings",
                "kind": "ok",
                "section_name": "financial_highlights",
                "section_md": "body",
                "chunk_ids": ["abc123"],
                "wall_time_ms": 412,
                "input_tokens": 100,
                "output_tokens": 50,
                "reason": "",
            },
            {
                "agent_name": "macro",
                "kind": "no_data",
                "section_name": "macro_context",
                "section_md": "",
                "chunk_ids": [],
                "wall_time_ms": 10,
                "input_tokens": 0,
                "output_tokens": 0,
                "reason": "no_data: nothing indexed",
            },
        ],
        "guardrail_decisions": [
            {
                "phase": "input",
                "rule_id": "jailbreak_v1_override",
                "action": "allow",
                "reason": "prompt passed",
            },
        ],
        "judge": {
            "run_id": "placeholder",
            "groundedness_score": {"summary": 0.92, "thesis": 0.85},
            "unsupported_claims": [],
            "safe_to_display": True,
            "contradiction_pairs": [],
            "off_policy_findings": [],
            "retry_count": 0,
            "elapsed_ms": 1234,
            "model_id": "nvidia_nim/llama3",
        },
        "quality": "normal",
        "unsupported_sections": [],
        "partial": False,
        "wall_time_ms": 8200,
    }


def _build_app(svc: ResearchService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v2/research", tags=["research"])
    app.dependency_overrides[get_current_user_id] = lambda: _USER_ID
    app.dependency_overrides[get_research_service] = lambda: svc
    return app


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


class TestGetRunTraceShape:
    """Unit tests for :meth:`ResearchService.get_run_trace` enrichment."""

    @pytest.mark.asyncio
    async def test_trace_includes_provenance_guardrails_judge(self) -> None:
        svc = ResearchService()
        record = _seed_run(svc, brief=_brief_with_provenance_and_judge())

        payload = await svc.get_run_trace(record.user_id, record.run_id)

        assert payload["run_id"] == str(record.run_id)
        assert payload["prompt"] == "analyse RELIANCE"
        assert payload["symbol"] == "RELIANCE"
        assert payload["status"] == "done"

        trace = payload["trace"]
        # Enriched keys are always present so the UI renders
        # unconditionally — Task 20.3 requirement.
        assert "provenance" in trace
        assert "guardrail_decisions" in trace
        assert "judge_reports" in trace

        # Provenance carries the per-agent payloads from the brief.
        assert len(trace["provenance"]) == 2
        assert trace["provenance"][0]["agent_name"] == "filings"
        assert trace["provenance"][1]["agent_name"] == "macro"

        # Guardrail decisions come through verbatim.
        assert len(trace["guardrail_decisions"]) == 1
        assert trace["guardrail_decisions"][0]["rule_id"] == "jailbreak_v1_override"

        # Judge reports is a list so multi-report runs (re-synthesis)
        # render identically. With one first-pass pass, the list has
        # a single entry.
        assert len(trace["judge_reports"]) == 1
        assert trace["judge_reports"][0]["safe_to_display"] is True
        assert trace["judge_reports"][0]["model_id"] == "nvidia_nim/llama3"

    @pytest.mark.asyncio
    async def test_trace_defaults_when_brief_missing(self) -> None:
        """A pending run (no brief yet) still returns the stable shape."""
        svc = ResearchService()
        record = _seed_run(svc, brief=None)

        payload = await svc.get_run_trace(record.user_id, record.run_id)
        trace = payload["trace"]
        # Defaults — empty lists so the UI renders "no data" states
        # rather than a missing-key error.
        assert trace["provenance"] == []
        assert trace["guardrail_decisions"] == []
        assert trace["judge_reports"] == []

    @pytest.mark.asyncio
    async def test_trace_rejects_foreign_run(self) -> None:
        """A run owned by a different user raises ``KeyError`` (router → 404)."""
        svc = ResearchService()
        foreign = uuid4()
        record = _seed_run(svc, user_id=foreign)

        with pytest.raises(KeyError):
            await svc.get_run_trace(UUID(_USER_ID), record.run_id)


# --------------------------------------------------------------------------- #
# HTTP smoke test                                                             #
# --------------------------------------------------------------------------- #


class TestTraceEndpointHTTP:
    """End-to-end smoke test via FastAPI :class:`TestClient`."""

    def test_endpoint_returns_200_with_enriched_shape(self) -> None:
        svc = ResearchService()
        record = _seed_run(svc, brief=_brief_with_provenance_and_judge())
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get(f"/api/v2/research/runs/{record.run_id}/trace")
        assert resp.status_code == 200
        body = resp.json()

        assert body["run_id"] == str(record.run_id)
        assert body["symbol"] == "RELIANCE"
        assert body["status"] == "done"

        trace = body["trace"]
        assert len(trace["provenance"]) == 2
        assert trace["guardrail_decisions"][0]["rule_id"] == "jailbreak_v1_override"
        assert trace["judge_reports"][0]["safe_to_display"] is True

    def test_endpoint_returns_404_for_unknown_run(self) -> None:
        svc = ResearchService()
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get(f"/api/v2/research/runs/{uuid4()}/trace")
        assert resp.status_code == 404
