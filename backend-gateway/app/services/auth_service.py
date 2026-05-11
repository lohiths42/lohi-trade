"""Authentication service — spec §1.3 compliant.

Key properties:
  • Argon2id password hashing (t=3, m=64MB, p=4) — NOT bcrypt.
  • RFC 6238 TOTP via pyotp (30s window, ±1 skew) for authenticator-app
    compatibility (Google Authenticator, 1Password, Raivo, etc.).
  • JWT sessions with 24h idle / 7d absolute expiry.
  • Argon2 rehash-on-verify so old hashes auto-upgrade.

Storage:
  Users live in data/users.json for now. Migration to PG users table is
  straightforward — same read/write contract. Single-user model means we
  expect 1 row. First run creates admin from env vars.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SECRET_KEY", "change-me-in-production"))
JWT_ALGORITHM = "HS256"
JWT_IDLE_SECONDS = 24 * 60 * 60          # 24h idle
JWT_ABSOLUTE_SECONDS = 7 * 24 * 60 * 60  # 7d absolute

# Argon2id parameters per spec §1.3: t=3, m=64MB, p=4
_PH = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB in KiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Argon2id-hash a plaintext password. Use on signup/change-password."""
    return _PH.hash(plain)


def verify_password(plain: str, hashed: str) -> tuple[bool, Optional[str]]:
    """
    Verify a plaintext password against an Argon2 hash.

    Returns (ok, new_hash_or_none):
      • ok          — True if the password matches.
      • new_hash    — If non-None, the caller should persist this upgraded
                      hash (Argon2's `check_needs_rehash` returned True, or
                      we detected a legacy bcrypt hash and re-hashed it).
    """
    # Legacy bcrypt fallback — old users.json files had $2b$ hashes.
    # Upgrade them to Argon2id transparently on first successful login.
    if hashed.startswith("$2a$") or hashed.startswith("$2b$") or hashed.startswith("$2y$"):
        try:
            import bcrypt
            ok = bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False, None
        if ok:
            return True, hash_password(plain)
        return False, None

    # Argon2id path
    try:
        _PH.verify(hashed, plain)
    except VerifyMismatchError:
        return False, None
    except (InvalidHashError, VerificationError):
        return False, None

    new_hash: Optional[str] = None
    try:
        if _PH.check_needs_rehash(hashed):
            new_hash = hash_password(plain)
    except Exception:
        pass
    return True, new_hash


# ── User store ───────────────────────────────────────────────────────────────
_USER_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "users.json"


def _default_user() -> dict:
    """First-run admin created from env vars."""
    return {
        "username": os.getenv("ADMIN_USERNAME", "admin"),
        "password_hash": hash_password(os.getenv("ADMIN_PASSWORD", "admin123")),
        "role": "admin",
        "totp_secret": os.getenv("TOTP_SECRET", ""),  # empty → TOTP not yet enrolled
        "recovery_hash": "",  # 12-word phrase hash, populated at setup
        "backup_codes": [],   # hashed single-use codes
    }


def _load_users() -> dict:
    try:
        if _USER_FILE.exists():
            with open(_USER_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
    except Exception as e:
        logger.warning(f"Failed to load users file ({e}); creating default admin")
    user = _default_user()
    _save_users({user["username"]: user})
    return {user["username"]: user}


def _save_users(users: dict) -> None:
    _USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically so a crash can't leave a half-written file.
    tmp = _USER_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, _USER_FILE)
    try:
        os.chmod(_USER_FILE, 0o600)
    except OSError:
        pass  # Windows


def _update_user(username: str, updates: dict) -> None:
    users = _load_users()
    if username not in users:
        return
    users[username].update(updates)
    _save_users(users)


# ── JWT sessions ─────────────────────────────────────────────────────────────

def create_token(username: str, role: str = "admin") -> str:
    """Issue a new session token. Carries iat and abs_exp so we enforce both
    idle timeout (via exp) and an absolute 7-day expiry."""
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + JWT_IDLE_SECONDS,
        "abs_exp": now + JWT_ABSOLUTE_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Returns decoded payload or None if invalid / idle-expired / past abs-exp."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

    # Enforce absolute expiry even if the idle exp was refreshed.
    abs_exp = payload.get("abs_exp")
    if abs_exp is not None and int(time.time()) >= int(abs_exp):
        return None
    return payload


# ── TOTP (RFC 6238 via pyotp) ────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a fresh base32 secret for a new user."""
    return pyotp.random_base32()


def totp_provisioning_uri(username: str, secret: str, issuer: str = "LOHI-TRADE") -> str:
    """Build the otpauth:// URI for QR-code provisioning."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. 30s window with ±1 skew."""
    if not secret:
        return True  # TOTP not enrolled → skip (first-run setup path)
    if not code or not code.isdigit() or len(code) != 6:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


# ── Authentication flow ──────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> Optional[dict]:
    """Verify credentials. Returns user dict (no hash) or None."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    ok, new_hash = verify_password(password, user["password_hash"])
    if not ok:
        return None
    if new_hash:
        # Transparently upgrade bcrypt → Argon2id or re-hash with stronger params
        _update_user(username, {"password_hash": new_hash})
        logger.info(f"Password hash upgraded for {username}")
    return {
        "username": user["username"],
        "role": user["role"],
        "totp_enabled": bool(user.get("totp_secret")),
    }


def authenticate_totp(username: str, code: str) -> bool:
    """Verify TOTP for a user. Returns True if valid or TOTP disabled."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return False
    secret = user.get("totp_secret", "")
    if not secret:
        return True  # TOTP not yet enrolled
    return verify_totp(secret, code)


def change_password(username: str, current: str, new: str) -> bool:
    """Verify current password then update to a new Argon2id hash."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return False
    ok, _ = verify_password(current, user["password_hash"])
    if not ok:
        return False
    _update_user(username, {"password_hash": hash_password(new)})
    return True


def enroll_totp(username: str) -> str:
    """Generate and save a new TOTP secret for the user. Returns the secret
    so the caller can render a QR code for initial provisioning."""
    secret = generate_totp_secret()
    _update_user(username, {"totp_secret": secret})
    return secret
