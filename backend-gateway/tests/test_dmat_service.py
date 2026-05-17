"""Unit tests for DMATService — format validation, encryption, verification, unlinking."""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

# Set a test encryption key before importing the service
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

from app.services.verification_service import (
    DMAT_API_TIMEOUT_SECONDS,
    MAX_RETRIES,
    DMATRejectionReason,
    DMATService,
    DMATStatus,
    DMATVerificationResult,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> DMATService:
    return DMATService(
        db_pool=db_pool,
        depository_api_url="https://test.depository.co.in/dmat/verify",
        depository_api_key="test-key",
    )


def _make_mock_pool(kyc_status="VERIFIED", dmat_count=0, open_positions=0):
    """Create a mock DB pool with configurable KYC status, DMAT count, and open positions."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    async def mock_fetchrow(query, *args):
        if "kyc_verifications" in query:
            if kyc_status is None:
                return None
            return {"status": kyc_status}
        elif "COUNT" in query and "dmat_accounts" in query:
            return {"cnt": dmat_count}
        elif "COUNT" in query and "orders" in query:
            return {"cnt": open_positions}
        elif "RETURNING id" in query:
            return {"id": "dmat-uuid-123"}
        return None

    conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
    conn.execute = AsyncMock(return_value="DELETE 1")
    return pool, conn


# ── validate_dmat_format tests ───────────────────────────────────────────────


class TestValidateDMATFormat:
    def test_valid_cdsl_16_digits(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("1234567890123456")
        assert valid is True
        assert depository == "CDSL"

    def test_valid_cdsl_all_zeros(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("0000000000000000")
        assert valid is True
        assert depository == "CDSL"

    def test_valid_nsdl_format(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("IN12345678901234")
        assert valid is True
        assert depository == "NSDL"

    def test_valid_nsdl_alphanumeric(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("INABCDEF12345678")
        assert valid is True
        assert depository == "NSDL"

    def test_valid_nsdl_lowercase_alpha(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("INabcdef12345678")
        assert valid is True
        assert depository == "NSDL"

    def test_cdsl_too_short(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("123456789012345")
        assert valid is False
        assert depository == ""

    def test_cdsl_too_long(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("12345678901234567")
        assert valid is False
        assert depository == ""

    def test_cdsl_with_letters(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("123456789012345A")
        assert valid is False
        assert depository == ""

    def test_nsdl_wrong_prefix(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("XX12345678901234")
        assert valid is False
        assert depository == ""

    def test_nsdl_too_short(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("IN1234567890123")
        assert valid is False
        assert depository == ""

    def test_nsdl_too_long(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("IN123456789012345")
        assert valid is False
        assert depository == ""

    def test_nsdl_special_chars(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("IN1234@678901234")
        assert valid is False
        assert depository == ""

    def test_empty_string(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("")
        assert valid is False
        assert depository == ""

    def test_none_input(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format(None)
        assert valid is False
        assert depository == ""

    def test_spaces_rejected(self):
        svc = _make_service()
        valid, depository = svc.validate_dmat_format("1234 56789012345")
        assert valid is False
        assert depository == ""


# ── encrypt_account / decrypt_account tests ──────────────────────────────────


class TestEncryptDecryptAccount:
    def test_round_trip_cdsl(self):
        svc = _make_service()
        account = "1234567890123456"
        encrypted = svc.encrypt_account(account)
        assert isinstance(encrypted, bytes)
        assert encrypted != account.encode()
        decrypted = svc.decrypt_account(encrypted)
        assert decrypted == account

    def test_round_trip_nsdl(self):
        svc = _make_service()
        account = "IN12345678901234"
        encrypted = svc.encrypt_account(account)
        decrypted = svc.decrypt_account(encrypted)
        assert decrypted == account

    def test_different_encryptions_differ(self):
        svc = _make_service()
        account = "1234567890123456"
        e1 = svc.encrypt_account(account)
        e2 = svc.encrypt_account(account)
        assert e1 != e2  # Fernet uses random IV


# ── KYC prerequisite check tests ─────────────────────────────────────────────


class TestKYCPrerequisite:
    @pytest.mark.asyncio
    async def test_kyc_not_verified_blocks_dmat(self):
        pool, conn = _make_mock_pool(kyc_status="PENDING")
        svc = _make_service(db_pool=pool)

        result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.KYC_NOT_VERIFIED.value

    @pytest.mark.asyncio
    async def test_no_kyc_record_blocks_dmat(self):
        pool, conn = _make_mock_pool(kyc_status=None)
        svc = _make_service(db_pool=pool)

        result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.KYC_NOT_VERIFIED.value

    @pytest.mark.asyncio
    async def test_no_db_pool_blocks_dmat(self):
        svc = _make_service(db_pool=None)

        result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.KYC_NOT_VERIFIED.value


# ── Max accounts limit tests ────────────────────────────────────────────────


class TestMaxAccountsLimit:
    @pytest.mark.asyncio
    async def test_max_accounts_reached(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=3)
        svc = _make_service(db_pool=pool)

        result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.MAX_ACCOUNTS_REACHED.value

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=2)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"valid": True, "dp_name": "HDFC Securities"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.LINKED


# ── verify_dmat tests ────────────────────────────────────────────────────────


class TestVerifyDMAT:
    @pytest.mark.asyncio
    async def test_invalid_format_rejected(self):
        svc = _make_service()
        result = await svc.verify_dmat("user-1", "INVALID")
        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.INVALID_FORMAT.value

    @pytest.mark.asyncio
    async def test_successful_cdsl_verification(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": True,
            "dp_name": "Zerodha Broking",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.LINKED
        assert result.depository == "CDSL"
        assert result.dp_name == "Zerodha Broking"
        assert result.linked_at is not None
        assert result.account_encrypted is not None
        assert result.dmat_id == "dmat-uuid-123"

    @pytest.mark.asyncio
    async def test_successful_nsdl_verification(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": True,
            "dp_name": "HDFC Securities",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_dmat("user-1", "IN12345678901234")

        assert result.status == DMATStatus.LINKED
        assert result.depository == "NSDL"
        assert result.dp_name == "HDFC Securities"

    @pytest.mark.asyncio
    async def test_rejected_by_depository(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": False,
            "reason": "pan_mismatch",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.PAN_MISMATCH.value

    @pytest.mark.asyncio
    async def test_rejected_account_frozen(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": False,
            "reason": "account_frozen",
        }

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.ACCOUNT_FROZEN.value

    @pytest.mark.asyncio
    async def test_unknown_rejection_reason_defaults(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
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

            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.INVALID_ACCOUNT.value

    @pytest.mark.asyncio
    async def test_api_unavailable_retries_and_fails(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
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
                result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == DMATRejectionReason.API_UNAVAILABLE.value
        assert mock_client.post.call_count == MAX_RETRIES
        assert mock_sleep.call_count == MAX_RETRIES - 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_cls.return_value = mock_client

            with patch(
                "app.services.verification_service.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await svc.verify_dmat("user-1", "1234567890123456")

        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "valid": True,
            "dp_name": "ICICI Direct",
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
                result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.LINKED
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_db_error_does_not_crash_verification(self):
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)

        call_count = {"fetchrow": 0}
        original_fetchrow = conn.fetchrow.side_effect

        async def fetchrow_then_fail(query, *args):
            call_count["fetchrow"] += 1
            if "RETURNING id" in query:
                raise Exception("DB connection lost")
            return await original_fetchrow(query, *args)

        conn.fetchrow = AsyncMock(side_effect=fetchrow_then_fail)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"valid": True, "dp_name": "Test DP"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            # Should not raise even though DB fails on store
            result = await svc.verify_dmat("user-1", "1234567890123456")

        assert result.status == DMATStatus.LINKED

    @pytest.mark.asyncio
    async def test_uses_15_second_timeout(self):
        """Verify the depository API uses 15-second timeout."""
        pool, conn = _make_mock_pool(kyc_status="VERIFIED", dmat_count=0)
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"valid": True, "dp_name": "Test"}

        with patch("app.services.verification_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            await svc.verify_dmat("user-1", "1234567890123456")

        mock_cls.assert_called_with(timeout=DMAT_API_TIMEOUT_SECONDS)
        assert DMAT_API_TIMEOUT_SECONDS == 15


# ── unlink_dmat tests ────────────────────────────────────────────────────────


class TestUnlinkDMAT:
    @pytest.mark.asyncio
    async def test_successful_unlink(self):
        pool, conn = _make_mock_pool(open_positions=0)
        conn.execute = AsyncMock(return_value="DELETE 1")
        svc = _make_service(db_pool=pool)

        result = await svc.unlink_dmat("user-1", "dmat-uuid-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_unlink_fails_with_open_positions(self):
        pool, conn = _make_mock_pool(open_positions=2)
        svc = _make_service(db_pool=pool)

        result = await svc.unlink_dmat("user-1", "dmat-uuid-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_unlink_no_db_pool(self):
        svc = _make_service(db_pool=None)

        result = await svc.unlink_dmat("user-1", "dmat-uuid-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_unlink_nonexistent_account(self):
        pool, conn = _make_mock_pool(open_positions=0)
        conn.execute = AsyncMock(return_value="DELETE 0")
        svc = _make_service(db_pool=pool)

        result = await svc.unlink_dmat("user-1", "nonexistent-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_unlink_db_error_returns_false(self):
        pool, conn = _make_mock_pool(open_positions=0)
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = _make_service(db_pool=pool)

        result = await svc.unlink_dmat("user-1", "dmat-uuid-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_open_positions_check_db_error_fails_safe(self):
        """If we can't check open positions, assume they exist (fail safe)."""
        pool, conn = _make_mock_pool()

        async def fetchrow_fail(query, *args):
            if "orders" in query:
                raise Exception("DB error")
            if "kyc_verifications" in query:
                return {"status": "VERIFIED"}
            return {"cnt": 0}

        conn.fetchrow = AsyncMock(side_effect=fetchrow_fail)
        svc = _make_service(db_pool=pool)

        result = await svc.unlink_dmat("user-1", "dmat-uuid-123")

        assert result is False


# ── DMATStatus enum tests ───────────────────────────────────────────────────


class TestDMATStatusEnum:
    def test_all_statuses_exist(self):
        assert DMATStatus.PENDING.value == "PENDING"
        assert DMATStatus.LINKED.value == "LINKED"
        assert DMATStatus.REJECTED.value == "REJECTED"

    def test_status_count(self):
        assert len(DMATStatus) == 3


# ── DMATRejectionReason enum tests ──────────────────────────────────────────


class TestDMATRejectionReasonEnum:
    def test_all_reasons_exist(self):
        assert DMATRejectionReason.INVALID_FORMAT.value == "invalid_format"
        assert DMATRejectionReason.INVALID_ACCOUNT.value == "invalid_account"
        assert DMATRejectionReason.PAN_MISMATCH.value == "pan_mismatch"
        assert DMATRejectionReason.ACCOUNT_FROZEN.value == "account_frozen"
        assert DMATRejectionReason.API_UNAVAILABLE.value == "api_unavailable"
        assert DMATRejectionReason.KYC_NOT_VERIFIED.value == "kyc_not_verified"
        assert DMATRejectionReason.MAX_ACCOUNTS_REACHED.value == "max_accounts_reached"
        assert DMATRejectionReason.OPEN_POSITIONS_EXIST.value == "open_positions_exist"


# ── DMATVerificationResult dataclass tests ──────────────────────────────────


class TestDMATVerificationResult:
    def test_creation_with_all_fields(self):
        now = datetime.now(timezone.utc)
        result = DMATVerificationResult(
            status=DMATStatus.LINKED,
            dmat_id="uuid-123",
            depository="CDSL",
            dp_name="Zerodha Broking",
            linked_at=now,
            account_encrypted=b"encrypted",
        )
        assert result.status == DMATStatus.LINKED
        assert result.dmat_id == "uuid-123"
        assert result.depository == "CDSL"
        assert result.dp_name == "Zerodha Broking"
        assert result.linked_at == now
        assert result.rejection_reason is None

    def test_creation_rejected(self):
        result = DMATVerificationResult(
            status=DMATStatus.REJECTED,
            rejection_reason="invalid_format",
        )
        assert result.status == DMATStatus.REJECTED
        assert result.rejection_reason == "invalid_format"
        assert result.dmat_id is None
        assert result.depository is None

    def test_defaults(self):
        result = DMATVerificationResult(status=DMATStatus.PENDING)
        assert result.dmat_id is None
        assert result.depository is None
        assert result.dp_name is None
        assert result.rejection_reason is None
        assert result.linked_at is None
        assert result.account_encrypted is None
