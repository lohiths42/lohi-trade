"""Unit tests for broker management API router (v2) endpoints."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.broker_v2 import (
    BrokerManagementService,
    router,
    get_broker_service,
)
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-broker-001"


def _create_test_app(
    broker_svc: BrokerManagementService = None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the broker_v2 router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "trader@example.com",
        "role": role,
        "type": "access",
    }

    if broker_svc is not None:
        app.dependency_overrides[get_broker_service] = lambda: broker_svc

    return app


def _mock_service() -> AsyncMock:
    return AsyncMock(spec=BrokerManagementService)


# ── Connect Broker Tests ────────────────────────────────────────────────────


class TestConnectBroker:
    def test_connect_success(self):
        svc = _mock_service()
        svc.connect_broker = AsyncMock(return_value={
            "broker_name": "kite",
            "status": "connected",
            "message": "Broker 'kite' connected successfully",
        })

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={
            "broker_name": "kite",
            "credentials": {"api_key": "test123"},
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["broker_name"] == "kite"
        assert data["status"] == "connected"
        svc.connect_broker.assert_awaited_once_with(TEST_USER_ID, "kite", {"api_key": "test123"})

    def test_connect_unsupported_broker_returns_400(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={
            "broker_name": "unknown_broker",
        })

        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()

    def test_connect_service_error_returns_400(self):
        svc = _mock_service()
        svc.connect_broker = AsyncMock(side_effect=ValueError("OAuth flow failed"))

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={"broker_name": "groww"})

        assert resp.status_code == 400
        assert "OAuth flow failed" in resp.json()["detail"]

    def test_connect_missing_broker_name_returns_422(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={})
        assert resp.status_code == 422

    def test_connect_case_insensitive(self):
        svc = _mock_service()
        svc.connect_broker = AsyncMock(return_value={
            "broker_name": "angelone",
            "status": "connected",
            "message": "Connected",
        })

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={"broker_name": "AngelOne"})

        assert resp.status_code == 200
        svc.connect_broker.assert_awaited_once_with(TEST_USER_ID, "angelone", {})


# ── Disconnect Broker Tests ─────────────────────────────────────────────────


class TestDisconnectBroker:
    def test_disconnect_success(self):
        svc = _mock_service()
        svc.disconnect_broker = AsyncMock(return_value=True)

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/brokers/kite/disconnect")

        assert resp.status_code == 200
        assert "disconnected" in resp.json()["message"].lower()
        svc.disconnect_broker.assert_awaited_once_with(TEST_USER_ID, "kite")

    def test_disconnect_unsupported_broker_returns_400(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/brokers/fakebroker/disconnect")

        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()

    def test_disconnect_service_error_returns_400(self):
        svc = _mock_service()
        svc.disconnect_broker = AsyncMock(side_effect=ValueError("Broker not connected"))

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.delete("/api/v2/brokers/shoonya/disconnect")

        assert resp.status_code == 400
        assert "not connected" in resp.json()["detail"].lower()


# ── Get Broker Status Tests ─────────────────────────────────────────────────


class TestGetBrokerStatus:
    def test_get_all_statuses(self):
        svc = _mock_service()
        svc.get_all_statuses = AsyncMock(return_value=[
            {"name": "shoonya", "status": "connected"},
            {"name": "angelone", "status": "disconnected"},
            {"name": "kite", "status": "token_expired"},
            {"name": "groww", "status": "disconnected"},
        ])

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.get("/api/v2/brokers/status")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["brokers"]) == 4
        names = {b["name"] for b in data["brokers"]}
        assert names == {"shoonya", "angelone", "kite", "groww"}

        kite = next(b for b in data["brokers"] if b["name"] == "kite")
        assert kite["status"] == "token_expired"

    def test_get_statuses_empty(self):
        svc = _mock_service()
        svc.get_all_statuses = AsyncMock(return_value=[])

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.get("/api/v2/brokers/status")

        assert resp.status_code == 200
        assert resp.json()["brokers"] == []


# ── Set Primary Broker Tests ────────────────────────────────────────────────


class TestSetPrimaryBroker:
    def test_set_primary_success(self):
        svc = _mock_service()
        svc.set_primary_broker = AsyncMock(return_value={
            "primary_broker": "kite",
            "backup_broker": "groww",
        })

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/primary", json={"broker_name": "kite"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_broker"] == "kite"
        assert data["backup_broker"] == "groww"
        svc.set_primary_broker.assert_awaited_once_with(TEST_USER_ID, "kite")

    def test_set_primary_unsupported_returns_400(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/primary", json={"broker_name": "invalid"})

        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()

    def test_set_primary_service_error_returns_400(self):
        svc = _mock_service()
        svc.set_primary_broker = AsyncMock(side_effect=ValueError("Broker not connected"))

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/primary", json={"broker_name": "kite"})

        assert resp.status_code == 400

    def test_set_primary_missing_name_returns_422(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/primary", json={})
        assert resp.status_code == 422


# ── Set Backup Broker Tests ─────────────────────────────────────────────────


class TestSetBackupBroker:
    def test_set_backup_success(self):
        svc = _mock_service()
        svc.set_backup_broker = AsyncMock(return_value={
            "primary_broker": "shoonya",
            "backup_broker": "angelone",
        })

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/backup", json={"broker_name": "angelone"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_broker"] == "shoonya"
        assert data["backup_broker"] == "angelone"
        svc.set_backup_broker.assert_awaited_once_with(TEST_USER_ID, "angelone")

    def test_set_backup_unsupported_returns_400(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/backup", json={"broker_name": "badbroker"})

        assert resp.status_code == 400

    def test_set_backup_service_error_returns_400(self):
        svc = _mock_service()
        svc.set_backup_broker = AsyncMock(side_effect=ValueError("Same as primary"))

        app = _create_test_app(broker_svc=svc)
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/backup", json={"broker_name": "kite"})

        assert resp.status_code == 400
        assert "same as primary" in resp.json()["detail"].lower()


# ── Service Not Initialized Tests ────────────────────────────────────────────


class TestServiceNotInitialized:
    def test_connect_returns_503(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={"broker_name": "kite"})
        assert resp.status_code == 503

    def test_status_returns_503(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        client = TestClient(app)
        resp = client.get("/api/v2/brokers/status")
        assert resp.status_code == 503


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestBrokerRBACEnforcement:
    def test_viewer_denied_connect(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={"broker_name": "kite"})
        assert resp.status_code == 403

    def test_viewer_denied_disconnect(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc, role="VIEWER")
        client = TestClient(app)
        resp = client.delete("/api/v2/brokers/kite/disconnect")
        assert resp.status_code == 403

    def test_viewer_denied_status(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc, role="VIEWER")
        client = TestClient(app)
        resp = client.get("/api/v2/brokers/status")
        assert resp.status_code == 403

    def test_viewer_denied_set_primary(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc, role="VIEWER")
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/primary", json={"broker_name": "kite"})
        assert resp.status_code == 403

    def test_viewer_denied_set_backup(self):
        svc = _mock_service()
        app = _create_test_app(broker_svc=svc, role="VIEWER")
        client = TestClient(app)
        resp = client.put("/api/v2/brokers/backup", json={"broker_name": "kite"})
        assert resp.status_code == 403

    def test_admin_allowed_connect(self):
        svc = _mock_service()
        svc.connect_broker = AsyncMock(return_value={
            "broker_name": "kite", "status": "connected", "message": "OK",
        })
        app = _create_test_app(broker_svc=svc, role="ADMIN")
        client = TestClient(app)
        resp = client.post("/api/v2/brokers/connect", json={"broker_name": "kite"})
        assert resp.status_code == 200

    def test_admin_allowed_status(self):
        svc = _mock_service()
        svc.get_all_statuses = AsyncMock(return_value=[])
        app = _create_test_app(broker_svc=svc, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/brokers/status")
        assert resp.status_code == 200
