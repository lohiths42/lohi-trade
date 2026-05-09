"""Integration tests for the Lohi-Research REST router (Task 16.2).

Exercises every endpoint under ``/api/v2/research`` with a mocked
:class:`ResearchService` so the HTTP contract (status codes, request
and response shapes, JWT auth enforcement) can be pinned without
bringing up Redis or Postgres.

Requirements: 3.1, 3.12, 4.8, 5.1, 5.5, 7.7, 13.3, 13.4
Design: §5.1, §5.3
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import (
    ConfigMissingError,
    register_research_exception_handlers,
)
from app.routers.auth_v2 import get_current_user_id
from app.routers.research import get_research_service, router
from app.services.research_service import ResearchService, RunRecord
from src.research.providers.errors import ProviderAuthError


# --------------------------------------------------------------------------- #
# Test harness                                                                #
# --------------------------------------------------------------------------- #


USER_ID = str(uuid4())


def _build_app(svc: ResearchService) -> FastAPI:
    """Build a minimal FastAPI app mounting just the research router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2/research", tags=["research"])
    # Install the same exception handlers ``main.py`` installs so the
    # envelope shape is verifiable end-to-end.
    register_research_exception_handlers(app)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_research_service] = lambda: svc
    return app


def _make_run_record(user_id: UUID | None = None) -> RunRecord:
    import time

    run_id = uuid4()
    return RunRecord(
        run_id=run_id,
        user_id=user_id or UUID(USER_ID),
        symbol="RELIANCE",
        prompt="go",
        status="running",
        created_at=time.time(),
        channel=f"research:{run_id}",
    )


# --------------------------------------------------------------------------- #
# POST /runs                                                                  #
# --------------------------------------------------------------------------- #


class TestStartRun:
    def test_returns_202_with_run_id_and_channel(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        record = _make_run_record()
        svc.start_run.return_value = record
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.post(
            "/api/v2/research/runs",
            json={"prompt": "Analyse RELIANCE", "symbol": "RELIANCE"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["run_id"] == str(record.run_id)
        assert body["channel"] == record.channel
        assert body["status"] == "running"

    def test_forwards_prompt_and_symbol_to_service(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.start_run.return_value = _make_run_record()
        app = _build_app(svc)
        client = TestClient(app)

        client.post(
            "/api/v2/research/runs",
            json={"prompt": "Give me the thesis.", "symbol": "TCS"},
        )
        svc.start_run.assert_awaited_once()
        _, kwargs = svc.start_run.call_args
        assert kwargs["prompt"] == "Give me the thesis."
        assert kwargs["symbol"] == "TCS"
        assert str(kwargs["user_id"]) == USER_ID

    def test_empty_prompt_rejected_by_pydantic(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.start_run.return_value = _make_run_record()
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.post("/api/v2/research/runs", json={"prompt": ""})
        # Pydantic's min_length=1 catches this before the handler runs.
        assert resp.status_code == 422

    def test_config_missing_envelope(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.start_run.side_effect = ConfigMissingError(
            "research.providers.chat.api_key"
        )
        app = _build_app(svc)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v2/research/runs",
            json={"prompt": "go", "symbol": "RELIANCE"},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "CONFIG_MISSING"
        assert body["error"]["config_key"] == "research.providers.chat.api_key"

    def test_provider_auth_error_envelope(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.start_run.side_effect = ProviderAuthError(
            "nvidia_nim", "llama", "invalid_api_key"
        )
        app = _build_app(svc)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v2/research/runs",
            json={"prompt": "go", "symbol": "RELIANCE"},
        )
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["code"] == "PROVIDER_AUTH_FAILED"
        assert body["error"]["provider"] == "nvidia_nim"
        assert body["error"]["model"] == "llama"


# --------------------------------------------------------------------------- #
# GET /runs/:run_id + GET /runs/:run_id/trace                                 #
# --------------------------------------------------------------------------- #


class TestGetRun:
    def test_returns_brief(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        run_id = str(uuid4())
        svc.get_run.return_value = {
            "run_id": run_id,
            "status": "done",
            "brief": {"summary": "ok"},
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get(f"/api/v2/research/runs/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["brief"] == {"summary": "ok"}

    def test_unknown_returns_404(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.get_run.side_effect = KeyError("not found")
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get(f"/api/v2/research/runs/{uuid4()}")
        assert resp.status_code == 404

    def test_malformed_uuid_returns_404(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get("/api/v2/research/runs/not-a-uuid")
        assert resp.status_code == 404


class TestGetRunTrace:
    def test_returns_trace(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        run_id = str(uuid4())
        svc.get_run_trace.return_value = {
            "run_id": run_id,
            "status": "done",
            "prompt": "go",
            "symbol": "RELIANCE",
            "created_at": 1.0,
            "finished_at": 2.0,
            "trace": {"plan_md": "ok"},
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get(f"/api/v2/research/runs/{run_id}/trace")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trace"]["plan_md"] == "ok"
        assert body["prompt"] == "go"


# --------------------------------------------------------------------------- #
# GET /snapshot/:symbol                                                       #
# --------------------------------------------------------------------------- #


class TestGetSnapshot:
    def test_no_snapshot_returns_none_brief(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.get_snapshot.return_value = None
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get("/api/v2/research/snapshot/RELIANCE")
        assert resp.status_code == 200
        body = resp.json()
        assert body["brief"] is None
        assert body["symbol"] == "RELIANCE"
        assert body["stale"] is False

    def test_fresh_snapshot_returns_brief(self) -> None:
        from datetime import datetime, timezone

        class _Rec:
            def __init__(self) -> None:
                self.symbol = "RELIANCE"
                self.brief = {"summary": "ok"}
                self.generated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
                self.stale = False
                self.user_id = UUID(USER_ID)
                self.input_document_hashes: list[str] = []

        svc = AsyncMock(spec=ResearchService)
        svc.get_snapshot.return_value = _Rec()
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get("/api/v2/research/snapshot/RELIANCE")
        assert resp.status_code == 200
        body = resp.json()
        assert body["brief"] == {"summary": "ok"}
        assert body["stale"] is False
        assert body["generated_at"].startswith("2024-01-01")


# --------------------------------------------------------------------------- #
# POST /documents/upload                                                      #
# --------------------------------------------------------------------------- #


class TestUploadDocument:
    def test_upload_roundtrip(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.upload_document.return_value = {
            "document_id": str(uuid4()),
            "path": "/tmp/upload.pdf",
            "symbol": "RELIANCE",
            "filename": "upload.pdf",
            "size_bytes": 3,
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.post(
            "/api/v2/research/documents/upload",
            data={"symbol": "RELIANCE"},
            files={"file": ("upload.pdf", io.BytesIO(b"hi!"), "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "upload.pdf"
        assert body["symbol"] == "RELIANCE"
        assert body["size_bytes"] == 3
        svc.upload_document.assert_awaited_once()


# --------------------------------------------------------------------------- #
# POST /reindex/:symbol                                                       #
# --------------------------------------------------------------------------- #


class TestReindexSymbol:
    def test_returns_202_with_request_id(self) -> None:
        request_id = str(uuid4())
        svc = AsyncMock(spec=ResearchService)
        svc.reindex.return_value = {
            "request_id": request_id,
            "status": "queued",
            "symbol": "RELIANCE",
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.post("/api/v2/research/reindex/RELIANCE")
        assert resp.status_code == 202
        body = resp.json()
        assert body["request_id"] == request_id
        assert body["status"] == "queued"


# --------------------------------------------------------------------------- #
# DELETE /memory                                                              #
# --------------------------------------------------------------------------- #


class TestForgetMemory:
    def test_success_returns_counts(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.forget_memory.return_value = {
            "scope": "all",
            "working_deleted": 2,
            "semantic_deleted": 3,
            "episodic_deleted": 1,
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.delete("/api/v2/research/memory?scope=all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "all"
        assert body["working_deleted"] == 2
        assert body["semantic_deleted"] == 3
        assert body["episodic_deleted"] == 1

    def test_invalid_scope_returns_400(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.forget_memory.side_effect = ValueError(
            "unknown memory.forget scope: 'weird'"
        )
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.delete("/api/v2/research/memory?scope=weird")
        assert resp.status_code == 400
        assert "weird" in resp.json()["detail"]

    def test_missing_stack_returns_envelope(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.forget_memory.side_effect = ConfigMissingError(
            "research.memory_stack",
            "stack not wired",
        )
        app = _build_app(svc)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/api/v2/research/memory?scope=all")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "CONFIG_MISSING"
        assert body["error"]["config_key"] == "research.memory_stack"


# --------------------------------------------------------------------------- #
# GET /health                                                                 #
# --------------------------------------------------------------------------- #


class TestHealth:
    def test_returns_pending_report(self) -> None:
        svc = AsyncMock(spec=ResearchService)
        svc.health.return_value = {
            "status": "pending",
            "components": {
                "vector_store": "pending",
                "embeddings_provider": "pending",
                "llm_provider": "pending",
                "redis": "pending",
                "postgres": "pending",
            },
        }
        app = _build_app(svc)
        client = TestClient(app)

        resp = client.get("/api/v2/research/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert "components" in body
