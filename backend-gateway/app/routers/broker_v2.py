"""Broker management API router (v2).

Endpoints for connecting/disconnecting brokers, viewing connection status,
and setting primary/backup broker preferences.

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 17.2, 17.7
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class ConnectBrokerRequest(BaseModel):
    broker_name: str = Field(..., description="Broker to connect (shoonya, angelone, kite, groww)")
    credentials: dict = Field(default_factory=dict, description="OAuth or API credentials for the broker")


class SetPrimaryBrokerRequest(BaseModel):
    broker_name: str = Field(..., description="Broker name to set as primary")


class SetBackupBrokerRequest(BaseModel):
    broker_name: str = Field(..., description="Broker name to set as backup")


class BrokerStatusItem(BaseModel):
    name: str
    status: str  # connected, disconnected, token_expired


class BrokerStatusResponse(BaseModel):
    brokers: list[BrokerStatusItem]


class BrokerPreferenceResponse(BaseModel):
    primary_broker: Optional[str] = None
    backup_broker: Optional[str] = None


class ConnectBrokerResponse(BaseModel):
    broker_name: str
    status: str
    message: str


class MessageResponse(BaseModel):
    message: str


# ── Supported brokers ────────────────────────────────────────────────────────

SUPPORTED_BROKERS = {"shoonya", "angelone", "kite", "groww"}


# ── Service layer abstraction ────────────────────────────────────────────────


class BrokerManagementService:
    """Thin service layer wrapping BrokerRouter for the API gateway.

    In production, this delegates to the BrokerRouter from
    src/ingestion/broker_router.py. For testability, methods are async
    and can be mocked.
    """

    async def connect_broker(self, user_id: str, broker_name: str, credentials: dict) -> dict:
        """Initiate OAuth flow / connect a broker for the user.

        Returns dict with keys: broker_name, status, message.
        """
        raise NotImplementedError("Production implementation required")

    async def disconnect_broker(self, user_id: str, broker_name: str) -> bool:
        """Disconnect a broker for the user. Returns True on success."""
        raise NotImplementedError("Production implementation required")

    async def get_all_statuses(self, user_id: str) -> list[dict]:
        """Return connection status for all supported brokers.

        Each dict has keys: name, status (connected/disconnected/token_expired).
        """
        raise NotImplementedError("Production implementation required")

    async def set_primary_broker(self, user_id: str, broker_name: str) -> dict:
        """Set the user's primary broker. Returns preference dict."""
        raise NotImplementedError("Production implementation required")

    async def set_backup_broker(self, user_id: str, broker_name: str) -> dict:
        """Set the user's backup broker. Returns preference dict."""
        raise NotImplementedError("Production implementation required")

    async def get_preference(self, user_id: str) -> dict:
        """Return user's current broker preference (primary + backup)."""
        raise NotImplementedError("Production implementation required")


# ── Service dependency ───────────────────────────────────────────────────────

_broker_service: Optional[BrokerManagementService] = None


def set_broker_service(svc: BrokerManagementService) -> None:
    """Called at app startup to inject the BrokerManagementService instance."""
    global _broker_service
    _broker_service = svc


def get_broker_service() -> BrokerManagementService:
    if _broker_service is None:
        raise HTTPException(status_code=503, detail="Broker service not initialized")
    return _broker_service


# ── Validation helper ────────────────────────────────────────────────────────


def _validate_broker_name(broker_name: str) -> str:
    """Normalize and validate broker name. Raises HTTPException on invalid."""
    name = broker_name.strip().lower()
    if name not in SUPPORTED_BROKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported broker '{broker_name}'. Must be one of: {', '.join(sorted(SUPPORTED_BROKERS))}",
        )
    return name


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/brokers/connect", response_model=ConnectBrokerResponse, status_code=200)
async def connect_broker(
    req: ConnectBrokerRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BrokerManagementService = Depends(get_broker_service),
):
    """Connect a broker (initiate OAuth flow).

    Requirements: 17.2, 17.7
    """
    name = _validate_broker_name(req.broker_name)
    try:
        result = await svc.connect_broker(user_id, name, req.credentials)
        logger.info("BROKER_EVENT connect user=%s broker=%s", user_id, name)
        return ConnectBrokerResponse(
            broker_name=result.get("broker_name", name),
            status=result.get("status", "connected"),
            message=result.get("message", f"Broker '{name}' connected successfully"),
        )
    except ValueError as exc:
        logger.warning("BROKER_EVENT connect_failed user=%s broker=%s reason=%s", user_id, name, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/brokers/{name}/disconnect", response_model=MessageResponse)
async def disconnect_broker(
    name: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BrokerManagementService = Depends(get_broker_service),
):
    """Disconnect a broker.

    Requirements: 17.2, 17.7
    """
    broker_name = _validate_broker_name(name)
    try:
        await svc.disconnect_broker(user_id, broker_name)
        logger.info("BROKER_EVENT disconnect user=%s broker=%s", user_id, broker_name)
        return MessageResponse(message=f"Broker '{broker_name}' disconnected successfully")
    except ValueError as exc:
        logger.warning("BROKER_EVENT disconnect_failed user=%s broker=%s reason=%s", user_id, broker_name, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/brokers/status", response_model=BrokerStatusResponse)
async def get_broker_status(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BrokerManagementService = Depends(get_broker_service),
):
    """Get connection status of all brokers.

    Requirements: 17.7
    """
    try:
        statuses = await svc.get_all_statuses(user_id)
        items = [BrokerStatusItem(name=s["name"], status=s["status"]) for s in statuses]
        return BrokerStatusResponse(brokers=items)
    except ValueError as exc:
        logger.warning("BROKER_EVENT status_failed user=%s reason=%s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/brokers/primary", response_model=BrokerPreferenceResponse)
async def set_primary_broker(
    req: SetPrimaryBrokerRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BrokerManagementService = Depends(get_broker_service),
):
    """Set user's primary broker.

    Requirements: 17.2
    """
    name = _validate_broker_name(req.broker_name)
    try:
        pref = await svc.set_primary_broker(user_id, name)
        logger.info("BROKER_EVENT set_primary user=%s broker=%s", user_id, name)
        return BrokerPreferenceResponse(
            primary_broker=pref.get("primary_broker"),
            backup_broker=pref.get("backup_broker"),
        )
    except ValueError as exc:
        logger.warning("BROKER_EVENT set_primary_failed user=%s reason=%s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/brokers/backup", response_model=BrokerPreferenceResponse)
async def set_backup_broker(
    req: SetBackupBrokerRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BrokerManagementService = Depends(get_broker_service),
):
    """Set user's backup broker.

    Requirements: 17.2
    """
    name = _validate_broker_name(req.broker_name)
    try:
        pref = await svc.set_backup_broker(user_id, name)
        logger.info("BROKER_EVENT set_backup user=%s broker=%s", user_id, name)
        return BrokerPreferenceResponse(
            primary_broker=pref.get("primary_broker"),
            backup_broker=pref.get("backup_broker"),
        )
    except ValueError as exc:
        logger.warning("BROKER_EVENT set_backup_failed user=%s reason=%s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
