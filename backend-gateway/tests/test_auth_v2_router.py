"""Unit tests for auth_v2 router endpoints and JWT auth dependency."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.auth_v2 import (
    router,
    get_account_service,
    get_current_user_id,
    get_current_user_payload,
    set_account_service,
)
from app.services.account_service import (
    AccountService,
    TokenPair,
    User,
    UserRole,
    _create_access_token,
    verify_access_token,
)
from datetime import datetime, timezone


# ── Test app setup ───────────────────────────────────────────────────────────

def _create_test_app(mock_svc: AccountService = None) -> FastAPI:
    """Create a minimal FastAPI app with the auth_v2 router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    if mock_svc is not None:
        app.dependency_overrides[get_account_service] = lambda: mock_svc

    return app


def _make_valid_token(user_id: str = "test-user-123", role: str = "TRADER") -> str:
    return _create_access_token(user_id, "test@example.com", role)


# ── get_current_user_id dependency tests ─────────────────────────────────────


class TestGetCurrentUserId:
    def test_valid_bearer_token(self):
        token = _make_valid_token("user-abc")
        result = get_current_user_id(authorization=f"Bearer {token}")
        assert result == "user-abc"

    def test_missing_header_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization=None)
        assert exc_info.value.status_code == 401

    def test_no_bearer_prefix_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization="Token abc123")
        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization="Bearer invalid.token.here")
        assert exc_info.value.status_code == 401

    def test_empty_bearer_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(authorization="Bearer ")
        assert exc_info.value.status_code == 401


class TestGetCurrentUserPayload:
    def test_returns_full_payload(self):
        token = _make_valid_token("user-xyz", role="ADMIN")
        payload = get_current_user_payload(authorization=f"Bearer {token}")
        assert payload["sub"] == "user-xyz"
        assert payload["role"] == "ADMIN"
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"

    def test_missing_header_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            get_current_user_payload(authorization=None)


# ── Endpoint tests ───────────────────────────────────────────────────────────


class TestRegisterEndpoint:
    def test_successful_registration(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.register_email = AsyncMock(return_value={
            "user": User(
                id="new-user-id",
                email="new@test.com",
                phone="9876543210",
                name="New User",
                role=UserRole.TRADER,
                is_onboarded=False,
                created_at=datetime.now(timezone.utc),
            ),
            "otp": "123456",
            "otp_expires_at": 9999999999.0,
        })

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/register", json={
            "email": "new@test.com",
            "password": "Str0ng!Pass",
            "phone": "9876543210",
            "name": "New User",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == "new-user-id"
        assert data["email"] == "new@test.com"
        mock_svc.register_email.assert_called_once_with(
            "new@test.com", "Str0ng!Pass", "9876543210", "New User"
        )

    def test_validation_error_returns_400(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.register_email = AsyncMock(side_effect=ValueError("Invalid email format"))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/register", json={
            "email": "bad",
            "password": "Str0ng!Pass",
            "phone": "9876543210",
            "name": "Test",
        })

        assert resp.status_code == 400
        assert "Invalid email" in resp.json()["detail"]

    def test_missing_fields_returns_422(self):
        mock_svc = AsyncMock(spec=AccountService)
        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/register", json={"email": "a@b.com"})
        assert resp.status_code == 422


class TestLoginEndpoint:
    def test_successful_login(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_email = AsyncMock(return_value=TokenPair(
            access_token="access-tok",
            refresh_token="refresh-tok",
        ))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/login", json={
            "email": "user@test.com",
            "password": "Str0ng!Pass",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "access-tok"
        assert data["refresh_token"] == "refresh-tok"
        assert data["token_type"] == "bearer"

    def test_invalid_credentials_returns_401(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_email = AsyncMock(side_effect=ValueError("Invalid email or password"))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/login", json={
            "email": "user@test.com",
            "password": "wrong",
        })

        assert resp.status_code == 401


class TestGoogleLoginEndpoint:
    def test_successful_google_login(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_google = AsyncMock(return_value=TokenPair(
            access_token="g-access",
            refresh_token="g-refresh",
        ))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/google", json={"id_token": "google-tok"})

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "g-access"
        mock_svc.login_google.assert_called_once_with("google-tok")

    def test_invalid_google_token_returns_401(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_google = AsyncMock(side_effect=ValueError("Invalid Google ID token"))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/google", json={"id_token": "bad"})

        assert resp.status_code == 401


class TestAppleLoginEndpoint:
    def test_successful_apple_login(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_apple = AsyncMock(return_value=TokenPair(
            access_token="a-access",
            refresh_token="a-refresh",
        ))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/apple", json={
            "auth_code": "apple-code",
            "user_name": "Apple User",
        })

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "a-access"
        mock_svc.login_apple.assert_called_once_with("apple-code", user_name="Apple User")

    def test_apple_without_name(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_apple = AsyncMock(return_value=TokenPair(
            access_token="a2", refresh_token="r2",
        ))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/apple", json={"auth_code": "code"})

        assert resp.status_code == 200
        mock_svc.login_apple.assert_called_once_with("code", user_name=None)

    def test_invalid_apple_code_returns_401(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.login_apple = AsyncMock(side_effect=ValueError("Invalid Apple authorization code"))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/apple", json={"auth_code": "bad"})

        assert resp.status_code == 401


class TestRefreshEndpoint:
    def test_successful_refresh(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.refresh_token = AsyncMock(return_value=TokenPair(
            access_token="new-access",
            refresh_token="new-refresh",
        ))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/refresh", json={"refresh_token": "old-refresh"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "new-access"
        assert data["refresh_token"] == "new-refresh"

    def test_invalid_refresh_token_returns_401(self):
        mock_svc = AsyncMock(spec=AccountService)
        mock_svc.refresh_token = AsyncMock(side_effect=ValueError("Invalid refresh token"))

        app = _create_test_app(mock_svc)
        client = TestClient(app)
        resp = client.post("/api/v2/auth/refresh", json={"refresh_token": "bogus"})

        assert resp.status_code == 401


class TestLogoutEndpoint:
    def test_successful_logout(self):
        mock_svc = AsyncMock(spec=AccountService)
        app = _create_test_app(mock_svc)
        client = TestClient(app)

        token = _make_valid_token("user-logout")
        resp = client.post(
            "/api/v2/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Logged out successfully"

    def test_logout_without_token_returns_401(self):
        mock_svc = AsyncMock(spec=AccountService)
        app = _create_test_app(mock_svc)
        client = TestClient(app)

        resp = client.post("/api/v2/auth/logout")
        assert resp.status_code == 401

    def test_logout_with_expired_token_returns_401(self):
        import jwt as pyjwt
        import time
        from app.services.account_service import JWT_SECRET, JWT_ALGORITHM

        expired_payload = {
            "sub": "user-expired",
            "email": "e@t.com",
            "role": "TRADER",
            "type": "access",
            "iat": int(time.time()) - 3600,
            "exp": int(time.time()) - 1800,
        }
        expired_token = pyjwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        mock_svc = AsyncMock(spec=AccountService)
        app = _create_test_app(mock_svc)
        client = TestClient(app)

        resp = client.post(
            "/api/v2/auth/logout",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401


# ── Service not initialized test ─────────────────────────────────────────────


class TestServiceNotInitialized:
    def test_503_when_service_not_set(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        # Don't override the dependency — it should return 503
        client = TestClient(app)
        resp = client.post("/api/v2/auth/login", json={
            "email": "a@b.com",
            "password": "test",
        })
        assert resp.status_code == 503
