"""User profile endpoints.

Provides endpoints for managing user profile flags such as the onboarding
status (is_onboarded).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth_v2 import get_current_user_id, get_account_service
from app.services.account_service import AccountService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class UpdateOnboardedRequest(BaseModel):
    is_onboarded: bool = Field(..., description="Set the user's onboarded flag")


class UpdateOnboardedResponse(BaseModel):
    user_id: str
    is_onboarded: bool
    message: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.put("/users/onboarded", response_model=UpdateOnboardedResponse)
async def update_onboarded(
    req: UpdateOnboardedRequest,
    user_id: str = Depends(get_current_user_id),
    svc: AccountService = Depends(get_account_service),
):
    """Update the authenticated user's is_onboarded flag.

    Called when the user completes or skips the onboarding walkthrough
    (Req 33.6), or when "Replay Tutorial" resets the flag (Req 33.7).
    """
    try:
        async with svc._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET is_onboarded = $1, updated_at = NOW() WHERE id = $2::uuid",
                req.is_onboarded,
                user_id,
            )
            # asyncpg returns a status string like "UPDATE 1"
            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="User not found")

        logger.info(
            "ONBOARDING_EVENT user_id=%s is_onboarded=%s",
            user_id,
            req.is_onboarded,
        )
        return UpdateOnboardedResponse(
            user_id=user_id,
            is_onboarded=req.is_onboarded,
            message="Onboarding status updated",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update onboarded flag: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update onboarding status")
