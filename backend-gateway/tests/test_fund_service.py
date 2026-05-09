"""Unit tests for FundService — deposit initiation, amount validation,
UPI link generation, balance crediting, failure notification, and reconciliation."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Ensure encryption key is set (shared with bank_service tests)
if "PAN_ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["PAN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from app.services.fund_service import (
    FundService,
    DepositTransaction,
    ReconciliationResult,
    PaymentMethod,
    TransactionStatus,
    MIN_DEPOSIT,
    MAX_DEPOSIT,
    UPI_LINK_EXPIRY_MINUTES,
    MAX_RETRIES,
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


# ── Amount validation tests ──────────────────────────────────────────────────


class TestValidateDepositAmount:
    def test_valid_minimum(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("100"))
        assert valid is True
        assert err is None

    def test_valid_maximum(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("1000000"))
        assert valid is True
        assert err is None

    def test_valid_mid_range(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("50000"))
        assert valid is True
        assert err is None

    def test_below_minimum_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("99"))
        assert valid is False
        assert "Minimum" in err

    def test_zero_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("0"))
        assert valid is False

    def test_negative_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("-100"))
        assert valid is False

    def test_above_maximum_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(Decimal("1000001"))
        assert valid is False
        assert "Maximum" in err

    def test_non_decimal_rejected(self):
        svc = _make_service()
        valid, err = svc.validate_deposit_amount(100)
        assert valid is False
        assert "Decimal" in err


# ── UPI link generation tests ────────────────────────────────────────────────


class TestGenerateUpiLink:
    def test_link_contains_transaction_id(self):
        svc = _make_service()
        link, expires = svc._generate_upi_link("txn-123", Decimal("500"))
        assert "txn-123" in link

    def test_link_contains_amount(self):
        svc = _make_service()
        link, expires = svc._generate_upi_link("txn-123", Decimal("500"))
        assert "500" in link

    def test_link_is_upi_scheme(self):
        svc = _make_service()
        link, expires = svc._generate_upi_link("txn-123", Decimal("500"))
        assert link.startswith("upi://pay")

    def test_link_contains_currency(self):
        svc = _make_service()
        link, expires = svc._generate_upi_link("txn-123", Decimal("500"))
        assert "INR" in link

    def test_expiry_is_15_minutes(self):
        svc = _make_service()
        before = datetime.now(timezone.utc)
        link, expires = svc._generate_upi_link("txn-123", Decimal("500"))
        after = datetime.now(timezone.utc)
        expected_min = before + timedelta(minutes=UPI_LINK_EXPIRY_MINUTES)
        expected_max = after + timedelta(minutes=UPI_LINK_EXPIRY_MINUTES)
        assert expected_min <= expires <= expected_max


# ── Initiate deposit tests ───────────────────────────────────────────────────


class TestInitiateDeposit:
    @pytest.mark.asyncio
    async def test_amount_below_minimum_fails(self):
        svc = _make_service()
        result = await svc.initiate_deposit("user-1", Decimal("50"), PaymentMethod.UPI)
        assert result.status == TransactionStatus.FAILED
        assert "Minimum" in result.failure_reason

    @pytest.mark.asyncio
    async def test_amount_above_maximum_fails(self):
        svc = _make_service()
        result = await svc.initiate_deposit(
            "user-1", Decimal("2000000"), PaymentMethod.NEFT
        )
        assert result.status == TransactionStatus.FAILED
        assert "Maximum" in result.failure_reason

    @pytest.mark.asyncio
    async def test_no_verified_bank_account_fails(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 0})
        svc = _make_service(db_pool=pool)
        result = await svc.initiate_deposit("user-1", Decimal("500"), PaymentMethod.UPI)
        assert result.status == TransactionStatus.FAILED
        assert "bank account" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_no_db_pool_bank_check_fails(self):
        svc = _make_service(db_pool=None)
        result = await svc.initiate_deposit("user-1", Decimal("500"), PaymentMethod.UPI)
        assert result.status == TransactionStatus.FAILED
        assert "bank account" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_gateway_unavailable_fails(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("timeout")
            )
            mock_cls.return_value = mock_client

            with patch(
                "app.services.fund_service.asyncio.sleep", new_callable=AsyncMock
            ):
                result = await svc.initiate_deposit(
                    "user-1", Decimal("500"), PaymentMethod.UPI
                )

        assert result.status == TransactionStatus.FAILED
        assert "gateway unavailable" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_gateway_returns_failed_status(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-001",
            "status": "FAILED",
            "reason": "Insufficient funds at source",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("500"), PaymentMethod.NET_BANKING
            )

        assert result.status == TransactionStatus.FAILED
        assert result.failure_reason == "Insufficient funds at source"

    @pytest.mark.asyncio
    async def test_successful_upi_deposit(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-upi-001",
            "status": "INITIATED",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("1000"), PaymentMethod.UPI
            )

        assert result.status == TransactionStatus.INITIATED
        assert result.payment_method == PaymentMethod.UPI
        assert result.amount == Decimal("1000")
        assert result.transaction_ref == "ref-upi-001"
        assert result.upi_link is not None
        assert "upi://pay" in result.upi_link
        assert result.upi_link_expires_at is not None
        assert result.failure_reason is None

    @pytest.mark.asyncio
    async def test_successful_neft_deposit_no_upi_link(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-neft-001",
            "status": "PROCESSING",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("50000"), PaymentMethod.NEFT
            )

        assert result.status == TransactionStatus.PROCESSING
        assert result.payment_method == PaymentMethod.NEFT
        assert result.upi_link is None
        assert result.upi_link_expires_at is None

    @pytest.mark.asyncio
    async def test_completed_deposit_credits_balance(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-instant-001",
            "status": "COMPLETED",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("5000"), PaymentMethod.UPI
            )

        assert result.status == TransactionStatus.COMPLETED
        assert result.completed_at is not None
        # Verify balance credit was called (execute called for store + credit)
        assert conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_rtgs_method_supported(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-rtgs-001",
            "status": "PROCESSING",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("500000"), PaymentMethod.RTGS
            )

        assert result.status == TransactionStatus.PROCESSING
        assert result.payment_method == PaymentMethod.RTGS

    @pytest.mark.asyncio
    async def test_transaction_has_valid_id(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={"cnt": 1})
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_ref": "ref-001",
            "status": "INITIATED",
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.initiate_deposit(
                "user-1", Decimal("200"), PaymentMethod.UPI
            )

        assert result.id  # non-empty
        assert len(result.id) == 36  # UUID format


# ── Confirm deposit tests ────────────────────────────────────────────────────


class TestConfirmDeposit:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_none(self):
        svc = _make_service(db_pool=None)
        result = await svc.confirm_deposit("txn-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_transaction_not_found_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = _make_service(db_pool=pool)
        result = await svc.confirm_deposit("txn-nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_already_completed_returns_transaction(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "id": "txn-123",
            "user_id": "user-1",
            "amount": Decimal("1000"),
            "payment_method": "UPI",
            "transaction_ref": "ref-001",
            "status": "COMPLETED",
            "failure_reason": None,
            "created_at": datetime.now(timezone.utc),
        })
        svc = _make_service(db_pool=pool)
        result = await svc.confirm_deposit("txn-123")
        assert result is not None
        assert result.status == TransactionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_transaction_returns_none(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "id": "txn-123",
            "user_id": "user-1",
            "amount": Decimal("1000"),
            "payment_method": "UPI",
            "transaction_ref": "ref-001",
            "status": "FAILED",
            "failure_reason": "Payment declined",
            "created_at": datetime.now(timezone.utc),
        })
        svc = _make_service(db_pool=pool)
        result = await svc.confirm_deposit("txn-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_initiated_transaction_gets_completed(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value={
            "id": "txn-123",
            "user_id": "user-1",
            "amount": Decimal("5000"),
            "payment_method": "NET_BANKING",
            "transaction_ref": "ref-002",
            "status": "INITIATED",
            "failure_reason": None,
            "created_at": datetime.now(timezone.utc),
        })
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)
        result = await svc.confirm_deposit("txn-123")
        assert result is not None
        assert result.status == TransactionStatus.COMPLETED
        assert result.completed_at is not None
        # Should have called execute for status update + balance credit
        assert conn.execute.call_count == 2


# ── Credit trading balance tests ─────────────────────────────────────────────


class TestCreditTradingBalance:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_false(self):
        svc = _make_service(db_pool=None)
        result = await svc._credit_trading_balance("user-1", Decimal("1000"))
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_credit(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock()
        svc = _make_service(db_pool=pool)
        result = await svc._credit_trading_balance("user-1", Decimal("5000"))
        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self):
        pool, conn = _make_mock_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = _make_service(db_pool=pool)
        result = await svc._credit_trading_balance("user-1", Decimal("5000"))
        assert result is False


# ── Reconciliation tests ────────────────────────────────────────────────────


class TestReconcileDeposits:
    @pytest.mark.asyncio
    async def test_gateway_unavailable_returns_empty_result(self):
        svc = _make_service()

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("timeout")
            )
            mock_cls.return_value = mock_client

            with patch(
                "app.services.fund_service.asyncio.sleep", new_callable=AsyncMock
            ):
                result = await svc.reconcile_deposits("2024-01-15")

        assert result.total_gateway_transactions == 0
        assert result.matched == 0

    @pytest.mark.asyncio
    async def test_all_matched(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[
            {"transaction_ref": "ref-001", "amount": Decimal("1000"), "status": "COMPLETED"},
            {"transaction_ref": "ref-002", "amount": Decimal("2000"), "status": "COMPLETED"},
        ])
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transactions": [
                {"transaction_ref": "ref-001", "amount": "1000", "status": "COMPLETED"},
                {"transaction_ref": "ref-002", "amount": "2000", "status": "COMPLETED"},
            ]
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.reconcile_deposits("2024-01-15")

        assert result.total_gateway_transactions == 2
        assert result.total_local_transactions == 2
        assert result.matched == 2
        assert result.mismatched == 0
        assert result.missing_locally == 0
        assert result.missing_on_gateway == 0

    @pytest.mark.asyncio
    async def test_amount_mismatch_detected(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[
            {"transaction_ref": "ref-001", "amount": Decimal("1000"), "status": "COMPLETED"},
        ])
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transactions": [
                {"transaction_ref": "ref-001", "amount": "999", "status": "COMPLETED"},
            ]
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.reconcile_deposits("2024-01-15")

        assert result.mismatched == 1
        assert result.matched == 0

    @pytest.mark.asyncio
    async def test_missing_locally_detected(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transactions": [
                {"transaction_ref": "ref-001", "amount": "1000", "status": "COMPLETED"},
            ]
        }

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.reconcile_deposits("2024-01-15")

        assert result.missing_locally == 1

    @pytest.mark.asyncio
    async def test_missing_on_gateway_detected(self):
        pool, conn = _make_mock_pool()
        conn.fetch = AsyncMock(return_value=[
            {"transaction_ref": "ref-001", "amount": Decimal("1000"), "status": "COMPLETED"},
        ])
        svc = _make_service(db_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"transactions": []}

        with patch("app.services.fund_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await svc.reconcile_deposits("2024-01-15")

        assert result.missing_on_gateway == 1
        assert result.reconciled_at is not None


# ── Payment method enum tests ────────────────────────────────────────────────


class TestPaymentMethodEnum:
    def test_upi_value(self):
        assert PaymentMethod.UPI.value == "UPI"

    def test_net_banking_value(self):
        assert PaymentMethod.NET_BANKING.value == "NET_BANKING"

    def test_neft_value(self):
        assert PaymentMethod.NEFT.value == "NEFT"

    def test_rtgs_value(self):
        assert PaymentMethod.RTGS.value == "RTGS"


# ── Transaction status enum tests ────────────────────────────────────────────


class TestTransactionStatusEnum:
    def test_initiated(self):
        assert TransactionStatus.INITIATED.value == "INITIATED"

    def test_processing(self):
        assert TransactionStatus.PROCESSING.value == "PROCESSING"

    def test_completed(self):
        assert TransactionStatus.COMPLETED.value == "COMPLETED"

    def test_failed(self):
        assert TransactionStatus.FAILED.value == "FAILED"
