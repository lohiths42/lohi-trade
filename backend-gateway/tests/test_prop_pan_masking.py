"""Property-based tests for PAN masking correctness.

**Validates: Requirements 1.7**

Property 7: PAN masking correctness — masked PAN always shows exactly
first 2 and last 2 characters with 6 asterisks.
"""

import os
import string

from cryptography.fernet import Fernet

# Set a test encryption key before importing the service module
_TEST_KEY = Fernet.generate_key().decode()
os.environ["PAN_ENCRYPTION_KEY"] = _TEST_KEY

import pytest
from app.services.verification_service import PANVerificationService
from hypothesis import given, settings
from hypothesis import strategies as st

# ── Strategies ───────────────────────────────────────────────────────────────

# Strategy: generate valid PAN strings (5 uppercase + 4 digits + 1 uppercase)
valid_pan = st.tuples(
    st.text(alphabet=string.ascii_uppercase, min_size=5, max_size=5),
    st.text(alphabet=string.digits, min_size=4, max_size=4),
    st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=1),
).map(lambda parts: parts[0] + parts[1] + parts[2])


# ── Property 7: PAN masking correctness ──────────────────────────────────────


class TestPANMaskingCorrectnessProperty:
    """**Validates: Requirements 1.7**

    Property 7: PAN masking correctness — masked PAN always shows exactly
    first 2 and last 2 characters with 6 asterisks.
    """

    def setup_method(self):
        self.service = PANVerificationService()

    @given(pan=valid_pan)
    @settings(max_examples=100)
    def test_masked_pan_length_is_always_10(self, pan: str):
        """For any valid 10-char PAN, the masked result is always 10 characters."""
        masked = self.service.mask_pan(pan)
        assert (
            len(masked) == 10
        ), f"Expected masked PAN length 10, got {len(masked)} for '{pan}' → '{masked}'"

    @given(pan=valid_pan)
    @settings(max_examples=100)
    def test_first_two_chars_preserved(self, pan: str):
        """First 2 characters of masked PAN match first 2 characters of original."""
        masked = self.service.mask_pan(pan)
        assert (
            masked[:2] == pan[:2]
        ), f"First 2 chars mismatch: original '{pan[:2]}', masked '{masked[:2]}'"

    @given(pan=valid_pan)
    @settings(max_examples=100)
    def test_last_two_chars_preserved(self, pan: str):
        """Last 2 characters of masked PAN match last 2 characters of original."""
        masked = self.service.mask_pan(pan)
        assert (
            masked[8:] == pan[8:]
        ), f"Last 2 chars mismatch: original '{pan[8:]}', masked '{masked[8:]}'"

    @given(pan=valid_pan)
    @settings(max_examples=100)
    def test_middle_six_chars_are_asterisks(self, pan: str):
        """Middle 6 characters of masked PAN are always asterisks."""
        masked = self.service.mask_pan(pan)
        assert (
            masked[2:8] == "******"
        ), f"Middle chars should be '******', got '{masked[2:8]}' for '{pan}' → '{masked}'"

    @given(s=st.text(min_size=0, max_size=50).filter(lambda x: len(x) != 10))
    @settings(max_examples=100)
    def test_non_10_char_strings_raise_value_error(self, s: str):
        """mask_pan raises ValueError for strings that are not exactly 10 characters."""
        with pytest.raises(ValueError, match="PAN must be exactly 10 characters"):
            self.service.mask_pan(s)
