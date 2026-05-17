"""Unit tests for RBAC middleware and admin endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.middleware.rbac import require_role
from app.routers.admin import get_admin_db_pool
from app.routers.admin import router as admin_router
from app.services.account_service import _create_access_token
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_token(user_id: str = "user-123", role: str = "TRADER") -> str:
    return _create_access_token(user_id, f"{user_id}@test.com", role)


def _create_rbac_test_app() -> FastAPI:
    """App with sample endpoints protected by require_role."""
    app = FastAPI()

    @app.get("/admin-only")
    async def admin_only(payload: dict = Depends(require_role("ADMIN"))):
        return {"user": payload["sub"], "role": payload["role"]}

    @app.get("/trader-or-admin")
    async def trader_or_admin(
        payload: dict = Depends(require_role("ADMIN", "TRADER")),
    ):
        return {"user": payload["sub"], "role": payload["role"]}

    @app.get("/viewer-ok")
    async def viewer_ok(
        payload: dict = Depends(require_role("ADMIN", "TRADER", "VIEWER")),
    ):
        return {"user": payload["sub"], "role": payload["role"]}

    return app


# ── require_role dependency tests ────────────────────────────────────────────


class TestRequireRole:
    def test_admin_can_access_admin_only(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "ADMIN"

    def test_trader_denied_admin_only(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("trader-1", "TRADER")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    def test_viewer_denied_admin_only(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("viewer-1", "VIEWER")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_trader_can_access_trader_or_admin(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("trader-1", "TRADER")
        resp = client.get("/trader-or-admin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "TRADER"

    def test_admin_can_access_trader_or_admin(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")
        resp = client.get("/trader-or-admin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_denied_trader_or_admin(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("viewer-1", "VIEWER")
        resp = client.get("/trader-or-admin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_all_roles_can_access_viewer_ok(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        for role in ["ADMIN", "TRADER", "VIEWER"]:
            token = _make_token(f"user-{role}", role)
            resp = client.get("/viewer-ok", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200, f"{role} should have access"

    def test_no_token_returns_401(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        resp = client.get("/admin-only")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        resp = client.get("/admin-only", headers={"Authorization": "Bearer bad.token.here"})
        assert resp.status_code == 401

    def test_invalid_role_in_definition_raises_valueerror(self):
        with pytest.raises(ValueError, match="Invalid roles"):
            require_role("SUPERADMIN")

    def test_payload_returned_on_success(self):
        app = _create_rbac_test_app()
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        data = resp.json()
        assert data["user"] == "admin-1"
        assert data["role"] == "ADMIN"


# ── Admin endpoint tests ─────────────────────────────────────────────────────


def _create_admin_test_app(mock_pool=None) -> FastAPI:
    """Create a FastAPI app with admin router and mock DB pool."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")

    if mock_pool is not None:
        app.dependency_overrides[get_admin_db_pool] = lambda: mock_pool

    return app


class _FakeAcquireCtx:
    """Async context manager that mimics asyncpg pool.acquire()."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


def _mock_pool_with_user(user_id: str, is_active: bool):
    """Create a mock asyncpg pool that returns a user row."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": user_id, "is_active": is_active})
    mock_conn.execute = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = _FakeAcquireCtx(mock_conn)

    return mock_pool, mock_conn


def _mock_pool_no_user():
    """Create a mock asyncpg pool that returns None (user not found)."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = _FakeAcquireCtx(mock_conn)

    return mock_pool, mock_conn


class TestDeactivateUser:
    def test_admin_can_deactivate_active_user(self):
        target_id = str(uuid.uuid4())
        mock_pool, mock_conn = _mock_pool_with_user(target_id, is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{target_id}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_active"] is False
        assert "deactivated" in data["message"].lower()
        # Verify refresh tokens were deleted
        assert mock_conn.execute.call_count == 2  # UPDATE + DELETE

    def test_deactivate_already_inactive_user(self):
        target_id = str(uuid.uuid4())
        mock_pool, _ = _mock_pool_with_user(target_id, is_active=False)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{target_id}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert "already deactivated" in resp.json()["message"].lower()

    def test_deactivate_nonexistent_user_returns_404(self):
        mock_pool, _ = _mock_pool_no_user()

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 404

    def test_admin_cannot_deactivate_self(self):
        admin_id = "admin-1"
        mock_pool, _ = _mock_pool_with_user(admin_id, is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token(admin_id, "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{admin_id}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 400
        assert "own account" in resp.json()["detail"].lower()

    def test_trader_cannot_deactivate(self):
        mock_pool, _ = _mock_pool_with_user("target", is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("trader-1", "TRADER")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    def test_viewer_cannot_deactivate(self):
        mock_pool, _ = _mock_pool_with_user("target", is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("viewer-1", "VIEWER")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    def test_no_auth_returns_401(self):
        mock_pool, _ = _mock_pool_with_user("target", is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)

        resp = client.put(f"/api/v2/admin/users/{uuid.uuid4()}/deactivate")
        assert resp.status_code == 401


class TestActivateUser:
    def test_admin_can_activate_inactive_user(self):
        target_id = str(uuid.uuid4())
        mock_pool, mock_conn = _mock_pool_with_user(target_id, is_active=False)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{target_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_active"] is True
        assert "reactivated" in data["message"].lower()

    def test_activate_already_active_user(self):
        target_id = str(uuid.uuid4())
        mock_pool, _ = _mock_pool_with_user(target_id, is_active=True)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{target_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert "already active" in resp.json()["message"].lower()

    def test_activate_nonexistent_user_returns_404(self):
        mock_pool, _ = _mock_pool_no_user()

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 404

    def test_trader_cannot_activate(self):
        mock_pool, _ = _mock_pool_with_user("target", is_active=False)

        app = _create_admin_test_app(mock_pool)
        client = TestClient(app)
        token = _make_token("trader-1", "TRADER")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    def test_db_not_initialized_returns_503(self):
        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v2")
        # Don't override the pool dependency
        client = TestClient(app)
        token = _make_token("admin-1", "ADMIN")

        resp = client.put(
            f"/api/v2/admin/users/{uuid.uuid4()}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 503
