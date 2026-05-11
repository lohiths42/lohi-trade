"""Property-based tests for PAN format validation.

**Validates: Requirements 1.1**

Property 6: PAN format validation — all strings matching [A-Z]{5}[0-9]{4}[A-Z]{1}
are accepted, all others rejected.
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

from app.services.verification_service import PANVerificationService

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# ── Strategies ───────────────────────────────────────────────────────────────

# Strategy: generate valid PAN strings (5 uppercase + 4 digits + 1 uppercase)
valid_pan = st.tuples(
    st.text(alphabet=string.ascii_uppercase, min_size=5, max_size=5),
    st.text(alphabet=string.digits, min_size=4, max_size=4),
    st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=1),
).map(lambda parts: parts[0] + parts[1] + parts[2])

# Strategy: arbitrary text strings that may or may not match PAN format
any_string = st.text(min_size=0, max_size=50)


# ── Property 6: PAN format validation ────────────────────────────────────────


class TestPANFormatValidationProperty:
    """**Validates: Requirements 1.1**

    Property 6: PAN format validation — all strings matching
    [A-Z]{5}[0-9]{4}[A-Z]{1} are accepted, all others rejected.
    """

    def setup_method(self):
        self.service = PANVerificationService()

    @given(pan=valid_pan)
    @settings(max_examples=100)
    def test_valid_pan_format_accepted(self, pan: str):
        """Any string matching [A-Z]{5}[0-9]{4}[A-Z]{1} must be accepted."""
        assert PAN_PATTERN.match(pan), f"Generated PAN doesn't match pattern: {pan}"
        result = self.service.validate_format(pan)
        assert result is True, f"Valid PAN '{pan}' was rejected"

    @given(s=any_string)
    @settings(max_examples=100)
    def test_non_matching_strings_rejected(self, s: str):
        """Any string NOT matching [A-Z]{5}[0-9]{4}[A-Z]{1} must be rejected."""
        assume(not PAN_PATTERN.match(s))
        result = self.service.validate_format(s)
        assert result is False, f"Invalid string '{s}' was accepted as valid PAN"

    @given(pan=valid_pan)
    @settings(max_examples=50)
    def test_validate_format_agrees_with_regex(self, pan: str):
        """validate_format() result must always agree with the PAN regex."""
        regex_match = bool(PAN_PATTERN.match(pan))
        service_result = self.service.validate_format(pan)
        assert service_result == regex_match, (
            f"Mismatch: regex says {regex_match}, service says {service_result} for '{pan}'"
        )

    @given(s=any_string)
    @settings(max_examples=100)
    def test_format_validation_matches_regex_for_arbitrary_input(self, s: str):
        """For any arbitrary string, validate_format() agrees with the regex."""
        regex_match = bool(PAN_PATTERN.match(s))
        service_result = self.service.validate_format(s)
        assert service_result == regex_match, (
            f"Mismatch: regex says {regex_match}, service says {service_result} for '{s!r}'"
        )
