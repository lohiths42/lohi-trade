"""Bank account and fund management API router.

Endpoints for bank account registration/management, fund deposits,
fund withdrawals, transaction history, and balance queries.

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 4-6 (all)
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id, get_current_user_payload
from app.services.bank_service import (
    BankAccountDetails,
    BankAccountService,
    BankAccountStatus,
)
from app.services.fund_service import (
    FundService,
    PaymentMethod,
    TransactionStatus,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class BankRegisterRequest(BaseModel):
    account_holder_name: str = Field(..., description="Name on the bank account")
    account_number: str = Field(..., description="Bank account number")
    ifsc_code: str = Field(..., description="IFSC code (11 characters)")
    bank_name: str = Field(..., description="Bank name")
    account_type: str = Field(..., description="Account type: savings or current")


class BankAccountItem(BaseModel):
    id: Optional[str] = None
    ifsc_code: str
    bank_name: str
    account_holder_name: str
    account_type: str
    is_primary: bool
    status: str
    rejection_reason: Optional[str] = None
    verified_at: Optional[str] = None
    created_at: Optional[str] = None


class BankRegisterResponse(BaseModel):
    status: str
    account: BankAccountItem
    message: str


class BankListResponse(BaseModel):
    accounts: list[BankAccountItem]
    count: int


class SetPrimaryResponse(BaseModel):
    success: bool
    message: str


class DepositRequest(BaseModel):
    amount: str = Field(..., description="Deposit amount in INR (e.g. '5000.00')")
    payment_method: str = Field(..., description="Payment method: UPI, NET_BANKING, NEFT, RTGS, IMPS")


class DepositResponse(BaseModel):
    transaction_id: str
    amount: str
    payment_method: str
    status: str
    upi_link: Optional[str] = None
    failure_reason: Optional[str] = None
    message: str


class WithdrawRequest(BaseModel):
    amount: str = Field(..., description="Withdrawal amount in INR (e.g. '5000.00')")
    bank_account_id: str = Field(..., description="ID of the verified bank account")


class WithdrawResponse(BaseModel):
    transaction_id: str
    amount: str
    bank_account_id: str
    status: str
    estimated_completion: Optional[str] = None
    failure_reason: Optional[str] = None
    message: str


class TransactionItem(BaseModel):
    id: str
    type: str
    amount: str
    payment_method: Optional[str] = None
    transaction_ref: Optional[str] = None
    status: str
    failure_reason: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class TransactionListResponse(BaseModel):
    transactions: list[TransactionItem]
    count: int


class BalanceResponse(BaseModel):
    available_balance: str
    blocked_margin: str
    withdrawable_balance: str


class MessageResponse(BaseModel):
    message: str


# ── Service dependencies ─────────────────────────────────────────────────────

_bank_service: Optional[BankAccountService] = None
_fund_service: Optional[FundService] = None


def set_bank_services(
    bank: BankAccountService,
    fund: FundService,
) -> None:
    """Called at app startup to inject service instances."""
    global _bank_service, _fund_service
    _bank_service = bank
    _fund_service = fund


def get_bank_service() -> BankAccountService:
    if _bank_service is None:
        raise HTTPException(status_code=503, detail="Bank account service not initialized")
    return _bank_service


def get_fund_service() -> FundService:
    if _fund_service is None:
        raise HTTPException(status_code=503, detail="Fund service not initialized")
    return _fund_service


# ── Bank Account Endpoints ───────────────────────────────────────────────────


@router.post("/bank/register", response_model=BankRegisterResponse)
async def register_bank_account(
    req: BankRegisterRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BankAccountService = Depends(get_bank_service),
):
    """Register a new bank account with IFSC validation and penny drop verification.

    Requirements: 4.1-4.9
    """
    try:
        details = BankAccountDetails(
            account_holder_name=req.account_holder_name,
            account_number=req.account_number,
            ifsc_code=req.ifsc_code,
            bank_name=req.bank_name,
            account_type=req.account_type,
        )
        result = await svc.register_bank_account(user_id, details)
        logger.info(
            "BANK_EVENT register user=%s status=%s",
            user_id, result.status.value,
        )
        account_item = BankAccountItem(
            id=result.id,
            ifsc_code=result.ifsc_code,
            bank_name=result.bank_name,
            account_holder_name=result.account_holder_name,
            account_type=result.account_type,
            is_primary=result.is_primary,
            status=result.status.value,
            rejection_reason=result.rejection_reason,
            verified_at=result.verified_at.isoformat() if result.verified_at else None,
            created_at=result.created_at.isoformat() if result.created_at else None,
        )
        if result.status == BankAccountStatus.VERIFIED:
            message = "Bank account registered and verified successfully"
        else:
            message = f"Bank account registration failed: {result.rejection_reason}"
        return BankRegisterResponse(
            status=result.status.value,
            account=account_item,
            message=message,
        )
    except Exception:
        logger.exception("Bank registration error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Bank account registration failed unexpectedly")


@router.get("/bank/list", response_model=BankListResponse)
async def list_bank_accounts(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BankAccountService = Depends(get_bank_service),
):
    """List all bank accounts for the authenticated user.

    Requirements: 4.7, 4.8
    """
    if svc.db_pool is None:
        return BankListResponse(accounts=[], count=0)

    try:
        async with svc.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, ifsc_code, bank_name, account_holder_name,
                          account_type, is_primary, status, verified_at, created_at
                   FROM bank_accounts
                   WHERE user_id = $1
                   ORDER BY created_at DESC""",
                user_id,
            )
        accounts = [
            BankAccountItem(
                id=str(row["id"]),
                ifsc_code=row["ifsc_code"],
                bank_name=row["bank_name"],
                account_holder_name=row["account_holder_name"],
                account_type=row["account_type"],
                is_primary=row["is_primary"],
                status=row["status"],
                verified_at=row["verified_at"].isoformat() if row["verified_at"] else None,
                created_at=row["created_at"].isoformat() if row["created_at"] else None,
            )
            for row in rows
        ]
        return BankListResponse(accounts=accounts, count=len(accounts))
    except Exception:
        logger.exception("Failed to list bank accounts for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve bank accounts")


@router.put("/bank/{bank_id}/primary", response_model=SetPrimaryResponse)
async def set_primary_bank_account(
    bank_id: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: BankAccountService = Depends(get_bank_service),
):
    """Set a bank account as the primary account for withdrawals.

    Requirements: 4.8
    """
    if svc.db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with svc.db_pool.acquire() as conn:
            # Verify the account exists, belongs to user, and is VERIFIED
            row = await conn.fetchrow(
                "SELECT id, status FROM bank_accounts WHERE id = $1 AND user_id = $2",
                bank_id, user_id,
            )
            if row is None:
                return SetPrimaryResponse(success=False, message="Bank account not found")
            if row["status"] != BankAccountStatus.VERIFIED.value:
                return SetPrimaryResponse(
                    success=False,
                    message="Only verified bank accounts can be set as primary",
                )

            # Unset all primary flags, then set the requested one
            await conn.execute(
                "UPDATE bank_accounts SET is_primary = FALSE WHERE user_id = $1",
                user_id,
            )
            await conn.execute(
                "UPDATE bank_accounts SET is_primary = TRUE WHERE id = $1 AND user_id = $2",
                bank_id, user_id,
            )

        logger.info("BANK_EVENT set_primary user=%s bank_id=%s", user_id, bank_id)
        return SetPrimaryResponse(success=True, message="Primary bank account updated")
    except Exception:
        logger.exception("Failed to set primary bank for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to update primary bank account")


# ── Fund Endpoints ───────────────────────────────────────────────────────────


@router.post("/fund/deposit", response_model=DepositResponse)
async def deposit_funds(
    req: DepositRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: FundService = Depends(get_fund_service),
):
    """Initiate a fund deposit via UPI, net banking, or NEFT/RTGS.

    Requirements: 5.1-5.8
    """
    try:
        amount = Decimal(req.amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount format")

    try:
        method = PaymentMethod(req.payment_method)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid payment method. Must be one of: {', '.join(m.value for m in PaymentMethod)}",
        )

    try:
        result = await svc.initiate_deposit(user_id, amount, method)
        logger.info(
            "FUND_EVENT deposit user=%s amount=%s method=%s status=%s",
            user_id, amount, method.value, result.status.value,
        )
        if result.status == TransactionStatus.FAILED:
            message = f"Deposit failed: {result.failure_reason}"
        elif result.status == TransactionStatus.COMPLETED:
            message = "Deposit completed successfully"
        else:
            message = "Deposit initiated successfully"

        return DepositResponse(
            transaction_id=result.id,
            amount=str(result.amount),
            payment_method=result.payment_method.value,
            status=result.status.value,
            upi_link=result.upi_link,
            failure_reason=result.failure_reason,
            message=message,
        )
    except Exception:
        logger.exception("Deposit error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Deposit failed unexpectedly")


@router.post("/fund/withdraw", response_model=WithdrawResponse)
async def withdraw_funds(
    req: WithdrawRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: FundService = Depends(get_fund_service),
):
    """Initiate a fund withdrawal to a verified bank account.

    Requirements: 6.1-6.8
    """
    try:
        amount = Decimal(req.amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount format")

    try:
        result = await svc.initiate_withdrawal(user_id, amount, req.bank_account_id)
        logger.info(
            "FUND_EVENT withdraw user=%s amount=%s bank=%s status=%s",
            user_id, amount, req.bank_account_id, result.status.value,
        )
        if result.status == WithdrawalStatus.FAILED:
            message = f"Withdrawal failed: {result.failure_reason}"
        elif result.status == WithdrawalStatus.COMPLETED:
            message = "Withdrawal completed successfully"
        else:
            message = "Withdrawal initiated successfully"

        return WithdrawResponse(
            transaction_id=result.id,
            amount=str(result.amount),
            bank_account_id=result.bank_account_id,
            status=result.status.value,
            estimated_completion=result.estimated_completion,
            failure_reason=result.failure_reason,
            message=message,
        )
    except Exception:
        logger.exception("Withdrawal error for user %s", user_id)
        raise HTTPException(status_code=500, detail="Withdrawal failed unexpectedly")


@router.get("/fund/transactions", response_model=TransactionListResponse)
async def list_transactions(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: FundService = Depends(get_fund_service),
):
    """List all fund transactions (deposits and withdrawals) for the user.

    Requirements: 5.6, 6.6
    """
    if svc.db_pool is None:
        return TransactionListResponse(transactions=[], count=0)

    try:
        async with svc.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, type, amount, payment_method, transaction_ref,
                          status, failure_reason, created_at, completed_at
                   FROM fund_transactions
                   WHERE user_id = $1
                   ORDER BY created_at DESC""",
                user_id,
            )
        transactions = [
            TransactionItem(
                id=str(row["id"]),
                type=row["type"],
                amount=str(row["amount"]),
                payment_method=row["payment_method"],
                transaction_ref=row["transaction_ref"],
                status=row["status"],
                failure_reason=row["failure_reason"],
                created_at=row["created_at"].isoformat() if row["created_at"] else None,
                completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
            )
            for row in rows
        ]
        return TransactionListResponse(transactions=transactions, count=len(transactions))
    except Exception:
        logger.exception("Failed to list transactions for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve transactions")


@router.get("/fund/balance", response_model=BalanceResponse)
async def get_balance(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: FundService = Depends(get_fund_service),
):
    """Get the user's trading balance including withdrawable amount.

    Requirements: 6.1
    """
    if svc.db_pool is None:
        return BalanceResponse(
            available_balance="0.00",
            blocked_margin="0.00",
            withdrawable_balance="0.00",
        )

    try:
        async with svc.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT available_balance, blocked_margin FROM trading_balances WHERE user_id = $1",
                user_id,
            )

        if row is None:
            return BalanceResponse(
                available_balance="0.00",
                blocked_margin="0.00",
                withdrawable_balance="0.00",
            )

        available = row["available_balance"] or Decimal("0")
        blocked = row["blocked_margin"] or Decimal("0")
        withdrawable = max(available - blocked, Decimal("0"))

        return BalanceResponse(
            available_balance=str(available),
            blocked_margin=str(blocked),
            withdrawable_balance=str(withdrawable),
        )
    except Exception:
        logger.exception("Failed to get balance for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve balance")
