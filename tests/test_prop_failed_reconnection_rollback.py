"""Property-based tests for Failed Reconnection Rollback.

Verifies that when a credential update is followed by a connection test
failure, the SetupService rolls back to the previous credential values.
The new credentials are NOT persisted — the original values remain in
the .env file.

# Feature: easy-setup-wizard, Property 7: Failed reconnection rollback

**Validates: Requirements 8.5**

Properties tested:
  1. For any credential update where the subsequent connection test fails,
     the credential store SHALL retain the previous credential value
     unchanged (the new value is not persisted until connection succeeds
     or user confirms).
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

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

from app.services.connection_tester import TestResult  # noqa: E402
from app.services.credential_store import CredentialStore  # noqa: E402
from app.services.service_registry import ServiceRegistry  # noqa: E402
from app.services.setup_service import SetupService  # noqa: E402

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Shoonya API key: 8+ characters (pattern: ^.{8,}$)
shoonya_api_key_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\n\r\x00\x1c\x1d\x1e\x85#'\"",
    ),
    min_size=8,
    max_size=30,
).filter(lambda s: s.strip() == s and len(s.strip()) >= 8)

# Shoonya client ID: uppercase alphanumeric, 4+ chars (pattern: ^[A-Z0-9]{4,}$)
shoonya_client_id_strategy = st.from_regex(r"[A-Z0-9]{4,12}", fullmatch=True)

# Shoonya password: 4+ characters (pattern: ^.{4,}$)
shoonya_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\n\r\x00\x1c\x1d\x1e\x85#'\"",
    ),
    min_size=4,
    max_size=30,
).filter(lambda s: s.strip() == s and len(s.strip()) >= 4)


@st.composite
def shoonya_credentials_strategy(draw):
    """Generate a valid set of broker_shoonya credentials."""
    return {
        "SHOONYA_API_KEY": draw(shoonya_api_key_strategy),
        "SHOONYA_CLIENT_ID": draw(shoonya_client_id_strategy),
        "SHOONYA_PASSWORD": draw(shoonya_password_strategy),
    }


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestFailedReconnectionRollback:
    """Property 7: Failed reconnection rollback."""

    @given(
        initial_creds=shoonya_credentials_strategy(),
        new_creds=shoonya_credentials_strategy(),
    )
    @settings(max_examples=100)
    def test_failed_connection_retains_original_credentials(
        self,
        initial_creds: dict[str, str],
        new_creds: dict[str, str],
    ) -> None:
        """For any credential update where the subsequent connection test
        fails, the credential store SHALL retain the previous credential
        value unchanged (the new value is not persisted until connection
        succeeds or user confirms).

        **Validates: Requirements 8.5**
        """
        # Skip if initial and new creds are identical (no rollback needed)
        if initial_creds == new_creds:
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            registry_path = repo_root / "data" / "service_registry.json"

            # Create the credential store and service registry
            credential_store = CredentialStore(repo_root=repo_root)
            service_registry = ServiceRegistry(registry_path=registry_path)

            # Write initial credentials to .env
            credential_store.write_credentials("broker_shoonya", initial_creds)

            # Verify initial credentials are written
            stored = credential_store.read_raw_credentials("broker_shoonya")
            for key, value in initial_creds.items():
                assert (
                    stored.get(key) == value
                ), f"Initial write failed for {key}: expected {value!r}, got {stored.get(key)!r}"

            # Create SetupService with a mocked ConnectionTester that always fails
            setup_service = SetupService(
                credential_store=credential_store,
                service_registry=service_registry,
            )

            # Mock the connection tester to simulate failure
            mock_tester = AsyncMock()
            mock_tester.test_broker_shoonya.return_value = TestResult(
                success=False,
                error="Authentication failed — simulated test failure",
                suggestion="Check your credentials.",
            )
            setup_service.connection_tester = mock_tester

            # Call submit_and_test with new credentials — should fail and rollback
            result = asyncio.run(
                setup_service.submit_and_test("broker_shoonya", new_creds),
            )

            # Verify the connection test reported failure
            assert not result.success, "Connection test should have failed"

            # Verify original credentials are retained (rollback occurred)
            final_stored = credential_store.read_raw_credentials("broker_shoonya")
            for key, value in initial_creds.items():
                assert final_stored.get(key) == value, (
                    f"Rollback failed for {key}: expected original {value!r}, "
                    f"got {final_stored.get(key)!r} (new was {new_creds[key]!r})"
                )
