"""Research API router — Lohi-Research gateway surface (Task 16.2).

Mounts eight endpoints under ``/api/v2/research`` behind the existing
JWT + RLS middleware (Req 8.2). Replaces the Phase 1 stub from
Task 1.6 with the full surface documented in design §5.1:

* ``POST   /runs``               — start a Research_Run (Req 1.1, 1.7, 5.1)
* ``GET    /runs/:run_id``       — final brief (Req 1.5)
* ``GET    /runs/:run_id/trace`` — full trace (Req 13.3, 13.4)
* ``GET    /snapshot/:symbol``   — precomputed snapshot (Req 5.5, 11.4)
* ``POST   /documents/upload``   — multipart PDF upload (Req 3.1)
* ``POST   /reindex/:symbol``    — idempotent reindex (Req 3.12)
* ``DELETE /memory``             — memory.forget dispatcher (Req 4.8, 4.9)
* ``GET    /health``             — aggregated probe (Req 7.7)

Every endpoint translates known exceptions into the design §5.3
structured error envelope via :mod:`app.middleware.errors` so the
shape is stable across the surface (Task 16.4). Unknown exceptions
fall through to FastAPI's default handlers, which the
``register_research_exception_handlers`` call in ``main.py`` (Task
16.4) catches with the same envelope.

Requirements: 3.1, 3.12, 4.8, 5.1, 5.5, 7.7, 13.3, 13.4, 2.10, 8.8, 13.1
Design: §5.1, §5.2, §5.3
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.middleware.errors import (
    ConfigMissingError,
    LatencyBudgetExceededError,
    ProviderTimeoutError,
    json_response_for,
)
from app.routers.auth_v2 import get_current_user_id
from app.services.research_service import ResearchService
from src.research.providers.errors import ProviderError

logger = logging.getLogger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# User ID helper                                                              #
# --------------------------------------------------------------------------- #


def _user_uuid(user_id: str) -> UUID:
    """Convert a string user_id (e.g. "admin") to a deterministic UUID.

    The v1 auth system uses usernames, not UUIDs. The research subsystem
    needs UUIDs for RLS scoping. We derive a stable UUID5 from the
    username so the same user always maps to the same UUID.
    """
    try:
        return UUID(user_id)
    except (TypeError, ValueError):
        from uuid import NAMESPACE_URL, uuid5

        return uuid5(NAMESPACE_URL, f"lohi-user:{user_id}")


# --------------------------------------------------------------------------- #
# Request / response models                                                   #
# --------------------------------------------------------------------------- #


class StartRunRequest(BaseModel):
    """Request body for ``POST /runs`` (design §5.1)."""

    prompt: str = Field(
        ...,
        min_length=1,
        description="User prompt. Passes through the Guardrail_Layer before the Orchestrator runs.",
    )
    symbol: Optional[str] = Field(
        None,
        description="Optional ticker scope. When omitted, Sub_Agents that require a symbol return no_data.",
    )
    agents: Optional[list[str]] = Field(
        None,
        description=(
            "Optional list of Sub_Agent names to restrict the fan-out. "
            "Unknown names are silently dropped by the Orchestrator plan step."
        ),
    )


class StartRunResponse(BaseModel):
    """Response body for ``POST /runs`` (design §5.1)."""

    run_id: str
    channel: str = Field(
        ...,
        description="Socket.IO channel the client subscribes to for partials + done events.",
    )
    status: str


class BriefResponse(BaseModel):
    """Response body for ``GET /runs/:run_id``."""

    run_id: str
    status: str
    brief: Optional[dict] = None


class TraceResponse(BaseModel):
    """Response body for ``GET /runs/:run_id/trace``."""

    run_id: str
    status: str
    prompt: str
    symbol: Optional[str] = None
    created_at: float
    finished_at: Optional[float] = None
    trace: dict


class SnapshotResponse(BaseModel):
    """Response body for ``GET /snapshot/:symbol``.

    ``brief=None`` when no fresh snapshot exists — callers should
    fall through to ``POST /runs`` for a full research run.
    """

    symbol: str
    brief: Optional[dict] = None
    generated_at: Optional[str] = None
    stale: bool = False


class UploadResponse(BaseModel):
    """Response body for ``POST /documents/upload``."""

    document_id: str
    path: str
    symbol: str
    filename: str
    size_bytes: int


class ReindexResponse(BaseModel):
    """Response body for ``POST /reindex/:symbol``."""

    request_id: str
    status: str
    symbol: str


class ForgetMemoryResponse(BaseModel):
    """Response body for ``DELETE /memory``."""

    scope: str
    working_deleted: int
    semantic_deleted: int
    episodic_deleted: int


# --------------------------------------------------------------------------- #
# Service dependency                                                          #
# --------------------------------------------------------------------------- #


_service: Optional[ResearchService] = None


def set_research_service(svc: ResearchService) -> None:
    """Called at app startup to inject the :class:`ResearchService`.

    Mirrors the pattern used by :mod:`app.routers.chatbot` —
    ``main.py`` constructs the service once and hands it to the
    router through this setter. Tests override the dependency via
    FastAPI's ``app.dependency_overrides`` map.
    """
    global _service
    _service = svc


def get_research_service() -> ResearchService:
    """FastAPI dependency returning the active :class:`ResearchService`.

    When no service has been injected, fall back to a bare stub so
    the Phase-1 ``GET /health`` behaviour keeps working on a gateway
    that hasn't fully wired the subsystem yet. Every mutation
    endpoint still guards against missing collaborators (e.g.
    :meth:`ResearchService.start_run` requires an
    ``orchestrator_factory``) and raises :class:`ConfigMissingError`
    which the envelope mapper translates to a 500.
    """
    if _service is None:
        return ResearchService()
    return _service


# --------------------------------------------------------------------------- #
# Error-handling helpers                                                      #
# --------------------------------------------------------------------------- #


def _translate_exception(exc: BaseException) -> JSONResponse:
    """Translate a known research exception into a structured response.

    Any exception surviving this helper is re-raised so FastAPI's
    global handlers (installed by
    :func:`register_research_exception_handlers` in ``main.py``)
    catch it with the same envelope. Keeping the per-endpoint
    translation keeps logs scoped to the route that raised and
    lets us attach route-specific metadata without cross-cutting
    middleware.
    """
    return json_response_for(exc)


# --------------------------------------------------------------------------- #
# Endpoints — run lifecycle                                                   #
# --------------------------------------------------------------------------- #


@router.post("/runs", response_model=StartRunResponse, status_code=202)
async def start_run(
    body: StartRunRequest,
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Start a ``Research_Run``.

    Returns ``202 Accepted`` with the ``run_id`` + Socket.IO channel
    so the caller can subscribe to streamed partials (design §5.1,
    §5.2). The final brief is retrievable via ``GET /runs/:run_id``
    or by listening for the ``research:done`` Socket.IO event.

    Requirements: 1.1, 1.7, 5.1
    """
    logger.info(
        "start_run called: user_id=%s, symbol=%s, prompt=%.50s", user_id, body.symbol, body.prompt
    )
    # Convert string user_id to UUID. The v1 auth system uses usernames
    # (e.g. "admin") not UUIDs, so we generate a deterministic UUID5
    # from the username for the research subsystem's RLS scoping.
    user_uuid = _user_uuid(user_id)
    try:
        record = await svc.start_run(
            user_id=user_uuid,
            symbol=body.symbol,
            prompt=body.prompt,
        )
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    except ValueError as exc:
        # ``_user_uuid(user_id)`` — the JWT extraction layer guarantees a
        # string, so this only triggers on a deployment bug. We
        # surface it through the envelope so clients see the
        # same shape regardless of failure mode.
        return _translate_exception(exc)
    except Exception as exc:
        # Catch-all: log the full traceback so operators can diagnose,
        # then return a structured error to the client.
        logger.exception("start_run failed with unexpected error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)[:500]}},
        )
    return StartRunResponse(
        run_id=str(record.run_id),
        channel=record.channel,
        status=record.status,
    )


@router.get("/runs/{run_id}", response_model=BriefResponse)
async def get_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Return the final brief for ``run_id``.

    Requirements: 1.5
    """
    try:
        payload = await svc.get_run(_user_uuid(user_id), UUID(run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Research run not found")
    except ValueError:
        # Malformed ``run_id`` — 404 rather than 422 so we don't leak
        # which IDs are in the UUID format vs not.
        raise HTTPException(status_code=404, detail="Research run not found")
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    return BriefResponse(**payload)


@router.get("/runs/{run_id}/trace", response_model=TraceResponse)
async def get_run_trace(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Return the full trace for ``run_id`` (plan + partials + provenance).

    Requirements: 13.3, 13.4
    """
    try:
        payload = await svc.get_run_trace(_user_uuid(user_id), UUID(run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Research run not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Research run not found")
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    return TraceResponse(**payload)


# --------------------------------------------------------------------------- #
# Endpoints — snapshot                                                        #
# --------------------------------------------------------------------------- #


@router.get("/snapshot/{symbol}", response_model=SnapshotResponse)
async def get_snapshot(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Return the fresh Snapshot for ``(user_id, symbol)``.

    When no Snapshot is fresh, returns ``brief=None`` with
    ``stale=false`` so the client can fall through to ``POST /runs``
    for a full research run. When a Snapshot exists but has been
    flagged stale by the snapshotter worker (design §3.10, Req 11.6),
    the brief body is still returned so the UI can render a "stale"
    badge rather than an empty state.

    Requirements: 5.5, 11.4, 11.6
    """
    try:
        record = await svc.get_snapshot(_user_uuid(user_id), symbol)
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    if record is None:
        return SnapshotResponse(symbol=symbol.upper().strip(), brief=None)
    return SnapshotResponse(
        symbol=record.symbol,
        brief=record.brief,
        generated_at=record.generated_at.isoformat(),
        stale=record.stale,
    )


# --------------------------------------------------------------------------- #
# Endpoints — documents + reindex                                             #
# --------------------------------------------------------------------------- #


@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to ingest"),
    symbol: Optional[str] = Form(None, description="Ticker symbol the document relates to"),
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Upload a PDF into the watch folder for ingestion.

    The uploaded file is written to
    ``data/research/uploads/`` where the ``user_uploads`` watcher
    (Phase 5 Task 5.4) picks it up. The watcher owns the end-to-end
    parse → chunk → embed → index pipeline; this endpoint is a thin
    handoff.

    Requirements: 3.1
    """
    filename = file.filename or "upload.pdf"
    content = await file.read()
    try:
        payload = await svc.upload_document(
            user_id=_user_uuid(user_id),
            filename=filename,
            content=content,
            symbol=symbol,
        )
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    return UploadResponse(**payload)


@router.post("/reindex/{symbol}", response_model=ReindexResponse, status_code=202)
async def reindex_symbol(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Queue a reindex request for ``(user_id, symbol)``.

    Idempotent on unchanged source content — chunk ids are
    SHA-256-derived so re-running the ingest pipeline yields the
    same chunk set when the underlying documents haven't changed
    (Req 3.12).

    Requirements: 3.12
    """
    try:
        payload = await svc.reindex(user_id=_user_uuid(user_id), symbol=symbol)
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    return ReindexResponse(**payload)


# --------------------------------------------------------------------------- #
# Endpoints — memory                                                          #
# --------------------------------------------------------------------------- #


@router.delete("/memory", response_model=ForgetMemoryResponse)
async def forget_memory(
    scope: str = Query(
        ...,
        description=(
            "Scope to forget: 'all' | 'working' | 'semantic' | 'episodic' | " "'symbol:<SYMBOL>'"
        ),
    ),
    user_id: str = Depends(get_current_user_id),
    svc: ResearchService = Depends(get_research_service),
) -> Any:
    """Delete memory entries for the authenticated user at ``scope``.

    Maps directly onto :func:`src.research.memory.forget.forget_memory`
    (Task 7.4). Accepted scopes are exactly the five documented in
    that module's docstring; any other value produces a 400 with the
    list of valid scopes so callers don't need to consult source.

    Requirements: 4.8, 4.9
    """
    try:
        payload = await svc.forget_memory(user_id=_user_uuid(user_id), scope=scope)
    except ValueError as exc:
        # Raised by ``forget_memory`` when the scope string is not
        # one of the documented shapes. 400 is the right status —
        # this is a client-supplied query parameter, not a server bug.
        raise HTTPException(status_code=400, detail=str(exc))
    except (
        ProviderError,
        ConfigMissingError,
        ProviderTimeoutError,
        LatencyBudgetExceededError,
    ) as exc:
        return _translate_exception(exc)
    return ForgetMemoryResponse(**payload)


# --------------------------------------------------------------------------- #
# Endpoints — health                                                          #
# --------------------------------------------------------------------------- #


@router.get("/health")
async def research_health(
    svc: ResearchService = Depends(get_research_service),
) -> dict:
    """Return the Lohi-Research health report.

    Every component is ``"pending"`` until Task 18.4 wires the real
    per-component probes. The ``vector_store`` field surfaces the
    auto-resolved backend once the §8 decision tree has run at least
    once (Task 3.2).

    Requirements: 7.7
    """
    return await svc.health()


# --------------------------------------------------------------------------- #
# Endpoints — metrics (Task 20.2)                                             #
# --------------------------------------------------------------------------- #


@router.get("/metrics")
async def research_metrics() -> Response:
    """Return the Lohi-Research Prometheus metrics in text format.

    Wired to the private registry in
    :mod:`src.research.observability.metrics` so the scrape surface is
    scoped to Lohi-Research metrics only — the base gateway's global
    ``prometheus_client.REGISTRY`` is not touched by this endpoint.

    Requirements: 13.2
    Design: §15
    """
    # Local import so the router's import graph stays free of the
    # metrics module when prometheus-client is not installed in a
    # trimmed test install — the ``/metrics`` call itself will then
    # raise, but every other endpoint keeps working.
    from src.research.observability.metrics import render_metrics

    data, content_type = render_metrics()
    return Response(content=data, media_type=content_type)
