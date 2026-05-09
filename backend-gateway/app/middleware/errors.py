"""Structured error envelope for the Lohi-Research gateway surface.

Implements the design §5.3 error envelope used by the
``/api/v2/research/*`` router and — via :class:`ResearchExceptionHandler`
— also wired as a FastAPI exception handler so uncaught provider
exceptions surface through the same envelope instead of FastAPI's
default ``{"detail": "..."}`` shape.

Envelope shape
--------------
Every error response emitted by the research surface has the shape::

    {
      "error": {
        "code":     "PROVIDER_AUTH_FAILED",
        "message":  "human-readable tail",
        "provider": "nvidia_nim",
        "model":    "meta/llama-3.1-70b-instruct"
      }
    }

The ``provider`` / ``model`` keys are omitted when they do not apply
(for example, ``CONFIG_MISSING`` errors don't necessarily carry a
provider). Unknown fields are never silently dropped — every field
passed to :func:`build_error_envelope` is echoed into the envelope
verbatim, so downstream callers can attach e.g. ``phase`` for
``LATENCY_BUDGET_EXCEEDED`` events without a contract change.

Exception → code mapping (design §5.3, Task 16.4)
-------------------------------------------------

``ProviderAuthError``
    From :mod:`src.research.providers.errors`. Maps to
    :data:`ERROR_CODE_PROVIDER_AUTH_FAILED` and copies the
    exception's ``provider`` and ``model`` onto the envelope.

``ProviderTimeout`` — currently signalled via :class:`asyncio.TimeoutError`
    raised from inside a provider adapter's ``complete``/``stream``.
    The mapper inspects the exception attributes (``provider``,
    ``model``) and falls back to the ``provider``/``model`` bound on
    the route call-site via ``ErrorContext`` when the exception
    itself does not carry them. Maps to
    :data:`ERROR_CODE_PROVIDER_TIMEOUT`.

``ConfigMissingError`` (lightweight custom exception defined below)
    Raised by the router when a required config key is absent. Maps
    to :data:`ERROR_CODE_CONFIG_MISSING`.

``LatencyBudgetExceededError`` (lightweight custom exception defined below)
    Raised by helpers that want to surface a latency-budget
    exceedance as a REST error — mirrors the Socket.IO event
    ``research:latency_budget_exceeded`` (design §5.2).

Anything else propagates through FastAPI's default handlers. The
router's per-endpoint ``try`` blocks catch known exceptions and
return a :class:`starlette.responses.JSONResponse` built from this
module, and :class:`ResearchExceptionHandler` provides a safety net
for any code path that forgets to wrap a provider call.

Satisfies
---------
* Req 2.10 — structured error envelope with ``provider``, ``model``,
  ``error_code`` on auth failure; never silently falls back to
  another provider.
* Req 8.8 — missing-config surfaces through the same envelope the
  rest of the gateway uses.
* Req 13.1 — provider-timeout errors carry ``provider``, ``model``,
  ``attempt``, ``elapsed_ms``.
* Design §5.3 — canonical ``{"error": {...}}`` envelope shape.
* Design §14 — one single error-mapping module so the gateway has
  exactly one place that knows how to translate provider exceptions
  into HTTP responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final, Mapping, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from src.research.providers.errors import (
    ProviderAuthError,
    ProviderError,
    UnknownProviderError,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Error code constants (design §5.3)                                          #
# --------------------------------------------------------------------------- #


#: Provider rejected the configured credentials. Carries ``provider``,
#: ``model``. Never falls back silently to another provider (Req 2.10).
ERROR_CODE_PROVIDER_AUTH_FAILED: Final[str] = "PROVIDER_AUTH_FAILED"

#: Provider request timed out. Carries ``provider``, ``model``,
#: optionally ``attempt`` and ``elapsed_ms`` (Req 13.1).
ERROR_CODE_PROVIDER_TIMEOUT: Final[str] = "PROVIDER_TIMEOUT"

#: A required config key is missing (Req 7.6, Req 8.8). Carries the
#: offending key name on ``config_key``.
ERROR_CODE_CONFIG_MISSING: Final[str] = "CONFIG_MISSING"

#: A latency budget from Req 5.1–5.3 was exceeded. Carries ``phase``,
#: ``observed_ms``, ``budget_ms`` (design §5.2, Req 5.9).
ERROR_CODE_LATENCY_BUDGET_EXCEEDED: Final[str] = "LATENCY_BUDGET_EXCEEDED"

#: Catch-all for any other provider-layer exception that does not
#: have a dedicated code. Surfaced so callers still see the
#: ``{"error": {...}}`` envelope instead of a bare FastAPI 500.
ERROR_CODE_PROVIDER_ERROR: Final[str] = "PROVIDER_ERROR"

#: Config names a provider with no registered factory. Raised by the
#: provider registry (see :class:`UnknownProviderError`).
ERROR_CODE_UNKNOWN_PROVIDER: Final[str] = "UNKNOWN_PROVIDER"

#: Fallback when the mapper cannot categorise an exception at all.
#: Never carries ``provider``/``model`` since by definition we don't
#: know them.
ERROR_CODE_INTERNAL_ERROR: Final[str] = "INTERNAL_ERROR"


# --------------------------------------------------------------------------- #
# Lightweight custom exceptions (design §5.3)                                 #
# --------------------------------------------------------------------------- #


class ConfigMissingError(Exception):
    """Raised when a required research config key is missing (Req 8.8).

    The router raises this from endpoint handlers that need a key
    (e.g. ``research.providers.chat.api_key`` for ``POST /runs``) so
    the error envelope carries the specific key name the operator
    must set. Carrying the key name in structured form lets the
    health page render a "fix this in settings.yaml" hint without
    parsing a free-text message.
    """

    def __init__(self, config_key: str, message: str | None = None) -> None:
        self.config_key = config_key
        self.message = message or (
            f"Required research config key {config_key!r} is missing or empty. "
            f"Set it in config/settings.yaml or the corresponding env var."
        )
        super().__init__(self.message)


class LatencyBudgetExceededError(Exception):
    """Raised when a latency budget from Req 5.1–5.3 is exceeded.

    Mirrors the Socket.IO ``research:latency_budget_exceeded`` event
    (design §5.2) on the REST side: if an endpoint decides to return
    a hard error because a budget was blown (rare — most call sites
    just emit the event and return partial results), it raises this
    so the envelope carries the structured ``phase``, ``observed_ms``,
    ``budget_ms`` trio.
    """

    def __init__(
        self,
        phase: str,
        observed_ms: int,
        budget_ms: int,
        message: str | None = None,
    ) -> None:
        self.phase = phase
        self.observed_ms = observed_ms
        self.budget_ms = budget_ms
        self.message = message or (
            f"Latency budget exceeded in phase={phase!r}: "
            f"observed_ms={observed_ms}, budget_ms={budget_ms}"
        )
        super().__init__(self.message)


class ProviderTimeoutError(ProviderError):
    """Dedicated provider-timeout exception for use by adapters.

    Provider adapters that want to surface a timeout with full
    structured context (Req 13.1) can raise this directly. The
    module-level :func:`to_envelope` also translates a plain
    :class:`asyncio.TimeoutError` into the same envelope — but
    without ``attempt`` / ``elapsed_ms`` since those are unknown.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        attempt: int | None = None,
        elapsed_ms: int | None = None,
        message: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.attempt = attempt
        self.elapsed_ms = elapsed_ms
        self.message = message or (
            f"Provider timeout: {provider}/{model} "
            f"(attempt={attempt}, elapsed_ms={elapsed_ms})"
        )
        super().__init__(self.message)


# --------------------------------------------------------------------------- #
# Envelope builder                                                            #
# --------------------------------------------------------------------------- #


def build_error_envelope(
    code: str,
    message: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the canonical ``{"error": {...}}`` envelope (design §5.3).

    ``provider`` and ``model`` are only included when truthy so an
    error that truly has no provider context (e.g. ``CONFIG_MISSING``
    without a provider binding) doesn't emit confusing ``null``s.
    Any extra keyword arguments are merged into the inner dict —
    this is how ``phase``/``observed_ms``/``budget_ms`` end up on
    ``LATENCY_BUDGET_EXCEEDED`` envelopes and ``config_key`` ends up
    on ``CONFIG_MISSING`` envelopes.
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if provider:
        error["provider"] = provider
    if model:
        error["model"] = model
    for k, v in extra.items():
        if v is not None:
            error[k] = v
    return {"error": error}


# --------------------------------------------------------------------------- #
# Exception → envelope mapper                                                 #
# --------------------------------------------------------------------------- #


# HTTP status codes per error code. Chosen so existing client-side
# error handling (which keys off HTTP status) behaves sensibly even
# before it learns to look at ``error.code``. Values are conservative:
# upstream auth / timeout / config issues are all 502 Bad Gateway
# (we are the gateway); budget exceedances are 504 Gateway Timeout;
# unknown-provider / config-missing are 500 Internal Server Error
# because they indicate a deployment misconfiguration, not a
# client-side mistake.
_HTTP_STATUS_BY_CODE: Mapping[str, int] = {
    ERROR_CODE_PROVIDER_AUTH_FAILED: 502,
    ERROR_CODE_PROVIDER_TIMEOUT: 504,
    ERROR_CODE_PROVIDER_ERROR: 502,
    ERROR_CODE_UNKNOWN_PROVIDER: 500,
    ERROR_CODE_CONFIG_MISSING: 500,
    ERROR_CODE_LATENCY_BUDGET_EXCEEDED: 504,
    ERROR_CODE_INTERNAL_ERROR: 500,
}


def http_status_for(code: str) -> int:
    """Return the HTTP status code for a given research error code.

    Falls back to ``500`` when the code is unknown so every mapped
    error has a stable HTTP response.
    """
    return _HTTP_STATUS_BY_CODE.get(code, 500)


def to_envelope(
    exc: BaseException,
    *,
    default_provider: Optional[str] = None,
    default_model: Optional[str] = None,
) -> tuple[int, dict[str, Any]]:
    """Translate ``exc`` into ``(http_status, envelope_dict)``.

    The mapping order matches design §5.3:

    1. :class:`ProviderAuthError`          → ``PROVIDER_AUTH_FAILED``
    2. :class:`ProviderTimeoutError`       → ``PROVIDER_TIMEOUT``
    3. :class:`asyncio.TimeoutError`       → ``PROVIDER_TIMEOUT`` (best-effort)
    4. :class:`UnknownProviderError`       → ``UNKNOWN_PROVIDER``
    5. :class:`ConfigMissingError`         → ``CONFIG_MISSING``
    6. :class:`LatencyBudgetExceededError` → ``LATENCY_BUDGET_EXCEEDED``
    7. :class:`ProviderError` (base)       → ``PROVIDER_ERROR``
    8. everything else                     → ``INTERNAL_ERROR``

    ``default_provider`` / ``default_model`` supply provider context
    when the exception itself does not carry it — e.g. a bare
    :class:`asyncio.TimeoutError` raised out of an ``httpx.AsyncClient``
    call inside an adapter. The router passes these in from an
    :class:`ErrorContext` scoped to the active provider.
    """
    if isinstance(exc, ProviderAuthError):
        return (
            http_status_for(ERROR_CODE_PROVIDER_AUTH_FAILED),
            build_error_envelope(
                ERROR_CODE_PROVIDER_AUTH_FAILED,
                str(exc),
                provider=exc.provider,
                model=exc.model,
                error_code=exc.error_code,
            ),
        )

    if isinstance(exc, ProviderTimeoutError):
        return (
            http_status_for(ERROR_CODE_PROVIDER_TIMEOUT),
            build_error_envelope(
                ERROR_CODE_PROVIDER_TIMEOUT,
                str(exc),
                provider=exc.provider or default_provider,
                model=exc.model or default_model,
                attempt=exc.attempt,
                elapsed_ms=exc.elapsed_ms,
            ),
        )

    if isinstance(exc, asyncio.TimeoutError):
        # Raised out of ``httpx`` / ``aiohttp`` / ``asyncio.wait_for``
        # when a provider request blew its timeout. We know nothing
        # structured about it beyond what the route's ``ErrorContext``
        # tells us, so attribute the timeout to ``default_provider`` /
        # ``default_model``.
        return (
            http_status_for(ERROR_CODE_PROVIDER_TIMEOUT),
            build_error_envelope(
                ERROR_CODE_PROVIDER_TIMEOUT,
                "Provider request timed out.",
                provider=default_provider,
                model=default_model,
            ),
        )

    if isinstance(exc, UnknownProviderError):
        return (
            http_status_for(ERROR_CODE_UNKNOWN_PROVIDER),
            build_error_envelope(
                ERROR_CODE_UNKNOWN_PROVIDER,
                str(exc),
                kind=exc.kind,
                name=exc.name,
                registered=list(exc.registered),
            ),
        )

    if isinstance(exc, ConfigMissingError):
        return (
            http_status_for(ERROR_CODE_CONFIG_MISSING),
            build_error_envelope(
                ERROR_CODE_CONFIG_MISSING,
                exc.message,
                config_key=exc.config_key,
            ),
        )

    if isinstance(exc, LatencyBudgetExceededError):
        return (
            http_status_for(ERROR_CODE_LATENCY_BUDGET_EXCEEDED),
            build_error_envelope(
                ERROR_CODE_LATENCY_BUDGET_EXCEEDED,
                exc.message,
                phase=exc.phase,
                observed_ms=exc.observed_ms,
                budget_ms=exc.budget_ms,
            ),
        )

    if isinstance(exc, ProviderError):
        return (
            http_status_for(ERROR_CODE_PROVIDER_ERROR),
            build_error_envelope(
                ERROR_CODE_PROVIDER_ERROR,
                str(exc),
                provider=default_provider,
                model=default_model,
            ),
        )

    # Unknown exception — surface as an internal error but still keep
    # the envelope shape stable for clients.
    return (
        http_status_for(ERROR_CODE_INTERNAL_ERROR),
        build_error_envelope(
            ERROR_CODE_INTERNAL_ERROR,
            "An unexpected error occurred.",
        ),
    )


def json_response_for(
    exc: BaseException,
    *,
    default_provider: Optional[str] = None,
    default_model: Optional[str] = None,
) -> JSONResponse:
    """Convenience wrapper returning a :class:`JSONResponse` for ``exc``."""
    status, body = to_envelope(
        exc,
        default_provider=default_provider,
        default_model=default_model,
    )
    return JSONResponse(status_code=status, content=body)


# --------------------------------------------------------------------------- #
# FastAPI exception handler registrations                                     #
# --------------------------------------------------------------------------- #


async def provider_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """FastAPI exception handler for provider-layer errors.

    Registered by :func:`register_research_exception_handlers` on the
    main app. Catches anything derived from :class:`ProviderError` and
    the lightweight custom exceptions defined in this module so a
    call path that forgets its own ``try``/``except`` still emits the
    design §5.3 envelope.
    """
    logger.warning(
        "Research gateway error: %s %s — %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
    )
    return json_response_for(exc)


def register_research_exception_handlers(app: Any) -> None:
    """Register the research exception handlers on a FastAPI app.

    Idempotent — safe to call multiple times (FastAPI overwrites
    duplicate handlers). The gateway's ``main.py`` calls this once
    during startup so the handler is active for every research
    endpoint even if an endpoint forgets its own ``try``/``except``.
    """
    app.add_exception_handler(ProviderError, provider_exception_handler)
    app.add_exception_handler(ConfigMissingError, provider_exception_handler)
    app.add_exception_handler(
        LatencyBudgetExceededError, provider_exception_handler
    )


__all__ = [
    # Error codes
    "ERROR_CODE_PROVIDER_AUTH_FAILED",
    "ERROR_CODE_PROVIDER_TIMEOUT",
    "ERROR_CODE_CONFIG_MISSING",
    "ERROR_CODE_LATENCY_BUDGET_EXCEEDED",
    "ERROR_CODE_PROVIDER_ERROR",
    "ERROR_CODE_UNKNOWN_PROVIDER",
    "ERROR_CODE_INTERNAL_ERROR",
    # Custom exceptions
    "ConfigMissingError",
    "LatencyBudgetExceededError",
    "ProviderTimeoutError",
    # Envelope builder + mapper
    "build_error_envelope",
    "to_envelope",
    "json_response_for",
    "http_status_for",
    # FastAPI wiring
    "provider_exception_handler",
    "register_research_exception_handlers",
]
