"""Unit tests for PUT /users/onboarded endpoint."""

from unittest.mock import AsyncMock, MagicMock

from app.routers.auth_v2 import get_account_service, get_current_user_id
from app.routers.users import router
from app.services.account_service import AccountService, _create_access_token
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_token(user_id: str = "user-123") -> str:
    return _create_access_token(user_id, "test@example.com", "TRADER")


def _create_app(mock_svc: AccountService = None, user_id: str = "user-123") -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    if mock_svc is not None:
        app.dependency_overrides[get_account_service] = lambda: mock_svc

    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return app


def _mock_account_service(execute_result: str = "UPDATE 1") -> AccountService:
    """Create a mock AccountService with a mock asyncpg pool."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=execute_result)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    mock_svc = MagicMock(spec=AccountService)
    mock_svc._pool = mock_pool
    return mock_svc, mock_conn


# ── Tests ────────────────────────────────────────────────────────────────────


class TestUpdateOnboarded:
    def test_set_onboarded_true(self):
        mock_svc, mock_conn = _mock_account_service("UPDATE 1")
        app = _create_app(mock_svc)
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={"is_onboarded": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-123"
        assert data["is_onboarded"] is True
        assert data["message"] == "Onboarding status updated"
        mock_conn.execute.assert_called_once()

    def test_set_onboarded_false_for_replay(self):
        mock_svc, mock_conn = _mock_account_service("UPDATE 1")
        app = _create_app(mock_svc)
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={"is_onboarded": False})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_onboarded"] is False

    def test_user_not_found_returns_404(self):
        mock_svc, _ = _mock_account_service("UPDATE 0")
        app = _create_app(mock_svc)
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={"is_onboarded": True})

        assert resp.status_code == 404
        assert "User not found" in resp.json()["detail"]

    def test_missing_body_returns_422(self):
        mock_svc, _ = _mock_account_service()
        app = _create_app(mock_svc)
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={})

        assert resp.status_code == 422

    def test_db_error_returns_500(self):
        mock_svc, mock_conn = _mock_account_service()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        app = _create_app(mock_svc)
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={"is_onboarded": True})

        assert resp.status_code == 500
        assert "Failed to update" in resp.json()["detail"]


class TestOnboardedAuthRequired:
    def test_no_auth_returns_401(self):
        """Without overriding get_current_user_id, the real dependency requires a token."""
        mock_svc, _ = _mock_account_service()
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_account_service] = lambda: mock_svc
        # Do NOT override get_current_user_id — real auth check runs
        client = TestClient(app)

        resp = client.put("/api/v2/users/onboarded", json={"is_onboarded": True})

        assert resp.status_code == 401
