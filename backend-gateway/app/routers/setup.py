"""Setup Router — API endpoints for the Easy Setup Wizard.

Provides credential submission, connection testing, service health,
and setup lifecycle management. All setup endpoints are restricted
to localhost-only access (no auth required, but loopback guard).

The /health/services endpoint exposes service configuration status
for use by the frontend's graceful degradation logic.

Requirements: 4.6, 5.5, 5.6, 6.1
Design: §Setup Router
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.credential_store import CredentialStore
from app.services.feature_gate import reload_registry
from app.services.service_registry import (
    ServiceRegistry,
)
from app.services.setup_service import SetupService

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic Models ─────────────────────────────────────────────────────────


class CredentialSubmission(BaseModel):
    """Request body for credential submission."""

    credentials: dict[str, str]  # key_name → value


class TestResult(BaseModel):
    """Response model for connection test results."""

    success: bool
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None


class ServiceStatus(BaseModel):
    """Status information for a single credential group."""

    group_id: str
    name: str
    status: str  # "configured" | "unconfigured" | "skipped" | "error"
    required: bool
    features_affected: list[str]


class SetupStatusResponse(BaseModel):
    """Full setup status response with all service statuses."""

    setup_complete: bool
    services: list[ServiceStatus]


# ── Dependencies ────────────────────────────────────────────────────────────


def require_localhost(request: Request) -> bool:
    """Reject requests not from loopback address.

    Setup endpoints are localhost-only for security — credentials
    should never be submitted over a network connection.
    (Requirement 5.5)
    """
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Setup endpoints are only accessible from localhost",
        )
    return True


def _get_setup_service() -> SetupService:
    """Create and return a SetupService instance.

    Uses the repository root (two levels up from backend-gateway/app/)
    to locate .env files and the service registry JSON.
    """
    repo_root = Path(__file__).resolve().parents[3]
    credential_store = CredentialStore(repo_root)
    registry_path = repo_root / "data" / "service_registry.json"
    service_registry = ServiceRegistry(registry_path)
    return SetupService(credential_store, service_registry)


def get_setup_service() -> SetupService:
    """Dependency injection for SetupService."""
    return _get_setup_service()


# ── Setup Endpoints ─────────────────────────────────────────────────────────


@router.get("/setup/status", response_model=SetupStatusResponse)
async def get_setup_status(
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> SetupStatusResponse:
    """Return current setup state with all service statuses.

    Returns the setup_complete flag and a list of all credential
    groups with their current configuration status.
    """
    status = service.get_status()
    return SetupStatusResponse(
        setup_complete=status.setup_complete,
        services=[
            ServiceStatus(
                group_id=s.group_id,
                name=s.name,
                status=s.status,
                required=s.required,
                features_affected=s.features_affected,
            )
            for s in status.services
        ],
    )


@router.post("/setup/credentials/{group_id}")
async def submit_credentials(
    group_id: str,
    body: CredentialSubmission,
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> dict:
    """Accept and validate credentials for a credential group.

    Validates format using regex patterns, writes to the appropriate
    .env file, and updates the service registry status.
    (Requirements 5.5, 5.6)
    """
    try:
        await service.submit_credentials(group_id, body.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Hot-reload the feature gate so route handlers immediately see the new state
    # (Requirement 8.3, 8.4)
    reload_registry()

    return {"status": "ok", "group_id": group_id}


@router.post("/setup/test/{group_id}", response_model=TestResult)
async def test_connection(
    group_id: str,
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> TestResult:
    """Trigger a connection test for a credential group.

    Reads stored credentials and probes the external service to
    verify they are valid and the service is reachable.
    (Requirement 6.1)
    """
    result = await service.test_connection(group_id)
    return TestResult(
        success=result.success,
        response_time_ms=result.response_time_ms,
        error=result.error,
        suggestion=result.suggestion,
    )


@router.post("/setup/skip/{group_id}")
async def skip_group(
    group_id: str,
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> dict:
    """Mark a credential group as skipped.

    Used when the user clicks "Skip for now" on an optional group.
    The group can be configured later from /settings/integrations.
    """
    try:
        await service.skip_group(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "ok", "group_id": group_id, "action": "skipped"}


@router.post("/setup/complete")
async def complete_setup(
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> dict:
    """Finalize the setup wizard.

    Marks setup as complete in the service registry with a timestamp.
    Called when the user finishes the wizard (clicks "Complete Setup").
    """
    await service.complete_setup()
    return {"status": "ok", "setup_complete": True}


@router.post("/setup/reset/{group_id}")
async def reset_group(
    group_id: str,
    _localhost: bool = Depends(require_localhost),
    service: SetupService = Depends(get_setup_service),
) -> dict:
    """Clear credentials and reset a group to unconfigured state.

    Removes stored credentials from the .env file and marks the
    group as UNCONFIGURED in the service registry.
    """
    try:
        await service.reset_group(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Hot-reload the feature gate so route handlers immediately see the reset state
    # (Requirement 8.3, 8.4)
    reload_registry()

    return {"status": "ok", "group_id": group_id, "action": "reset"}


# ── Health Endpoint ─────────────────────────────────────────────────────────


@router.get("/health/services", response_model=SetupStatusResponse)
async def get_service_health(
    service: SetupService = Depends(get_setup_service),
) -> SetupStatusResponse:
    """Return service health status for all credential groups.

    This endpoint is accessible without authentication or localhost
    restriction — it exposes only configuration status (not credential
    values) for use by the frontend's graceful degradation logic.
    (Requirement 4.6)
    """
    status = service.get_status()
    return SetupStatusResponse(
        setup_complete=status.setup_complete,
        services=[
            ServiceStatus(
                group_id=s.group_id,
                name=s.name,
                status=s.status,
                required=s.required,
                features_affected=s.features_affected,
            )
            for s in status.services
        ],
    )
