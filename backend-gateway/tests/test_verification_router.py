"""Unit tests for verification API router endpoints (PAN, KYC, DMAT)."""

import io
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.verification import (
    router,
    get_pan_service,
    get_kyc_service,
    get_dmat_service,
)
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.verification_service import (
    PANVerificationService,
    PANVerificationResult,
    PANStatus,
    KYCService,
    KYCSubmissionResult,
    KYCStatus,
    DMATService,
    DMATVerificationResult,
    DMATStatus,
)
from app.services.account_service import _create_access_token


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-001"
TEST_TOKEN = None


def _make_token(user_id: str = TEST_USER_ID, role: str = "TRADER") -> str:
    return _create_access_token(user_id, "test@example.com", role)


def _create_test_app(
    pan_svc: PANVerificationService = None,
    kyc_svc: KYCService = None,
    dmat_svc: DMATService = None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the verification router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    # Override auth dependencies
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if pan_svc is not None:
        app.dependency_overrides[get_pan_service] = lambda: pan_svc
    if kyc_svc is not None:
        app.dependency_overrides[get_kyc_service] = lambda: kyc_svc
    if dmat_svc is not None:
        app.dependency_overrides[get_dmat_service] = lambda: dmat_svc

    return app


def _make_mock_pool(mock_conn):
    """Create a mock asyncpg pool with proper async context manager for acquire()."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


# ── PAN Endpoint Tests ───────────────────────────────────────────────────────


class TestSubmitPAN:
    def test_successful_pan_verification(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_pan.verify_pan = AsyncMock(return_value=PANVerificationResult(
            status=PANStatus.VERIFIED,
            holder_name="John Doe",
            pan_masked="AB****Z1",
            verified_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        ))

        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={"pan": "ABCDE1234Z"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["holder_name"] == "John Doe"
        assert data["pan_masked"] == "AB****Z1"
        assert "successfully" in data["message"]
        mock_pan.verify_pan.assert_called_once_with(TEST_USER_ID, "ABCDE1234Z")

    def test_pan_rejected_invalid_format(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_pan.verify_pan = AsyncMock(return_value=PANVerificationResult(
            status=PANStatus.REJECTED,
            rejection_reason="invalid_pan",
        ))

        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={"pan": "INVALID"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "invalid_pan"
        assert "failed" in data["message"]

    def test_pan_missing_field_returns_422(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={})
        assert resp.status_code == 422

    def test_pan_service_not_initialized_returns_503(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={"pan": "ABCDE1234Z"})
        assert resp.status_code == 503


class TestGetPANStatus:
    def test_pan_status_with_db(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "status": "VERIFIED",
            "pan_masked": "AB****Z1",
            "holder_name": "John Doe",
            "rejection_reason": None,
            "verified_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        })
        mock_pan.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/pan/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["holder_name"] == "John Doe"

    def test_pan_status_no_record(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pan.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/pan/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "NOT_SUBMITTED"

    def test_pan_status_no_db_pool(self):
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_pan.db_pool = None

        app = _create_test_app(pan_svc=mock_pan)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/pan/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"


# ── KYC Endpoint Tests ───────────────────────────────────────────────────────


class TestSubmitKYC:
    def test_successful_kyc_submission(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.submit_kyc = AsyncMock(return_value=KYCSubmissionResult(
            status=KYCStatus.VERIFIED,
            verification_ref="KYC-REF-123",
            submitted_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            verified_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        ))

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)

        # Multipart form data with file upload
        resp = client.post(
            "/api/v2/verify/kyc",
            data={
                "full_name": "John Doe",
                "date_of_birth": "1990-01-15",
                "address": "123 Main St, Mumbai",
            },
            files={"government_id_photo": ("id.jpg", b"fake-image-data", "image/jpeg")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["verification_ref"] == "KYC-REF-123"
        assert "successfully" in data["message"]
        mock_kyc.submit_kyc.assert_called_once()

    def test_kyc_rejected_pan_not_verified(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.submit_kyc = AsyncMock(return_value=KYCSubmissionResult(
            status=KYCStatus.NOT_STARTED,
            rejection_reason="PAN verification must be completed before KYC",
        ))

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)
        resp = client.post(
            "/api/v2/verify/kyc",
            data={
                "full_name": "John Doe",
                "date_of_birth": "1990-01-15",
                "address": "123 Main St",
            },
            files={"government_id_photo": ("id.jpg", b"fake-data", "image/jpeg")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "NOT_STARTED"
        assert "PAN" in data["rejection_reason"]

    def test_kyc_queued_for_retry(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.submit_kyc = AsyncMock(return_value=KYCSubmissionResult(
            status=KYCStatus.PENDING,
            queued_for_retry=True,
            rejection_reason="KYC provider temporarily unavailable",
            submitted_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)
        resp = client.post(
            "/api/v2/verify/kyc",
            data={
                "full_name": "Jane Doe",
                "date_of_birth": "1985-06-20",
                "address": "456 Oak Ave",
            },
            files={"government_id_photo": ("id.png", b"image-bytes", "image/png")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "PENDING"
        assert data["queued_for_retry"] is True

    def test_kyc_with_aadhaar(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.submit_kyc = AsyncMock(return_value=KYCSubmissionResult(
            status=KYCStatus.VERIFIED,
            verification_ref="KYC-AAD-456",
        ))

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)
        resp = client.post(
            "/api/v2/verify/kyc",
            data={
                "full_name": "Test User",
                "date_of_birth": "1992-03-10",
                "address": "789 Pine Rd",
                "aadhaar_number": "123456789012",
            },
            files={"government_id_photo": ("doc.jpg", b"photo-data", "image/jpeg")},
        )

        assert resp.status_code == 200
        # Verify aadhaar was passed through
        call_args = mock_kyc.submit_kyc.call_args
        documents = call_args[0][1]
        assert documents.aadhaar_number == "123456789012"


class TestGetKYCStatus:
    def test_kyc_status_verified(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.check_kyc_status = AsyncMock(return_value=KYCStatus.VERIFIED)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "rejection_reason": None,
            "verification_ref": "KYC-REF-789",
        })
        mock_kyc.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/kyc/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["verification_ref"] == "KYC-REF-789"

    def test_kyc_status_not_started(self):
        mock_kyc = AsyncMock(spec=KYCService)
        mock_kyc.check_kyc_status = AsyncMock(return_value=KYCStatus.NOT_STARTED)
        mock_kyc.db_pool = None

        app = _create_test_app(kyc_svc=mock_kyc)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/kyc/status")

        assert resp.status_code == 200
        assert resp.json()["status"] == "NOT_STARTED"


# ── DMAT Endpoint Tests ──────────────────────────────────────────────────────


class TestLinkDMAT:
    def test_successful_dmat_link(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.verify_dmat = AsyncMock(return_value=DMATVerificationResult(
            status=DMATStatus.LINKED,
            dmat_id="dmat-uuid-001",
            depository="CDSL",
            dp_name="HDFC Securities",
            linked_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        ))

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/dmat", json={"account_number": "1234567890123456"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "LINKED"
        assert data["dmat_id"] == "dmat-uuid-001"
        assert data["depository"] == "CDSL"
        assert data["dp_name"] == "HDFC Securities"
        assert "successfully" in data["message"]
        mock_dmat.verify_dmat.assert_called_once_with(TEST_USER_ID, "1234567890123456")

    def test_dmat_rejected_invalid_format(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.verify_dmat = AsyncMock(return_value=DMATVerificationResult(
            status=DMATStatus.REJECTED,
            rejection_reason="invalid_format",
        ))

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/dmat", json={"account_number": "BAD"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "invalid_format"

    def test_dmat_rejected_kyc_not_verified(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.verify_dmat = AsyncMock(return_value=DMATVerificationResult(
            status=DMATStatus.REJECTED,
            depository="NSDL",
            rejection_reason="kyc_not_verified",
        ))

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/dmat", json={"account_number": "IN12345678901234"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "kyc_not_verified"

    def test_dmat_rejected_max_accounts(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.verify_dmat = AsyncMock(return_value=DMATVerificationResult(
            status=DMATStatus.REJECTED,
            depository="CDSL",
            rejection_reason="max_accounts_reached",
        ))

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/dmat", json={"account_number": "1234567890123456"})

        assert resp.status_code == 200
        assert resp.json()["rejection_reason"] == "max_accounts_reached"

    def test_dmat_missing_field_returns_422(self):
        mock_dmat = AsyncMock(spec=DMATService)
        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.post("/api/v2/verify/dmat", json={})
        assert resp.status_code == 422


class TestUnlinkDMAT:
    def test_successful_unlink(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.unlink_dmat = AsyncMock(return_value=True)

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.delete("/api/v2/verify/dmat/dmat-uuid-001")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "successfully" in data["message"]
        mock_dmat.unlink_dmat.assert_called_once_with(TEST_USER_ID, "dmat-uuid-001")

    def test_unlink_fails_open_positions(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.unlink_dmat = AsyncMock(return_value=False)

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.delete("/api/v2/verify/dmat/dmat-uuid-002")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Cannot unlink" in data["message"]


class TestListDMATAccounts:
    def test_list_with_accounts(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {
                "id": "dmat-001",
                "depository": "CDSL",
                "dp_name": "HDFC Securities",
                "status": "LINKED",
                "linked_at": datetime(2024, 1, 10, tzinfo=timezone.utc),
            },
            {
                "id": "dmat-002",
                "depository": "NSDL",
                "dp_name": "Zerodha",
                "status": "LINKED",
                "linked_at": datetime(2024, 2, 5, tzinfo=timezone.utc),
            },
        ])
        mock_dmat.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/dmat/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["accounts"]) == 2
        assert data["accounts"][0]["depository"] == "CDSL"
        assert data["accounts"][1]["depository"] == "NSDL"

    def test_list_empty(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_dmat.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/dmat/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["accounts"] == []

    def test_list_no_db_pool(self):
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.db_pool = None

        app = _create_test_app(dmat_svc=mock_dmat)
        client = TestClient(app)
        resp = client.get("/api/v2/verify/dmat/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestRBACEnforcement:
    def test_viewer_role_denied(self):
        """VIEWER role should be denied access to verification endpoints."""
        mock_pan = AsyncMock(spec=PANVerificationService)
        app = _create_test_app(pan_svc=mock_pan, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={"pan": "ABCDE1234Z"})
        assert resp.status_code == 403

    def test_admin_role_allowed(self):
        """ADMIN role should have access to verification endpoints."""
        mock_pan = AsyncMock(spec=PANVerificationService)
        mock_pan.verify_pan = AsyncMock(return_value=PANVerificationResult(
            status=PANStatus.VERIFIED,
            holder_name="Admin User",
            pan_masked="AD****N1",
        ))

        app = _create_test_app(pan_svc=mock_pan, role="ADMIN")
        client = TestClient(app)
        resp = client.post("/api/v2/verify/pan", json={"pan": "ADMIN1234N"})
        assert resp.status_code == 200

    def test_trader_role_allowed(self):
        """TRADER role should have access to verification endpoints."""
        mock_dmat = AsyncMock(spec=DMATService)
        mock_dmat.db_pool = None

        app = _create_test_app(dmat_svc=mock_dmat, role="TRADER")
        client = TestClient(app)
        resp = client.get("/api/v2/verify/dmat/list")
        assert resp.status_code == 200
