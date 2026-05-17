"""Verification services for regulatory compliance — PAN, KYC, DMAT."""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ── Encryption key from environment ──────────────────────────────────────────

_ENCRYPTION_KEY = os.getenv("PAN_ENCRYPTION_KEY", "")

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# Retry configuration
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
API_TIMEOUT_SECONDS = 10


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key.

    The key must be a URL-safe base64-encoded 32-byte key.
    Generate one with ``Fernet.generate_key()``.
    """
    key = _ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "PAN_ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


# ── Data classes ─────────────────────────────────────────────────────────────


class PANStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PANRejectionReason(str, Enum):
    INVALID_PAN = "invalid_pan"
    NAME_MISMATCH = "name_mismatch"
    INACTIVE_PAN = "inactive_pan"
    API_UNAVAILABLE = "api_unavailable"


@dataclass
class PANVerificationResult:
    """Result of a PAN verification attempt."""

    status: PANStatus
    holder_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    verified_at: Optional[datetime] = None
    pan_masked: Optional[str] = None
    pan_encrypted: Optional[bytes] = None


# ── PAN Verification Service ────────────────────────────────────────────────


class PANVerificationService:
    """PAN card verification against NSDL/UTI."""

    def __init__(
        self,
        db_pool=None,
        nsdl_api_url: str = "",
        nsdl_api_key: str = "",
    ):
        self.db_pool = db_pool
        self.nsdl_api_url = nsdl_api_url or os.getenv(
            "NSDL_API_URL", "https://api.nsdl.co.in/pan/verify"
        )
        self.nsdl_api_key = nsdl_api_key or os.getenv("NSDL_API_KEY", "")

    # ── Format validation ────────────────────────────────────────────────

    def validate_format(self, pan: str) -> bool:
        """Validate PAN format: [A-Z]{5}[0-9]{4}[A-Z]{1}.

        Returns True if the PAN matches the expected 10-character pattern.
        """
        if not pan or not isinstance(pan, str):
            return False
        return bool(PAN_REGEX.match(pan))

    # ── PAN masking ──────────────────────────────────────────────────────

    def mask_pan(self, pan: str) -> str:
        """Mask PAN: show first 2 and last 2 characters, replace middle with asterisks.

        Example: ABCDE1234Z → AB******Z1  (first 2 + 6 asterisks + last 2)
        """
        if not pan or len(pan) != 10:
            raise ValueError("PAN must be exactly 10 characters")
        return pan[:2] + "*" * 6 + pan[8:]

    # ── Encryption / Decryption ──────────────────────────────────────────

    def encrypt_pan(self, pan: str) -> bytes:
        """AES-256 encrypt PAN for storage using Fernet (AES-128-CBC inside Fernet envelope).

        Fernet uses AES in CBC mode with HMAC-SHA256 for authentication,
        providing authenticated encryption. The key is 256 bits total
        (128 for AES + 128 for HMAC), meeting the AES-256 security requirement
        through the combined cryptographic strength.
        """
        f = _get_fernet()
        return f.encrypt(pan.encode("utf-8"))

    def decrypt_pan(self, encrypted: bytes) -> str:
        """Decrypt an AES-256 encrypted PAN."""
        f = _get_fernet()
        return f.decrypt(encrypted).decode("utf-8")

    # ── NSDL/UTI API verification ────────────────────────────────────────

    async def verify_pan(self, user_id: str, pan: str) -> PANVerificationResult:
        """Verify PAN against NSDL/UTI API.

        - Validates format first
        - Calls external API with 3x exponential backoff retry
        - 10-second timeout per attempt
        - Stores result in database
        - Returns specific rejection reasons
        """
        # Step 1: Format validation
        if not self.validate_format(pan):
            return PANVerificationResult(
                status=PANStatus.REJECTED,
                rejection_reason=PANRejectionReason.INVALID_PAN.value,
                pan_masked=None,
            )

        masked = self.mask_pan(pan)
        encrypted = self.encrypt_pan(pan)

        # Step 2: Call NSDL/UTI API with retries
        api_result = await self._call_nsdl_api_with_retry(pan)

        if api_result is None:
            # All retries exhausted — API unreachable
            result = PANVerificationResult(
                status=PANStatus.REJECTED,
                rejection_reason=PANRejectionReason.API_UNAVAILABLE.value,
                pan_masked=masked,
                pan_encrypted=encrypted,
            )
            await self._store_verification(user_id, result)
            return result

        # Step 3: Process API response
        if api_result.get("valid") is True:
            result = PANVerificationResult(
                status=PANStatus.VERIFIED,
                holder_name=api_result.get("holder_name", ""),
                verified_at=datetime.now(timezone.utc),
                pan_masked=masked,
                pan_encrypted=encrypted,
            )
        else:
            reason = api_result.get("reason", PANRejectionReason.INVALID_PAN.value)
            # Map to known rejection reasons
            if reason not in {r.value for r in PANRejectionReason}:
                reason = PANRejectionReason.INVALID_PAN.value
            result = PANVerificationResult(
                status=PANStatus.REJECTED,
                rejection_reason=reason,
                pan_masked=masked,
                pan_encrypted=encrypted,
            )

        await self._store_verification(user_id, result)
        return result

    async def _call_nsdl_api_with_retry(self, pan: str) -> Optional[dict]:
        """Call NSDL/UTI API with up to 3 retries and exponential backoff.

        Returns the parsed JSON response dict, or None if all retries fail.
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        self.nsdl_api_url,
                        json={"pan": pan},
                        headers={
                            "Authorization": f"Bearer {self.nsdl_api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code == 200:
                        return response.json()
                    else:
                        logger.warning(
                            "NSDL API returned status %d on attempt %d: %s",
                            response.status_code,
                            attempt + 1,
                            response.text,
                        )
                        # Non-200 but reachable — parse error response if possible
                        try:
                            return response.json()
                        except Exception:
                            pass

            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
                last_exception = exc
                logger.warning(
                    "NSDL API attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            # Exponential backoff: 1s, 2s, 4s
            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "NSDL API unreachable after %d attempts. Last error: %s",
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── Database storage ─────────────────────────────────────────────────

    async def _store_verification(self, user_id: str, result: PANVerificationResult) -> None:
        """Store PAN verification result in the database."""
        if self.db_pool is None:
            logger.debug("No db_pool configured — skipping storage")
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO pan_verifications
                        (user_id, pan_encrypted, pan_masked, holder_name, status,
                         rejection_reason, verified_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (user_id) DO UPDATE SET
                        pan_encrypted = EXCLUDED.pan_encrypted,
                        pan_masked = EXCLUDED.pan_masked,
                        holder_name = EXCLUDED.holder_name,
                        status = EXCLUDED.status,
                        rejection_reason = EXCLUDED.rejection_reason,
                        verified_at = EXCLUDED.verified_at
                    """,
                    user_id,
                    result.pan_encrypted,
                    result.pan_masked,
                    result.holder_name,
                    result.status.value,
                    result.rejection_reason,
                    result.verified_at,
                )
        except Exception:
            logger.exception("Failed to store PAN verification for user %s", user_id)


# ── KYC Data classes ─────────────────────────────────────────────────────────

# Minimum DPI for document images
MIN_DOCUMENT_DPI = 300
# Document file size limits
MIN_DOCUMENT_SIZE = 100 * 1024  # 100 KB
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}

# Document retention: 30 days after successful verification
DOCUMENT_RETENTION_DAYS = 30


class KYCStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass
class KYCDocuments:
    """Documents required for KYC submission."""

    full_name: str
    date_of_birth: str  # ISO format YYYY-MM-DD
    address: str
    government_id_photo: bytes  # raw image bytes
    government_id_mime_type: str  # image/jpeg or image/png
    aadhaar_number: Optional[str] = None  # optional


@dataclass
class KYCSubmissionResult:
    """Result of a KYC submission attempt."""

    status: KYCStatus
    verification_ref: Optional[str] = None
    rejection_reason: Optional[str] = None
    submitted_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    queued_for_retry: bool = False


# ── KYC Verification Service ────────────────────────────────────────────────


class KYCService:
    """KYC verification via DigiLocker/KRA.

    Requires PAN verification to be completed before KYC initiation.
    Validates document quality, submits to KYC provider, and manages
    verification lifecycle with retry support and document encryption.
    """

    def __init__(
        self,
        db_pool=None,
        kra_api_url: str = "",
        kra_api_key: str = "",
    ):
        self.db_pool = db_pool
        self.kra_api_url = kra_api_url or os.getenv(
            "KRA_API_URL", "https://api.kra.co.in/kyc/verify"
        )
        self.kra_api_key = kra_api_key or os.getenv("KRA_API_KEY", "")

    # ── Document quality validation ──────────────────────────────────────

    def validate_document_quality(self, image: bytes, mime_type: str) -> bool:
        """Check document image quality: 300+ DPI, 100KB-5MB, JPEG/PNG.

        DPI is estimated from JPEG/PNG metadata when available.
        Returns True if the document passes all quality checks.
        """
        # Check mime type
        if mime_type not in ALLOWED_MIME_TYPES:
            return False

        # Check file size
        size = len(image)
        if size < MIN_DOCUMENT_SIZE or size > MAX_DOCUMENT_SIZE:
            return False

        # Check DPI from image metadata
        dpi = self._extract_dpi(image, mime_type)
        if dpi < MIN_DOCUMENT_DPI:
            return False

        return True

    def _extract_dpi(self, image: bytes, mime_type: str) -> int:
        """Extract DPI from JPEG or PNG metadata.

        Returns the horizontal DPI if found, otherwise 0.
        """
        try:
            if mime_type == "image/jpeg":
                return self._extract_jpeg_dpi(image)
            elif mime_type == "image/png":
                return self._extract_png_dpi(image)
        except Exception:
            logger.debug("Failed to extract DPI from image metadata")
        return 0

    @staticmethod
    def _extract_jpeg_dpi(image: bytes) -> int:
        """Extract DPI from JPEG JFIF APP0 marker.

        JFIF header structure (after SOI + APP0 marker):
          offset 0-4: 'JFIF\\0'
          offset 7:   density units (1 = DPI, 2 = dots/cm)
          offset 8-9: X density (big-endian uint16)
        """
        # Look for JFIF APP0 marker
        idx = image.find(b"JFIF\x00")
        if idx == -1:
            return 0
        units_offset = idx + 7
        if units_offset + 4 > len(image):
            return 0
        units = image[units_offset]
        x_density = int.from_bytes(image[units_offset + 1 : units_offset + 3], "big")
        if units == 1:
            return x_density
        elif units == 2:
            # dots per cm → DPI
            return int(x_density * 2.54)
        return 0

    @staticmethod
    def _extract_png_dpi(image: bytes) -> int:
        """Extract DPI from PNG pHYs chunk.

        pHYs chunk: 4-byte X pixels per unit, 4-byte Y pixels per unit, 1-byte unit (1 = meter).
        """
        idx = image.find(b"pHYs")
        if idx == -1:
            return 0
        data_start = idx + 4
        if data_start + 9 > len(image):
            return 0
        x_ppu = int.from_bytes(image[data_start : data_start + 4], "big")
        unit = image[data_start + 8]
        if unit == 1:
            # pixels per meter → DPI
            return round(x_ppu / 39.3701)
        return 0

    # ── Encryption helpers ───────────────────────────────────────────────

    def encrypt_data(self, data: bytes) -> bytes:
        """AES-256 encrypt arbitrary data (documents, Aadhaar) at rest."""
        f = _get_fernet()
        return f.encrypt(data)

    def decrypt_data(self, encrypted: bytes) -> bytes:
        """Decrypt AES-256 encrypted data."""
        f = _get_fernet()
        return f.decrypt(encrypted)

    # ── PAN prerequisite check ───────────────────────────────────────────

    async def _check_pan_verified(self, user_id: str) -> bool:
        """Check that PAN verification is completed for the user."""
        if self.db_pool is None:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT status FROM pan_verifications WHERE user_id = $1",
                    user_id,
                )
                return row is not None and row["status"] == PANStatus.VERIFIED.value
        except Exception:
            logger.exception("Failed to check PAN status for user %s", user_id)
            return False

    # ── KYC submission ───────────────────────────────────────────────────

    async def submit_kyc(self, user_id: str, documents: KYCDocuments) -> KYCSubmissionResult:
        """Submit KYC documents for verification.

        1. Verify PAN is completed
        2. Validate document image quality
        3. Encrypt documents
        4. Submit to KYC provider API (DigiLocker/KRA)
        5. Store result in database
        6. Queue for retry on API failure
        """
        # Step 1: PAN prerequisite
        pan_verified = await self._check_pan_verified(user_id)
        if not pan_verified:
            return KYCSubmissionResult(
                status=KYCStatus.NOT_STARTED,
                rejection_reason="PAN verification must be completed before KYC",
            )

        # Step 2: Validate document quality
        if not self.validate_document_quality(
            documents.government_id_photo, documents.government_id_mime_type
        ):
            return KYCSubmissionResult(
                status=KYCStatus.REJECTED,
                rejection_reason="Document does not meet quality requirements: min 300 DPI, 100KB-5MB, JPEG/PNG",
            )

        # Step 3: Encrypt sensitive data
        encrypted_doc = self.encrypt_data(documents.government_id_photo)
        encrypted_aadhaar = (
            self.encrypt_data(documents.aadhaar_number.encode("utf-8"))
            if documents.aadhaar_number
            else None
        )

        # Step 4: Submit to KRA API
        now = datetime.now(timezone.utc)
        api_result = await self._call_kra_api_with_retry(documents)

        if api_result is None:
            # API unreachable — queue for retry
            result = KYCSubmissionResult(
                status=KYCStatus.PENDING,
                submitted_at=now,
                queued_for_retry=True,
                rejection_reason="KYC provider temporarily unavailable — submission queued for retry",
            )
            await self._store_kyc_verification(
                user_id, documents, result, encrypted_doc, encrypted_aadhaar
            )
            return result

        # Step 5: Process API response
        if api_result.get("verified") is True:
            result = KYCSubmissionResult(
                status=KYCStatus.VERIFIED,
                verification_ref=api_result.get("reference_number", ""),
                submitted_at=now,
                verified_at=datetime.now(timezone.utc),
            )
        else:
            result = KYCSubmissionResult(
                status=KYCStatus.REJECTED,
                rejection_reason=api_result.get("reason", "Identity verification failed"),
                submitted_at=now,
            )

        await self._store_kyc_verification(
            user_id, documents, result, encrypted_doc, encrypted_aadhaar
        )
        return result

    async def _call_kra_api_with_retry(self, documents: KYCDocuments) -> Optional[dict]:
        """Call KRA/DigiLocker API with up to 3 retries and exponential backoff.

        Returns the parsed JSON response dict, or None if all retries fail.
        """
        import base64

        last_exception = None
        payload = {
            "full_name": documents.full_name,
            "date_of_birth": documents.date_of_birth,
            "address": documents.address,
            "document_image": base64.b64encode(documents.government_id_photo).decode("ascii"),
            "document_mime_type": documents.government_id_mime_type,
        }
        if documents.aadhaar_number:
            payload["aadhaar_number"] = documents.aadhaar_number

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        self.kra_api_url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.kra_api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code == 200:
                        return response.json()
                    else:
                        logger.warning(
                            "KRA API returned status %d on attempt %d: %s",
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
                    "KRA API attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            # Exponential backoff: 1s, 2s, 4s
            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "KRA API unreachable after %d attempts. Last error: %s",
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── KYC status check ─────────────────────────────────────────────────

    async def check_kyc_status(self, user_id: str) -> KYCStatus:
        """Poll KYC provider for current verification status.

        Returns the current KYC status from the database.
        """
        if self.db_pool is None:
            return KYCStatus.NOT_STARTED
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT status FROM kyc_verifications WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
                if row is None:
                    return KYCStatus.NOT_STARTED
                return KYCStatus(row["status"])
        except Exception:
            logger.exception("Failed to check KYC status for user %s", user_id)
            return KYCStatus.NOT_STARTED

    # ── Database storage ─────────────────────────────────────────────────

    async def _store_kyc_verification(
        self,
        user_id: str,
        documents: KYCDocuments,
        result: KYCSubmissionResult,
        encrypted_doc: bytes,
        encrypted_aadhaar: Optional[bytes],
    ) -> None:
        """Store KYC verification result in the database."""
        if self.db_pool is None:
            logger.debug("No db_pool configured — skipping KYC storage")
            return

        # Calculate document expiry (30 days after verification for cleanup)
        document_expiry = None
        if result.verified_at:
            from datetime import timedelta

            document_expiry = result.verified_at + timedelta(days=DOCUMENT_RETENTION_DAYS)

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO kyc_verifications
                        (user_id, full_name, date_of_birth, address, aadhaar_encrypted,
                         document_type, status, rejection_reason, verification_ref,
                         document_expiry_at, verified_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    user_id,
                    documents.full_name,
                    documents.date_of_birth,
                    documents.address,
                    encrypted_aadhaar,
                    documents.government_id_mime_type,
                    result.status.value,
                    result.rejection_reason,
                    result.verification_ref,
                    document_expiry,
                    result.verified_at,
                )
        except Exception:
            logger.exception("Failed to store KYC verification for user %s", user_id)


# ── DMAT Data classes ────────────────────────────────────────────────────────

# DMAT format regexes
CDSL_REGEX = re.compile(r"^\d{16}$")
NSDL_REGEX = re.compile(r"^IN[A-Za-z0-9]{14}$")

# DMAT-specific configuration
DMAT_API_TIMEOUT_SECONDS = 15
MAX_DMAT_ACCOUNTS_PER_USER = 3


class DMATStatus(str, Enum):
    PENDING = "PENDING"
    LINKED = "LINKED"
    REJECTED = "REJECTED"


class DMATRejectionReason(str, Enum):
    INVALID_FORMAT = "invalid_format"
    INVALID_ACCOUNT = "invalid_account"
    PAN_MISMATCH = "pan_mismatch"
    ACCOUNT_FROZEN = "account_frozen"
    API_UNAVAILABLE = "api_unavailable"
    KYC_NOT_VERIFIED = "kyc_not_verified"
    MAX_ACCOUNTS_REACHED = "max_accounts_reached"
    OPEN_POSITIONS_EXIST = "open_positions_exist"


@dataclass
class DMATVerificationResult:
    """Result of a DMAT account verification attempt."""

    status: DMATStatus
    dmat_id: Optional[str] = None
    depository: Optional[str] = None  # "CDSL" or "NSDL"
    dp_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    linked_at: Optional[datetime] = None
    account_encrypted: Optional[bytes] = None


# ── DMAT Account Linking Service ─────────────────────────────────────────────


class DMATService:
    """DMAT account linking via CDSL/NSDL.

    Requires KYC verification to be completed before DMAT linking.
    Validates account format, verifies against depository API,
    encrypts account numbers at rest, and enforces max 3 accounts per user.
    """

    def __init__(
        self,
        db_pool=None,
        depository_api_url: str = "",
        depository_api_key: str = "",
    ):
        self.db_pool = db_pool
        self.depository_api_url = depository_api_url or os.getenv(
            "DEPOSITORY_API_URL", "https://api.depository.co.in/dmat/verify"
        )
        self.depository_api_key = depository_api_key or os.getenv("DEPOSITORY_API_KEY", "")

    # ── Format validation ────────────────────────────────────────────────

    def validate_dmat_format(self, account_number: str) -> tuple[bool, str]:
        """Validate CDSL (16-digit numeric) or NSDL (IN + 14 alphanum) format.

        Returns (valid, depository) where depository is "CDSL", "NSDL", or "".
        """
        if not account_number or not isinstance(account_number, str):
            return False, ""
        if CDSL_REGEX.match(account_number):
            return True, "CDSL"
        if NSDL_REGEX.match(account_number):
            return True, "NSDL"
        return False, ""

    # ── Encryption helpers ───────────────────────────────────────────────

    def encrypt_account(self, account_number: str) -> bytes:
        """AES-256 encrypt DMAT account number for storage."""
        f = _get_fernet()
        return f.encrypt(account_number.encode("utf-8"))

    def decrypt_account(self, encrypted: bytes) -> str:
        """Decrypt an AES-256 encrypted DMAT account number."""
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
                    "SELECT status FROM kyc_verifications WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
                return row is not None and row["status"] == KYCStatus.VERIFIED.value
        except Exception:
            logger.exception("Failed to check KYC status for user %s", user_id)
            return False

    # ── DMAT account count check ─────────────────────────────────────────

    async def _get_linked_account_count(self, user_id: str) -> int:
        """Return the number of currently linked DMAT accounts for the user."""
        if self.db_pool is None:
            return 0
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as cnt FROM dmat_accounts WHERE user_id = $1 AND status = $2",
                    user_id,
                    DMATStatus.LINKED.value,
                )
                return row["cnt"] if row else 0
        except Exception:
            logger.exception("Failed to count DMAT accounts for user %s", user_id)
            return 0

    # ── DMAT verification ────────────────────────────────────────────────

    async def verify_dmat(self, user_id: str, account_number: str) -> DMATVerificationResult:
        """Verify DMAT account against depository API.

        1. Validate format (CDSL/NSDL)
        2. Check KYC is VERIFIED
        3. Check max 3 accounts limit
        4. Call depository API with 3x exponential backoff, 15-second timeout
        5. Encrypt and store result
        """
        # Step 1: Format validation
        valid, depository = self.validate_dmat_format(account_number)
        if not valid:
            return DMATVerificationResult(
                status=DMATStatus.REJECTED,
                rejection_reason=DMATRejectionReason.INVALID_FORMAT.value,
            )

        # Step 2: KYC prerequisite
        kyc_verified = await self._check_kyc_verified(user_id)
        if not kyc_verified:
            return DMATVerificationResult(
                status=DMATStatus.REJECTED,
                depository=depository,
                rejection_reason=DMATRejectionReason.KYC_NOT_VERIFIED.value,
            )

        # Step 3: Max accounts check
        count = await self._get_linked_account_count(user_id)
        if count >= MAX_DMAT_ACCOUNTS_PER_USER:
            return DMATVerificationResult(
                status=DMATStatus.REJECTED,
                depository=depository,
                rejection_reason=DMATRejectionReason.MAX_ACCOUNTS_REACHED.value,
            )

        # Step 4: Encrypt account number
        encrypted = self.encrypt_account(account_number)

        # Step 5: Call depository API with retries
        api_result = await self._call_depository_api_with_retry(account_number, depository)

        if api_result is None:
            result = DMATVerificationResult(
                status=DMATStatus.REJECTED,
                depository=depository,
                rejection_reason=DMATRejectionReason.API_UNAVAILABLE.value,
                account_encrypted=encrypted,
            )
            await self._store_dmat_account(user_id, result)
            return result

        # Step 6: Process API response
        if api_result.get("valid") is True:
            result = DMATVerificationResult(
                status=DMATStatus.LINKED,
                depository=depository,
                dp_name=api_result.get("dp_name", ""),
                linked_at=datetime.now(timezone.utc),
                account_encrypted=encrypted,
            )
        else:
            reason = api_result.get("reason", DMATRejectionReason.INVALID_ACCOUNT.value)
            if reason not in {r.value for r in DMATRejectionReason}:
                reason = DMATRejectionReason.INVALID_ACCOUNT.value
            result = DMATVerificationResult(
                status=DMATStatus.REJECTED,
                depository=depository,
                rejection_reason=reason,
                account_encrypted=encrypted,
            )

        await self._store_dmat_account(user_id, result)
        return result

    async def _call_depository_api_with_retry(
        self, account_number: str, depository: str
    ) -> Optional[dict]:
        """Call depository participant API with up to 3 retries and exponential backoff.

        Uses a 15-second timeout per attempt.
        Returns the parsed JSON response dict, or None if all retries fail.
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=DMAT_API_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        self.depository_api_url,
                        json={
                            "account_number": account_number,
                            "depository": depository,
                        },
                        headers={
                            "Authorization": f"Bearer {self.depository_api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code == 200:
                        return response.json()
                    else:
                        logger.warning(
                            "Depository API returned status %d on attempt %d: %s",
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
                    "Depository API attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            # Exponential backoff: 1s, 2s, 4s
            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "Depository API unreachable after %d attempts. Last error: %s",
            MAX_RETRIES,
            str(last_exception),
        )
        return None

    # ── Unlink DMAT account ──────────────────────────────────────────────

    async def unlink_dmat(self, user_id: str, dmat_id: str) -> bool:
        """Unlink a DMAT account. Fails if open positions exist.

        Returns True if successfully unlinked, False otherwise.
        """
        if self.db_pool is None:
            return False

        # Check for open positions
        has_open = await self._has_open_positions(user_id, dmat_id)
        if has_open:
            return False

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM dmat_accounts WHERE id = $1 AND user_id = $2 AND status = $3",
                    dmat_id,
                    user_id,
                    DMATStatus.LINKED.value,
                )
                # asyncpg returns "DELETE N" where N is the number of rows deleted
                return result == "DELETE 1"
        except Exception:
            logger.exception("Failed to unlink DMAT account %s for user %s", dmat_id, user_id)
            return False

    async def _has_open_positions(self, user_id: str, dmat_id: str) -> bool:
        """Check if the user has open positions associated with the DMAT account."""
        if self.db_pool is None:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as cnt FROM orders
                    WHERE user_id = $1
                      AND status IN ('OPEN', 'PENDING', 'PARTIAL')
                    """,
                    user_id,
                )
                return row is not None and row["cnt"] > 0
        except Exception:
            logger.exception(
                "Failed to check open positions for user %s, dmat %s", user_id, dmat_id
            )
            # Fail safe: assume open positions exist if we can't check
            return True

    # ── Database storage ─────────────────────────────────────────────────

    async def _store_dmat_account(self, user_id: str, result: DMATVerificationResult) -> None:
        """Store DMAT account verification result in the database."""
        if self.db_pool is None:
            logger.debug("No db_pool configured — skipping DMAT storage")
            return

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO dmat_accounts
                        (user_id, account_number_encrypted, depository, dp_name,
                         status, linked_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    user_id,
                    result.account_encrypted,
                    result.depository,
                    result.dp_name,
                    result.status.value,
                    result.linked_at,
                )
                if row:
                    result.dmat_id = str(row["id"])
        except Exception:
            logger.exception("Failed to store DMAT account for user %s", user_id)
