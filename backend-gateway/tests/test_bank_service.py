"""Unit tests for BankAccountService — IFSC validation, encryption, registration, penny drop."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

# Set a test encryption key before importing the service
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

from app.services.bank_service import (
    MAX_RETRIES,
    BankAccountDetails,
    BankAccountRejectionReason,
    BankAccountService,
    BankAccountStatus,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> BankAccountService:
    return BankAccountService(
        db_pool=db_pool,
        ifsc_api_url="https://test.ifsc.razorpay.com",
        payment_api_url="https://test.payment-gateway.co.in",
        payment_api_key="test-key",
    )


def _make_mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


def _make_details(**overrides) -> BankAccountDetails:
    defaults = {
        "account_holder_name": "JOHN DOE",
        "account_number": "1234567890",
        "ifsc_code": "HDFC0001234",
        "bank_name": "HDFC Bank",
        "account_type": "savings",
    }
    defaults.update(overrides)
    return BankAccountDetails(**defaults)


def _mock_httpx_client(responses):
    """Create a mock httpx.AsyncClient that returns the given responses in order."""
    mock_cls = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    if isinstance(responses, list):
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.post = AsyncMock(side_effect=responses)
    else:
        mock_client.get = AsyncMock(return_value=responses)
        mock_client.post = AsyncMock(return_value=responses)

    mock_cls.return_value = mock_client
    return mock_cls, mock_client


# ── IFSC format validation tests ─────────────────────────────────────────────


class TestValidateIfscFormat:
    def test_valid_ifsc(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("HDFC0001234") is True

    def test_valid_ifsc_sbin(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("SBIN0012345") is True

    def test_valid_ifsc_alphanumeric_suffix(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("ICIC0ABC123") is True

    def test_lowercase_rejected(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("hdfc0001234") is False

    def test_missing_zero_at_fifth(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("HDFC1001234") is False

    def test_too_short(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("HDFC000123") is False

    def test_too_long(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("HDFC00012345") is False

    def test_empty_string(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("") is False

    def test_none_input(self):
        svc = _make_service()
        assert svc.validate_ifsc_format(None) is False

    def test_special_chars_rejected(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("HDFC0@01234") is False

    def test_digits_in_bank_code(self):
        svc = _make_service()
        assert svc.validate_ifsc_format("1234001234A") is False


# ── Encryption tests ─────────────────────────────────────────────────────────


class TestEncryptDecrypt:
    def test_round_trip(self):
        svc = _make_service()
        acct = "9876543210"
        encrypted = svc.encrypt_account_number(acct)
        assert isinstance(encrypted, bytes)
        assert encrypted != acct.encode()
        decrypted = svc.decrypt_account_number(encrypted)
        assert decrypted == acct

    def test_different_encryptions_differ(self):
        svc = _make_service()
        acct = "9876543210"
        e1 = svc.encrypt_account_number(acct)
        e2 = svc.encrypt_account_number(acct)
        assert e1 != e2  # different due to random IV

    def test_missing_key_raises(self):
        import app.services.bank_service as bs

        original_key = bs._ENCRYPTION_KEY
        original_env = os.environ.pop("PAN_ENCRYPTION_KEY", None)
        bs._ENCRYPTION_KEY = ""
        try:
            svc = _make_service()
            with pytest.raises(RuntimeError, match="PAN_ENCRYPTION_KEY"):
                svc.encrypt_account_number("1234567890")
        finally:
            bs._ENCRYPTION_KEY = original_key
            if original_env is not None:
                os.environ["PAN_ENCRYPTION_KEY"] = original_env


# ── Name matching tests ──────────────────────────────────────────────────────


class TestNamesMatch:
    def test_exact_match(self):
        assert BankAccountService._names_match("JOHN DOE", "JOHN DOE") is True

    def test_case_insensitive(self):
        assert BankAccountService._names_match("John Doe", "JOHN DOE") is True

    def test_extra_whitespace(self):
        assert BankAccountService._names_match("JOHN  DOE", "JOHN DOE") is True

    def test_leading_trailing_spaces(self):
        assert BankAccountService._names_match("  JOHN DOE  ", "JOHN DOE") is True

    def test_different_names(self):
        assert BankAccountService._names_match("JOHN DOE", "JANE DOE") is False

    def test_empty_kyc_name(self):
        assert BankAccountService._names_match("", "JOHN DOE") is False

    def test_empty_bank_name(self):
        assert BankAccountService._names_match("JOHN DOE", "") is False

    def test_none_kyc_name(self):
        assert BankAccountService._names_match(None, "JOHN DOE") is False

    def test_none_bank_name(self):
        assert BankAccountService._names_match("JOHN DOE", None) is False


# ── IFSC API verification tests ──────────────────────────────────────────────


class TestVerifyIfsc:
    @pytest.mark.asyncio
    async def test_valid_ifsc_returns_info(self):
        svc = _make_service()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"BANK": "HDFC", "BRANCH": "Mumbai"}

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_ifsc("HDFC0001234")

        assert result is not None
        assert result["BANK"] == "HDFC"

    @pytest.mark.asyncio
    async def test_invalid_format_returns_none(self):
        svc = _make_service()
        result = await svc.verify_ifsc("INVALID")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        svc = _make_service()
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_ifsc("HDFC0001234")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_timeout_retries(self):
        svc = _make_service()

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch("app.services.bank_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.verify_ifsc("HDFC0001234")

        assert result is None
        assert mock_client.get.call_count == MAX_RETRIES


# ── register_bank_account tests ──────────────────────────────────────────────


class TestRegisterBankAccount:
    @pytest.mark.asyncio
    async def test_invalid_account_type_rejected(self):
        svc = _make_service()
        details = _make_details(account_type="checking")
        result = await svc.register_bank_account("user-1", details)
        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.INVALID_ACCOUNT_TYPE.value

    @pytest.mark.asyncio
    async def test_invalid_ifsc_rejected(self):
        svc = _make_service()
        details = _make_details(ifsc_code="INVALID")
        result = await svc.register_bank_account("user-1", details)
        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.INVALID_IFSC.value

    @pytest.mark.asyncio
    async def test_kyc_not_verified_rejected(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"status": "PENDING"})
        svc = _make_service(db_pool=pool)
        details = _make_details()
        result = await svc.register_bank_account("user-1", details)
        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.KYC_NOT_VERIFIED.value

    @pytest.mark.asyncio
    async def test_max_accounts_reached_rejected(self):
        pool, conn = _make_mock_pool()
        # First call: KYC check returns VERIFIED
        # Second call: account count returns 3
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},
                {"cnt": 3},
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()
        result = await svc.register_bank_account("user-1", details)
        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.MAX_ACCOUNTS_REACHED.value

    @pytest.mark.asyncio
    async def test_ifsc_not_found_rejected(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 0},  # account count
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()

        # IFSC API returns 404
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.IFSC_NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_penny_drop_api_unavailable(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 0},  # account count
                {"id": "bank-1"},  # store returns id
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()

        # IFSC API succeeds, penny drop API fails
        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            # First call is IFSC GET, then penny drop POST fails
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch("app.services.bank_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.API_UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_penny_drop_verification_failed(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 0},  # account count
                {"id": "bank-1"},  # store returns id
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {"verified": False, "reason": "account_invalid"}

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.PENNY_DROP_FAILED.value

    @pytest.mark.asyncio
    async def test_name_mismatch_rejected(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 0},  # account count
                {"full_name": "JANE SMITH"},  # KYC name
                {"id": "bank-1"},  # store returns id
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details(account_holder_name="JOHN DOE")

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {
            "verified": True,
            "holder_name": "JOHN DOE",
            "reference": "ref-123",
        }

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.NAME_MISMATCH.value

    @pytest.mark.asyncio
    async def test_successful_registration_first_account_is_primary(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 0},  # account count (first account)
                {"full_name": "JOHN DOE"},  # KYC name
                {"id": "bank-uuid-1"},  # store returns id
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {
            "verified": True,
            "holder_name": "JOHN DOE",
            "reference": "ref-123",
        }

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.VERIFIED
        assert result.is_primary is True
        assert result.verified_at is not None
        assert result.id == "bank-uuid-1"
        assert result.ifsc_code == "HDFC0001234"
        assert result.bank_name == "HDFC Bank"
        assert result.account_holder_name == "JOHN DOE"
        assert result.account_type == "savings"
        assert result.account_number_encrypted is not None

    @pytest.mark.asyncio
    async def test_second_account_not_primary(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},  # KYC check
                {"cnt": 1},  # account count (second account)
                {"full_name": "JOHN DOE"},  # KYC name
                {"id": "bank-uuid-2"},  # store returns id
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details()

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {
            "verified": True,
            "holder_name": "JOHN DOE",
            "reference": "ref-456",
        }

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.VERIFIED
        assert result.is_primary is False

    @pytest.mark.asyncio
    async def test_current_account_type_accepted(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"status": "VERIFIED"},
                {"cnt": 0},
                {"full_name": "JOHN DOE"},
                {"id": "bank-uuid-3"},
            ]
        )
        svc = _make_service(db_pool=pool)
        details = _make_details(account_type="current")

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {
            "verified": True,
            "holder_name": "JOHN DOE",
            "reference": "ref-789",
        }

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.VERIFIED
        assert result.account_type == "current"

    @pytest.mark.asyncio
    async def test_no_db_pool_kyc_check_fails(self):
        """Without db_pool, KYC check returns False → registration rejected."""
        svc = _make_service(db_pool=None)
        details = _make_details()
        result = await svc.register_bank_account("user-1", details)
        assert result.status == BankAccountStatus.FAILED
        assert result.rejection_reason == BankAccountRejectionReason.KYC_NOT_VERIFIED.value

    @pytest.mark.asyncio
    async def test_db_error_during_storage_does_not_crash(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": "VERIFIED"}  # KYC check
            elif call_count == 2:
                return {"cnt": 0}  # account count
            elif call_count == 3:
                return {"full_name": "JOHN DOE"}  # KYC name
            elif call_count == 4:
                raise Exception("DB connection lost")  # store fails
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        svc = _make_service(db_pool=pool)
        details = _make_details()

        ifsc_response = MagicMock()
        ifsc_response.status_code = 200
        ifsc_response.json.return_value = {"BANK": "HDFC"}

        penny_response = MagicMock()
        penny_response.status_code = 200
        penny_response.json.return_value = {
            "verified": True,
            "holder_name": "JOHN DOE",
            "reference": "ref-123",
        }

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=ifsc_response)
            mock_client.post = AsyncMock(return_value=penny_response)
            mock_cls.return_value = mock_client

            # Should not raise even though DB fails during storage
            result = await svc.register_bank_account("user-1", details)

        assert result.status == BankAccountStatus.VERIFIED


# ── verify_penny_drop tests ──────────────────────────────────────────────────


class TestVerifyPennyDrop:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_false(self):
        svc = _make_service(db_pool=None)
        result = await svc.verify_penny_drop("user-1", "bank-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_account_not_found_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)
        result = await svc.verify_penny_drop("user-1", "bank-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_already_verified_returns_true(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={"id": "bank-1", "status": BankAccountStatus.VERIFIED.value}
        )
        svc = _make_service(db_pool=pool)
        result = await svc.verify_penny_drop("user-1", "bank-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_failed_account_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={"id": "bank-1", "status": BankAccountStatus.FAILED.value}
        )
        svc = _make_service(db_pool=pool)
        result = await svc.verify_penny_drop("user-1", "bank-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_pending_verified_by_gateway(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={"id": "bank-1", "status": BankAccountStatus.PENDING.value}
        )
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verified": True}

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_penny_drop("user-1", "bank-1")

        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_not_verified_by_gateway(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={"id": "bank-1", "status": BankAccountStatus.PENDING.value}
        )
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verified": False}

        with patch("app.services.bank_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.verify_penny_drop("user-1", "bank-1")

        assert result is False
