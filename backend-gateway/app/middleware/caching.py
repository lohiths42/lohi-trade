"""HTTP caching middleware for static/infrequently-changing API responses.

Adds Cache-Control and ETag headers to responses for stock universe and
sector data endpoints. These datasets change at most once daily (7 AM IST
catalog refresh), so aggressive caching is safe.

Requirements: 34.12
"""

import hashlib
import logging
from typing import Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Path prefixes that serve static/infrequently-changing data
CACHEABLE_PREFIXES: Set[str] = {
    "/api/v2/stocks",
    "/api/v2/sectors",
}

# Cache-Control: public data refreshed daily, allow 5-minute browser cache
# and 1-hour shared (CDN/proxy) cache with stale-while-revalidate for
# seamless background refresh.
CACHE_CONTROL_VALUE = "public, max-age=300, s-maxage=3600, stale-while-revalidate=60"


def _is_cacheable_path(path: str) -> bool:
    """Return True if the request path matches a cacheable prefix."""
    for prefix in CACHEABLE_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _compute_etag(body: bytes) -> str:
    """Compute a weak ETag from the response body using MD5."""
    digest = hashlib.md5(body).hexdigest()
    return f'W/"{digest}"'


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    """Add Cache-Control and ETag headers to cacheable GET responses.

    Only applies to GET requests matching ``CACHEABLE_PREFIXES`` that
    return a 2xx status code. Supports conditional requests via
    ``If-None-Match`` → 304 Not Modified.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only cache GET requests
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path

        if not _is_cacheable_path(path):
            return await call_next(request)

        response = await call_next(request)

        # Only cache successful responses
        if response.status_code < 200 or response.status_code >= 300:
            return response

        # Read the response body to compute ETag
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode("utf-8")
            else:
                body += chunk

        etag = _compute_etag(body)

        # Check If-None-Match for conditional request
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": CACHE_CONTROL_VALUE,
                },
            )

        # Return response with caching headers
        return Response(
            content=body,
            status_code=response.status_code,
            headers={
                **dict(response.headers),
                "Cache-Control": CACHE_CONTROL_VALUE,
                "ETag": etag,
            },
            media_type=response.media_type,
        )
