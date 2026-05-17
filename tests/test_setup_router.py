"""Unit tests for the Setup Router — API endpoints for the Easy Setup Wizard.

Tests:
- Localhost-only guard rejects non-loopback requests (Requirement 5.5)
- Credential submission with valid/invalid formats (Requirement 2.4)
- Skip flow updates registry correctly (Requirement 3.1)
- Complete endpoint sets setup_complete flag (Requirement 8.3)

Requirements: 5.5, 2.4, 3.1
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway",
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

from app.routers.setup import (
    get_setup_service,
    require_localhost,
    router,
)
from app.services.credential_store import CredentialStore
from app.services.service_registry import ServiceRegistry, ServiceStatus
from app.services.setup_service import SetupService
from fastapi import FastAPI
from fastapi.testclient import TestClient

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

    # Override the get_setup_service dependency to use our test instance
    app.dependency_overrides[get_setup_service] = lambda: setup_service

    return TestClient(app)


@pytest.fixture
def non_localhost_client(setup_service: SetupService) -> TestClient:
    """Create a TestClient that simulates a non-localhost request."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_setup_service] = lambda: setup_service

    # Override require_localhost to simulate rejection for non-loopback
    # We'll test the actual guard logic separately; this client is for
    # verifying the endpoint behavior when the guard rejects.
    return TestClient(app)


# ---------------------------------------------------------------------------
# Localhost Guard Tests (Requirement 5.5)
# ---------------------------------------------------------------------------


class TestLocalhostGuard:
    """Requirement 5.5: Setup endpoints accept only localhost connections."""

    def test_localhost_request_allowed(self, app_client: TestClient):
        """GET /api/setup/status from localhost (127.0.0.1) → 200."""
        # TestClient defaults to 'testclient' as host, but FastAPI TestClient
        # sets request.client to a mock with host="testclient". We need to
        # override require_localhost to allow it for normal tests.
        # For this test, we override to always pass (simulating localhost).
        app = app_client.app
        app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.get("/api/setup/status")
        assert response.status_code == 200

    def test_non_localhost_request_rejected(self, setup_service: SetupService):
        """GET /api/setup/status from non-localhost IP → 403."""
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_setup_service] = lambda: setup_service
        # Do NOT override require_localhost — let it run its real logic

        client = TestClient(app)
        # TestClient's default host is "testclient" which is not in the
        # allowed list ("127.0.0.1", "::1", "localhost"), so it should be rejected.
        response = client.get("/api/setup/status")
        assert response.status_code == 403
        assert "localhost" in response.json()["detail"].lower()

    def test_require_localhost_allows_127_0_0_1(self):
        """require_localhost allows requests from 127.0.0.1."""
        request = MagicMock()
        request.client.host = "127.0.0.1"
        result = require_localhost(request)
        assert result is True

    def test_require_localhost_allows_ipv6_loopback(self):
        """require_localhost allows requests from ::1."""
        request = MagicMock()
        request.client.host = "::1"
        result = require_localhost(request)
        assert result is True

    def test_require_localhost_allows_localhost_string(self):
        """require_localhost allows requests from 'localhost'."""
        request = MagicMock()
        request.client.host = "localhost"
        result = require_localhost(request)
        assert result is True

    def test_require_localhost_rejects_external_ip(self):
        """require_localhost rejects requests from external IPs."""
        from fastapi import HTTPException

        request = MagicMock()
        request.client.host = "192.168.1.100"
        with pytest.raises(HTTPException) as exc_info:
            require_localhost(request)
        assert exc_info.value.status_code == 403

    def test_require_localhost_rejects_no_client(self):
        """require_localhost rejects requests with no client info."""
        from fastapi import HTTPException

        request = MagicMock()
        request.client = None
        with pytest.raises(HTTPException) as exc_info:
            require_localhost(request)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Credential Submission Tests (Requirement 2.4)
# ---------------------------------------------------------------------------


class TestCredentialSubmission:
    """Requirement 2.4: Validate credential format on submission."""

    def test_valid_credentials_accepted(self, app_client: TestClient):
        """POST /api/setup/credentials/broker_shoonya with valid creds → 200."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "abcdefgh12345678",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "mypassword",
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["group_id"] == "broker_shoonya"

    def test_invalid_credentials_rejected(self, app_client: TestClient):
        """POST /api/setup/credentials/broker_shoonya with invalid creds → 422."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # SHOONYA_CLIENT_ID requires uppercase alphanumeric, min 4 chars
        # SHOONYA_API_KEY requires min 8 chars
        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "short",  # Too short (< 8 chars)
                    "SHOONYA_CLIENT_ID": "ab",  # Too short and lowercase
                    "SHOONYA_PASSWORD": "hi",  # Too short (< 4 chars)
                },
            },
        )
        assert response.status_code == 422

    def test_empty_credentials_rejected(self, app_client: TestClient):
        """POST /api/setup/credentials/broker_shoonya with empty values → 422."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "",
                    "SHOONYA_CLIENT_ID": "",
                    "SHOONYA_PASSWORD": "",
                },
            },
        )
        assert response.status_code == 422

    def test_unknown_group_rejected(self, app_client: TestClient):
        """POST /api/setup/credentials/nonexistent → 422."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/nonexistent_group",
            json={"credentials": {"SOME_KEY": "some_value"}},
        )
        assert response.status_code == 422

    def test_valid_nvidia_nim_credentials(self, app_client: TestClient):
        """POST /api/setup/credentials/nvidia_nim with valid API key → 200."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/nvidia_nim",
            json={
                "credentials": {
                    "NVIDIA_NIM_API_KEY": "nvapi-abcdefghijklmnopqrst",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_invalid_nvidia_nim_credentials(self, app_client: TestClient):
        """POST /api/setup/credentials/nvidia_nim with invalid key → 422."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # Missing 'nvapi-' prefix
        response = app_client.post(
            "/api/setup/credentials/nvidia_nim",
            json={
                "credentials": {
                    "NVIDIA_NIM_API_KEY": "invalid-key-without-prefix",
                },
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Skip Flow Tests (Requirement 3.1)
# ---------------------------------------------------------------------------


class TestSkipFlow:
    """Requirement 3.1: Skip optional groups and update registry."""

    def test_skip_telegram_updates_registry(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """POST /api/setup/skip/telegram → 200, registry shows SKIPPED."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post("/api/setup/skip/telegram")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["group_id"] == "telegram"
        assert data["action"] == "skipped"

        # Verify registry was updated
        status = setup_service.registry.get_status("telegram")
        assert status == ServiceStatus.SKIPPED

    def test_skip_nvidia_nim_updates_registry(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """POST /api/setup/skip/nvidia_nim → 200, registry shows SKIPPED."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post("/api/setup/skip/nvidia_nim")
        assert response.status_code == 200

        status = setup_service.registry.get_status("nvidia_nim")
        assert status == ServiceStatus.SKIPPED

    def test_skip_unknown_group_rejected(self, app_client: TestClient):
        """POST /api/setup/skip/nonexistent → 422."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post("/api/setup/skip/nonexistent_group")
        assert response.status_code == 422

    def test_skip_multiple_groups(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """Skipping multiple groups updates each independently."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        app_client.post("/api/setup/skip/telegram")
        app_client.post("/api/setup/skip/nvidia_nim")
        app_client.post("/api/setup/skip/ollama")

        assert setup_service.registry.get_status("telegram") == ServiceStatus.SKIPPED
        assert setup_service.registry.get_status("nvidia_nim") == ServiceStatus.SKIPPED
        assert setup_service.registry.get_status("ollama") == ServiceStatus.SKIPPED
        # Unskipped groups remain unconfigured
        assert setup_service.registry.get_status("broker_shoonya") == ServiceStatus.UNCONFIGURED


# ---------------------------------------------------------------------------
# Complete Setup Tests (Requirement 8.3)
# ---------------------------------------------------------------------------


class TestCompleteSetup:
    """Requirement 8.3: Complete endpoint sets setup_complete flag."""

    def test_complete_setup_sets_flag(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """POST /api/setup/complete → 200, setup_complete=True."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # Verify initially not complete
        assert setup_service.registry.setup_complete is False

        response = app_client.post("/api/setup/complete")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["setup_complete"] is True

        # Verify registry was updated
        assert setup_service.registry.setup_complete is True

    def test_complete_setup_persists_across_reload(
        self,
        tmp_dir: Path,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """setup_complete flag persists when registry is reloaded."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        app_client.post("/api/setup/complete")

        # Reload registry from the same file
        registry_path = setup_service.registry.registry_path
        new_registry = ServiceRegistry(registry_path=registry_path)
        assert new_registry.setup_complete is True

    def test_status_reflects_complete(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """GET /api/setup/status shows setup_complete=True after completion."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # Complete setup
        app_client.post("/api/setup/complete")

        # Check status
        response = app_client.get("/api/setup/status")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_complete"] is True


# ---------------------------------------------------------------------------
# Setup Status Endpoint Tests
# ---------------------------------------------------------------------------


class TestSetupStatus:
    """Additional tests for the GET /api/setup/status endpoint."""

    def test_status_returns_all_services(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """GET /api/setup/status returns entries for all credential groups."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.get("/api/setup/status")
        assert response.status_code == 200
        data = response.json()

        # Should have entries for all 6 credential groups
        from app.services.service_registry import CREDENTIAL_GROUPS

        assert len(data["services"]) == len(CREDENTIAL_GROUPS)

        group_ids = {svc["group_id"] for svc in data["services"]}
        expected_ids = {g.group_id for g in CREDENTIAL_GROUPS}
        assert group_ids == expected_ids

    def test_status_reflects_configured_service(
        self,
        app_client: TestClient,
        setup_service: SetupService,
    ):
        """Status shows 'configured' after credentials are submitted."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # Submit valid credentials
        app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "abcdefgh12345678",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "mypassword",
                },
            },
        )

        # Check status
        response = app_client.get("/api/setup/status")
        data = response.json()
        shoonya_svc = next(s for s in data["services"] if s["group_id"] == "broker_shoonya")
        assert shoonya_svc["status"] == "configured"


# ---------------------------------------------------------------------------
# Hot-Reload Tests (Requirements 8.3, 8.4, 8.5)
# ---------------------------------------------------------------------------


class TestHotReload:
    """Requirements 8.3, 8.4, 8.5: Hot-reload feature gate on credential updates."""

    @patch("app.routers.setup.reload_registry")
    def test_submit_credentials_triggers_reload(
        self,
        mock_reload,
        app_client: TestClient,
    ):
        """POST /api/setup/credentials/{group_id} calls reload_registry on success."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "abcdefgh12345678",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "mypassword",
                },
            },
        )
        assert response.status_code == 200
        mock_reload.assert_called_once()

    @patch("app.routers.setup.reload_registry")
    def test_submit_invalid_credentials_does_not_trigger_reload(
        self,
        mock_reload,
        app_client: TestClient,
    ):
        """POST /api/setup/credentials/{group_id} does NOT call reload_registry on validation failure."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "short",
                    "SHOONYA_CLIENT_ID": "ab",
                    "SHOONYA_PASSWORD": "hi",
                },
            },
        )
        assert response.status_code == 422
        mock_reload.assert_not_called()

    @patch("app.routers.setup.reload_registry")
    def test_reset_group_triggers_reload(self, mock_reload, app_client: TestClient):
        """POST /api/setup/reset/{group_id} calls reload_registry on success."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        # First submit credentials so there's something to reset
        app_client.post(
            "/api/setup/credentials/broker_shoonya",
            json={
                "credentials": {
                    "SHOONYA_API_KEY": "abcdefgh12345678",
                    "SHOONYA_CLIENT_ID": "ABC123",
                    "SHOONYA_PASSWORD": "mypassword",
                },
            },
        )
        mock_reload.reset_mock()

        # Now reset
        response = app_client.post("/api/setup/reset/broker_shoonya")
        assert response.status_code == 200
        mock_reload.assert_called_once()

    @patch("app.routers.setup.reload_registry")
    def test_reset_unknown_group_does_not_trigger_reload(
        self,
        mock_reload,
        app_client: TestClient,
    ):
        """POST /api/setup/reset/nonexistent does NOT call reload_registry."""
        app_client.app.dependency_overrides[require_localhost] = lambda: True

        response = app_client.post("/api/setup/reset/nonexistent_group")
        assert response.status_code == 422
        mock_reload.assert_not_called()
