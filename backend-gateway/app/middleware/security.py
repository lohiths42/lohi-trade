"""Security middleware for the FastAPI gateway.

Provides:
- InputSanitizationMiddleware — blocks requests containing SQL injection,
  XSS script tags, or command injection patterns (returns 400).
- RequestLoggingMiddleware — logs user_id, endpoint, method, status code,
  and response time for every request.
- CORS — configured in main.py via FastAPI's CORSMiddleware with origins
  loaded from the ``CORS_ORIGINS`` environment variable.
- Response compression — GZipMiddleware from Starlette with
  ``minimum_size=1024`` (1 KB).

Requirements: 30.3, 30.4, 30.5, 30.7, 34.7
"""

import logging
import re
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ── Dangerous input patterns ────────────────────────────────────────────────

# SQL injection patterns (case-insensitive)
SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|UNION)\b\s)", re.IGNORECASE
    ),
    re.compile(r"(--|;)\s*$", re.MULTILINE),
    re.compile(r"'\s*(OR|AND)\s+'", re.IGNORECASE),
    re.compile(r"'\s*(OR|AND)\s+\d+\s*=\s*\d+", re.IGNORECASE),
    re.compile(r"1\s*=\s*1"),
]

# XSS patterns
XSS_PATTERNS: list[re.Pattern] = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"<\s*iframe", re.IGNORECASE),
]

# Command injection patterns
# NOTE: We intentionally avoid matching bare `&` because it appears in
# legitimate values like sector names ("Banking & Finance").  Instead we
# match shell-specific sequences: `&&`, `||`, back-ticks, `$(`, and `;`.
COMMAND_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(&&|\|\||[;`]|\$\()"),
    re.compile(r"\b(rm|cat|ls|wget|curl|bash|sh|chmod|chown|sudo|eval)\b", re.IGNORECASE),
]


# ── Pure detection helpers (testable without middleware) ─────────────────────


def contains_sql_injection(text: str) -> bool:
    """Return ``True`` if *text* matches any SQL injection pattern."""
    for pattern in SQL_INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def contains_xss(text: str) -> bool:
    """Return ``True`` if *text* matches any XSS pattern."""
    for pattern in XSS_PATTERNS:
        if pattern.search(text):
            return True
    return False


def contains_command_injection(text: str) -> bool:
    """Return ``True`` if *text* matches any command injection pattern."""
    for pattern in COMMAND_INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def is_suspicious(text: str) -> Optional[str]:
    """Check *text* for all attack vectors.

    Returns a short reason string if suspicious, ``None`` otherwise.
    """
    if contains_sql_injection(text):
        return "sql_injection"
    if contains_xss(text):
        return "xss"
    if contains_command_injection(text):
        return "command_injection"
    return None


# ── InputSanitizationMiddleware ─────────────────────────────────────────────


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body or query parameters contain attack patterns.

    Returns HTTP 400 with a JSON body ``{"detail": "Suspicious input detected"}``
    when a match is found.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check query parameters (decoded values)
        for value in request.query_params.values():
            reason = is_suspicious(value)
            if reason:
                logger.warning(
                    "Blocked suspicious query param: reason=%s path=%s",
                    reason,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Suspicious input detected"},
                )

        # Check request body for methods that carry a body
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body_text = body_bytes.decode("utf-8", errors="ignore")
                    reason = is_suspicious(body_text)
                    if reason:
                        logger.warning(
                            "Blocked suspicious body: reason=%s path=%s",
                            reason,
                            request.url.path,
                        )
                        return JSONResponse(
                            status_code=400,
                            content={"detail": "Suspicious input detected"},
                        )
            except Exception:
                pass  # If we can't read the body, let it through

        return await call_next(request)


# ── RequestLoggingMiddleware ────────────────────────────────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with user_id, endpoint, method, status, and response time."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.time()
        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000, 2)

        user_id = getattr(request.state, "user_id", "anonymous")

        logger.info(
            "request: user_id=%s method=%s path=%s status=%s response_time_ms=%.2f",
            user_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        return response
