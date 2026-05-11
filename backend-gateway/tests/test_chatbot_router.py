"""Unit tests for chatbot API router endpoints.

Tests cover: POST /chatbot/message, GET /chatbot/history, DELETE /chatbot/session.
All endpoints require JWT authentication.

Requirements: 18.1, 18.4
"""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.chatbot import router, set_chatbot_service, get_chatbot_service
from app.services.chatbot_service import ChatbotService, ChatResponse


# ── Test app setup ───────────────────────────────────────────────────────────


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with the chatbot router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2", tags=["chatbot"])
    return app


def _mock_auth_user(user_id: str = "test-user-123"):
    """Return a dependency override for get_current_user_id."""
    def override():
        return user_id
    return override


def _make_mock_service() -> ChatbotService:
    """Create a mock ChatbotService with async methods."""
    svc = AsyncMock(spec=ChatbotService)
    return svc


# ── POST /chatbot/message tests ─────────────────────────────────────────────


class TestSendMessage:
    def setup_method(self):
        self.app = _create_test_app()
        self.mock_svc = _make_mock_service()
        from app.routers.auth_v2 import get_current_user_id
        self.app.dependency_overrides[get_current_user_id] = _mock_auth_user()
        self.app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_send_message_success(self):
        self.mock_svc.chat.return_value = ChatResponse(
            text="Your total P&L is ₹5000",
            sources=["trades (10 records)"],
            response_time_ms=150,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={"message": "What is my total P&L?"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Your total P&L is ₹5000"
        assert data["chart_data"] is None
        assert data["chart_type"] is None
        assert "trades" in data["sources"][0]
        assert data["response_time_ms"] == 150

    def test_send_message_with_chart(self):
        chart_bytes = b"<svg>chart</svg>"
        self.mock_svc.chat.return_value = ChatResponse(
            text="Here is your equity curve",
            chart_data=chart_bytes,
            chart_type="equity_curve",
            sources=["trades (5 records)"],
            response_time_ms=800,
        )

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={"message": "Show my equity curve"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Here is your equity curve"
        assert data["chart_type"] == "equity_curve"
        # Verify base64 encoding
        decoded = base64.b64decode(data["chart_data"])
        assert decoded == chart_bytes

    def test_send_message_calls_service_with_user_id(self):
        self.mock_svc.chat.return_value = ChatResponse(text="ok", response_time_ms=10)

        self.client.post(
            "/api/v2/chatbot/message",
            json={"message": "hello"},
        )

        self.mock_svc.chat.assert_called_once_with("test-user-123", "hello")

    def test_send_message_missing_body(self):
        resp = self.client.post("/api/v2/chatbot/message", json={})
        assert resp.status_code == 422

    def test_send_message_service_error(self):
        self.mock_svc.chat.side_effect = Exception("LLM error")

        resp = self.client.post(
            "/api/v2/chatbot/message",
            json={"message": "hello"},
        )

        assert resp.status_code == 500
        assert "Failed to process" in resp.json()["detail"]

    def test_send_message_requires_auth(self):
        """Without auth override, the endpoint should require authentication."""
        app = _create_test_app()
        app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        client = TestClient(app)

        resp = client.post(
            "/api/v2/chatbot/message",
            json={"message": "hello"},
        )

        assert resp.status_code == 401


# ── GET /chatbot/history tests ───────────────────────────────────────────────


class TestGetHistory:
    def setup_method(self):
        self.app = _create_test_app()
        self.mock_svc = _make_mock_service()
        from app.routers.auth_v2 import get_current_user_id
        self.app.dependency_overrides[get_current_user_id] = _mock_auth_user()
        self.app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_get_history_success(self):
        self.mock_svc.get_history.return_value = [
            {"role": "user", "content": "hello", "timestamp": "2024-01-01T00:00:00"},
            {"role": "assistant", "content": "hi there", "timestamp": "2024-01-01T00:00:01"},
        ]

        resp = self.client.get("/api/v2/chatbot/history")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "hello"
        assert data["messages"][1]["role"] == "assistant"

    def test_get_history_empty(self):
        self.mock_svc.get_history.return_value = []

        resp = self.client.get("/api/v2/chatbot/history")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["messages"] == []

    def test_get_history_calls_service_with_user_id(self):
        self.mock_svc.get_history.return_value = []

        self.client.get("/api/v2/chatbot/history")

        self.mock_svc.get_history.assert_called_once_with("test-user-123")

    def test_get_history_service_error(self):
        self.mock_svc.get_history.side_effect = Exception("Redis error")

        resp = self.client.get("/api/v2/chatbot/history")

        assert resp.status_code == 500
        assert "Failed to retrieve" in resp.json()["detail"]

    def test_get_history_requires_auth(self):
        app = _create_test_app()
        app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        client = TestClient(app)

        resp = client.get("/api/v2/chatbot/history")

        assert resp.status_code == 401


# ── DELETE /chatbot/session tests ────────────────────────────────────────────


class TestClearSession:
    def setup_method(self):
        self.app = _create_test_app()
        self.mock_svc = _make_mock_service()
        from app.routers.auth_v2 import get_current_user_id
        self.app.dependency_overrides[get_current_user_id] = _mock_auth_user()
        self.app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        self.client = TestClient(self.app)

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_clear_session_success(self):
        self.mock_svc.clear_session.return_value = True

        resp = self.client.delete("/api/v2/chatbot/session")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "cleared" in data["message"].lower()

    def test_clear_session_failure(self):
        self.mock_svc.clear_session.return_value = False

        resp = self.client.delete("/api/v2/chatbot/session")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "failed" in data["message"].lower()

    def test_clear_session_calls_service_with_user_id(self):
        self.mock_svc.clear_session.return_value = True

        self.client.delete("/api/v2/chatbot/session")

        self.mock_svc.clear_session.assert_called_once_with("test-user-123")

    def test_clear_session_service_error(self):
        self.mock_svc.clear_session.side_effect = Exception("Redis error")

        resp = self.client.delete("/api/v2/chatbot/session")

        assert resp.status_code == 500
        assert "Failed to clear" in resp.json()["detail"]

    def test_clear_session_requires_auth(self):
        app = _create_test_app()
        app.dependency_overrides[get_chatbot_service] = lambda: self.mock_svc
        client = TestClient(app)

        resp = client.delete("/api/v2/chatbot/session")

        assert resp.status_code == 401


# ── Service dependency tests ─────────────────────────────────────────────────


class TestServiceDependency:
    def test_service_not_initialized_returns_503(self):
        app = _create_test_app()
        from app.routers.auth_v2 import get_current_user_id
        app.dependency_overrides[get_current_user_id] = _mock_auth_user()
        # Do NOT override get_chatbot_service — let it use the real one
        # Reset the module-level service to None
        from app.routers import chatbot as chatbot_module
        original = chatbot_module._chatbot_service
        chatbot_module._chatbot_service = None
        client = TestClient(app)

        try:
            resp = client.post(
                "/api/v2/chatbot/message",
                json={"message": "hello"},
            )
            assert resp.status_code == 503
            assert "not initialized" in resp.json()["detail"]
        finally:
            chatbot_module._chatbot_service = original

    def test_set_chatbot_service(self):
        from app.routers import chatbot as chatbot_module
        original = chatbot_module._chatbot_service
        try:
            mock_svc = _make_mock_service()
            set_chatbot_service(mock_svc)
            assert chatbot_module._chatbot_service is mock_svc
        finally:
            chatbot_module._chatbot_service = original
