"""Property-based tests for DMAT format validation.

**Validates: Requirements 3.2**

Property 8: DMAT format validation — CDSL (16-digit) and NSDL (IN + 14 alphanum)
formats correctly identified.
"""

import os
import re
import string

from cryptography.fernet import Fernet

# Set a test encryption key before importing the service module
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.verification_service import DMATService

CDSL_REGEX = re.compile(r"^\d{16}$")
NSDL_REGEX = re.compile(r"^IN[A-Za-z0-9]{14}$")

# ── Strategies ───────────────────────────────────────────────────────────────

# Strategy: generate valid CDSL strings (exactly 16 digits)
valid_cdsl = st.text(alphabet=string.digits, min_size=16, max_size=16)

# Strategy: generate valid NSDL strings ("IN" + 14 alphanumeric characters)
_alphanum = string.ascii_letters + string.digits
valid_nsdl = st.text(alphabet=_alphanum, min_size=14, max_size=14).map(
    lambda suffix: "IN" + suffix
)

# Strategy: arbitrary text strings
any_string = st.text(min_size=0, max_size=50)


# ── Property 8: DMAT format validation ───────────────────────────────────────


class TestDMATFormatValidationProperty:
    """**Validates: Requirements 3.2**

    Property 8: DMAT format validation — CDSL (16-digit) and NSDL
    (IN + 14 alphanum) formats correctly identified.
    """

    def setup_method(self):
        self.service = DMATService()

    # ── Property 1: Valid CDSL strings identified as CDSL ────────────────

    @given(account=valid_cdsl)
    @settings(max_examples=100)
    def test_valid_cdsl_format_identified(self, account: str):
        """Any 16-digit numeric string should be identified as CDSL."""
        assert CDSL_REGEX.match(account), f"Generated CDSL doesn't match pattern: {account}"
        valid, depository = self.service.validate_dmat_format(account)
        assert valid is True, f"Valid CDSL '{account}' was rejected"
        assert depository == "CDSL", f"Expected depository 'CDSL', got '{depository}'"

    # ── Property 2: Valid NSDL strings identified as NSDL ────────────────

    @given(account=valid_nsdl)
    @settings(max_examples=100)
    def test_valid_nsdl_format_identified(self, account: str):
        """Any string starting with 'IN' + 14 alphanumeric chars should be identified as NSDL."""
        assert NSDL_REGEX.match(account), f"Generated NSDL doesn't match pattern: {account}"
        valid, depository = self.service.validate_dmat_format(account)
        assert valid is True, f"Valid NSDL '{account}' was rejected"
        assert depository == "NSDL", f"Expected depository 'NSDL', got '{depository}'"

    # ── Property 3: Non-matching strings rejected ────────────────────────

    @given(s=any_string)
    @settings(max_examples=100)
    def test_non_matching_strings_rejected(self, s: str):
        """Strings not matching either CDSL or NSDL format should be rejected."""
        assume(not CDSL_REGEX.match(s))
        assume(not NSDL_REGEX.match(s))
        valid, depository = self.service.validate_dmat_format(s)
        assert valid is False, f"Invalid string '{s}' was accepted"
        assert depository == "", f"Expected empty depository, got '{depository}'"

    # ── Property 4: Return type is always a 2-tuple ──────────────────────

    @given(s=any_string)
    @settings(max_examples=100)
    def test_validate_dmat_format_returns_2_tuple(self, s: str):
        """validate_dmat_format always returns a 2-tuple (bool, str)."""
        result = self.service.validate_dmat_format(s)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 2, f"Expected 2-tuple, got {len(result)}-tuple"
        valid, depository = result
        assert isinstance(valid, bool), f"Expected bool for valid, got {type(valid)}"
        assert isinstance(depository, str), f"Expected str for depository, got {type(depository)}"
