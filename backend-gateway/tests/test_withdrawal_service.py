"""Unit tests for FundService — withdrawal initiation, amount validation,
withdrawable balance, daily limits, bank account verification, IST cutoff,
debit reversal on failure, and transaction storage."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Ensure encryption key is set
if "PAN_ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet

    os.environ["PAN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from app.services.fund_service import (
    FundService,
    PaymentMethod,
    WithdrawalStatus,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(db_pool=None) -> FundService:
    return FundService(
        db_pool=db_pool,
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


# ── Withdrawal amount validation tests ───────────────────────────────────────


class TestValidateWithdrawalAmount:
    def test_valid_minimum(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(Decimal("100"))
        assert valid is True
        assert err is None

    def test_valid_large_amount(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(Decimal("500000"))
        assert valid is True
        assert err is None

    def test_below_minimum_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(Decimal("99"))
        assert valid is False
        assert "Minimum" in err

    def test_zero_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(Decimal("0"))
        assert valid is False

    def test_negative_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(Decimal("-50"))
        assert valid is False

    def test_non_decimal_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_withdrawal_amount(100)
        assert valid is False
        assert "Decimal" in err


# ── Withdrawable balance tests ───────────────────────────────────────────────


class TestGetWithdrawableBalance:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_zero(self):
        svc = _make_service(db_pool=None)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("0")

    @pytest.mark.asyncio
    async def test_no_balance_record_returns_zero(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("0")

    @pytest.mark.asyncio
    async def test_balance_minus_margin(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={
                "available_balance": Decimal("50000"),
                "blocked_margin": Decimal("10000"),
            }
        )
        svc = _make_service(db_pool=pool)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("40000")

    @pytest.mark.asyncio
    async def test_zero_margin_full_balance(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={
                "available_balance": Decimal("100000"),
                "blocked_margin": Decimal("0"),
            }
        )
        svc = _make_service(db_pool=pool)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("100000")

    @pytest.mark.asyncio
    async def test_margin_exceeds_balance_returns_zero(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={
                "available_balance": Decimal("5000"),
                "blocked_margin": Decimal("10000"),
            }
        )
        svc = _make_service(db_pool=pool)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("0")

    @pytest.mark.asyncio
    async def test_db_error_returns_zero(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        svc = _make_service(db_pool=pool)
        result = await svc.get_withdrawable_balance("user-1")
        assert result == Decimal("0")


# ── IST cutoff tests ────────────────────────────────────────────────────────


class TestEstimatedCompletion:
    def test_before_cutoff_same_day(self):
        # 10:00 AM IST = 4:30 AM UTC
        now_utc = datetime(2024, 3, 15, 4, 30, 0, tzinfo=timezone.utc)
        result = FundService._get_estimated_completion(now_utc)
        assert result == "same_day"

    def test_after_cutoff_next_business_day(self):
        # 5:00 PM IST = 11:30 AM UTC
        now_utc = datetime(2024, 3, 15, 11, 30, 0, tzinfo=timezone.utc)
        result = FundService._get_estimated_completion(now_utc)
        assert result == "next_business_day"

    def test_exactly_at_cutoff_next_business_day(self):
        # 4:00 PM IST = 10:30 AM UTC
        now_utc = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = FundService._get_estimated_completion(now_utc)
        assert result == "next_business_day"

    def test_just_before_cutoff_same_day(self):
        # 3:59 PM IST = 10:29 AM UTC
        now_utc = datetime(2024, 3, 15, 10, 29, 0, tzinfo=timezone.utc)
        result = FundService._get_estimated_completion(now_utc)
        assert result == "same_day"


# ── Initiate withdrawal tests ────────────────────────────────────────────────


class TestInitiateWithdrawal:
    @pytest.mark.asyncio
    async def test_amount_below_minimum_fails(self):
        svc = _make_service()
        result = await svc.initiate_withdrawal("user-1", Decimal("50"), "bank-1")
        assert result.status == WithdrawalStatus.FAILED
        assert "Minimum" in result.failure_reason

    @pytest.mark.asyncio
    async def test_unverified_bank_account_fails(self):
        pool, conn = _make_mock_pool()
        # _get_verified_bank_account returns None
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)
        result = await svc.initiate_withdrawal("user-1", Decimal("500"), "bank-bad")
        assert result.status == WithdrawalStatus.FAILED
        assert "not found or not verified" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_no_db_pool_bank_check_fails(self):
        svc = _make_service(db_pool=None)
        result = await svc.initiate_withdrawal("user-1", Decimal("500"), "bank-1")
        assert result.status == WithdrawalStatus.FAILED
        assert "not found or not verified" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_insufficient_balance_fails(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_verified_bank_account
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                # get_withdrawable_balance
                return {"available_balance": Decimal("200"), "blocked_margin": Decimal("100")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        svc = _make_service(db_pool=pool)
        result = await svc.initiate_withdrawal("user-1", Decimal("500"), "bank-1")
        assert result.status == WithdrawalStatus.FAILED
        assert "Insufficient" in result.failure_reason

    @pytest.mark.asyncio
    async def test_daily_limit_exceeded_fails(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_verified_bank_account
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                # get_withdrawable_balance
                return {"available_balance": Decimal("5000000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                # _get_daily_withdrawal_total
                return {"total": Decimal("2400000")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        svc = _make_service(db_pool=pool)
        result = await svc.initiate_withdrawal("user-1", Decimal("200000"), "bank-1")
        assert result.status == WithdrawalStatus.FAILED
        assert "Daily withdrawal limit" in result.failure_reason

    @pytest.mark.asyncio
    async def test_gateway_unavailable_reverses_debit(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("50000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                return {"total": Decimal("0")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client

            with patch("app.services.fund_service.asyncio.sleep", new_callable=AsyncMock):
                result = await svc.initiate_withdrawal("user-1", Decimal("5000"), "bank-1")

        assert result.status == WithdrawalStatus.FAILED
        assert "debit reversed" in result.failure_reason.lower()
        # Verify debit + reverse happened (execute called for debit, then credit for reverse, then store)
        assert conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_gateway_returns_failed_reverses_debit(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("50000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                return {"total": Decimal("0")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-w-001",
            "status": "FAILED",
            "reason": "Bank account inactive",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_withdrawal("user-1", Decimal("5000"), "bank-1")

        assert result.status == WithdrawalStatus.FAILED
        assert result.failure_reason == "Bank account inactive"

    @pytest.mark.asyncio
    async def test_successful_withdrawal(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("100000"), "blocked_margin": Decimal("10000")}
            elif call_count == 3:
                return {"total": Decimal("0")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-w-002",
            "status": "PROCESSING",
            "method": "NEFT",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_withdrawal("user-1", Decimal("5000"), "bank-1")

        assert result.status == WithdrawalStatus.PROCESSING
        assert result.amount == Decimal("5000")
        assert result.transaction_ref == "ref-w-002"
        assert result.bank_account_id == "bank-1"
        assert result.payment_method == PaymentMethod.NEFT
        assert result.estimated_completion in ("same_day", "next_business_day")
        assert result.failure_reason is None
        assert result.id  # non-empty UUID

    @pytest.mark.asyncio
    async def test_successful_withdrawal_imps(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "SBIN0012345",
                    "bank_name": "SBI",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("50000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                return {"total": Decimal("0")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-w-imps-001",
            "status": "PROCESSING",
            "method": "IMPS",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_withdrawal("user-1", Decimal("1000"), "bank-1")

        assert result.status == WithdrawalStatus.PROCESSING
        assert result.payment_method == PaymentMethod.IMPS

    @pytest.mark.asyncio
    async def test_completed_withdrawal_has_completed_at(self):
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("50000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                return {"total": Decimal("0")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-w-003",
            "status": "COMPLETED",
            "method": "IMPS",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_withdrawal("user-1", Decimal("2000"), "bank-1")

        assert result.status == WithdrawalStatus.COMPLETED
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_daily_limit_exact_boundary_succeeds(self):
        """Withdrawal that brings daily total exactly to the limit should succeed."""
        pool, conn = _make_mock_pool()
        call_count = 0

        async def mock_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": "bank-1",
                    "ifsc_code": "HDFC0001234",
                    "bank_name": "HDFC",
                    "account_holder_name": "Test User",
                }
            elif call_count == 2:
                return {"available_balance": Decimal("5000000"), "blocked_margin": Decimal("0")}
            elif call_count == 3:
                return {"total": Decimal("2400000")}
            return None

        conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-w-exact",
            "status": "PROCESSING",
            "method": "NEFT",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            # 2400000 + 100000 = 2500000 = exactly the limit
            result = await svc.initiate_withdrawal("user-1", Decimal("100000"), "bank-1")

        assert result.status == WithdrawalStatus.PROCESSING


# ── Debit / reverse debit tests ──────────────────────────────────────────────


class TestDebitAndReverse:
    @pytest.mark.asyncio
    async def test_debit_no_db_returns_false(self):
        svc = _make_service(db_pool=None)
        result = await svc._debit_trading_balance("user-1", Decimal("1000"))
        assert result is False

    @pytest.mark.asyncio
    async def test_debit_success(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)
        result = await svc._debit_trading_balance("user-1", Decimal("5000"))
        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_debit_db_error_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = _make_service(db_pool=pool)
        result = await svc._debit_trading_balance("user-1", Decimal("5000"))
        assert result is False

    @pytest.mark.asyncio
    async def test_reverse_debit_credits_back(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)
        result = await svc._reverse_withdrawal_debit("user-1", Decimal("5000"))
        assert result is True


# ── WithdrawalStatus enum tests ──────────────────────────────────────────────


class TestWithdrawalStatusEnum:
    def test_requested(self):
        assert WithdrawalStatus.REQUESTED.value == "REQUESTED"

    def test_processing(self):
        assert WithdrawalStatus.PROCESSING.value == "PROCESSING"

    def test_completed(self):
        assert WithdrawalStatus.COMPLETED.value == "COMPLETED"

    def test_failed(self):
        assert WithdrawalStatus.FAILED.value == "FAILED"
