"""Redis-based sliding window rate limiter for FastAPI.

Uses Redis sorted sets with timestamps as scores to implement a sliding
window rate limit per user. Read endpoints (GET/HEAD/OPTIONS) allow 100
requests per minute; write endpoints (POST/PUT/PATCH/DELETE) allow 30
requests per minute.

Redis keys: ``rate:{user_id}:read`` and ``rate:{user_id}:write``

Requirements: 30.1, 30.2
"""

import logging
import time
import uuid
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

READ_LIMIT = 100  # requests per window
WRITE_LIMIT = 30  # requests per window
WINDOW_SECONDS = 60  # sliding window size


# ── Core rate-check function (testable without middleware) ───────────────────


async def check_rate_limit(
    redis,
    user_id: str,
    endpoint_type: str,
    now: Optional[float] = None,
) -> tuple[bool, int]:
    """Check and record a request against the sliding window rate limit.

    Args:
        redis: An ``redis.asyncio.Redis`` instance.
        user_id: Authenticated user identifier.
        endpoint_type: ``"read"`` or ``"write"``.
        now: Current timestamp (epoch seconds). Defaults to ``time.time()``.

    Returns:
        A tuple ``(allowed, retry_after)`` where *allowed* is ``True`` when
        the request is within limits and *retry_after* is the number of
        seconds the client should wait before retrying (0 when allowed).
    """
    if now is None:
        now = time.time()

    limit = READ_LIMIT if endpoint_type == "read" else WRITE_LIMIT
    key = f"rate:{user_id}:{endpoint_type}"
    window_start = now - WINDOW_SECONDS

    # Unique member so each request gets its own entry
    member = f"{now}:{uuid.uuid4().hex[:8]}"

    pipe = redis.pipeline()
    # 1. Remove entries older than the window
    pipe.zremrangebyscore(key, "-inf", window_start)
    # 2. Add current request
    pipe.zadd(key, {member: now})
    # 3. Count entries in the window
    pipe.zcard(key)
    # 4. Get the oldest entry score (to compute retry-after)
    pipe.zrange(key, 0, 0, withscores=True)
    # 5. Set TTL so keys auto-expire
    pipe.expire(key, WINDOW_SECONDS + 1)

    results = await pipe.execute()
    count = results[2]
    oldest_entries = results[3]

    if count > limit:
        # Over limit — compute retry-after from oldest entry
        if oldest_entries:
            oldest_score = oldest_entries[0][1]
            retry_after = max(1, int((oldest_score + WINDOW_SECONDS) - now) + 1)
        else:
            retry_after = WINDOW_SECONDS
        # Remove the entry we just added since the request is rejected
        await redis.zrem(key, member)
        return False, retry_after

    return True, 0


def classify_method(method: str) -> str:
    """Return ``"read"`` or ``"write"`` based on HTTP method."""
    return "read" if method.upper() in READ_METHODS else "write"


# ── FastAPI Middleware ───────────────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-user sliding window rate limits.

    Requires ``request.state.user_id`` to be set by an upstream auth
    middleware. Unauthenticated requests (no user_id) are passed through
    without rate limiting.

    The middleware needs an ``redis.asyncio.Redis`` instance passed at
    construction time.
    """

    def __init__(self, app, redis_client=None):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        # Skip if no Redis client configured
        if self.redis is None:
            return await call_next(request)

        # Extract user_id — set by auth middleware on request.state
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            # Unauthenticated requests are not rate-limited
            return await call_next(request)

        endpoint_type = classify_method(request.method)
        allowed, retry_after = await check_rate_limit(
            self.redis, user_id, endpoint_type
        )

        if not allowed:
            logger.warning(
                "Rate limit exceeded: user=%s type=%s retry_after=%ds",
                user_id,
                endpoint_type,
                retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
