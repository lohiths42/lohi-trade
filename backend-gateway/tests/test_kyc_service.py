"""Unit tests for KYCService — document validation, encryption, submission, status checks."""

import asyncio
import os
import struct
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

# Set a test encryption key before importing the service
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

from app.services.verification_service import (
    KYCService,
    KYCDocuments,
    KYCSubmissionResult,
    KYCStatus,
    MAX_RETRIES,
    MIN_DOCUMENT_DPI,
    MIN_DOCUMENT_SIZE,
    MAX_DOCUMENT_SIZE,
    ALLOWED_MIME_TYPES,
    DOCUMENT_RETENTION_DAYS,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> KYCService:
    return KYCService(
        db_pool=db_pool,
        kra_api_url="https://test.kra.co.in/kyc/verify",
        kra_api_key="test-key",
    )


def _make_mock_pool(pan_status="VERIFIED"):
    """Create a mock DB pool that returns PAN status and supports KYC inserts."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    # Default: PAN is verified
    conn.fetchrow = AsyncMock(return_value={"status": pan_status})
    conn.execute = AsyncMock()
    return pool, conn


def _make_jpeg_image(dpi: int = 300, size_bytes: int = 150_000) -> bytes:
    """Create a minimal JPEG-like byte sequence with JFIF header encoding the given DPI."""
    # SOI marker
    header = b"\xff\xd8"
    # APP0 marker
    header += b"\xff\xe0"
    # APP0 length (16 bytes)
    header += b"\x00\x10"
    # JFIF identifier
    header += b"JFIF\x00"
    # Version 1.1
    header += b"\x01\x01"
    # Units: 1 = DPI
    header += b"\x01"
    # X density (big-endian uint16)
    header += struct.pack(">H", dpi)
    # Y density (big-endian uint16)
    header += struct.pack(">H", dpi)
    # Thumbnail dimensions 0x0
    header += b"\x00\x00"

    # Pad to desired size
    padding_needed = max(0, size_bytes - len(header))
    return header + b"\x00" * padding_needed


def _make_png_image(dpi: int = 300, size_bytes: int = 150_000) -> bytes:
    """Create a minimal PNG-like byte sequence with pHYs chunk encoding the given DPI."""
    # PNG signature
    header = b"\x89PNG\r\n\x1a\n"
    # pHYs chunk: pixels per meter
    ppm = int(dpi * 39.3701)
    phys_data = b"pHYs"
    phys_data += struct.pack(">I", ppm)  # X pixels per unit
    phys_data += struct.pack(">I", ppm)  # Y pixels per unit
    phys_data += b"\x01"                 # unit = meter

    combined = header + phys_data
    padding_needed = max(0, size_bytes - len(combined))
    return combined + b"\x00" * padding_needed


def _make_documents(**overrides) -> KYCDocuments:
    """Create a valid KYCDocuments instance with sensible defaults."""
    defaults = dict(
        full_name="John Doe",
        date_of_birth="1990-01-15",
        address="123 Main St, Mumbai, Maharashtra 400001",
        government_id_photo=_make_jpeg_image(dpi=300, size_bytes=150_000),
        government_id_mime_type="image/jpeg",
        aadhaar_number=None,
    )
    defaults.update(overrides)
    return KYCDocuments(**defaults)


# ── validate_document_quality tests ──────────────────────────────────────────


class TestValidateDocumentQuality:
    def test_valid_jpeg_300dpi(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=150_000)
        assert svc.validate_document_quality(img, "image/jpeg") is True

    def test_valid_png_300dpi(self):
        svc = _make_service()
        img = _make_png_image(dpi=300, size_bytes=150_000)
        assert svc.validate_document_quality(img, "image/png") is True

    def test_high_dpi_accepted(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=600, size_bytes=200_000)
        assert svc.validate_document_quality(img, "image/jpeg") is True

    def test_low_dpi_rejected(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=150, size_bytes=150_000)
        assert svc.validate_document_quality(img, "image/jpeg") is False

    def test_wrong_mime_type_rejected(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=150_000)
        assert svc.validate_document_quality(img, "image/gif") is False
        assert svc.validate_document_quality(img, "application/pdf") is False

    def test_too_small_rejected(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=50_000)  # 50KB < 100KB
        assert svc.validate_document_quality(img, "image/jpeg") is False

    def test_too_large_rejected(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=6_000_000)  # 6MB > 5MB
        assert svc.validate_document_quality(img, "image/jpeg") is False

    def test_exact_min_size_accepted(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=MIN_DOCUMENT_SIZE)
        assert svc.validate_document_quality(img, "image/jpeg") is True

    def test_exact_max_size_accepted(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=MAX_DOCUMENT_SIZE)
        assert svc.validate_document_quality(img, "image/jpeg") is True

    def test_exact_max_size_png_accepted(self):
        svc = _make_service()
        img = _make_png_image(dpi=300, size_bytes=MAX_DOCUMENT_SIZE)
        assert svc.validate_document_quality(img, "image/png") is True

    def test_empty_image_rejected(self):
        svc = _make_service()
        assert svc.validate_document_quality(b"", "image/jpeg") is False

    def test_no_dpi_metadata_rejected(self):
        """Image without JFIF/pHYs header → DPI=0 → rejected."""
        svc = _make_service()
        img = b"\xff\xd8" + b"\x00" * 150_000  # JPEG SOI but no JFIF
        assert svc.validate_document_quality(img, "image/jpeg") is False


# ── encrypt_data / decrypt_data tests ────────────────────────────────────────


class TestEncryptDecryptData:
    def test_round_trip_bytes(self):
        svc = _make_service()
        data = b"sensitive document content"
        encrypted = svc.encrypt_data(data)
        assert encrypted != data
        decrypted = svc.decrypt_data(encrypted)
        assert decrypted == data

    def test_round_trip_image(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=300, size_bytes=150_000)
        encrypted = svc.encrypt_data(img)
        decrypted = svc.decrypt_data(encrypted)
        assert decrypted == img

    def test_different_encryptions_differ(self):
        svc = _make_service()
        data = b"test data"
        e1 = svc.encrypt_data(data)
        e2 = svc.encrypt_data(data)
        assert e1 != e2  # Fernet uses random IV


# ── PAN prerequisite check tests ─────────────────────────────────────────────


class TestPANPrerequisite:
    @pytest.mark.asyncio
    async def test_pan_not_verified_blocks_kyc(self):
        pool, conn = _make_mock_pool(pan_status="PENDING")
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.NOT_STARTED
        assert "PAN verification" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_no_pan_record_blocks_kyc(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.NOT_STARTED

    @pytest.mark.asyncio
    async def test_no_db_pool_blocks_kyc(self):
        svc = _make_service(db_pool=None)
        docs = _make_documents()

        result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.NOT_STARTED


# ── submit_kyc tests ─────────────────────────────────────────────────────────


class TestSubmitKYC:
    @pytest.mark.asyncio
    async def test_bad_document_quality_rejected(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents(
            government_id_photo=_make_jpeg_image(dpi=100, size_bytes=150_000)
        )

        result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.REJECTED
        assert "quality" in result.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_successful_verification(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": True,
            "reference_number": "KYC-REF-12345",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.VERIFIED
        assert result.verification_ref == "KYC-REF-12345"
        assert result.verified_at is not None
        assert result.submitted_at is not None
        assert result.queued_for_retry is False
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejected_by_provider(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": False,
            "reason": "Name mismatch with government records",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.REJECTED
        assert "Name mismatch" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_api_unavailable_queues_for_retry(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch("app.services.verification_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.PENDING
        assert result.queued_for_retry is True
        assert "queued" in result.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_retry_exhaustion_with_backoff(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_cls.return_value = mock_client

            with patch("app.services.verification_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await svc.submit_kyc("user-1", docs)

        assert mock_client.post.call_count == MAX_RETRIES
        assert mock_sleep.call_count == MAX_RETRIES - 1
        # Verify exponential backoff delays
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "verified": True,
            "reference_number": "KYC-REF-99999",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=[httpx.TimeoutException("timeout"), success_response]
            )
            mock_cls.return_value = mock_client

            with patch("app.services.verification_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.VERIFIED
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_aadhaar_encrypted_when_provided(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents(aadhaar_number="123456789012")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": True,
            "reference_number": "KYC-REF-AAD",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.VERIFIED
        # Verify DB was called with encrypted aadhaar (non-None 5th arg)
        call_args = conn.execute.call_args
        assert call_args is not None
        # The 5th positional arg (index 4) is encrypted_aadhaar
        assert call_args[0][5] is not None  # aadhaar_encrypted is not None

    @pytest.mark.asyncio
    async def test_aadhaar_none_when_not_provided(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)
        docs = _make_documents(aadhaar_number=None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": True,
            "reference_number": "KYC-REF-NOAAD",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.VERIFIED
        # The 5th positional arg (index 4) is encrypted_aadhaar — should be None
        call_args = conn.execute.call_args
        assert call_args[0][5] is None

    @pytest.mark.asyncio
    async def test_db_error_does_not_crash_submission(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        svc = _make_service(db_pool=pool)
        docs = _make_documents()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": True,
            "reference_number": "KYC-REF-DBERR",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            # Should not raise even though DB fails
            result = await svc.submit_kyc("user-1", docs)

        assert result.status == KYCStatus.VERIFIED


# ── check_kyc_status tests ───────────────────────────────────────────────────


class TestCheckKYCStatus:
    @pytest.mark.asyncio
    async def test_returns_verified(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"status": "VERIFIED"})
        svc = _make_service(db_pool=pool)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_returns_pending(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"status": "PENDING"})
        svc = _make_service(db_pool=pool)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.PENDING

    @pytest.mark.asyncio
    async def test_returns_rejected(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"status": "REJECTED"})
        svc = _make_service(db_pool=pool)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.REJECTED

    @pytest.mark.asyncio
    async def test_no_record_returns_not_started(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.NOT_STARTED

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_not_started(self):
        svc = _make_service(db_pool=None)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.NOT_STARTED

    @pytest.mark.asyncio
    async def test_db_error_returns_not_started(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        svc = _make_service(db_pool=pool)

        status = await svc.check_kyc_status("user-1")
        assert status == KYCStatus.NOT_STARTED


# ── KYCStatus enum tests ────────────────────────────────────────────────────


class TestKYCStatusEnum:
    def test_all_statuses_exist(self):
        assert KYCStatus.NOT_STARTED.value == "NOT_STARTED"
        assert KYCStatus.PENDING.value == "PENDING"
        assert KYCStatus.VERIFIED.value == "VERIFIED"
        assert KYCStatus.REJECTED.value == "REJECTED"

    def test_status_count(self):
        assert len(KYCStatus) == 4


# ── KYCDocuments dataclass tests ─────────────────────────────────────────────


class TestKYCDocuments:
    def test_creation_with_all_fields(self):
        docs = _make_documents(aadhaar_number="123456789012")
        assert docs.full_name == "John Doe"
        assert docs.date_of_birth == "1990-01-15"
        assert docs.address == "123 Main St, Mumbai, Maharashtra 400001"
        assert docs.government_id_mime_type == "image/jpeg"
        assert docs.aadhaar_number == "123456789012"

    def test_creation_without_aadhaar(self):
        docs = _make_documents()
        assert docs.aadhaar_number is None


# ── DPI extraction edge cases ────────────────────────────────────────────────


class TestDPIExtraction:
    def test_jpeg_dpi_extraction(self):
        svc = _make_service()
        img = _make_jpeg_image(dpi=350)
        dpi = svc._extract_dpi(img, "image/jpeg")
        assert dpi == 350

    def test_png_dpi_extraction(self):
        svc = _make_service()
        img = _make_png_image(dpi=400)
        dpi = svc._extract_dpi(img, "image/png")
        # PNG DPI is converted from pixels/meter, so allow small rounding
        assert abs(dpi - 400) <= 1

    def test_no_jfif_header_returns_zero(self):
        svc = _make_service()
        img = b"\xff\xd8" + b"\x00" * 100
        dpi = svc._extract_dpi(img, "image/jpeg")
        assert dpi == 0

    def test_no_phys_chunk_returns_zero(self):
        svc = _make_service()
        img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        dpi = svc._extract_dpi(img, "image/png")
        assert dpi == 0

    def test_unknown_mime_returns_zero(self):
        svc = _make_service()
        dpi = svc._extract_dpi(b"data", "image/bmp")
        assert dpi == 0

    def test_jpeg_dots_per_cm_conversion(self):
        """JFIF units=2 means dots per cm; should convert to DPI."""
        svc = _make_service()
        # Build a JFIF header with units=2 (dots/cm), density=118 (~300 DPI)
        header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01"
        header += b"\x02"  # units = 2 (dots per cm)
        header += struct.pack(">H", 118)  # X density
        header += struct.pack(">H", 118)  # Y density
        header += b"\x00\x00"
        img = header + b"\x00" * 150_000
        dpi = svc._extract_dpi(img, "image/jpeg")
        assert dpi == int(118 * 2.54)  # ~299
