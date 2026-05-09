"""Watchlist management API router.

Endpoints for creating, listing, updating, deleting watchlists,
adding/removing securities, and fetching pre-built watchlists.

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 9.4, 9.7
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.watchlist_service import (
    WatchlistError,
    WatchlistService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., description="Watchlist name")


class RenameWatchlistRequest(BaseModel):
    name: str = Field(..., description="New watchlist name")


class AddSecurityRequest(BaseModel):
    symbol: str = Field(..., description="Security symbol to add")


class WatchlistItem(BaseModel):
    id: Optional[str] = None
    name: str
    is_prebuilt: bool = False
    sort_order: int = 0
    created_at: Optional[str] = None


class WatchlistResponse(BaseModel):
    watchlist: WatchlistItem
    message: str


class WatchlistListResponse(BaseModel):
    watchlists: list[WatchlistItem]
    count: int


class SecurityPriceItem(BaseModel):
    symbol: str
    company_name: str = ""
    ltp: float = 0.0
    change_percent: float = 0.0
    volume: int = 0
    sort_order: int = 0


class WatchlistDetailResponse(BaseModel):
    id: Optional[str] = None
    name: str
    is_prebuilt: bool = False
    securities: list[SecurityPriceItem]


class WatchlistSecurityResponse(BaseModel):
    id: Optional[str] = None
    watchlist_id: Optional[str] = None
    symbol: str
    sort_order: int = 0
    message: str


class MessageResponse(BaseModel):
    message: str


# ── Service dependency ───────────────────────────────────────────────────────

_watchlist_service: Optional[WatchlistService] = None


def set_watchlist_service(svc: WatchlistService) -> None:
    """Called at app startup to inject the WatchlistService instance."""
    global _watchlist_service
    _watchlist_service = svc


def get_watchlist_service() -> WatchlistService:
    if _watchlist_service is None:
        raise HTTPException(status_code=503, detail="Watchlist service not initialized")
    return _watchlist_service


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/watchlists", response_model=WatchlistResponse, status_code=201)
async def create_watchlist(
    req: CreateWatchlistRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Create a new custom watchlist.

    Requirements: 9.4
    """
    try:
        wl = await svc.create_watchlist(user_id, req.name)
        logger.info("WATCHLIST_EVENT create user=%s name=%s", user_id, req.name)
        return WatchlistResponse(
            watchlist=WatchlistItem(
                id=wl.id,
                name=wl.name,
                is_prebuilt=wl.is_prebuilt,
                sort_order=wl.sort_order,
                created_at=wl.created_at.isoformat() if wl.created_at else None,
            ),
            message="Watchlist created successfully",
        )
    except WatchlistError as exc:
        logger.warning("WATCHLIST_EVENT create_failed user=%s reason=%s", user_id, exc.reason)
        raise HTTPException(status_code=400, detail=exc.message)


@router.get("/watchlists", response_model=WatchlistListResponse)
async def list_watchlists(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """List all watchlists for the authenticated user.

    Requirements: 9.4
    """
    watchlists = await svc.get_user_watchlists(user_id)
    items = [
        WatchlistItem(
            id=wl.id,
            name=wl.name,
            is_prebuilt=wl.is_prebuilt,
            sort_order=wl.sort_order,
            created_at=wl.created_at.isoformat() if wl.created_at else None,
        )
        for wl in watchlists
    ]
    return WatchlistListResponse(watchlists=items, count=len(items))


@router.get("/watchlists/prebuilt", response_model=WatchlistListResponse)
async def get_prebuilt_watchlists(
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Return pre-built watchlists (Nifty 50, Nifty Bank, etc.).

    Requirements: 9.7
    """
    watchlists = await svc.get_prebuilt_watchlists()
    items = [
        WatchlistItem(
            id=wl.id,
            name=wl.name,
            is_prebuilt=wl.is_prebuilt,
            sort_order=wl.sort_order,
            created_at=wl.created_at.isoformat() if wl.created_at else None,
        )
        for wl in watchlists
    ]
    return WatchlistListResponse(watchlists=items, count=len(items))


@router.get("/watchlists/{watchlist_id}", response_model=WatchlistDetailResponse)
async def get_watchlist(
    watchlist_id: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Get a watchlist with live price data for all securities.

    Requirements: 9.4
    """
    try:
        wl = await svc.get_watchlist_with_prices(user_id, watchlist_id)
        securities = [
            SecurityPriceItem(
                symbol=s.symbol,
                company_name=s.company_name,
                ltp=s.ltp,
                change_percent=s.change_percent,
                volume=s.volume,
                sort_order=s.sort_order,
            )
            for s in wl.securities
        ]
        return WatchlistDetailResponse(
            id=wl.id,
            name=wl.name,
            is_prebuilt=wl.is_prebuilt,
            securities=securities,
        )
    except WatchlistError as exc:
        logger.warning("WATCHLIST_EVENT get_failed id=%s reason=%s", watchlist_id, exc.reason)
        raise HTTPException(status_code=404, detail=exc.message)


@router.put("/watchlists/{watchlist_id}", response_model=WatchlistResponse)
async def rename_watchlist(
    watchlist_id: str,
    req: RenameWatchlistRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Rename an existing watchlist.

    Requirements: 9.4
    """
    try:
        wl = await svc.rename_watchlist(user_id, watchlist_id, req.name)
        logger.info("WATCHLIST_EVENT rename user=%s id=%s", user_id, watchlist_id)
        return WatchlistResponse(
            watchlist=WatchlistItem(
                id=wl.id,
                name=wl.name,
                is_prebuilt=wl.is_prebuilt,
                sort_order=wl.sort_order,
                created_at=wl.created_at.isoformat() if wl.created_at else None,
            ),
            message="Watchlist renamed successfully",
        )
    except WatchlistError as exc:
        logger.warning("WATCHLIST_EVENT rename_failed id=%s reason=%s", watchlist_id, exc.reason)
        raise HTTPException(status_code=400, detail=exc.message)


@router.delete("/watchlists/{watchlist_id}", response_model=MessageResponse)
async def delete_watchlist(
    watchlist_id: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Delete a custom watchlist.

    Requirements: 9.4
    """
    try:
        await svc.delete_watchlist(user_id, watchlist_id)
        logger.info("WATCHLIST_EVENT delete user=%s id=%s", user_id, watchlist_id)
        return MessageResponse(message="Watchlist deleted successfully")
    except WatchlistError as exc:
        logger.warning("WATCHLIST_EVENT delete_failed id=%s reason=%s", watchlist_id, exc.reason)
        raise HTTPException(status_code=400, detail=exc.message)


@router.post(
    "/watchlists/{watchlist_id}/securities",
    response_model=WatchlistSecurityResponse,
    status_code=201,
)
async def add_security(
    watchlist_id: str,
    req: AddSecurityRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Add a security to a watchlist.

    Requirements: 9.4
    """
    try:
        item = await svc.add_security(user_id, watchlist_id, req.symbol)
        logger.info(
            "WATCHLIST_EVENT add_security user=%s watchlist=%s symbol=%s",
            user_id, watchlist_id, req.symbol,
        )
        return WatchlistSecurityResponse(
            id=item.id,
            watchlist_id=item.watchlist_id,
            symbol=item.symbol,
            sort_order=item.sort_order,
            message=f"Security '{item.symbol}' added to watchlist",
        )
    except WatchlistError as exc:
        logger.warning(
            "WATCHLIST_EVENT add_security_failed watchlist=%s reason=%s",
            watchlist_id, exc.reason,
        )
        raise HTTPException(status_code=400, detail=exc.message)


@router.delete(
    "/watchlists/{watchlist_id}/securities/{symbol}",
    response_model=MessageResponse,
)
async def remove_security(
    watchlist_id: str,
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: WatchlistService = Depends(get_watchlist_service),
):
    """Remove a security from a watchlist.

    Requirements: 9.4
    """
    try:
        await svc.remove_security(user_id, watchlist_id, symbol)
        logger.info(
            "WATCHLIST_EVENT remove_security user=%s watchlist=%s symbol=%s",
            user_id, watchlist_id, symbol,
        )
        return MessageResponse(message=f"Security '{symbol.upper()}' removed from watchlist")
    except WatchlistError as exc:
        logger.warning(
            "WATCHLIST_EVENT remove_security_failed watchlist=%s reason=%s",
            watchlist_id, exc.reason,
        )
        raise HTTPException(status_code=400, detail=exc.message)
