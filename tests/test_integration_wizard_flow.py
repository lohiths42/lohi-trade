"""
Integration tests for the full Easy Setup Wizard flow.

Tests end-to-end scenarios through the API:
1. Full wizard flow: POST credentials → POST test → POST complete → GET status
2. Update flow: POST credentials (initial) → POST credentials (update) → GET status
3. Degraded mode: POST skip for all optional groups → GET health/services

Requirements: 2.4, 3.2, 6.1, 8.3
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway"
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.setup import (
    get_setup_service,
    require_localhost,
    router,
)
from app.services.connection_tester import TestResult
from app.services.credential_store import CredentialStore
from app.services.service_registry import (
    CREDENTIAL_GROUPS,
    ServiceRegistry,
    ServiceStatus,
)
from app.services.setup_service import SetupService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for .env and registry files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def setup_service(tmp_dir: Path) -> SetupService:
    """Create a SetupService with temp file paths."""
    registry_path = tmp_dir / "service_registry.json"
    credential_store = CredentialStore(repo_root=tmp_dir)
    service_registry = ServiceRegistry(registry_path=registry_path)
    return SetupService(
        credential_store=credential_store,
        service_registry=service_registry,
    )


@pytest.fixture
def app_client(setup_service: SetupService) -> TestClient:
    """Create a FastAPI TestClient with the setup router and overridden deps."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    # Override dependencies for testing
    app.dependency_overrides[get_setup_service] = lambda: setup_service
    app.dependency_overrides[require_localhost] = lambda: True

    return TestClient(app)


# ---------------------------------------------------------------------------
# Integration Test: Full Wizard Flow (Requirements 2.4, 3.2, 6.1, 8.3)
# ---------------------------------------------------------------------------


class TestFullWizardFlow:
    """Test the complete wizard flow: credentials → test → complete → verify."""

    @patch("app.routers.setup.reload_registry")
    def test_full_flow_credentials_test_complete(
        self, mock_reload, app_client: TestClient, setup_service: SetupService
    ):
        """Full wizard flow: submit credentials → test connection → complete setup → verify status.

        Validates Requirements 2.4, 6.1, 8.3:
        - Credentials are validated and persisted
        - Connection test returns success
        - Setup is marked complete
        - Registry reflects configured + complete state
        """
        # Step 1: Submit credentials for broker_shoonya
        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "abcdefgh12345678",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "mypassword",
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert mock_reload.called

        # Step 2: Test connection (mock the ConnectionTester to avoid real network calls)
        with patch.object(
            setup_service.connection_tester,
            "test_broker_shoonya",
            new_callable=AsyncMock,
            return_value=TestResult(success=True, response_time_ms=42.5),
        ):
            response = app_client.post("/api/setup/test/broker_shoonya")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["response_time_ms"] == 42.5

        # Step 3: Complete setup
        response = app_client.post("/api/setup/complete")
        assert response.status_code == 200
        assert response.json()["setup_complete"] is True

        # Step 4: Verify status reflects configured + complete
        response = app_client.get("/api/setup/status")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_complete"] is True

        # broker_shoonya should be configured
        shoonya_svc = next(
            s for s in data["services"] if s["group_id"] == "broker_shoonya"
        )
        assert shoonya_svc["status"] == "configured"

    @patch("app.routers.setup.reload_registry")
    def test_full_flow_multiple_groups(
        self, mock_reload, app_client: TestClient, setup_service: SetupService
    ):
        """Full wizard flow with multiple credential groups configured.

        Validates Requirement 3.2: wizard completes with multiple services.
        """
        # Submit NVIDIA NIM credentials
        response = app_client.post(
            "/api/setup/credentials/nvidia_nim",
            json={
                "credentials": {
                    "NVIDIA_NIM_API_KEY": "nvapi-abcdefghijklmnopqrst",
                }
            },
        )
        assert response.status_code == 200

        # Submit Telegram credentials
        response = app_client.post(
            "/api/setup/credentials/telegram",
            json={
                "credentials": {
                    "TELEGRAM_BOT_TOKEN": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz012345678",
                    "TELEGRAM_CHAT_ID": "-1001234567890",
                }
            },
        )
        assert response.status_code == 200

        # Test connections (mocked)
        with patch.object(
            setup_service.connection_tester,
            "test_nvidia_nim",
            new_callable=AsyncMock,
            return_value=TestResult(success=True, response_time_ms=150.0),
        ):
            response = app_client.post("/api/setup/test/nvidia_nim")
            assert response.status_code == 200
            assert response.json()["success"] is True

        with patch.object(
            setup_service.connection_tester,
            "test_telegram",
            new_callable=AsyncMock,
            return_value=TestResult(success=True, response_time_ms=80.0),
        ):
            response = app_client.post("/api/setup/test/telegram")
            assert response.status_code == 200
            assert response.json()["success"] is True

        # Complete setup
        response = app_client.post("/api/setup/complete")
        assert response.status_code == 200

        # Verify all configured services in status
        response = app_client.get("/api/setup/status")
        data = response.json()
        assert data["setup_complete"] is True

        nvidia_svc = next(
            s for s in data["services"] if s["group_id"] == "nvidia_nim"
        )
        telegram_svc = next(
            s for s in data["services"] if s["group_id"] == "telegram"
        )
        assert nvidia_svc["status"] == "configured"
        assert telegram_svc["status"] == "configured"


# ---------------------------------------------------------------------------
# Integration Test: Update Credential Flow (Requirements 8.3)
# ---------------------------------------------------------------------------


class TestUpdateCredentialFlow:
    """Test credential update flow: submit → update → verify reconnection."""

    @patch("app.routers.setup.reload_registry")
    def test_update_credential_triggers_reload(
        self, mock_reload, app_client: TestClient, setup_service: SetupService
    ):
        """Update credential: submit initial → submit updated → verify registry updated.

        Validates Requirement 8.3: credential update triggers service reconnection
        (reload_registry is called on each credential submission).
        """
        # Step 1: Submit initial credentials
        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "initial_key_12345",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "initial_pass",
                }
            },
        )
        assert response.status_code == 200
        assert mock_reload.call_count == 1

        # Verify initial status is configured
        response = app_client.get("/api/setup/status")
        data = response.json()
        shoonya_svc = next(
            s for s in data["services"] if s["group_id"] == "broker_shoonya"
        )
        assert shoonya_svc["status"] == "configured"

        # Step 2: Update credentials with new values
        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "updated_key_67890",
                    "SHOONYA_CLIENT_ID": "XYZ789",
                    "SHOONYA_PASSWORD": "updated_pass",
                }
            },
        )
        assert response.status_code == 200
        # reload_registry should be called again for the update
        assert mock_reload.call_count == 2

        # Step 3: Verify status still shows configured after update
        response = app_client.get("/api/setup/status")
        data = response.json()
        shoonya_svc = next(
            s for s in data["services"] if s["group_id"] == "broker_shoonya"
        )
        assert shoonya_svc["status"] == "configured"

    @patch("app.routers.setup.reload_registry")
    def test_update_credential_persists_new_values(
        self, mock_reload, app_client: TestClient, setup_service: SetupService
    ):
        """Updated credentials are persisted and readable from the store.

        Validates that the credential store reflects the latest values
        after an update.
        """
        # Submit initial credentials
        app_client.post(
            "/api/setup/credentials/nvidia_nim",
            json={
                "credentials": {
                    "NVIDIA_NIM_API_KEY": "nvapi-initial_key_abcdefgh",
                }
            },
        )

        # Read back initial value
        creds = setup_service.credential_store.read_raw_credentials("nvidia_nim")
        assert creds["NVIDIA_NIM_API_KEY"] == "nvapi-initial_key_abcdefgh"

        # Update with new value
        app_client.post(
            "/api/setup/credentials/nvidia_nim",
            json={
                "credentials": {
                    "NVIDIA_NIM_API_KEY": "nvapi-updated_key_ijklmnop",
                }
            },
        )

        # Read back updated value
        creds = setup_service.credential_store.read_raw_credentials("nvidia_nim")
        assert creds["NVIDIA_NIM_API_KEY"] == "nvapi-updated_key_ijklmnop"


# ---------------------------------------------------------------------------
# Integration Test: Degraded Mode (Requirements 3.2)
# ---------------------------------------------------------------------------


class TestDegradedMode:
    """Test skip-all-optional flow and degraded mode behavior."""

    def test_skip_all_optional_groups_degraded_mode(
        self, app_client: TestClient, setup_service: SetupService
    ):
        """Skip all optional groups → verify degraded mode works correctly.

        Validates Requirement 3.2: skipping all optional groups completes
        setup in degraded mode where only configured services are active.
        Features dependent on skipped services are correctly marked unavailable.
        """
        # Identify optional groups
        optional_groups = [g for g in CREDENTIAL_GROUPS if not g.required]

        # Skip all optional groups
        for group in optional_groups:
            response = app_client.post(f"/api/setup/skip/{group.group_id}")
            assert response.status_code == 200
            assert response.json()["action"] == "skipped"

        # Complete setup
        response = app_client.post("/api/setup/complete")
        assert response.status_code == 200

        # Verify health/services endpoint reflects degraded state
        response = app_client.get("/api/health/services")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_complete"] is True

        # All optional groups should be "skipped"
        for group in optional_groups:
            svc = next(
                s for s in data["services"] if s["group_id"] == group.group_id
            )
            assert svc["status"] == "skipped", (
                f"Expected '{group.group_id}' to be 'skipped', got '{svc['status']}'"
            )

        # Required groups that were not configured should remain "unconfigured"
        required_groups = [g for g in CREDENTIAL_GROUPS if g.required]
        for group in required_groups:
            svc = next(
                s for s in data["services"] if s["group_id"] == group.group_id
            )
            assert svc["status"] == "unconfigured", (
                f"Expected '{group.group_id}' to be 'unconfigured', got '{svc['status']}'"
            )

    def test_skip_all_optional_features_unavailable(
        self, app_client: TestClient, setup_service: SetupService
    ):
        """Skipped services correctly mark their dependent features as unavailable.

        Validates that the feature gate correctly reports features as
        unavailable when their dependency groups are skipped.
        """
        # Skip all optional groups
        optional_groups = [g for g in CREDENTIAL_GROUPS if not g.required]
        for group in optional_groups:
            app_client.post(f"/api/setup/skip/{group.group_id}")

        # Check feature availability via the registry
        features = setup_service.registry.get_available_features()

        # Features that depend only on optional (now skipped) services
        # should be unavailable
        # telegram_notifications depends on "telegram" (skipped)
        assert features.get("telegram_notifications") is False

        # live_trading depends on broker_shoonya|broker_angelone (both skipped)
        assert features.get("live_trading") is False

    def test_partial_config_mixed_status(
        self, app_client: TestClient, setup_service: SetupService
    ):
        """Configure some groups, skip others → verify mixed status in health endpoint.

        Validates that the health endpoint correctly reflects a mix of
        configured and skipped services.
        """
        # Configure broker_shoonya
        with patch("app.routers.setup.reload_registry"):
            response = app_client.post(
                "/api/setup/credentials/broker_shoonya",
                json={
                    "credentials": {
                        "SHOONYA_API_KEY": "abcdefgh12345678",
                        "SHOONYA_CLIENT_ID": "ABC123",
                        "SHOONYA_PASSWORD": "mypassword",
                    }
                },
            )
            assert response.status_code == 200

        # Skip telegram
        response = app_client.post("/api/setup/skip/telegram")
        assert response.status_code == 200

        # Complete setup
        response = app_client.post("/api/setup/complete")
        assert response.status_code == 200

        # Verify health/services shows mixed status
        response = app_client.get("/api/health/services")
        data = response.json()

        shoonya_svc = next(
            s for s in data["services"] if s["group_id"] == "broker_shoonya"
        )
        telegram_svc = next(
            s for s in data["services"] if s["group_id"] == "telegram"
        )

        assert shoonya_svc["status"] == "configured"
        assert telegram_svc["status"] == "skipped"

        # Features: live_trading should be available (broker_shoonya configured)
        features = setup_service.registry.get_available_features()
        assert features.get("live_trading") is True
        # telegram_notifications should be unavailable (telegram skipped)
        assert features.get("telegram_notifications") is False

    @patch("app.routers.setup.reload_registry")
    def test_health_services_returns_all_groups(
        self, mock_reload, app_client: TestClient
    ):
        """GET /health/services returns entries for every registered credential group.

        Validates that the health endpoint is complete regardless of
        configuration state.
        """
        response = app_client.get("/api/health/services")
        assert response.status_code == 200
        data = response.json()

        # Should have entries for all credential groups
        assert len(data["services"]) == len(CREDENTIAL_GROUPS)

        returned_ids = {svc["group_id"] for svc in data["services"]}
        expected_ids = {g.group_id for g in CREDENTIAL_GROUPS}
        assert returned_ids == expected_ids

        # Each service should have required fields
        for svc in data["services"]:
            assert "group_id" in svc
            assert "name" in svc
            assert "status" in svc
            assert "required" in svc
            assert "features_affected" in svc
