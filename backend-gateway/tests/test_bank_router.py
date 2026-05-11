"""Unit tests for bank account and fund management API router endpoints."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.bank import (
    router,
    get_bank_service,
    get_fund_service,
)
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.bank_service import (
    BankAccount,
    BankAccountService,
    BankAccountStatus,
)
from app.services.fund_service import (
    DepositTransaction,
    FundService,
    PaymentMethod,
    TransactionStatus,
    WithdrawalStatus,
    WithdrawalTransaction,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "test-user-bank-001"


def _create_test_app(
    bank_svc: BankAccountService = None,
    fund_svc: FundService = None,
    role: str = "TRADER",
) -> FastAPI:
    """Create a minimal FastAPI app with the bank router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "role": role,
        "type": "access",
    }

    if bank_svc is not None:
        app.dependency_overrides[get_bank_service] = lambda: bank_svc
    if fund_svc is not None:
        app.dependency_overrides[get_fund_service] = lambda: fund_svc

    return app


def _make_mock_pool(mock_conn):
    """Create a mock asyncpg pool with proper async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


# ── Bank Register Tests ──────────────────────────────────────────────────────


class TestRegisterBankAccount:
    def test_successful_registration(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        now = datetime(2024, 3, 1, tzinfo=timezone.utc)
        mock_bank.register_bank_account = AsyncMock(return_value=BankAccount(
            id="bank-001",
            user_id=TEST_USER_ID,
            ifsc_code="HDFC0001234",
            bank_name="HDFC Bank",
            account_holder_name="John Doe",
            account_type="savings",
            is_primary=True,
            status=BankAccountStatus.VERIFIED,
            verified_at=now,
            created_at=now,
        ))

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.post("/api/v2/bank/register", json={
            "account_holder_name": "John Doe",
            "account_number": "1234567890",
            "ifsc_code": "HDFC0001234",
            "bank_name": "HDFC Bank",
            "account_type": "savings",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "VERIFIED"
        assert data["account"]["id"] == "bank-001"
        assert data["account"]["is_primary"] is True
        assert "successfully" in data["message"]

    def test_registration_failed_invalid_ifsc(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_bank.register_bank_account = AsyncMock(return_value=BankAccount(
            status=BankAccountStatus.FAILED,
            rejection_reason="invalid_ifsc",
            ifsc_code="BAD",
            bank_name="Test Bank",
            account_holder_name="John",
            account_type="savings",
        ))

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.post("/api/v2/bank/register", json={
            "account_holder_name": "John",
            "account_number": "123",
            "ifsc_code": "BAD",
            "bank_name": "Test Bank",
            "account_type": "savings",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["account"]["rejection_reason"] == "invalid_ifsc"
        assert "failed" in data["message"]

    def test_registration_missing_field_returns_422(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.post("/api/v2/bank/register", json={"account_holder_name": "John"})
        assert resp.status_code == 422

    def test_service_not_initialized_returns_503(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v2")
        app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": TEST_USER_ID, "email": "t@t.com", "role": "TRADER", "type": "access",
        }
        client = TestClient(app)
        resp = client.post("/api/v2/bank/register", json={
            "account_holder_name": "John",
            "account_number": "123",
            "ifsc_code": "HDFC0001234",
            "bank_name": "HDFC",
            "account_type": "savings",
        })
        assert resp.status_code == 503


# ── Bank List Tests ──────────────────────────────────────────────────────────


class TestListBankAccounts:
    def test_list_with_accounts(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {
                "id": "bank-001",
                "ifsc_code": "HDFC0001234",
                "bank_name": "HDFC Bank",
                "account_holder_name": "John Doe",
                "account_type": "savings",
                "is_primary": True,
                "status": "VERIFIED",
                "verified_at": datetime(2024, 1, 10, tzinfo=timezone.utc),
                "created_at": datetime(2024, 1, 10, tzinfo=timezone.utc),
            },
            {
                "id": "bank-002",
                "ifsc_code": "SBIN0012345",
                "bank_name": "SBI",
                "account_holder_name": "John Doe",
                "account_type": "current",
                "is_primary": False,
                "status": "VERIFIED",
                "verified_at": datetime(2024, 2, 5, tzinfo=timezone.utc),
                "created_at": datetime(2024, 2, 5, tzinfo=timezone.utc),
            },
        ])
        mock_bank.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.get("/api/v2/bank/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["accounts"][0]["bank_name"] == "HDFC Bank"
        assert data["accounts"][0]["is_primary"] is True
        assert data["accounts"][1]["bank_name"] == "SBI"

    def test_list_empty(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_bank.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.get("/api/v2/bank/list")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["accounts"] == []

    def test_list_no_db_pool(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_bank.db_pool = None

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.get("/api/v2/bank/list")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── Set Primary Tests ────────────────────────────────────────────────────────


class TestSetPrimaryBankAccount:
    def test_set_primary_success(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "bank-001",
            "status": "VERIFIED",
        })
        mock_conn.execute = AsyncMock()
        mock_bank.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.put("/api/v2/bank/bank-001/primary")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "updated" in data["message"]

    def test_set_primary_not_found(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_bank.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.put("/api/v2/bank/nonexistent/primary")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not found" in data["message"]

    def test_set_primary_not_verified(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "bank-001",
            "status": "PENDING",
        })
        mock_bank.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.put("/api/v2/bank/bank-001/primary")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "verified" in data["message"].lower()

    def test_set_primary_no_db_pool(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_bank.db_pool = None

        app = _create_test_app(bank_svc=mock_bank)
        client = TestClient(app)
        resp = client.put("/api/v2/bank/bank-001/primary")

        assert resp.status_code == 503


# ── Deposit Tests ────────────────────────────────────────────────────────────


class TestDepositFunds:
    def test_successful_upi_deposit(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.initiate_deposit = AsyncMock(return_value=DepositTransaction(
            id="txn-001",
            user_id=TEST_USER_ID,
            amount=Decimal("5000"),
            payment_method=PaymentMethod.UPI,
            status=TransactionStatus.INITIATED,
            upi_link="upi://pay?pa=lohi-trade@upi&tr=txn-001&am=5000&cu=INR",
            created_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "5000",
            "payment_method": "UPI",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "INITIATED"
        assert data["transaction_id"] == "txn-001"
        assert data["upi_link"] is not None
        assert "initiated" in data["message"]

    def test_deposit_completed(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.initiate_deposit = AsyncMock(return_value=DepositTransaction(
            id="txn-002",
            user_id=TEST_USER_ID,
            amount=Decimal("1000"),
            payment_method=PaymentMethod.NET_BANKING,
            status=TransactionStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "1000",
            "payment_method": "NET_BANKING",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert "completed" in data["message"]

    def test_deposit_failed_amount_too_low(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.initiate_deposit = AsyncMock(return_value=DepositTransaction(
            id="txn-003",
            user_id=TEST_USER_ID,
            amount=Decimal("50"),
            payment_method=PaymentMethod.UPI,
            status=TransactionStatus.FAILED,
            failure_reason="Minimum deposit is ₹100",
            created_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "50",
            "payment_method": "UPI",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["failure_reason"] is not None
        assert "failed" in data["message"].lower()

    def test_deposit_invalid_amount_format(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "not-a-number",
            "payment_method": "UPI",
        })
        assert resp.status_code == 400
        assert "Invalid amount" in resp.json()["detail"]

    def test_deposit_invalid_payment_method(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "1000",
            "payment_method": "BITCOIN",
        })
        assert resp.status_code == 400
        assert "Invalid payment method" in resp.json()["detail"]

    def test_deposit_missing_fields_returns_422(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={})
        assert resp.status_code == 422


# ── Withdrawal Tests ─────────────────────────────────────────────────────────


class TestWithdrawFunds:
    def test_successful_withdrawal(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.initiate_withdrawal = AsyncMock(return_value=WithdrawalTransaction(
            id="wtxn-001",
            user_id=TEST_USER_ID,
            amount=Decimal("10000"),
            bank_account_id="bank-001",
            status=WithdrawalStatus.PROCESSING,
            estimated_completion="same_day",
            created_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/withdraw", json={
            "amount": "10000",
            "bank_account_id": "bank-001",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "PROCESSING"
        assert data["estimated_completion"] == "same_day"
        assert "initiated" in data["message"]

    def test_withdrawal_failed_insufficient_balance(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.initiate_withdrawal = AsyncMock(return_value=WithdrawalTransaction(
            id="wtxn-002",
            user_id=TEST_USER_ID,
            amount=Decimal("999999"),
            bank_account_id="bank-001",
            status=WithdrawalStatus.FAILED,
            failure_reason="Insufficient withdrawable balance. Available: ₹5000",
            created_at=datetime.now(timezone.utc),
        ))

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/withdraw", json={
            "amount": "999999",
            "bank_account_id": "bank-001",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert "Insufficient" in data["failure_reason"]

    def test_withdrawal_invalid_amount(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/withdraw", json={
            "amount": "abc",
            "bank_account_id": "bank-001",
        })
        assert resp.status_code == 400

    def test_withdrawal_missing_fields_returns_422(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.post("/api/v2/fund/withdraw", json={})
        assert resp.status_code == 422


# ── Transaction List Tests ───────────────────────────────────────────────────


class TestListTransactions:
    def test_list_with_transactions(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {
                "id": "txn-001",
                "type": "DEPOSIT",
                "amount": Decimal("5000"),
                "payment_method": "UPI",
                "transaction_ref": "ref-001",
                "status": "COMPLETED",
                "failure_reason": None,
                "created_at": datetime(2024, 3, 1, tzinfo=timezone.utc),
                "completed_at": datetime(2024, 3, 1, tzinfo=timezone.utc),
            },
            {
                "id": "wtxn-001",
                "type": "WITHDRAWAL",
                "amount": Decimal("2000"),
                "payment_method": "NEFT",
                "transaction_ref": "ref-002",
                "status": "PROCESSING",
                "failure_reason": None,
                "created_at": datetime(2024, 3, 2, tzinfo=timezone.utc),
                "completed_at": None,
            },
        ])
        mock_fund.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/transactions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["transactions"][0]["type"] == "DEPOSIT"
        assert data["transactions"][1]["type"] == "WITHDRAWAL"

    def test_list_empty(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_fund.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/transactions")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_no_db_pool(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.db_pool = None

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/transactions")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── Balance Tests ────────────────────────────────────────────────────────────


class TestGetBalance:
    def test_balance_with_data(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "available_balance": Decimal("50000"),
            "blocked_margin": Decimal("10000"),
        })
        mock_fund.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/balance")

        assert resp.status_code == 200
        data = resp.json()
        assert data["available_balance"] == "50000"
        assert data["blocked_margin"] == "10000"
        assert data["withdrawable_balance"] == "40000"

    def test_balance_no_record(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_fund.db_pool = _make_mock_pool(mock_conn)

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/balance")

        assert resp.status_code == 200
        data = resp.json()
        assert data["available_balance"] == "0.00"
        assert data["withdrawable_balance"] == "0.00"

    def test_balance_no_db_pool(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.db_pool = None

        app = _create_test_app(fund_svc=mock_fund)
        client = TestClient(app)
        resp = client.get("/api/v2/fund/balance")

        assert resp.status_code == 200
        data = resp.json()
        assert data["available_balance"] == "0.00"


# ── RBAC Tests ───────────────────────────────────────────────────────────────


class TestBankRBACEnforcement:
    def test_viewer_role_denied_bank_register(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        app = _create_test_app(bank_svc=mock_bank, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/bank/register", json={
            "account_holder_name": "John",
            "account_number": "123",
            "ifsc_code": "HDFC0001234",
            "bank_name": "HDFC",
            "account_type": "savings",
        })
        assert resp.status_code == 403

    def test_viewer_role_denied_deposit(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/fund/deposit", json={
            "amount": "1000",
            "payment_method": "UPI",
        })
        assert resp.status_code == 403

    def test_viewer_role_denied_withdraw(self):
        mock_fund = AsyncMock(spec=FundService)
        app = _create_test_app(fund_svc=mock_fund, role="VIEWER")
        client = TestClient(app)
        resp = client.post("/api/v2/fund/withdraw", json={
            "amount": "1000",
            "bank_account_id": "bank-001",
        })
        assert resp.status_code == 403

    def test_admin_role_allowed_bank_list(self):
        mock_bank = AsyncMock(spec=BankAccountService)
        mock_bank.db_pool = None
        app = _create_test_app(bank_svc=mock_bank, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/bank/list")
        assert resp.status_code == 200

    def test_admin_role_allowed_balance(self):
        mock_fund = AsyncMock(spec=FundService)
        mock_fund.db_pool = None
        app = _create_test_app(fund_svc=mock_fund, role="ADMIN")
        client = TestClient(app)
        resp = client.get("/api/v2/fund/balance")
        assert resp.status_code == 200
