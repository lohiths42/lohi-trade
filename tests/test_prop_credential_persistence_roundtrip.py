"""Property-based tests for Credential Persistence Round-Trip.

Verifies that the CredentialStore correctly writes key-value pairs to
.env files and reads them back identically. Any valid set of credentials
(valid env var names, non-empty string values) must survive a write → read
cycle.

# Feature: easy-setup-wizard, Property 6: Credential persistence round-trip

**Validates: Requirements 5.1**

Properties tested:
  1. For any valid set of credentials (key-value pairs where keys are valid
     environment variable names and values are non-empty strings), writing
     them to the appropriate .env file and then reading them back SHALL
     produce equivalent key-value pairs.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway",
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

from app.services.credential_store import CredentialStore  # noqa: E402
from app.services.service_registry import (  # noqa: E402
    _GROUPS_BY_ID,
    CredentialGroup,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid environment variable names: start with uppercase letter or underscore,
# followed by uppercase letters, digits, or underscores. Minimum length 1.
env_var_name_strategy = st.from_regex(
    r"[A-Z][A-Z0-9_]{0,30}",
    fullmatch=True,
)

# Non-empty string values for credentials. Constrain to printable ASCII
# characters that are valid in .env files:
# - No newlines/carriage returns (line-based format)
# - No null bytes
# - No Unicode line separators (Python's splitlines() treats \x1c, \x1d,
#   \x1e, \x85, \u2028, \u2029 as line breaks)
# - Values must not be only whitespace
# - Values must not start/end with whitespace (stripped during parse)
# - Values must not start with '#' (treated as comment)
# Real credentials (API keys, tokens) are printable ASCII strings.
env_var_value_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),  # letters, numbers, punctuation, symbols
        blacklist_characters="\n\r\x00\x1c\x1d\x1e\x85#'\"",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() == s and len(s.strip()) > 0)

# Strategy: generate a dict of 1-5 valid key-value pairs
credentials_dict_strategy = st.dictionaries(
    keys=env_var_name_strategy,
    values=env_var_value_strategy,
    min_size=1,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestCredentialPersistenceRoundTrip:
    """Property 6: Credential persistence round-trip."""

    @given(credentials=credentials_dict_strategy)
    @settings(max_examples=100)
    def test_credentials_survive_write_read_round_trip(
        self,
        credentials: dict[str, str],
    ) -> None:
        """For any valid set of credentials (key-value pairs where keys are
        valid environment variable names and values are non-empty strings),
        writing them to the appropriate .env file and then reading them back
        SHALL produce equivalent key-value pairs.

        **Validates: Requirements 5.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)

            # Create a temporary credential group that uses our generated keys
            test_group_id = "test_roundtrip_group"
            credential_keys = list(credentials.keys())

            test_group = CredentialGroup(
                group_id=test_group_id,
                name="Test Round-Trip Group",
                description="Temporary group for property testing",
                required=False,
                env_file=".env",
                credential_keys=credential_keys,
                validation_patterns={},
                documentation_url="https://example.com",
                tooltip_hints={},
                features_dependent=[],
            )

            # Patch _GROUPS_BY_ID to include our test group
            patched_groups = {**_GROUPS_BY_ID, test_group_id: test_group}

            with patch(
                "app.services.credential_store._GROUPS_BY_ID",
                patched_groups,
            ):
                store = CredentialStore(repo_root=repo_root)

                # Write credentials
                store.write_credentials(test_group_id, credentials)

                # Verify the .env file was created
                env_path = repo_root / ".env"
                assert env_path.exists(), ".env file should exist after write"

                # Read back raw credentials
                result = store.read_raw_credentials(test_group_id)

                # Assert equivalence for all keys
                for key, expected_value in credentials.items():
                    actual_value = result.get(key, "")
                    assert actual_value == expected_value, (
                        f"Round-trip mismatch for key '{key}': "
                        f"wrote {expected_value!r}, read back {actual_value!r}"
                    )

    @given(credentials=credentials_dict_strategy)
    @settings(max_examples=100)
    def test_credentials_written_to_correct_env_file(
        self,
        credentials: dict[str, str],
    ) -> None:
        """Credentials for a group with env_file='.env.research' must be
        written to .env.research, not .env.

        **Validates: Requirements 5.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)

            test_group_id = "test_research_group"
            credential_keys = list(credentials.keys())

            test_group = CredentialGroup(
                group_id=test_group_id,
                name="Test Research Group",
                description="Temporary group for research env testing",
                required=False,
                env_file=".env.research",
                credential_keys=credential_keys,
                validation_patterns={},
                documentation_url="https://example.com",
                tooltip_hints={},
                features_dependent=[],
            )

            patched_groups = {**_GROUPS_BY_ID, test_group_id: test_group}

            with patch(
                "app.services.credential_store._GROUPS_BY_ID",
                patched_groups,
            ):
                store = CredentialStore(repo_root=repo_root)

                # Write credentials
                store.write_credentials(test_group_id, credentials)

                # Verify .env.research was created (not .env)
                env_research_path = repo_root / ".env.research"
                assert (
                    env_research_path.exists()
                ), ".env.research file should exist for research groups"

                # Read back and verify equivalence
                result = store.read_raw_credentials(test_group_id)

                for key, expected_value in credentials.items():
                    actual_value = result.get(key, "")
                    assert actual_value == expected_value, (
                        f"Round-trip mismatch for key '{key}' in .env.research: "
                        f"wrote {expected_value!r}, read back {actual_value!r}"
                    )
