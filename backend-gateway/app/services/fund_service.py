"""Fund deposit service.

Handles fund deposits via UPI, net banking, and NEFT/RTGS.
Generates UPI payment links, credits trading balances on confirmation,
enforces deposit limits, records transactions, and runs daily reconciliation.
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MIN_DEPOSIT = Decimal("100")
MAX_DEPOSIT = Decimal("1000000")
UPI_LINK_EXPIRY_MINUTES = 15

MIN_WITHDRAWAL = Decimal("100")
DAILY_MAX_WITHDRAWAL = Decimal("2500000")

# IST cutoff: 4:00 PM IST = 10:30 UTC
WITHDRAWAL_CUTOFF_HOUR_IST = 16
WITHDRAWAL_CUTOFF_MINUTE_IST = 0

# Retry configuration (same pattern as bank_service)
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
API_TIMEOUT_SECONDS = 10


# ── Enums ────────────────────────────────────────────────────────────────────


class PaymentMethod(str, Enum):
    UPI = "UPI"
    NET_BANKING = "NET_BANKING"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"


class TransactionStatus(str, Enum):
    INITIATED = "INITIATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class DepositTransaction:
    """A fund deposit transaction record."""

    id: str = ""
    user_id: str = ""
    amount: Decimal = Decimal("0")
    payment_method: PaymentMethod = PaymentMethod.UPI
    transaction_ref: str = ""
    status: TransactionStatus = TransactionStatus.INITIATED
    failure_reason: Optional[str] = None
    upi_link: Optional[str] = None
    upi_link_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class ReconciliationResult:
    """Result of daily reconciliation run."""

    total_gateway_transactions: int = 0
    total_local_transactions: int = 0
    matched: int = 0
    mismatched: int = 0
    missing_locally: int = 0
    missing_on_gateway: int = 0
    reconciled_at: Optional[datetime] = None


@dataclass
class WithdrawalTransaction:
    """A fund withdrawal transaction record."""

    id: str = ""
    user_id: str = ""
    amount: Decimal = Decimal("0")
    bank_account_id: str = ""
    payment_method: PaymentMethod = PaymentMethod.NEFT
    transaction_ref: str = ""
    status: WithdrawalStatus = WithdrawalStatus.REQUESTED
    failure_reason: Optional[str] = None
    estimated_completion: Optional[str] = None  # "same_day" or "next_business_day"
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Fund Service ─────────────────────────────────────────────────────────────


class FundService:
    """Fund deposit management service.

    Supports UPI, net banking, and NEFT/RTGS deposits with amount validation,
    payment gateway integration, balance crediting, and daily reconciliation.
    """

    def __init__(
        self,
        db_pool=None,
        payment_api_url: str = "",
        payment_api_key: str = "",
    ):
        self.db_pool = db_pool
        self.payment_api_url = payment_api_url or os.getenv(
            "PAYMENT_API_URL", "https://api.payment-gateway.co.in"
        )
        self.payment_api_key = payment_api_key or os.getenv("PAYMENT_API_KEY", "")

    # ── Amount validation ────────────────────────────────────────────────

    def validate_deposit_amount(self, amount: Decimal) -> tuple[bool, Optional[str]]:
        """Validate deposit amount is within allowed range.

        Returns (is_valid, error_message).
        Min ₹100, Max ₹10,00,000.
        """
        if not isinstance(amount, Decimal):
            return False, "Amount must be a Decimal"
        if amount < MIN_DEPOSIT:
            return False, f"Minimum deposit is ₹{MIN_DEPOSIT}"
        if amount > MAX_DEPOSIT:
            return False, f"Maximum deposit is ₹{MAX_DEPOSIT}"
        return True, None

    # ── Verified bank account check ──────────────────────────────────────

    async def _has_verified_bank_account(self, user_id: str) -> bool:
        """Check that the user has at least one VERIFIED bank account."""
        if self.db_pool is None:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as cnt FROM bank_accounts "
                    "WHERE user_id = $1 AND status = 'VERIFIED'",
                    user_id,
                )
                return row is not None and row["cnt"] > 0
        except Exception:
            logger.exception("Failed to check bank accounts for user %s", user_id)
            return False

    # ── Payment gateway interaction ──────────────────────────────────────

    async def _call_payment_gateway(self, endpoint: str, payload: dict) -> Optional[dict]:
        """Call payment gateway API with retry and exponential backoff.

        Returns response dict on success, None on failure.
        """
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.payment_api_url}/{endpoint}",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.payment_api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code == 200:
                        return response.json()
                    else:
                        logger.warning(
                            "Payment API %s returned status %d on attempt %d",
                            endpoint,
                            response.status_code,
                            attempt + 1,
                        )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
                last_exception = exc
                logger.warning(
                    "Payment API %s attempt %d/%d failed: %s",
                    endpoint,
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "Payment API %s unreachable after %d attempts. Last error: %s",
            endpoint,
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── UPI link generation ──────────────────────────────────────────────

    def _generate_upi_link(self, transaction_id: str, amount: Decimal) -> tuple[str, datetime]:
        """Generate a UPI payment link with 15-minute expiry.

        Returns (upi_link, expires_at).
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=UPI_LINK_EXPIRY_MINUTES)
        upi_link = (
            f"upi://pay?pa=lohi-trade@upi"
            f"&pn=LOHI-TRADE"
            f"&tr={transaction_id}"
            f"&am={amount}"
            f"&cu=INR"
        )
        return upi_link, expires_at

    # ── Initiate deposit ─────────────────────────────────────────────────

    async def initiate_deposit(
        self, user_id: str, amount: Decimal, method: PaymentMethod
    ) -> DepositTransaction:
        """Initiate a fund deposit via UPI, net banking, or NEFT/RTGS.

        Steps:
        1. Validate deposit amount (min ₹100, max ₹10,00,000)
        2. Check user has at least one verified bank account
        3. Generate transaction ID
        4. For UPI: generate payment link with 15-minute expiry
        5. Call payment gateway to initiate deposit
        6. Record transaction in fund_transactions table
        7. Return DepositTransaction with status
        """
        now = datetime.now(timezone.utc)
        transaction_id = str(uuid.uuid4())

        # Step 1: Validate amount
        valid, error = self.validate_deposit_amount(amount)
        if not valid:
            return DepositTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                payment_method=method,
                status=TransactionStatus.FAILED,
                failure_reason=error,
                created_at=now,
            )

        # Step 2: Check verified bank account
        has_bank = await self._has_verified_bank_account(user_id)
        if not has_bank:
            return DepositTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                payment_method=method,
                status=TransactionStatus.FAILED,
                failure_reason="No verified bank account found",
                created_at=now,
            )

        # Step 3-4: Generate UPI link if applicable
        upi_link = None
        upi_expires = None
        if method == PaymentMethod.UPI:
            upi_link, upi_expires = self._generate_upi_link(transaction_id, amount)

        # Step 5: Call payment gateway
        gateway_payload = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "amount": str(amount),
            "method": method.value,
            "currency": "INR",
        }
        gateway_response = await self._call_payment_gateway("deposit/initiate", gateway_payload)

        if gateway_response is None:
            txn = DepositTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                payment_method=method,
                status=TransactionStatus.FAILED,
                failure_reason="Payment gateway unavailable",
                created_at=now,
            )
            await self._store_transaction(txn)
            await self._notify_user_failure(user_id, txn)
            return txn

        # Build transaction from gateway response
        txn_ref = gateway_response.get("transaction_ref", "")
        gw_status = gateway_response.get("status", "INITIATED")

        status = TransactionStatus.INITIATED
        if gw_status == "PROCESSING":
            status = TransactionStatus.PROCESSING
        elif gw_status == "COMPLETED":
            status = TransactionStatus.COMPLETED
        elif gw_status == "FAILED":
            status = TransactionStatus.FAILED

        txn = DepositTransaction(
            id=transaction_id,
            user_id=user_id,
            amount=amount,
            payment_method=method,
            transaction_ref=txn_ref,
            status=status,
            upi_link=upi_link,
            upi_link_expires_at=upi_expires,
            created_at=now,
        )

        if status == TransactionStatus.FAILED:
            txn.failure_reason = gateway_response.get("reason", "Payment failed")
            await self._store_transaction(txn)
            await self._notify_user_failure(user_id, txn)
            return txn

        # Step 6: Store transaction
        await self._store_transaction(txn)

        # If already completed by gateway, credit balance immediately
        if status == TransactionStatus.COMPLETED:
            txn.completed_at = datetime.now(timezone.utc)
            await self._credit_trading_balance(user_id, amount)

        return txn

    # ── Confirm deposit (callback from payment gateway) ──────────────────

    async def confirm_deposit(self, transaction_id: str) -> Optional[DepositTransaction]:
        """Confirm a deposit after payment gateway callback.

        Credits trading balance within 30 seconds of confirmation.
        Returns updated transaction or None if not found.
        """
        if self.db_pool is None:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, user_id, amount, payment_method, transaction_ref, "
                    "status, failure_reason, created_at "
                    "FROM fund_transactions WHERE id = $1 AND type = 'DEPOSIT'",
                    transaction_id,
                )
                if row is None:
                    return None

                current_status = row["status"]
                if current_status == TransactionStatus.COMPLETED.value:
                    # Already completed
                    return DepositTransaction(
                        id=str(row["id"]),
                        user_id=str(row["user_id"]),
                        amount=row["amount"],
                        payment_method=PaymentMethod(row["payment_method"]),
                        transaction_ref=row["transaction_ref"] or "",
                        status=TransactionStatus.COMPLETED,
                        created_at=row["created_at"],
                    )

                if current_status == TransactionStatus.FAILED.value:
                    return None

                # Credit balance and update status
                now = datetime.now(timezone.utc)
                await conn.execute(
                    "UPDATE fund_transactions SET status = $1, completed_at = $2 " "WHERE id = $3",
                    TransactionStatus.COMPLETED.value,
                    now,
                    transaction_id,
                )

                user_id = str(row["user_id"])
                amount = row["amount"]
                await self._credit_trading_balance(user_id, amount)

                return DepositTransaction(
                    id=str(row["id"]),
                    user_id=user_id,
                    amount=amount,
                    payment_method=PaymentMethod(row["payment_method"]),
                    transaction_ref=row["transaction_ref"] or "",
                    status=TransactionStatus.COMPLETED,
                    completed_at=now,
                    created_at=row["created_at"],
                )
        except Exception:
            logger.exception("Failed to confirm deposit %s", transaction_id)
            return None

    # ── Credit trading balance ───────────────────────────────────────────

    async def _credit_trading_balance(self, user_id: str, amount: Decimal) -> bool:
        """Credit the user's available trading balance.

        Uses UPSERT to create balance row if it doesn't exist.
        """
        if self.db_pool is None:
            logger.debug("No db_pool — skipping balance credit")
            return False

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO trading_balances (user_id, available_balance, blocked_margin, updated_at)
                    VALUES ($1, $2, 0, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET available_balance = trading_balances.available_balance + $2,
                        updated_at = NOW()
                    """,
                    user_id,
                    amount,
                )
                return True
        except Exception:
            logger.exception("Failed to credit balance for user %s, amount %s", user_id, amount)
            return False

    # ── Notify user on failure ───────────────────────────────────────────

    async def _notify_user_failure(self, user_id: str, txn: DepositTransaction) -> None:
        """Notify user about a failed deposit with the failure reason."""
        logger.info(
            "Deposit FAILED for user %s: amount=%s, method=%s, reason=%s",
            user_id,
            txn.amount,
            txn.payment_method.value,
            txn.failure_reason,
        )
        # In production, this would push a notification via WebSocket/FCM/email.
        # For now, we log the failure. The notification infrastructure can be
        # plugged in when the notification service is implemented.

    # ── Store transaction ────────────────────────────────────────────────

    async def _store_transaction(self, txn: DepositTransaction) -> None:
        """Store a deposit transaction in the fund_transactions table."""
        if self.db_pool is None:
            logger.debug("No db_pool — skipping transaction storage")
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO fund_transactions
                        (id, user_id, type, amount, payment_method,
                         transaction_ref, status, failure_reason, created_at, completed_at)
                    VALUES ($1, $2, 'DEPOSIT', $3, $4, $5, $6, $7, $8, $9)
                    """,
                    txn.id,
                    txn.user_id,
                    txn.amount,
                    txn.payment_method.value,
                    txn.transaction_ref,
                    txn.status.value,
                    txn.failure_reason,
                    txn.created_at,
                    txn.completed_at,
                )
        except Exception:
            logger.exception("Failed to store deposit transaction %s", txn.id)

    # ── Daily reconciliation ─────────────────────────────────────────────

    async def reconcile_deposits(self, date_str: str) -> ReconciliationResult:
        """Reconcile deposit records with payment gateway settlement reports.

        Runs daily at 6:00 PM IST. Compares local fund_transactions with
        gateway settlement data for the given date.

        Args:
            date_str: Date in YYYY-MM-DD format to reconcile.

        Returns:
            ReconciliationResult with match/mismatch counts.
        """
        result = ReconciliationResult(reconciled_at=datetime.now(timezone.utc))

        # Fetch settlement report from payment gateway
        gateway_data = await self._call_payment_gateway(
            "settlement/report",
            {"date": date_str, "type": "DEPOSIT"},
        )

        if gateway_data is None:
            logger.error("Cannot reconcile: gateway settlement report unavailable for %s", date_str)
            return result

        gateway_transactions = gateway_data.get("transactions", [])
        result.total_gateway_transactions = len(gateway_transactions)

        # Build lookup from gateway data
        gw_lookup = {}
        for gt in gateway_transactions:
            ref = gt.get("transaction_ref", "")
            if ref:
                gw_lookup[ref] = gt

        # Fetch local transactions for the date
        local_transactions = await self._get_transactions_for_date(date_str)
        result.total_local_transactions = len(local_transactions)

        local_refs = set()
        for lt in local_transactions:
            ref = lt.get("transaction_ref", "")
            local_refs.add(ref)
            if ref in gw_lookup:
                gw_entry = gw_lookup[ref]
                gw_amount = Decimal(str(gw_entry.get("amount", "0")))
                local_amount = lt.get("amount", Decimal("0"))
                gw_status = gw_entry.get("status", "")
                local_status = lt.get("status", "")

                if gw_amount == local_amount and gw_status == local_status:
                    result.matched += 1
                else:
                    result.mismatched += 1
                    logger.warning(
                        "Reconciliation mismatch for ref %s: "
                        "gateway(amount=%s, status=%s) vs local(amount=%s, status=%s)",
                        ref,
                        gw_amount,
                        gw_status,
                        local_amount,
                        local_status,
                    )
            else:
                result.missing_on_gateway += 1

        # Check for gateway transactions missing locally
        for ref in gw_lookup:
            if ref not in local_refs:
                result.missing_locally += 1
                logger.warning("Transaction ref %s found on gateway but missing locally", ref)

        return result

    async def _get_transactions_for_date(self, date_str: str) -> list[dict]:
        """Fetch local deposit transactions for a given date."""
        if self.db_pool is None:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT transaction_ref, amount, status FROM fund_transactions "
                    "WHERE type = 'DEPOSIT' AND created_at::date = $1::date",
                    date_str,
                )
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch transactions for date %s", date_str)
            return []

    # ══════════════════════════════════════════════════════════════════════
    # WITHDRAWAL METHODS
    # ══════════════════════════════════════════════════════════════════════

    # ── Withdrawal amount validation ─────────────────────────────────────

    def validate_withdrawal_amount(self, amount: Decimal) -> tuple[bool, Optional[str]]:
        """Validate withdrawal amount meets minimum requirement.

        Returns (is_valid, error_message).
        Min ₹100.
        """
        if not isinstance(amount, Decimal):
            return False, "Amount must be a Decimal"
        if amount < MIN_WITHDRAWAL:
            return False, f"Minimum withdrawal is ₹{MIN_WITHDRAWAL}"
        return True, None

    # ── Get withdrawable balance ─────────────────────────────────────────

    async def get_withdrawable_balance(self, user_id: str) -> Decimal:
        """Total balance minus margin blocked for open positions.

        Returns Decimal("0") if no balance record exists or db is unavailable.
        """
        if self.db_pool is None:
            return Decimal("0")

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT available_balance, blocked_margin "
                    "FROM trading_balances WHERE user_id = $1",
                    user_id,
                )
                if row is None:
                    return Decimal("0")
                available = row["available_balance"] or Decimal("0")
                blocked = row["blocked_margin"] or Decimal("0")
                withdrawable = available - blocked
                return max(withdrawable, Decimal("0"))
        except Exception:
            logger.exception("Failed to get withdrawable balance for user %s", user_id)
            return Decimal("0")

    # ── Daily withdrawal total ───────────────────────────────────────────

    async def _get_daily_withdrawal_total(self, user_id: str) -> Decimal:
        """Get total withdrawal amount for the current day (UTC).

        Counts only non-FAILED withdrawals.
        """
        if self.db_pool is None:
            return Decimal("0")

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount), 0) as total FROM fund_transactions "
                    "WHERE user_id = $1 AND type = 'WITHDRAWAL' "
                    "AND status != $2 "
                    "AND created_at::date = CURRENT_DATE",
                    user_id,
                    WithdrawalStatus.FAILED.value,
                )
                return row["total"] if row else Decimal("0")
        except Exception:
            logger.exception("Failed to get daily withdrawal total for user %s", user_id)
            return Decimal("0")

    # ── Verify bank account is VERIFIED ──────────────────────────────────

    async def _get_verified_bank_account(self, user_id: str, bank_id: str) -> Optional[dict]:
        """Fetch a bank account only if it belongs to the user and is VERIFIED.

        Returns dict with account details or None.
        """
        if self.db_pool is None:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, ifsc_code, bank_name, account_holder_name "
                    "FROM bank_accounts "
                    "WHERE id = $1 AND user_id = $2 AND status = 'VERIFIED'",
                    bank_id,
                    user_id,
                )
                return dict(row) if row else None
        except Exception:
            logger.exception("Failed to fetch bank account %s for user %s", bank_id, user_id)
            return None

    # ── Determine processing timeline ────────────────────────────────────

    @staticmethod
    def _get_estimated_completion(now_utc: datetime) -> str:
        """Determine if withdrawal processes same day or next business day.

        Before 4:00 PM IST → same_day
        After 4:00 PM IST → next_business_day
        """
        ist = ZoneInfo("Asia/Kolkata")
        now_ist = now_utc.astimezone(ist)
        cutoff = now_ist.replace(
            hour=WITHDRAWAL_CUTOFF_HOUR_IST,
            minute=WITHDRAWAL_CUTOFF_MINUTE_IST,
            second=0,
            microsecond=0,
        )
        if now_ist < cutoff:
            return "same_day"
        return "next_business_day"

    # ── Debit trading balance ────────────────────────────────────────────

    async def _debit_trading_balance(self, user_id: str, amount: Decimal) -> bool:
        """Debit the user's available trading balance for withdrawal.

        Returns True on success, False on failure.
        """
        if self.db_pool is None:
            return False

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE trading_balances
                    SET available_balance = available_balance - $2,
                        updated_at = NOW()
                    WHERE user_id = $1
                    """,
                    user_id,
                    amount,
                )
                return True
        except Exception:
            logger.exception("Failed to debit balance for user %s, amount %s", user_id, amount)
            return False

    # ── Reverse debit on failure ─────────────────────────────────────────

    async def _reverse_withdrawal_debit(self, user_id: str, amount: Decimal) -> bool:
        """Reverse a withdrawal debit by crediting the amount back.

        Called when the bank transfer fails.
        """
        return await self._credit_trading_balance(user_id, amount)

    # ── Store withdrawal transaction ─────────────────────────────────────

    async def _store_withdrawal_transaction(self, txn: WithdrawalTransaction) -> None:
        """Store a withdrawal transaction in the fund_transactions table."""
        if self.db_pool is None:
            logger.debug("No db_pool — skipping withdrawal transaction storage")
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO fund_transactions
                        (id, user_id, type, amount, payment_method,
                         bank_account_id, transaction_ref, status,
                         failure_reason, created_at, completed_at)
                    VALUES ($1, $2, 'WITHDRAWAL', $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    txn.id,
                    txn.user_id,
                    txn.amount,
                    txn.payment_method.value,
                    txn.bank_account_id,
                    txn.transaction_ref,
                    txn.status.value,
                    txn.failure_reason,
                    txn.created_at,
                    txn.completed_at,
                )
        except Exception:
            logger.exception("Failed to store withdrawal transaction %s", txn.id)

    # ── Notify user on withdrawal failure ────────────────────────────────

    async def _notify_withdrawal_failure(self, user_id: str, txn: WithdrawalTransaction) -> None:
        """Notify user about a failed withdrawal with the failure reason."""
        logger.info(
            "Withdrawal FAILED for user %s: amount=%s, bank=%s, reason=%s",
            user_id,
            txn.amount,
            txn.bank_account_id,
            txn.failure_reason,
        )

    # ── Initiate withdrawal ──────────────────────────────────────────────

    async def initiate_withdrawal(
        self, user_id: str, amount: Decimal, bank_id: str
    ) -> WithdrawalTransaction:
        """Initiate a fund withdrawal to a verified bank account.

        Steps:
        1. Validate withdrawal amount (min ₹100)
        2. Verify bank account is VERIFIED and belongs to user
        3. Check withdrawable balance (total - margin blocked)
        4. Check daily withdrawal limit (₹25,00,000)
        5. Debit trading balance
        6. Determine processing timeline (before/after 4 PM IST)
        7. Initiate NEFT/IMPS transfer via payment gateway
        8. On gateway failure: reverse debit and notify user
        9. Store transaction and return result
        """
        now = datetime.now(timezone.utc)
        transaction_id = str(uuid.uuid4())

        # Step 1: Validate amount
        valid, error = self.validate_withdrawal_amount(amount)
        if not valid:
            return WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason=error,
                created_at=now,
            )

        # Step 2: Verify bank account is VERIFIED
        bank_account = await self._get_verified_bank_account(user_id, bank_id)
        if bank_account is None:
            return WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason="Bank account not found or not verified",
                created_at=now,
            )

        # Step 3: Check withdrawable balance
        withdrawable = await self.get_withdrawable_balance(user_id)
        if amount > withdrawable:
            return WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason=f"Insufficient withdrawable balance. Available: ₹{withdrawable}",
                created_at=now,
            )

        # Step 4: Check daily withdrawal limit
        daily_total = await self._get_daily_withdrawal_total(user_id)
        if daily_total + amount > DAILY_MAX_WITHDRAWAL:
            remaining = DAILY_MAX_WITHDRAWAL - daily_total
            return WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason=f"Daily withdrawal limit exceeded. Remaining today: ₹{remaining}",
                created_at=now,
            )

        # Step 5: Debit trading balance
        debited = await self._debit_trading_balance(user_id, amount)
        if not debited:
            return WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason="Failed to debit trading balance",
                created_at=now,
            )

        # Step 6: Determine processing timeline
        estimated = self._get_estimated_completion(now)

        # Step 7: Initiate bank transfer via payment gateway
        gateway_payload = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "amount": str(amount),
            "bank_account_id": bank_id,
            "ifsc_code": bank_account.get("ifsc_code", ""),
            "account_holder_name": bank_account.get("account_holder_name", ""),
            "method": "NEFT",
            "currency": "INR",
        }
        gateway_response = await self._call_payment_gateway("withdrawal/initiate", gateway_payload)

        # Step 8: Handle gateway failure — reverse debit
        if gateway_response is None:
            await self._reverse_withdrawal_debit(user_id, amount)
            txn = WithdrawalTransaction(
                id=transaction_id,
                user_id=user_id,
                amount=amount,
                bank_account_id=bank_id,
                status=WithdrawalStatus.FAILED,
                failure_reason="Payment gateway unavailable — debit reversed",
                estimated_completion=estimated,
                created_at=now,
            )
            await self._store_withdrawal_transaction(txn)
            await self._notify_withdrawal_failure(user_id, txn)
            return txn

        # Parse gateway response
        txn_ref = gateway_response.get("transaction_ref", "")
        gw_status = gateway_response.get("status", "REQUESTED")
        payment_method_str = gateway_response.get("method", "NEFT")

        try:
            payment_method = PaymentMethod(payment_method_str)
        except ValueError:
            payment_method = PaymentMethod.NEFT

        status = WithdrawalStatus.REQUESTED
        if gw_status == "PROCESSING":
            status = WithdrawalStatus.PROCESSING
        elif gw_status == "COMPLETED":
            status = WithdrawalStatus.COMPLETED
        elif gw_status == "FAILED":
            status = WithdrawalStatus.FAILED

        txn = WithdrawalTransaction(
            id=transaction_id,
            user_id=user_id,
            amount=amount,
            bank_account_id=bank_id,
            payment_method=payment_method,
            transaction_ref=txn_ref,
            status=status,
            estimated_completion=estimated,
            created_at=now,
        )

        if status == WithdrawalStatus.FAILED:
            txn.failure_reason = gateway_response.get("reason", "Transfer failed")
            await self._reverse_withdrawal_debit(user_id, amount)
            await self._store_withdrawal_transaction(txn)
            await self._notify_withdrawal_failure(user_id, txn)
            return txn

        if status == WithdrawalStatus.COMPLETED:
            txn.completed_at = datetime.now(timezone.utc)

        # Step 9: Store transaction
        await self._store_withdrawal_transaction(txn)
        return txn
