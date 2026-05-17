"""Admin endpoints for user management.

Provides ADMIN-only endpoints for account deactivation/reactivation.
Deactivation prevents login and halts all active trading for the user.

Requirements: 29.6
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.middleware.rbac import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────


class UserStatusResponse(BaseModel):
    user_id: str
    is_active: bool
    message: str


# ── Admin service dependency ─────────────────────────────────────────────────

_admin_db_pool = None


def set_admin_db_pool(pool) -> None:
    """Called at app startup to inject the asyncpg pool."""
    global _admin_db_pool
    _admin_db_pool = pool


def get_admin_db_pool():
    """FastAPI dependency to retrieve the DB pool."""
    if _admin_db_pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return _admin_db_pool


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.put(
    "/admin/users/{user_id}/deactivate",
    response_model=UserStatusResponse,
)
async def deactivate_user(
    user_id: str,
    payload: dict = Depends(require_role("ADMIN")),
    pool=Depends(get_admin_db_pool),
):
    """Deactivate a user account. Prevents login and halts trading.

    Only ADMIN users can deactivate accounts. An admin cannot deactivate
    their own account.
    """
    admin_id = payload.get("sub")
    if admin_id == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate your own account",
        )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, is_active FROM users WHERE id = $1::uuid",
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        if not row["is_active"]:
            return UserStatusResponse(
                user_id=user_id,
                is_active=False,
                message="User is already deactivated",
            )

        await conn.execute(
            "UPDATE users SET is_active = FALSE, updated_at = NOW() WHERE id = $1::uuid",
            user_id,
        )

        # Invalidate all refresh tokens so the user can't get new access tokens
        await conn.execute(
            "DELETE FROM refresh_tokens WHERE user_id = $1::uuid",
            user_id,
        )

    logger.info(
        "ADMIN_EVENT user_deactivated admin=%s target_user=%s",
        admin_id,
        user_id,
    )
    return UserStatusResponse(
        user_id=user_id,
        is_active=False,
        message="User account deactivated. Login prevented and trading halted.",
    )


@router.put(
    "/admin/users/{user_id}/activate",
    response_model=UserStatusResponse,
)
async def activate_user(
    user_id: str,
    payload: dict = Depends(require_role("ADMIN")),
    pool=Depends(get_admin_db_pool),
):
    """Reactivate a previously deactivated user account.

    Only ADMIN users can reactivate accounts.
    """
    admin_id = payload.get("sub")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, is_active FROM users WHERE id = $1::uuid",
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        if row["is_active"]:
            return UserStatusResponse(
                user_id=user_id,
                is_active=True,
                message="User is already active",
            )

        await conn.execute(
            "UPDATE users SET is_active = TRUE, updated_at = NOW() WHERE id = $1::uuid",
            user_id,
        )

    logger.info(
        "ADMIN_EVENT user_activated admin=%s target_user=%s",
        admin_id,
        user_id,
    )
    return UserStatusResponse(
        user_id=user_id,
        is_active=True,
        message="User account reactivated. Login and trading restored.",
    )
