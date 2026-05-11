"""Bank account registration and verification service.

Handles bank account linking, IFSC validation, penny drop verification,
and account management with AES-256 encryption at rest.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

import httpx
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ── Encryption key (shared with verification_service) ────────────────────────

_ENCRYPTION_KEY = os.getenv("PAN_ENCRYPTION_KEY", "")

# IFSC format: 4 uppercase letters + 0 + 6 alphanumeric characters
IFSC_REGEX = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

# Retry configuration
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
API_TIMEOUT_SECONDS = 10

# Limits
MAX_BANK_ACCOUNTS_PER_USER = 3


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key."""
    key = os.getenv("PAN_ENCRYPTION_KEY", "") or _ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "PAN_ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


# ── Data classes ─────────────────────────────────────────────────────────────


class BankAccountStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class BankAccountRejectionReason(str, Enum):
    INVALID_IFSC = "invalid_ifsc"
    IFSC_NOT_FOUND = "ifsc_not_found"
    PENNY_DROP_FAILED = "penny_drop_failed"
    NAME_MISMATCH = "name_mismatch"
    KYC_NOT_VERIFIED = "kyc_not_verified"
    MAX_ACCOUNTS_REACHED = "max_accounts_reached"
    API_UNAVAILABLE = "api_unavailable"
    INVALID_ACCOUNT_TYPE = "invalid_account_type"


VALID_ACCOUNT_TYPES = {"savings", "current"}


@dataclass
class BankAccountDetails:
    """Details required for bank account registration."""
    account_holder_name: str
    account_number: str
    ifsc_code: str
    bank_name: str
    account_type: str  # "savings" or "current"


@dataclass
class BankAccount:
    """Registered bank account record."""
    id: Optional[str] = None
    user_id: Optional[str] = None
    account_number_encrypted: Optional[bytes] = None
    ifsc_code: str = ""
    bank_name: str = ""
    account_holder_name: str = ""
    account_type: str = ""
    is_primary: bool = False
    status: BankAccountStatus = BankAccountStatus.PENDING
    rejection_reason: Optional[str] = None
    verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ── Bank Account Service ─────────────────────────────────────────────────────


class BankAccountService:
    """Bank account registration and fund management."""

    def __init__(
        self,
        db_pool=None,
        ifsc_api_url: str = "",
        payment_api_url: str = "",
        payment_api_key: str = "",
    ):
        self.db_pool = db_pool
        self.ifsc_api_url = ifsc_api_url or os.getenv(
            "IFSC_API_URL", "https://ifsc.razorpay.com"
        )
        self.payment_api_url = payment_api_url or os.getenv(
            "PAYMENT_API_URL", "https://api.payment-gateway.co.in"
        )
        self.payment_api_key = payment_api_key or os.getenv("PAYMENT_API_KEY", "")

    # ── IFSC validation ──────────────────────────────────────────────────

    def validate_ifsc_format(self, ifsc: str) -> bool:
        """Validate IFSC format: 4 uppercase letters + 0 + 6 alphanumeric.

        Example: HDFC0001234, SBIN0012345
        """
        if not ifsc or not isinstance(ifsc, str):
            return False
        return bool(IFSC_REGEX.match(ifsc))

    async def verify_ifsc(self, ifsc: str) -> Optional[dict]:
        """Verify IFSC code against RBI IFSC directory.

        Returns bank details dict if valid, None if not found or API error.
        """
        if not self.validate_ifsc_format(ifsc):
            return None

        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.get(f"{self.ifsc_api_url}/{ifsc}")
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 404:
                        return None
                    else:
                        logger.warning(
                            "IFSC API returned status %d on attempt %d",
                            response.status_code,
                            attempt + 1,
                        )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
                last_exception = exc
                logger.warning(
                    "IFSC API attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "IFSC API unreachable after %d attempts. Last error: %s",
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── Encryption helpers ───────────────────────────────────────────────

    def encrypt_account_number(self, account_number: str) -> bytes:
        """AES-256 encrypt bank account number for storage."""
        f = _get_fernet()
        return f.encrypt(account_number.encode("utf-8"))

    def decrypt_account_number(self, encrypted: bytes) -> str:
        """Decrypt an AES-256 encrypted bank account number."""
        f = _get_fernet()
        return f.decrypt(encrypted).decode("utf-8")

    # ── KYC prerequisite check ───────────────────────────────────────────

    async def _check_kyc_verified(self, user_id: str) -> bool:
        """Check that KYC verification is VERIFIED for the user."""
        if self.db_pool is None:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT status FROM kyc_verifications WHERE user_id = $1 "
                    "ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
                return row is not None and row["status"] == "VERIFIED"
        except Exception:
            logger.exception("Failed to check KYC status for user %s", user_id)
            return False

    # ── Account count check ──────────────────────────────────────────────

    async def _get_account_count(self, user_id: str) -> int:
        """Return the number of bank accounts (non-FAILED) for the user."""
        if self.db_pool is None:
            return 0
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as cnt FROM bank_accounts "
                    "WHERE user_id = $1 AND status != $2",
                    user_id,
                    BankAccountStatus.FAILED.value,
                )
                return row["cnt"] if row else 0
        except Exception:
            logger.exception("Failed to count bank accounts for user %s", user_id)
            return 0

    # ── KYC name retrieval ───────────────────────────────────────────────

    async def _get_kyc_name(self, user_id: str) -> Optional[str]:
        """Retrieve the KYC-verified full name for the user."""
        if self.db_pool is None:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT full_name FROM kyc_verifications WHERE user_id = $1 "
                    "AND status = 'VERIFIED' ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
                return row["full_name"] if row else None
        except Exception:
            logger.exception("Failed to get KYC name for user %s", user_id)
            return None

    # ── Penny drop verification ──────────────────────────────────────────

    async def _initiate_penny_drop(
        self, account_number: str, ifsc: str, account_holder_name: str
    ) -> Optional[dict]:
        """Initiate penny drop verification (₹1 credit) via payment gateway.

        Returns dict with verification result, or None if API unreachable.
        Expected response: {"verified": bool, "holder_name": str, "reference": str}
        """
        last_exception = None
        payload = {
            "account_number": account_number,
            "ifsc_code": ifsc,
            "amount": "1.00",
            "purpose": "penny_drop_verification",
        }

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.payment_api_url}/penny-drop",
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
                            "Payment API returned status %d on attempt %d: %s",
                            response.status_code,
                            attempt + 1,
                            response.text,
                        )
                        try:
                            return response.json()
                        except Exception:
                            pass

            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
                last_exception = exc
                logger.warning(
                    "Payment API attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "Payment API unreachable after %d attempts. Last error: %s",
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── Register bank account ────────────────────────────────────────────

    async def register_bank_account(
        self, user_id: str, details: BankAccountDetails
    ) -> BankAccount:
        """Register a bank account. Validates IFSC, initiates penny drop.

        Steps:
        1. Validate account type
        2. Validate IFSC format
        3. Check KYC is VERIFIED
        4. Check max 3 accounts limit
        5. Verify IFSC against RBI directory
        6. Encrypt account number
        7. Initiate penny drop verification
        8. Confirm holder name matches KYC name
        9. Store in database, designate as primary if first account
        """
        # Step 1: Validate account type
        if details.account_type not in VALID_ACCOUNT_TYPES:
            return BankAccount(
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.INVALID_ACCOUNT_TYPE.value,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
            )

        # Step 2: Validate IFSC format
        if not self.validate_ifsc_format(details.ifsc_code):
            return BankAccount(
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.INVALID_IFSC.value,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
            )

        # Step 3: Check KYC prerequisite
        kyc_verified = await self._check_kyc_verified(user_id)
        if not kyc_verified:
            return BankAccount(
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.KYC_NOT_VERIFIED.value,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
            )

        # Step 4: Check max accounts limit
        count = await self._get_account_count(user_id)
        if count >= MAX_BANK_ACCOUNTS_PER_USER:
            return BankAccount(
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.MAX_ACCOUNTS_REACHED.value,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
            )

        # Step 5: Verify IFSC against RBI directory
        ifsc_info = await self.verify_ifsc(details.ifsc_code)
        if ifsc_info is None:
            return BankAccount(
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.IFSC_NOT_FOUND.value,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
            )

        # Step 6: Encrypt account number
        encrypted = self.encrypt_account_number(details.account_number)

        # Step 7: Initiate penny drop verification
        penny_result = await self._initiate_penny_drop(
            details.account_number, details.ifsc_code, details.account_holder_name
        )

        if penny_result is None:
            # API unreachable
            account = BankAccount(
                user_id=user_id,
                account_number_encrypted=encrypted,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.API_UNAVAILABLE.value,
            )
            await self._store_bank_account(user_id, account)
            return account

        # Step 8: Check penny drop result and name match
        if not penny_result.get("verified", False):
            account = BankAccount(
                user_id=user_id,
                account_number_encrypted=encrypted,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.PENNY_DROP_FAILED.value,
            )
            await self._store_bank_account(user_id, account)
            return account

        # Confirm holder name matches KYC name
        kyc_name = await self._get_kyc_name(user_id)
        penny_holder_name = penny_result.get("holder_name", "")
        if kyc_name and not self._names_match(kyc_name, penny_holder_name):
            account = BankAccount(
                user_id=user_id,
                account_number_encrypted=encrypted,
                ifsc_code=details.ifsc_code,
                bank_name=details.bank_name,
                account_holder_name=details.account_holder_name,
                account_type=details.account_type,
                status=BankAccountStatus.FAILED,
                rejection_reason=BankAccountRejectionReason.NAME_MISMATCH.value,
            )
            await self._store_bank_account(user_id, account)
            return account

        # Step 9: Success — designate as primary if first account
        is_primary = count == 0
        now = datetime.now(timezone.utc)
        account = BankAccount(
            user_id=user_id,
            account_number_encrypted=encrypted,
            ifsc_code=details.ifsc_code,
            bank_name=details.bank_name,
            account_holder_name=details.account_holder_name,
            account_type=details.account_type,
            is_primary=is_primary,
            status=BankAccountStatus.VERIFIED,
            verified_at=now,
            created_at=now,
        )
        await self._store_bank_account(user_id, account)
        return account

    # ── Name matching ────────────────────────────────────────────────────

    @staticmethod
    def _names_match(kyc_name: str, bank_name: str) -> bool:
        """Case-insensitive name comparison, ignoring extra whitespace."""
        if not kyc_name or not bank_name:
            return False
        return " ".join(kyc_name.upper().split()) == " ".join(bank_name.upper().split())

    # ── Penny drop verification confirmation ─────────────────────────────

    async def verify_penny_drop(self, user_id: str, bank_id: str) -> bool:
        """Confirm penny drop verification result for a pending bank account.

        Checks the payment gateway for the penny drop status and updates
        the bank account accordingly.
        Returns True if verification succeeded, False otherwise.
        """
        if self.db_pool is None:
            return False

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, status FROM bank_accounts "
                    "WHERE id = $1 AND user_id = $2",
                    bank_id,
                    user_id,
                )
                if row is None:
                    return False
                if row["status"] == BankAccountStatus.VERIFIED.value:
                    return True
                if row["status"] == BankAccountStatus.FAILED.value:
                    return False

                # Check payment gateway for penny drop status
                result = await self._check_penny_drop_status(bank_id)
                if result and result.get("verified", False):
                    await conn.execute(
                        "UPDATE bank_accounts SET status = $1, verified_at = $2 "
                        "WHERE id = $3 AND user_id = $4",
                        BankAccountStatus.VERIFIED.value,
                        datetime.now(timezone.utc),
                        bank_id,
                        user_id,
                    )
                    return True
                return False
        except Exception:
            logger.exception(
                "Failed to verify penny drop for bank %s, user %s", bank_id, user_id
            )
            return False

    async def _check_penny_drop_status(self, bank_id: str) -> Optional[dict]:
        """Check penny drop verification status from payment gateway."""
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self.payment_api_url}/penny-drop/status/{bank_id}",
                    headers={
                        "Authorization": f"Bearer {self.payment_api_key}",
                    },
                )
                if response.status_code == 200:
                    return response.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
            logger.warning("Penny drop status check failed: %s", str(exc))
        return None

    # ── Database storage ─────────────────────────────────────────────────

    async def _store_bank_account(self, user_id: str, account: BankAccount) -> None:
        """Store bank account in the database."""
        if self.db_pool is None:
            logger.debug("No db_pool configured — skipping bank account storage")
            return

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO bank_accounts
                        (user_id, account_number_encrypted, ifsc_code, bank_name,
                         account_holder_name, account_type, is_primary, status,
                         verified_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id
                    """,
                    user_id,
                    account.account_number_encrypted,
                    account.ifsc_code,
                    account.bank_name,
                    account.account_holder_name,
                    account.account_type,
                    account.is_primary,
                    account.status.value,
                    account.verified_at,
                )
                if row:
                    account.id = str(row["id"])
        except Exception:
            logger.exception("Failed to store bank account for user %s", user_id)
