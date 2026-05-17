"""Unit tests for the Lohi-Research structured error envelope (Task 16.4).

Covers :mod:`app.middleware.errors`:

* :func:`build_error_envelope` — correct envelope shape per design §5.3.
* :func:`to_envelope` — exception → ``(status, envelope)`` mapping for
  every documented exception type.
* :func:`http_status_for` — status code lookup for every code.
* FastAPI integration — :func:`register_research_exception_handlers`
  installs working handlers that produce the same envelope.

Requirements: 2.10, 8.8, 13.1
Design: §5.3, §14
"""

from __future__ import annotations

import asyncio

import pytest
from app.middleware.errors import (
    ERROR_CODE_CONFIG_MISSING,
    ERROR_CODE_INTERNAL_ERROR,
    ERROR_CODE_LATENCY_BUDGET_EXCEEDED,
    ERROR_CODE_PROVIDER_AUTH_FAILED,
    ERROR_CODE_PROVIDER_ERROR,
    ERROR_CODE_PROVIDER_TIMEOUT,
    ERROR_CODE_UNKNOWN_PROVIDER,
    ConfigMissingError,
    LatencyBudgetExceededError,
    ProviderTimeoutError,
    build_error_envelope,
    http_status_for,
    register_research_exception_handlers,
    to_envelope,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.research.providers.errors import (
    ProviderAuthError,
    ProviderError,
    UnknownProviderError,
)


class TestBuildErrorEnvelope:
    """Shape matches design §5.3 verbatim."""

    def test_minimal_envelope(self) -> None:
        env = build_error_envelope("X_CODE", "something broke")
        assert env == {"error": {"code": "X_CODE", "message": "something broke"}}

    def test_provider_and_model_included_when_truthy(self) -> None:
        env = build_error_envelope(
            ERROR_CODE_PROVIDER_AUTH_FAILED,
            "auth failed",
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
        )
        assert env["error"]["provider"] == "nvidia_nim"
        assert env["error"]["model"] == "meta/llama-3.1-70b-instruct"

    def test_provider_omitted_when_none(self) -> None:
        env = build_error_envelope("CODE", "msg", provider=None, model=None)
        assert "provider" not in env["error"]
        assert "model" not in env["error"]

    def test_extra_kwargs_are_merged(self) -> None:
        env = build_error_envelope(
            ERROR_CODE_LATENCY_BUDGET_EXCEEDED,
            "blew the budget",
            phase="first_token",
            observed_ms=1200,
            budget_ms=800,
        )
        inner = env["error"]
        assert inner["phase"] == "first_token"
        assert inner["observed_ms"] == 1200
        assert inner["budget_ms"] == 800

    def test_none_extras_are_dropped(self) -> None:
        """``extra=None`` values should not pollute the envelope."""
        env = build_error_envelope("CODE", "msg", provider="p", model="m", attempt=None)
        assert "attempt" not in env["error"]


class TestToEnvelope:
    """Exception → ``(status, envelope)`` mapping."""

    def test_provider_auth_error(self) -> None:
        exc = ProviderAuthError(
            provider="openai",
            model="gpt-4o-mini",
            error_code="invalid_api_key",
        )
        status, env = to_envelope(exc)
        assert status == 502
        assert env["error"]["code"] == ERROR_CODE_PROVIDER_AUTH_FAILED
        assert env["error"]["provider"] == "openai"
        assert env["error"]["model"] == "gpt-4o-mini"
        assert env["error"]["error_code"] == "invalid_api_key"

    def test_provider_timeout_error(self) -> None:
        exc = ProviderTimeoutError(
            provider="nvidia_nim",
            model="llama",
            attempt=2,
            elapsed_ms=15000,
        )
        status, env = to_envelope(exc)
        assert status == 504
        assert env["error"]["code"] == ERROR_CODE_PROVIDER_TIMEOUT
        assert env["error"]["provider"] == "nvidia_nim"
        assert env["error"]["model"] == "llama"
        assert env["error"]["attempt"] == 2
        assert env["error"]["elapsed_ms"] == 15000

    def test_asyncio_timeout_uses_defaults(self) -> None:
        """Bare :class:`asyncio.TimeoutError` maps to PROVIDER_TIMEOUT."""
        status, env = to_envelope(
            asyncio.TimeoutError("upstream slow"),
            default_provider="nvidia_nim",
            default_model="llama",
        )
        assert status == 504
        assert env["error"]["code"] == ERROR_CODE_PROVIDER_TIMEOUT
        assert env["error"]["provider"] == "nvidia_nim"
        assert env["error"]["model"] == "llama"

    def test_unknown_provider_error(self) -> None:
        exc = UnknownProviderError(
            kind="llm",
            name="mistral",
            registered=("nvidia_nim", "openai"),
        )
        status, env = to_envelope(exc)
        assert status == 500
        assert env["error"]["code"] == ERROR_CODE_UNKNOWN_PROVIDER
        assert env["error"]["kind"] == "llm"
        assert env["error"]["name"] == "mistral"
        assert env["error"]["registered"] == ["nvidia_nim", "openai"]

    def test_config_missing_error(self) -> None:
        exc = ConfigMissingError("research.providers.chat.api_key")
        status, env = to_envelope(exc)
        assert status == 500
        assert env["error"]["code"] == ERROR_CODE_CONFIG_MISSING
        assert env["error"]["config_key"] == "research.providers.chat.api_key"

    def test_latency_budget_exceeded_error(self) -> None:
        exc = LatencyBudgetExceededError(
            phase="first_token",
            observed_ms=1200,
            budget_ms=800,
        )
        status, env = to_envelope(exc)
        assert status == 504
        assert env["error"]["code"] == ERROR_CODE_LATENCY_BUDGET_EXCEEDED
        assert env["error"]["phase"] == "first_token"
        assert env["error"]["observed_ms"] == 1200
        assert env["error"]["budget_ms"] == 800

    def test_generic_provider_error(self) -> None:
        class _CustomProviderError(ProviderError):
            pass

        status, env = to_envelope(
            _CustomProviderError("rate limited"),
            default_provider="openai",
            default_model="gpt",
        )
        assert status == 502
        assert env["error"]["code"] == ERROR_CODE_PROVIDER_ERROR
        assert env["error"]["provider"] == "openai"
        assert env["error"]["model"] == "gpt"

    def test_unknown_exception_maps_to_internal_error(self) -> None:
        status, env = to_envelope(RuntimeError("whoops"))
        assert status == 500
        assert env["error"]["code"] == ERROR_CODE_INTERNAL_ERROR


class TestHttpStatusFor:
    """Every documented code has a stable status."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            (ERROR_CODE_PROVIDER_AUTH_FAILED, 502),
            (ERROR_CODE_PROVIDER_TIMEOUT, 504),
            (ERROR_CODE_PROVIDER_ERROR, 502),
            (ERROR_CODE_UNKNOWN_PROVIDER, 500),
            (ERROR_CODE_CONFIG_MISSING, 500),
            (ERROR_CODE_LATENCY_BUDGET_EXCEEDED, 504),
            (ERROR_CODE_INTERNAL_ERROR, 500),
        ],
    )
    def test_known_codes(self, code: str, expected: int) -> None:
        assert http_status_for(code) == expected

    def test_unknown_code_falls_back_to_500(self) -> None:
        assert http_status_for("NOT_A_REAL_CODE") == 500


class TestFastAPIIntegration:
    """Handlers installed via ``register_research_exception_handlers``.

    Uses a minimal FastAPI app to verify that an uncaught
    :class:`ProviderError` in a route produces the design §5.3
    envelope with the correct HTTP status.
    """

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        register_research_exception_handlers(app)

        @app.get("/raise-auth")
        def _raise_auth() -> dict:
            raise ProviderAuthError("openai", "gpt-4o-mini", "invalid_api_key")

        @app.get("/raise-config-missing")
        def _raise_config() -> dict:
            raise ConfigMissingError("research.providers.chat.api_key")

        @app.get("/raise-latency")
        def _raise_latency() -> dict:
            raise LatencyBudgetExceededError(phase="first_token", observed_ms=1500, budget_ms=800)

        return app

    def test_provider_auth_error_returns_502_envelope(self) -> None:
        app = self._build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise-auth")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["code"] == ERROR_CODE_PROVIDER_AUTH_FAILED
        assert body["error"]["provider"] == "openai"
        assert body["error"]["model"] == "gpt-4o-mini"

    def test_config_missing_returns_500_envelope(self) -> None:
        app = self._build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise-config-missing")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == ERROR_CODE_CONFIG_MISSING
        assert body["error"]["config_key"] == "research.providers.chat.api_key"

    def test_latency_budget_exceeded_returns_504_envelope(self) -> None:
        app = self._build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise-latency")
        assert resp.status_code == 504
        body = resp.json()
        assert body["error"]["code"] == ERROR_CODE_LATENCY_BUDGET_EXCEEDED
        assert body["error"]["phase"] == "first_token"
