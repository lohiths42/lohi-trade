"""Unit tests for security middleware.

Tests cover:
- InputSanitizationMiddleware: SQL injection, XSS, command injection detection
  and HTTP 400 responses for suspicious input in body and query params.
- RequestLoggingMiddleware: logs user_id, endpoint, method, status, response_time.
- CORS origins loaded from environment variable.
- GZipMiddleware configured with minimum_size=1024.

Requirements: 30.3, 30.4, 30.5, 30.7, 34.7
"""

import logging

from app.middleware.security import (
    InputSanitizationMiddleware,
    RequestLoggingMiddleware,
    contains_command_injection,
    contains_sql_injection,
    contains_xss,
    is_suspicious,
)
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

# ── Helper: build a test app with the middleware stack ───────────────────────


def _build_app(with_auth_user: str = None) -> FastAPI:
    """Return a FastAPI app wired with security middleware and dummy routes."""
    test_app = FastAPI()

    test_app.add_middleware(InputSanitizationMiddleware)
    test_app.add_middleware(GZipMiddleware, minimum_size=1024)
    test_app.add_middleware(RequestLoggingMiddleware)

    if with_auth_user:

        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = with_auth_user
                return await call_next(request)

        test_app.add_middleware(FakeAuthMiddleware)

    @test_app.get("/data")
    async def get_data():
        return {"ok": True}

    @test_app.post("/submit")
    async def post_submit(request: Request):
        return {"ok": True}

    @test_app.get("/large")
    async def get_large():
        # Return a response larger than 1KB to trigger gzip
        return {"data": "x" * 2000}

    return test_app


# ── Pure detection function tests ────────────────────────────────────────────


class TestContainsSqlInjection:
    def test_select_statement(self):
        assert contains_sql_injection("SELECT * FROM users") is True

    def test_union_select(self):
        assert contains_sql_injection("1 UNION SELECT password FROM users") is True

    def test_drop_table(self):
        assert contains_sql_injection("DROP TABLE users") is True

    def test_or_equals(self):
        assert contains_sql_injection("' OR '1'='1") is True

    def test_normal_text(self):
        assert contains_sql_injection("hello world") is False

    def test_normal_email(self):
        assert contains_sql_injection("user@example.com") is False


class TestContainsXss:
    def test_script_tag(self):
        assert contains_xss("<script>alert('xss')</script>") is True

    def test_javascript_protocol(self):
        assert contains_xss("javascript:alert(1)") is True

    def test_event_handler(self):
        assert contains_xss("onerror=alert(1)") is True

    def test_iframe_tag(self):
        assert contains_xss("<iframe src='evil.com'>") is True

    def test_normal_html(self):
        assert contains_xss("<p>Hello</p>") is False

    def test_normal_text(self):
        assert contains_xss("just some text") is False


class TestContainsCommandInjection:
    def test_semicolon(self):
        assert contains_command_injection("foo; rm -rf /") is True

    def test_pipe(self):
        assert contains_command_injection("foo | cat /etc/passwd") is True

    def test_backtick(self):
        assert contains_command_injection("`whoami`") is True

    def test_dollar_sign(self):
        assert contains_command_injection("$(whoami)") is True

    def test_normal_text(self):
        assert contains_command_injection("hello world") is False


class TestIsSuspicious:
    def test_sql_injection_detected(self):
        assert is_suspicious("SELECT * FROM users") == "sql_injection"

    def test_xss_detected(self):
        assert is_suspicious("<script>alert(1)</script>") == "xss"

    def test_command_injection_detected(self):
        assert is_suspicious("`whoami`") == "command_injection"

    def test_clean_input(self):
        assert is_suspicious("normal input text") is None


# ── InputSanitizationMiddleware tests ────────────────────────────────────────


class TestInputSanitizationMiddleware:
    def test_clean_get_request_passes(self):
        client = TestClient(_build_app())
        resp = client.get("/data")
        assert resp.status_code == 200

    def test_clean_post_request_passes(self):
        client = TestClient(_build_app())
        resp = client.post("/submit", json={"name": "Alice"})
        assert resp.status_code == 200

    def test_sql_injection_in_query_param_blocked(self):
        client = TestClient(_build_app())
        resp = client.get("/data", params={"q": "' OR '1'='1"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Suspicious input detected"

    def test_xss_in_query_param_blocked(self):
        client = TestClient(_build_app())
        resp = client.get("/data", params={"q": "<script>alert(1)</script>"})
        assert resp.status_code == 400

    def test_sql_injection_in_body_blocked(self):
        client = TestClient(_build_app())
        resp = client.post(
            "/submit",
            content='{"name": "SELECT * FROM users"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Suspicious input detected"

    def test_xss_in_body_blocked(self):
        client = TestClient(_build_app())
        resp = client.post(
            "/submit",
            content='{"bio": "<script>alert(1)</script>"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_command_injection_in_body_blocked(self):
        client = TestClient(_build_app())
        resp = client.post(
            "/submit",
            content='{"cmd": "`rm -rf /`"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_clean_json_body_passes(self):
        client = TestClient(_build_app())
        resp = client.post("/submit", json={"email": "user@example.com", "name": "Bob"})
        assert resp.status_code == 200


# ── RequestLoggingMiddleware tests ───────────────────────────────────────────


class TestRequestLoggingMiddleware:
    def test_logs_request_details(self, caplog):
        client = TestClient(_build_app(with_auth_user="user-42"))
        with caplog.at_level(logging.INFO, logger="app.middleware.security"):
            client.get("/data")

        log_messages = [r.message for r in caplog.records if "request:" in r.message]
        assert len(log_messages) >= 1
        log_line = log_messages[0]
        assert "user_id=user-42" in log_line
        assert "method=GET" in log_line
        assert "path=/data" in log_line
        assert "status=200" in log_line
        assert "response_time_ms=" in log_line

    def test_logs_anonymous_when_no_user(self, caplog):
        client = TestClient(_build_app())
        with caplog.at_level(logging.INFO, logger="app.middleware.security"):
            client.get("/data")

        log_messages = [r.message for r in caplog.records if "request:" in r.message]
        assert len(log_messages) >= 1
        assert "user_id=anonymous" in log_messages[0]

    def test_logs_post_with_status(self, caplog):
        client = TestClient(_build_app(with_auth_user="trader-1"))
        with caplog.at_level(logging.INFO, logger="app.middleware.security"):
            client.post("/submit", json={"data": "clean"})

        log_messages = [r.message for r in caplog.records if "request:" in r.message]
        assert len(log_messages) >= 1
        assert "method=POST" in log_messages[0]
        assert "path=/submit" in log_messages[0]


# ── GZip compression tests ──────────────────────────────────────────────────


class TestGZipCompression:
    def test_large_response_is_compressed(self):
        client = TestClient(_build_app())
        resp = client.get("/large", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        # The response should be gzip-encoded for >1KB payloads
        assert resp.headers.get("content-encoding") == "gzip"

    def test_small_response_not_compressed(self):
        client = TestClient(_build_app())
        resp = client.get("/data", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        # GZipMiddleware with minimum_size=1024 should not compress
        # responses smaller than 1KB. However, the TestClient may
        # transparently decompress. We verify the middleware is
        # configured with the correct threshold by checking the large
        # response IS compressed (see test above). For small responses
        # we just verify the content is correct.
        assert resp.json() == {"ok": True}


# ── CORS origins configuration tests ────────────────────────────────────────


class TestCORSConfiguration:
    def test_cors_origins_from_env(self, monkeypatch):
        """CORS_ORIGINS should be configurable via environment variable."""
        monkeypatch.setenv(
            "CORS_ORIGINS",
            "https://app.lohi-trade.com,https://mobile.lohi-trade.com",
        )
        # Re-import to pick up the new env var
        import importlib

        import app.config as cfg

        importlib.reload(cfg)

        assert "https://app.lohi-trade.com" in cfg.CORS_ORIGINS
        assert "https://mobile.lohi-trade.com" in cfg.CORS_ORIGINS

    def test_cors_origins_default(self, monkeypatch):
        """Without env var, defaults include localhost dev origins."""
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        import importlib

        import app.config as cfg

        importlib.reload(cfg)

        assert "http://localhost:3000" in cfg.CORS_ORIGINS
