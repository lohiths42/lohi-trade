"""Role-based access control (RBAC) middleware for FastAPI.

Provides a `require_role(*roles)` dependency that verifies the authenticated
user's JWT contains one of the allowed roles. Roles: ADMIN, TRADER, VIEWER.

Usage:
    @router.get("/admin/users")
    async def list_users(payload: dict = Depends(require_role("ADMIN"))):
        ...

Requirements: 29.3, 29.6
"""

import logging
from typing import Callable

from fastapi import Depends, HTTPException

from app.routers.auth_v2 import get_current_user_payload

logger = logging.getLogger(__name__)

VALID_ROLES = {"ADMIN", "TRADER", "VIEWER"}


def require_role(*roles: str) -> Callable:
    """Return a FastAPI dependency that enforces role-based access.

    Args:
        *roles: One or more role strings (ADMIN, TRADER, VIEWER).

    Returns:
        A dependency function that returns the full JWT payload if the
        user's role is in the allowed set, or raises HTTP 403.
    """
    allowed = set(roles)
    invalid = allowed - VALID_ROLES
    if invalid:
        raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")

    async def _check_role(
        payload: dict = Depends(get_current_user_payload),
    ) -> dict:
        user_role_raw = payload.get("role", "")
        # Normalize case so v1 OSS tokens (role="admin") satisfy v2 checks
        # that declare roles as "ADMIN" etc.
        user_role = str(user_role_raw).upper()
        if user_role not in allowed:
            logger.warning(
                "RBAC denied: user=%s role=%s required=%s endpoint accessed",
                payload.get("sub"),
                user_role,
                allowed,
            )
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {', '.join(sorted(allowed))}",
            )
        return payload

    return _check_role
