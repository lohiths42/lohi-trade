"""Account service: multi-user registration, email/password auth, social login, JWT lifecycle.

Extends the existing single-user auth_service.py for multi-user support with
PostgreSQL (asyncpg), bcrypt password hashing, JWT access/refresh tokens,
and social login via Google OAuth and Apple Sign-In.
"""

import hashlib
import logging
import os
import re
import secrets
import time
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import bcrypt
import httpx
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SECRET_KEY", "change-me-in-production"))
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRY_SECONDS = 15 * 60        # 15 minutes
REFRESH_TOKEN_EXPIRY_SECONDS = 30 * 24 * 3600  # 30 days
OTP_EXPIRY_SECONDS = 15 * 60                 # 15 minutes

# Password policy: min 8 chars, 1 upper, 1 lower, 1 digit, 1 special
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_UPPER_RE = re.compile(r"[A-Z]")
_PASSWORD_LOWER_RE = re.compile(r"[a-z]")
_PASSWORD_DIGIT_RE = re.compile(r"\d")
_PASSWORD_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")

# Google OAuth config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
_GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"

# Apple Sign-In config
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")  # Service ID (e.g. com.lohi.trade)
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "")  # PEM-encoded .p8 key
_APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

# Indian mobile phone: exactly 10 digits
_PHONE_RE = re.compile(r"^\d{10}$")

# Basic email validation
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ── Data classes ─────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    TRADER = "TRADER"
    VIEWER = "VIEWER"


class VerificationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class KYCStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass
class TokenPair:
    access_token: str   # 15-minute expiry
    refresh_token: str  # 30-day expiry


@dataclass
class User:
    id: str
    email: str
    phone: Optional[str]
    name: str
    role: UserRole
    is_onboarded: bool
    created_at: datetime


# ── Validation helpers ───────────────────────────────────────────────────────

def validate_password(password: str) -> tuple[bool, str]:
    """Validate password against policy. Returns (valid, error_message)."""
    if len(password) < _PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {_PASSWORD_MIN_LENGTH} characters"
    if not _PASSWORD_UPPER_RE.search(password):
        return False, "Password must contain at least one uppercase letter"
    if not _PASSWORD_LOWER_RE.search(password):
        return False, "Password must contain at least one lowercase letter"
    if not _PASSWORD_DIGIT_RE.search(password):
        return False, "Password must contain at least one digit"
    if not _PASSWORD_SPECIAL_RE.search(password):
        return False, "Password must contain at least one special character"
    return True, ""


def validate_email(email: str) -> bool:
    """Basic email format validation."""
    return bool(_EMAIL_RE.match(email))


def validate_phone(phone: str) -> bool:
    """Validate Indian mobile phone number (10 digits)."""
    return bool(_PHONE_RE.match(phone))


# ── Password hashing ────────────────────────────────────────────────────────
# Per spec §1.3: Argon2id with t=3, m=64MB, p=4. Legacy bcrypt hashes are
# transparently upgraded on first successful verification.

_PH = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB in KiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    """Hash password using Argon2id (spec-compliant)."""
    return _PH.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password. Accepts Argon2id and legacy bcrypt hashes."""
    # Legacy bcrypt path — any row still holding $2a/$2b/$2y
    if hashed.startswith("$2a$") or hashed.startswith("$2b$") or hashed.startswith("$2y$"):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    # Argon2 path
    try:
        _PH.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def rehash_if_needed(plain: str, hashed: str) -> Optional[str]:
    """Return a new hash if the stored one should be upgraded.

    Useful for migration: call after a successful verify_password, and if
    non-None, persist the new hash. Covers both bcrypt→Argon2 migration and
    Argon2 parameter bumps.
    """
    if hashed.startswith("$2a$") or hashed.startswith("$2b$") or hashed.startswith("$2y$"):
        return hash_password(plain)
    try:
        if _PH.check_needs_rehash(hashed):
            return hash_password(plain)
    except Exception:
        return None
    return None


# ── Token helpers ────────────────────────────────────────────────────────────

def _create_access_token(user_id: str, email: str, role: str) -> str:
    """Create a short-lived JWT access token (15 minutes)."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _create_refresh_token() -> str:
    """Create a cryptographically random refresh token string."""
    return secrets.token_urlsafe(48)


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hash of refresh token for storage (never store raw)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT access token. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Access token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid access token: {e}")
        return None


def _generate_otp() -> str:
    """Generate a 6-digit OTP for email verification."""
    return f"{secrets.randbelow(1_000_000):06d}"


# ── AccountService ───────────────────────────────────────────────────────────

class AccountService:
    """Multi-user account creation with email/password authentication.

    Uses asyncpg connection pool for PostgreSQL access. All methods are async.
    """

    def __init__(self, db_pool):
        """Initialize with an asyncpg connection pool."""
        self._pool = db_pool

    async def register_email(
        self, email: str, password: str, phone: str, name: str
    ) -> dict:
        """Register a new user via email/password.

        Validates email, password policy, phone format. Hashes password with
        bcrypt, stores user in PostgreSQL, generates OTP for email verification
        (valid 15 minutes).

        Returns dict with user info and otp (in production, OTP would be sent
        via email/SMS, not returned directly).

        Raises ValueError on validation failure or duplicate email.
        """
        # Validate email
        if not validate_email(email):
            raise ValueError("Invalid email format")

        # Validate password
        valid, msg = validate_password(password)
        if not valid:
            raise ValueError(msg)

        # Validate phone
        if not validate_phone(phone):
            raise ValueError("Phone must be a 10-digit Indian mobile number")

        # Hash password
        pw_hash = hash_password(password)

        # Generate OTP for email verification
        otp = _generate_otp()
        otp_expires_at = datetime.now(timezone.utc).timestamp() + OTP_EXPIRY_SECONDS

        async with self._pool.acquire() as conn:
            # Check for duplicate email
            existing = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", email
            )
            if existing:
                raise ValueError("An account with this email already exists")

            # Insert user
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, password_hash, phone, name, role)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, email, phone, name, role, is_onboarded, created_at
                """,
                email, pw_hash, phone, name, UserRole.TRADER.value,
            )

        user = User(
            id=str(row["id"]),
            email=row["email"],
            phone=row["phone"],
            name=row["name"],
            role=UserRole(row["role"]),
            is_onboarded=row["is_onboarded"],
            created_at=row["created_at"],
        )

        logger.info(f"User registered: {user.email} (id={user.id})")

        # In production, send OTP via email/SMS. Here we return it for the caller.
        return {
            "user": user,
            "otp": otp,
            "otp_expires_at": otp_expires_at,
        }

    async def login_email(self, email: str, password: str) -> TokenPair:
        """Authenticate with email/password and issue token pair.

        Returns TokenPair with access token (15-min) and refresh token (30-day).
        Stores hashed refresh token in the database.

        Raises ValueError on invalid credentials or inactive account.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, email, password_hash, role, is_active, name
                FROM users WHERE email = $1
                """,
                email,
            )

        if not row:
            raise ValueError("Invalid email or password")

        if not row["password_hash"]:
            raise ValueError(
                "This account uses social login. Please sign in with Google or Apple."
            )

        if not verify_password(password, row["password_hash"]):
            raise ValueError("Invalid email or password")

        if not row["is_active"]:
            raise ValueError("Account is deactivated. Contact support.")

        user_id = str(row["id"])
        role = row["role"]
        user_email = row["email"]

        # Create tokens
        access_token = _create_access_token(user_id, user_email, role)
        refresh_token = _create_refresh_token()
        refresh_hash = _hash_refresh_token(refresh_token)

        # Store refresh token
        expires_at = datetime.fromtimestamp(
            time.time() + REFRESH_TOKEN_EXPIRY_SECONDS, tz=timezone.utc
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
                """,
                row["id"], refresh_hash, expires_at,
            )

        logger.info(f"User logged in: {user_email}")
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    async def refresh_token(self, refresh_token_str: str) -> TokenPair:
        """Validate refresh token and issue a new access token + refresh token.

        The old refresh token is consumed (deleted) and a new one is issued
        (refresh token rotation for security).

        Raises ValueError if refresh token is invalid or expired.
        """
        token_hash = _hash_refresh_token(refresh_token_str)

        async with self._pool.acquire() as conn:
            # Find and validate refresh token
            row = await conn.fetchrow(
                """
                SELECT rt.id AS token_id, rt.user_id, rt.expires_at,
                       u.email, u.role, u.is_active
                FROM refresh_tokens rt
                JOIN users u ON u.id = rt.user_id
                WHERE rt.token_hash = $1
                """,
                token_hash,
            )

            if not row:
                raise ValueError("Invalid refresh token")

            if row["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                # Clean up expired token
                await conn.execute(
                    "DELETE FROM refresh_tokens WHERE id = $1", row["token_id"]
                )
                raise ValueError("Refresh token has expired")

            if not row["is_active"]:
                raise ValueError("Account is deactivated")

            # Delete old refresh token (rotation)
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE id = $1", row["token_id"]
            )

            # Issue new tokens
            user_id = str(row["user_id"])
            access_token = _create_access_token(user_id, row["email"], row["role"])
            new_refresh = _create_refresh_token()
            new_refresh_hash = _hash_refresh_token(new_refresh)

            expires_at = datetime.fromtimestamp(
                time.time() + REFRESH_TOKEN_EXPIRY_SECONDS, tz=timezone.utc
            )
            await conn.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
                """,
                row["user_id"], new_refresh_hash, expires_at,
            )

        logger.info(f"Token refreshed for user: {row['email']}")
        return TokenPair(access_token=access_token, refresh_token=new_refresh)

    # ── Social login helpers ─────────────────────────────────────────────────

    async def _issue_tokens_for_user(self, conn, user_id, email: str, role: str) -> TokenPair:
        """Issue access + refresh token pair and store refresh hash in DB."""
        access_token = _create_access_token(str(user_id), email, role)
        refresh_token = _create_refresh_token()
        refresh_hash = _hash_refresh_token(refresh_token)

        expires_at = datetime.fromtimestamp(
            time.time() + REFRESH_TOKEN_EXPIRY_SECONDS, tz=timezone.utc
        )
        await conn.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            user_id, refresh_hash, expires_at,
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    async def _find_or_create_social_user(
        self, conn, provider: str, provider_id: str, email: str, name: str
    ) -> TokenPair:
        """Core social login flow: find existing link, link to email match, or create new user.

        1. If social_logins row exists for (provider, provider_id) → login that user.
        2. Else if a user with the same email exists → link provider and login.
        3. Else → create new user (no password) and link provider.

        Returns TokenPair. Raises ValueError if account is deactivated.
        """
        # 1. Check for existing social login link
        row = await conn.fetchrow(
            """
            SELECT sl.user_id, u.email, u.role, u.is_active
            FROM social_logins sl
            JOIN users u ON u.id = sl.user_id
            WHERE sl.provider = $1 AND sl.provider_id = $2
            """,
            provider, provider_id,
        )
        if row:
            if not row["is_active"]:
                raise ValueError("Account is deactivated. Contact support.")
            logger.info(f"Social login ({provider}) for existing linked user: {row['email']}")
            return await self._issue_tokens_for_user(
                conn, row["user_id"], row["email"], row["role"]
            )

        # 2. Check if a user with the same email already exists → link
        existing_user = await conn.fetchrow(
            "SELECT id, email, role, is_active FROM users WHERE email = $1",
            email,
        )
        if existing_user:
            if not existing_user["is_active"]:
                raise ValueError("Account is deactivated. Contact support.")
            await self._link_social_provider_internal(
                conn, existing_user["id"], provider, provider_id
            )
            logger.info(f"Linked {provider} to existing account: {email}")
            return await self._issue_tokens_for_user(
                conn, existing_user["id"], existing_user["email"], existing_user["role"]
            )

        # 3. Create new user (no password) and link provider
        new_user = await conn.fetchrow(
            """
            INSERT INTO users (email, name, role)
            VALUES ($1, $2, $3)
            RETURNING id, email, role
            """,
            email, name, UserRole.TRADER.value,
        )
        await self._link_social_provider_internal(
            conn, new_user["id"], provider, provider_id
        )
        logger.info(f"Created new user via {provider}: {email}")
        return await self._issue_tokens_for_user(
            conn, new_user["id"], new_user["email"], new_user["role"]
        )

    async def _link_social_provider_internal(
        self, conn, user_id, provider: str, provider_id: str
    ) -> None:
        """Insert a social_logins row. Ignores if already linked (idempotent)."""
        await conn.execute(
            """
            INSERT INTO social_logins (user_id, provider, provider_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (provider, provider_id) DO NOTHING
            """,
            user_id, provider, provider_id,
        )

    # ── Google OAuth ─────────────────────────────────────────────────────────

    async def login_google(self, google_id_token: str) -> TokenPair:
        """Verify Google ID token, extract email/name, create or link account.

        Uses Google's tokeninfo endpoint to verify the ID token. Extracts
        email, name, and sub (provider_id). Creates a new user if none exists,
        or links to an existing account with the same email.

        Never stores the Google access token — only provider_id and provider type.

        Raises ValueError on invalid token or deactivated account.
        """
        if not google_id_token:
            raise ValueError("Google ID token is required")

        # Verify token with Google
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _GOOGLE_TOKEN_INFO_URL,
                params={"id_token": google_id_token},
            )

        if resp.status_code != 200:
            raise ValueError("Invalid Google ID token")

        token_data = resp.json()

        # Validate audience matches our client ID
        if GOOGLE_CLIENT_ID and token_data.get("aud") != GOOGLE_CLIENT_ID:
            raise ValueError("Google token audience mismatch")

        email = token_data.get("email")
        if not email:
            raise ValueError("Google account has no email")

        if not token_data.get("email_verified", "false") == "true":
            raise ValueError("Google email is not verified")

        name = token_data.get("name", email.split("@")[0])
        provider_id = token_data.get("sub")
        if not provider_id:
            raise ValueError("Invalid Google token: missing sub")

        async with self._pool.acquire() as conn:
            return await self._find_or_create_social_user(
                conn, "google", provider_id, email, name
            )

    # ── Apple Sign-In ────────────────────────────────────────────────────────

    async def login_apple(self, apple_auth_code: str, user_name: Optional[str] = None) -> TokenPair:
        """Verify Apple auth code, create or link account.

        Exchanges the authorization code for an ID token via Apple's token
        endpoint. Handles email-sharing and email-hidden scenarios:
        - If user shared email: uses the real email.
        - If user hid email: uses Apple's private relay email (*@privaterelay.appleid.com).

        Never stores the Apple access/refresh token — only provider_id (sub).

        Raises ValueError on invalid auth code or deactivated account.
        """
        if not apple_auth_code:
            raise ValueError("Apple authorization code is required")

        # Build client_secret JWT for Apple
        client_secret = self._build_apple_client_secret()

        # Exchange auth code for tokens
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _APPLE_TOKEN_URL,
                data={
                    "client_id": APPLE_CLIENT_ID,
                    "client_secret": client_secret,
                    "code": apple_auth_code,
                    "grant_type": "authorization_code",
                },
            )

        if resp.status_code != 200:
            raise ValueError("Invalid Apple authorization code")

        token_data = resp.json()
        id_token_str = token_data.get("id_token")
        if not id_token_str:
            raise ValueError("Apple response missing id_token")

        # Decode the ID token (Apple signs with RS256, we verify via JWKS)
        apple_claims = await self._verify_apple_id_token(id_token_str)

        provider_id = apple_claims.get("sub")
        if not provider_id:
            raise ValueError("Invalid Apple token: missing sub")

        # Apple may or may not share the email
        email = apple_claims.get("email")
        if not email:
            # Fallback: check if we already have this provider linked
            async with self._pool.acquire() as conn:
                existing = await conn.fetchrow(
                    """
                    SELECT u.email FROM social_logins sl
                    JOIN users u ON u.id = sl.user_id
                    WHERE sl.provider = 'apple' AND sl.provider_id = $1
                    """,
                    provider_id,
                )
            if existing:
                email = existing["email"]
            else:
                raise ValueError(
                    "Apple did not share email and no existing account found. "
                    "Please retry and allow email sharing."
                )

        name = user_name or email.split("@")[0]

        async with self._pool.acquire() as conn:
            return await self._find_or_create_social_user(
                conn, "apple", provider_id, email, name
            )

    def _build_apple_client_secret(self) -> str:
        """Build a short-lived JWT client_secret for Apple token exchange."""
        now = int(time.time())
        payload = {
            "iss": APPLE_TEAM_ID,
            "iat": now,
            "exp": now + 300,  # 5 minutes
            "aud": "https://appleid.apple.com",
            "sub": APPLE_CLIENT_ID,
        }
        headers = {"kid": APPLE_KEY_ID, "alg": "ES256"}
        return jwt.encode(payload, APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers)

    async def _verify_apple_id_token(self, id_token_str: str) -> dict:
        """Verify Apple ID token using Apple's public JWKS keys."""
        # Fetch Apple's public keys
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_APPLE_KEYS_URL)

        if resp.status_code != 200:
            raise ValueError("Failed to fetch Apple public keys")

        apple_keys = resp.json().get("keys", [])

        # Decode token header to find the matching key
        unverified_header = jwt.get_unverified_header(id_token_str)
        kid = unverified_header.get("kid")

        matching_key = None
        for key in apple_keys:
            if key.get("kid") == kid:
                matching_key = key
                break

        if not matching_key:
            raise ValueError("Apple token key ID not found in JWKS")

        # Build public key from JWK and verify
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(matching_key)

        try:
            claims = jwt.decode(
                id_token_str,
                public_key,
                algorithms=["RS256"],
                audience=APPLE_CLIENT_ID,
                issuer="https://appleid.apple.com",
            )
            return claims
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid Apple ID token: {e}")

    # ── Link social provider (public) ────────────────────────────────────────

    async def link_social_provider(
        self, user_id: str, provider: str, provider_id: str
    ) -> None:
        """Link a social provider to an existing user account.

        Stores only provider_id and provider type — never stores social access tokens.

        Raises ValueError if provider is invalid or already linked to another account.
        """
        if provider not in ("google", "apple"):
            raise ValueError(f"Unsupported provider: {provider}")

        if not provider_id:
            raise ValueError("Provider ID is required")

        async with self._pool.acquire() as conn:
            # Check if this provider_id is already linked to a different user
            existing = await conn.fetchrow(
                """
                SELECT user_id FROM social_logins
                WHERE provider = $1 AND provider_id = $2
                """,
                provider, provider_id,
            )
            if existing:
                existing_uid = str(existing["user_id"])
                if existing_uid == user_id:
                    return  # Already linked to this user, no-op
                raise ValueError(
                    f"This {provider} account is already linked to another user"
                )

            # Verify the user exists
            user_uuid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(user_id)
            user = await conn.fetchval(
                "SELECT id FROM users WHERE id = $1",
                user_uuid,
            )
            if not user:
                raise ValueError("User not found")

            await conn.execute(
                """
                INSERT INTO social_logins (user_id, provider, provider_id)
                VALUES ($1, $2, $3)
                """,
                user, provider, provider_id,
            )
