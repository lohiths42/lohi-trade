"""Property-based tests for authentication: password policy and JWT token lifecycle.

**Validates: Requirements 29.2, 32.6**

Property 3: Password policy enforcement — all accepted passwords satisfy
    min 8 chars, 1 upper, 1 lower, 1 digit, 1 special char.
Property 4: JWT token lifecycle — access tokens expire after 15 minutes,
    refresh tokens after 30 days.
"""

import re
import string
import time

import jwt as pyjwt
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.account_service import (
    ACCESS_TOKEN_EXPIRY_SECONDS,
    JWT_ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRY_SECONDS,
    _create_access_token,
    validate_password,
    verify_access_token,
)


# ── Strategies ───────────────────────────────────────────────────────────────

# Strategy: arbitrary text strings (may or may not satisfy password policy)
any_string = st.text(min_size=0, max_size=128)

# Strategy: strings that are guaranteed to satisfy the password policy
def _valid_password_strategy():
    """Generate strings that always satisfy the password policy."""
    return st.tuples(
        st.text(
            alphabet=string.ascii_uppercase, min_size=1, max_size=10
        ),
        st.text(
            alphabet=string.ascii_lowercase, min_size=1, max_size=10
        ),
        st.text(alphabet=string.digits, min_size=1, max_size=10),
        st.text(
            alphabet="!@#$%^&*()-_=+[]{}|;:',.<>?/`~",
            min_size=1,
            max_size=10,
        ),
        st.text(
            alphabet=string.ascii_letters + string.digits + "!@#$%^&*()-_=+",
            min_size=0,
            max_size=20,
        ),
    ).map(lambda parts: "".join(parts)).filter(lambda s: len(s) >= 8)


valid_password = _valid_password_strategy()


# ── Property 3: Password policy enforcement ──────────────────────────────────


class TestPasswordPolicyProperty:
    """**Validates: Requirements 29.2**

    Property 3: Password policy enforcement — all accepted passwords satisfy
    min 8 chars, 1 upper, 1 lower, 1 digit, 1 special char.
    """

    @given(password=any_string)
    @settings(max_examples=100)
    def test_accepted_passwords_satisfy_all_rules(self, password: str):
        """If validate_password returns True, the password must have >= 8 chars,
        at least 1 uppercase, 1 lowercase, 1 digit, and 1 special character."""
        ok, _ = validate_password(password)
        if ok:
            assert len(password) >= 8, "Accepted password shorter than 8 chars"
            assert re.search(r"[A-Z]", password), "Accepted password missing uppercase"
            assert re.search(r"[a-z]", password), "Accepted password missing lowercase"
            assert re.search(r"\d", password), "Accepted password missing digit"
            assert re.search(
                r"[^A-Za-z0-9]", password
            ), "Accepted password missing special char"

    @given(password=valid_password)
    @settings(max_examples=100)
    def test_valid_passwords_are_accepted(self, password: str):
        """Passwords that satisfy all rules must be accepted."""
        ok, msg = validate_password(password)
        assert ok is True, f"Valid password rejected: {msg}"

    @given(password=st.text(alphabet=string.ascii_lowercase + string.digits + "!@#$%", min_size=8, max_size=30))
    @settings(max_examples=50)
    def test_no_uppercase_rejected(self, password: str):
        """Passwords without any uppercase letter must be rejected."""
        assume(not re.search(r"[A-Z]", password))
        ok, msg = validate_password(password)
        assert ok is False, "Password without uppercase was accepted"
        assert "uppercase" in msg.lower()

    @given(
        upper=st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=5),
        digits=st.text(alphabet=string.digits, min_size=1, max_size=5),
        special=st.text(alphabet="!@#$%^&*", min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_no_lowercase_rejected(self, upper: str, digits: str, special: str):
        """Passwords with upper, digit, special but NO lowercase must be rejected."""
        password = upper + digits + special
        assume(len(password) >= 8)
        assume(not re.search(r"[a-z]", password))
        ok, _ = validate_password(password)
        assert ok is False, "Password without lowercase was accepted"

    @given(
        upper=st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=5),
        lower=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=5),
        special=st.text(alphabet="!@#$%^&*", min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_no_digit_rejected(self, upper: str, lower: str, special: str):
        """Passwords with upper, lower, special but NO digit must be rejected."""
        password = upper + lower + special
        assume(len(password) >= 8)
        assume(not re.search(r"\d", password))
        ok, _ = validate_password(password)
        assert ok is False, "Password without digit was accepted"

    @given(
        upper=st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=5),
        lower=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=5),
        digits=st.text(alphabet=string.digits, min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_no_special_char_rejected(self, upper: str, lower: str, digits: str):
        """Passwords with upper, lower, digit but NO special char must be rejected."""
        password = upper + lower + digits
        assume(len(password) >= 8)
        assume(not re.search(r"[^A-Za-z0-9]", password))
        ok, _ = validate_password(password)
        assert ok is False, "Password without special char was accepted"

    @given(password=st.text(min_size=0, max_size=7))
    @settings(max_examples=50)
    def test_short_passwords_rejected(self, password: str):
        """Passwords shorter than 8 characters must always be rejected."""
        ok, _ = validate_password(password)
        assert ok is False, f"Short password (len={len(password)}) was accepted"


# ── Property 4: JWT token lifecycle ──────────────────────────────────────────


class TestJWTTokenLifecycleProperty:
    """**Validates: Requirements 32.6**

    Property 4: JWT token lifecycle — access tokens expire after 15 minutes,
    refresh tokens after 30 days.
    """

    @given(
        user_id=st.uuids().map(str),
        email=st.emails(),
        role=st.sampled_from(["ADMIN", "TRADER", "VIEWER"]),
    )
    @settings(max_examples=50)
    def test_access_token_expiry_is_15_minutes(
        self, user_id: str, email: str, role: str
    ):
        """The exp claim in an access token must be exactly
        ACCESS_TOKEN_EXPIRY_SECONDS (900s / 15 min) after iat."""
        token = _create_access_token(user_id, email, role)
        payload = pyjwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )

        iat = payload["iat"]
        exp = payload["exp"]
        assert exp - iat == ACCESS_TOKEN_EXPIRY_SECONDS, (
            f"Expected exp - iat == {ACCESS_TOKEN_EXPIRY_SECONDS}, "
            f"got {exp - iat}"
        )

    @given(
        user_id=st.uuids().map(str),
        email=st.emails(),
        role=st.sampled_from(["ADMIN", "TRADER", "VIEWER"]),
    )
    @settings(max_examples=50)
    def test_access_token_verifiable_before_expiry(
        self, user_id: str, email: str, role: str
    ):
        """A freshly created access token must be verifiable and contain
        the correct sub, email, and role claims."""
        token = _create_access_token(user_id, email, role)
        payload = verify_access_token(token)

        assert payload is not None, "Fresh access token failed verification"
        assert payload["sub"] == user_id
        assert payload["email"] == email
        assert payload["role"] == role
        assert payload["type"] == "access"

    @given(
        user_id=st.uuids().map(str),
        email=st.emails(),
        role=st.sampled_from(["ADMIN", "TRADER", "VIEWER"]),
    )
    @settings(max_examples=25)
    def test_expired_access_token_rejected(
        self, user_id: str, email: str, role: str
    ):
        """An access token whose exp is in the past must be rejected
        by verify_access_token."""
        now = int(time.time())
        payload = {
            "sub": user_id,
            "email": email,
            "role": role,
            "type": "access",
            "iat": now - ACCESS_TOKEN_EXPIRY_SECONDS - 60,
            "exp": now - 60,  # expired 60 seconds ago
        }
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        result = verify_access_token(token)
        assert result is None, "Expired access token was not rejected"

    def test_access_token_expiry_constant_is_15_minutes(self):
        """ACCESS_TOKEN_EXPIRY_SECONDS must equal 15 * 60 = 900."""
        assert ACCESS_TOKEN_EXPIRY_SECONDS == 15 * 60

    def test_refresh_token_expiry_constant_is_30_days(self):
        """REFRESH_TOKEN_EXPIRY_SECONDS must equal 30 * 24 * 3600 = 2592000."""
        assert REFRESH_TOKEN_EXPIRY_SECONDS == 30 * 24 * 3600
