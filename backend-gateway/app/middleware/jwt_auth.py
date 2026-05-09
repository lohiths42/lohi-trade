"""JWT authentication middleware for FastAPI.

Sets ``request.state.user_id`` on every authenticated request so that
downstream middleware (RequestLoggingMiddleware, RateLimitMiddleware) and
RLS context can use it.

For unauthenticated requests (no Authorization header or invalid token),
``request.state.user_id`` is left unset — individual route dependencies
(``get_current_user_id``, ``require_role``) handle 401 enforcement.

Requirements: 29.5, 12.6
"""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extract JWT Bearer token and set user context on every request.

    This middleware does NOT reject unauthenticated requests — that is
    handled by per-route dependencies. It only sets ``request.state.user_id``
    when a valid token is present, enabling:

    - RequestLoggingMiddleware to log the user_id
    - RateLimitMiddleware to enforce per-user limits
    - RLS context (``app.state.current_user_id``) for database queries
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        user_id = _extract_user_id(request)
        if user_id:
            request.state.user_id = user_id
            # Set app-level RLS context for database queries
            request.app.state.current_user_id = user_id

        response = await call_next(request)

        # Clean up app-level state after request
        if user_id:
            request.app.state.current_user_id = None

        return response


def _extract_user_id(request: Request) -> Optional[str]:
    """Extract user_id from JWT Bearer token without raising errors.

    OSS single-user mode emits tokens via /api/auth/login (v1 auth_service).
    Multi-user Pro mode emits tokens via /api/v2/auth/login (v2 account_service).
    Both schemes use JWT — try v2 first (superset), fall back to v1.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]

    # Try v2 (multi-user) first
    try:
        from app.services.account_service import verify_access_token

        payload = verify_access_token(token)
        if payload and "sub" in payload:
            return payload["sub"]
    except Exception:
        pass

    # Fall back to v1 (single-user OSS) — tokens issued by auth_service.create_token
    try:
        from app.services.auth_service import verify_token as v1_verify_token

        payload = v1_verify_token(token)
        if payload and "sub" in payload:
            return payload["sub"]
    except Exception:
        pass

    return None
