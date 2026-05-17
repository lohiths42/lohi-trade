"""Unit tests for PANVerificationService — format validation, masking, encryption, verification."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

# Set a test encryption key before importing the service
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

from app.services.verification_service import (
    MAX_RETRIES,
    PANRejectionReason,
    PANStatus,
    PANVerificationService,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> PANVerificationService:
    return PANVerificationService(
        db_pool=db_pool,
        nsdl_api_url="https://test.nsdl.co.in/pan/verify",
        nsdl_api_key="test-key",
    )


def _make_mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


# ── validate_format tests ────────────────────────────────────────────────────


class TestValidateFormat:
    def test_valid_pan(self):
        svc = _make_service()
        assert svc.validate_format("ABCDE1234Z") is True

    def test_valid_pan_various(self):
        svc = _make_service()
        assert svc.validate_format("ZZZZZ9999A") is True
        assert svc.validate_format("AABBC0001D") is True

    def test_lowercase_rejected(self):
        svc = _make_service()
        assert svc.validate_format("abcde1234z") is False

    def test_mixed_case_rejected(self):
        svc = _make_service()
        assert svc.validate_format("ABcDE1234Z") is False

    def test_too_short(self):
        svc = _make_service()
        assert svc.validate_format("ABCDE123Z") is False

    def test_too_long(self):
        svc = _make_service()
        assert svc.validate_format("ABCDE12345Z") is False

    def test_empty_string(self):
        svc = _make_service()
        assert svc.validate_format("") is False

    def test_none_input(self):
        svc = _make_service()
        assert svc.validate_format(None) is False

    def test_digits_in_alpha_positions(self):
        svc = _make_service()
        assert svc.validate_format("12345ABCDZ") is False

    def test_alpha_in_digit_positions(self):
        svc = _make_service()
        assert svc.validate_format("ABCDEABCDZ") is False

    def test_special_chars_rejected(self):
        svc = _make_service()
        assert svc.validate_format("ABCD@1234Z") is False

    def test_spaces_rejected(self):
        svc = _make_service()
        assert svc.validate_format("ABCDE 234Z") is False

    def test_fourth_char_type_indicator(self):
        """PAN 4th char indicates entity type — all uppercase letters valid."""
        svc = _make_service()
        for c in "ABCFGHLJPT":
            pan = f"ABC{c}E1234Z"
            assert svc.validate_format(pan) is True


# ── mask_pan tests ───────────────────────────────────────────────────────────


class TestMaskPan:
    def test_standard_masking(self):
        svc = _make_service()
        assert svc.mask_pan("ABCDE1234Z") == "AB******4Z"

    def test_masking_preserves_first_two_and_last_two(self):
        svc = _make_service()
        masked = svc.mask_pan("XYZPQ9876W")
        assert masked[:2] == "XY"
        assert masked[-2:] == "6W"
        assert masked[2:8] == "******"

    def test_masking_length(self):
        svc = _make_service()
        masked = svc.mask_pan("ABCDE1234Z")
        assert len(masked) == 10

    def test_masking_asterisk_count(self):
        svc = _make_service()
        masked = svc.mask_pan("ABCDE1234Z")
        assert masked.count("*") == 6

    def test_short_pan_raises(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="10 characters"):
            svc.mask_pan("ABC")

    def test_empty_pan_raises(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="10 characters"):
            svc.mask_pan("")

    def test_none_pan_raises(self):
        svc = _make_service()
        with pytest.raises(ValueError):
            svc.mask_pan(None)


# ── encrypt_pan / decrypt_pan tests ──────────────────────────────────────────


class TestEncryptDecrypt:
    def test_round_trip(self):
        svc = _make_service()
        pan = "ABCDE1234Z"
        encrypted = svc.encrypt_pan(pan)
        assert isinstance(encrypted, bytes)
        assert encrypted != pan.encode()
        decrypted = svc.decrypt_pan(encrypted)
        assert decrypted == pan

    def test_different_encryptions_differ(self):
        """Fernet includes a timestamp + IV, so encryptions of the same value differ."""
        svc = _make_service()
        pan = "ABCDE1234Z"
        e1 = svc.encrypt_pan(pan)
        e2 = svc.encrypt_pan(pan)
        assert e1 != e2  # different due to random IV

    def test_decrypt_wrong_key_fails(self):
        svc = _make_service()
        encrypted = svc.encrypt_pan("ABCDE1234Z")

        # Temporarily swap key
        other_key = Fernet.generate_key().decode()
        import app.services.verification_service as vs

        original_key = vs._ENCRYPTION_KEY
        vs._ENCRYPTION_KEY = other_key
        try:
            with pytest.raises(Exception):
                svc.decrypt_pan(encrypted)
        finally:
            vs._ENCRYPTION_KEY = original_key

    def test_missing_key_raises(self):
        import app.services.verification_service as vs

        original_key = vs._ENCRYPTION_KEY
        vs._ENCRYPTION_KEY = ""
        try:
            svc = _make_service()
            with pytest.raises(RuntimeError, match="PAN_ENCRYPTION_KEY"):
                svc.encrypt_pan("ABCDE1234Z")
        finally:
            vs._ENCRYPTION_KEY = original_key


# ── verify_pan tests ─────────────────────────────────────────────────────────


class TestVerifyPan:
    @pytest.mark.asyncio
    async def test_invalid_format_rejected_immediately(self):
        svc = _make_service()
        result = await svc.verify_pan("user-1", "INVALID")
        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.INVALID_PAN.value

    @pytest.mark.asyncio
    async def test_successful_verification(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": True,
            "holder_name": "JOHN DOE",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.VERIFIED
        assert result.holder_name == "JOHN DOE"
        assert result.verified_at is not None
        assert result.pan_masked == "AB******4Z"
        assert result.pan_encrypted is not None
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejected_name_mismatch(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": False,
            "reason": "name_mismatch",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.NAME_MISMATCH.value

    @pytest.mark.asyncio
    async def test_rejected_inactive_pan(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": False,
            "reason": "inactive_pan",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.INACTIVE_PAN.value

    @pytest.mark.asyncio
    async def test_unknown_rejection_reason_defaults(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": False,
            "reason": "some_unknown_reason",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.INVALID_PAN.value

    @pytest.mark.asyncio
    async def test_api_timeout_retries_and_fails(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch(
                "app.services.verification_service.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.API_UNAVAILABLE.value
        # Should have retried MAX_RETRIES times
        assert mock_client.post.call_count == MAX_RETRIES
        # Should have slept (MAX_RETRIES - 1) times for backoff
        assert mock_sleep.call_count == MAX_RETRIES - 1

    @pytest.mark.asyncio
    async def test_api_connect_error_retries(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            mock_cls.return_value = mock_client

            with patch("app.services.verification_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.REJECTED
        assert result.rejection_reason == PANRejectionReason.API_UNAVAILABLE.value
        assert mock_client.post.call_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch(
                "app.services.verification_service.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await svc.verify_pan("user-1", "ABCDE1234Z")

        # Backoff: 1s after 1st fail, 2s after 2nd fail
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        pool, conn = _make_mock_pool()
        svc = _make_service(db_pool=pool)

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"valid": True, "holder_name": "JANE DOE"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=[httpx.TimeoutException("timeout"), success_response]
            )
            mock_cls.return_value = mock_client

            with patch("app.services.verification_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.VERIFIED
        assert result.holder_name == "JANE DOE"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_db_pool_skips_storage(self):
        """When db_pool is None, verify_pan still works but skips DB storage."""
        svc = _make_service(db_pool=None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"valid": True, "holder_name": "TEST"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_db_error_does_not_crash_verification(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"valid": True, "holder_name": "TEST"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            # Should not raise even though DB fails
            result = await svc.verify_pan("user-1", "ABCDE1234Z")

        assert result.status == PANStatus.VERIFIED
