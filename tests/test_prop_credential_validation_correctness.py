"""
Property-based tests for Credential Validation Correctness.

Verifies that the CredentialStore.validate_credentials method correctly
validates credential values against their associated regex patterns. For
any random string, the validator SHALL return an error if and only if the
value does not match the expected regex pattern (including rejecting empty
strings for required fields).

# Feature: easy-setup-wizard, Property 1: Credential validation correctness

**Validates: Requirements 2.4**

Properties tested:
  1. For any credential value and its associated validation pattern, the
     validator returns a validation error iff the value does not match the
     expected regex pattern (including empty strings for required fields).
"""

import re
import sys
import tempfile
from pathlib import Path

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway"
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

from app.services.credential_store import CredentialStore  # noqa: E402
from app.services.service_registry import (  # noqa: E402
    CREDENTIAL_GROUPS,
    CredentialGroup,
)

# ---------------------------------------------------------------------------
# Collect all groups that have validation patterns (non-empty credential_keys)
# ---------------------------------------------------------------------------

GROUPS_WITH_PATTERNS: list[CredentialGroup] = [
    g for g in CREDENTIAL_GROUPS if g.validation_patterns
]

# Build a flat list of (group_id, key_name, pattern) tuples for testing
VALIDATION_ENTRIES: list[tuple[str, str, str]] = []
for group in GROUPS_WITH_PATTERNS:
    for key, pattern in group.validation_patterns.items():
        VALIDATION_ENTRIES.append((group.group_id, key, pattern))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating random strings (both matching and non-matching)
# Include empty strings to test required field validation
random_credential_value = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=0,
    max_size=100,
)

# Strategy for selecting a validation entry (group_id, key, pattern)
validation_entry_strategy = st.sampled_from(VALIDATION_ENTRIES)

# Strategy for generating strings that MATCH specific patterns
# We generate valid strings for each known pattern to ensure positive cases


def valid_nvidia_nim_key() -> st.SearchStrategy[str]:
    """Generate strings matching ^nvapi-[A-Za-z0-9_-]{20,}$"""
    suffix = st.text(
        alphabet=st.sampled_from(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        ),
        min_size=20,
        max_size=60,
    )
    return suffix.map(lambda s: f"nvapi-{s}")


def valid_nubra_phone() -> st.SearchStrategy[str]:
    """Generate strings matching ^\\d{10}$"""
    return st.text(
        alphabet=st.sampled_from("0123456789"),
        min_size=10,
        max_size=10,
    )


def valid_nubra_mpin() -> st.SearchStrategy[str]:
    """Generate strings matching ^\\d{4,6}$"""
    return st.text(
        alphabet=st.sampled_from("0123456789"),
        min_size=4,
        max_size=6,
    )


def valid_nubra_totp() -> st.SearchStrategy[str]:
    """Generate strings matching ^[A-Za-z0-9+/=]{16,}$"""
    return st.text(
        alphabet=st.sampled_from(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        ),
        min_size=16,
        max_size=40,
    )


def valid_shoonya_api_key() -> st.SearchStrategy[str]:
    """Generate strings matching ^.{8,}$"""
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\n\r\x00",
        ),
        min_size=8,
        max_size=40,
    )


def valid_shoonya_client_id() -> st.SearchStrategy[str]:
    """Generate strings matching ^[A-Z0-9]{4,}$"""
    return st.text(
        alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        min_size=4,
        max_size=12,
    )


def valid_shoonya_password() -> st.SearchStrategy[str]:
    """Generate strings matching ^.{4,}$"""
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\n\r\x00",
        ),
        min_size=4,
        max_size=30,
    )


def valid_telegram_bot_token() -> st.SearchStrategy[str]:
    """Generate strings matching ^\\d+:[A-Za-z0-9_-]{35,}$"""
    digits = st.text(
        alphabet=st.sampled_from("0123456789"),
        min_size=1,
        max_size=10,
    )
    suffix = st.text(
        alphabet=st.sampled_from(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        ),
        min_size=35,
        max_size=50,
    )
    return st.tuples(digits, suffix).map(lambda t: f"{t[0]}:{t[1]}")


def valid_telegram_chat_id() -> st.SearchStrategy[str]:
    """Generate strings matching ^-?\\d+$"""
    return st.one_of(
        st.integers(min_value=0, max_value=999999999).map(str),
        st.integers(min_value=1, max_value=999999999).map(lambda n: f"-{n}"),
    )


def valid_angelone_api_key() -> st.SearchStrategy[str]:
    """Generate strings matching ^.{8,}$"""
    return valid_shoonya_api_key()


def valid_angelone_client_id() -> st.SearchStrategy[str]:
    """Generate strings matching ^[A-Z0-9]{4,}$"""
    return valid_shoonya_client_id()


def valid_angelone_password() -> st.SearchStrategy[str]:
    """Generate strings matching ^.{4,}$"""
    return valid_shoonya_password()


# Map (group_id, key) → strategy that generates valid values
VALID_VALUE_STRATEGIES: dict[tuple[str, str], st.SearchStrategy[str]] = {
    ("nvidia_nim", "NVIDIA_NIM_API_KEY"): valid_nvidia_nim_key(),
    ("nubra", "NUBRA_PHONE_NO"): valid_nubra_phone(),
    ("nubra", "NUBRA_MPIN"): valid_nubra_mpin(),
    ("nubra", "NUBRA_TOTP_SECRET"): valid_nubra_totp(),
    ("broker_shoonya", "SHOONYA_API_KEY"): valid_shoonya_api_key(),
    ("broker_shoonya", "SHOONYA_CLIENT_ID"): valid_shoonya_client_id(),
    ("broker_shoonya", "SHOONYA_PASSWORD"): valid_shoonya_password(),
    ("telegram", "TELEGRAM_BOT_TOKEN"): valid_telegram_bot_token(),
    ("telegram", "TELEGRAM_CHAT_ID"): valid_telegram_chat_id(),
    ("broker_angelone", "ANGELONE_API_KEY"): valid_angelone_api_key(),
    ("broker_angelone", "ANGELONE_CLIENT_ID"): valid_angelone_client_id(),
    ("broker_angelone", "ANGELONE_PASSWORD"): valid_angelone_password(),
}


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestCredentialValidationCorrectness:
    """Property 1: Credential validation correctness."""

    @given(
        entry=validation_entry_strategy,
        value=random_credential_value,
    )
    @settings(max_examples=200)
    def test_validator_returns_error_iff_value_does_not_match_pattern(
        self, entry: tuple[str, str, str], value: str
    ) -> None:
        """For any credential value and its associated validation pattern,
        the validator SHALL return a validation error if and only if the
        value does not match the expected regex pattern (including rejecting
        empty strings for required fields).

        **Validates: Requirements 2.4**
        """
        group_id, key_name, pattern = entry

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = CredentialStore(repo_root=Path(tmp_dir))

            # Submit credentials with the generated value for this key
            credentials = {key_name: value}
            errors = store.validate_credentials(group_id, credentials)

            # Determine expected result independently
            if not value:
                # Empty string should always produce an error
                assert key_name in errors, (
                    f"Empty string for '{key_name}' in group '{group_id}' "
                    f"should produce a validation error, but got none. "
                    f"Pattern: {pattern}"
                )
            elif re.match(pattern, value):
                # Value matches pattern → no error expected
                assert key_name not in errors, (
                    f"Value {value!r} matches pattern {pattern!r} for "
                    f"'{key_name}' in group '{group_id}', but validator "
                    f"returned error: {errors.get(key_name)}"
                )
            else:
                # Value does not match pattern → error expected
                assert key_name in errors, (
                    f"Value {value!r} does NOT match pattern {pattern!r} for "
                    f"'{key_name}' in group '{group_id}', but validator "
                    f"returned no error."
                )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_valid_values_pass_validation(self, data: st.DataObject) -> None:
        """For any value that matches the regex pattern, the validator
        SHALL NOT return an error for that field.

        This test generates values known to match each pattern to ensure
        positive validation cases are covered.

        **Validates: Requirements 2.4**
        """
        # Pick a random (group_id, key) pair
        group_key = data.draw(st.sampled_from(list(VALID_VALUE_STRATEGIES.keys())))
        group_id, key_name = group_key

        # Generate a valid value for this key
        valid_value = data.draw(VALID_VALUE_STRATEGIES[group_key])

        # Look up the pattern
        group = next(g for g in CREDENTIAL_GROUPS if g.group_id == group_id)
        pattern = group.validation_patterns[key_name]

        # Sanity check: our generator should produce matching values
        assert re.match(pattern, valid_value), (
            f"Generator produced value {valid_value!r} that doesn't match "
            f"pattern {pattern!r} for {key_name}"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = CredentialStore(repo_root=Path(tmp_dir))

            credentials = {key_name: valid_value}
            errors = store.validate_credentials(group_id, credentials)

            assert key_name not in errors, (
                f"Valid value {valid_value!r} for '{key_name}' in group "
                f"'{group_id}' should pass validation, but got error: "
                f"{errors.get(key_name)}. Pattern: {pattern}"
            )

    @given(entry=validation_entry_strategy)
    @settings(max_examples=100)
    def test_empty_string_always_rejected(
        self, entry: tuple[str, str, str]
    ) -> None:
        """For any credential key with a validation pattern, an empty
        string SHALL always produce a validation error (required field).

        **Validates: Requirements 2.4**
        """
        group_id, key_name, pattern = entry

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = CredentialStore(repo_root=Path(tmp_dir))

            credentials = {key_name: ""}
            errors = store.validate_credentials(group_id, credentials)

            assert key_name in errors, (
                f"Empty string for '{key_name}' in group '{group_id}' "
                f"should always be rejected, but no error was returned."
            )
