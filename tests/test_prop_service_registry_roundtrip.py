"""Property-based tests for Service Registry State Round-Trip.

Verifies that the ServiceRegistry correctly persists state to JSON and
restores it identically on reload. Any valid mapping of group_ids to
ServiceStatus values must survive a serialize → deserialize cycle.

# Feature: easy-setup-wizard, Property 2: Service registry state round-trip

**Validates: Requirements 3.4**

Properties tested:
  1. For any valid registry state (mapping of group_ids to ServiceStatus),
     serializing to JSON and deserializing back produces an equivalent state
     with all group statuses preserved.
"""

import json
import sys
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Import shim for backend-gateway (hyphenated directory name)
# ---------------------------------------------------------------------------
# The service_registry module lives under ``backend-gateway/app/services/``.
# Because ``backend-gateway`` has a hyphen, there is no clean Python import
# path. We add the backend-gateway directory to sys.path so that
# ``app.services.service_registry`` resolves correctly.

_backend_gateway_dir = str(
    Path(__file__).resolve().parents[1] / "backend-gateway",
)
if _backend_gateway_dir not in sys.path:
    sys.path.insert(0, _backend_gateway_dir)

from app.services.service_registry import (  # noqa: E402
    CREDENTIAL_GROUPS,
    ServiceRegistry,
    ServiceStatus,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All valid group IDs from the static CREDENTIAL_GROUPS list
VALID_GROUP_IDS = [g.group_id for g in CREDENTIAL_GROUPS]

# Strategy: generate a random ServiceStatus for each group_id
service_status_strategy = st.sampled_from(list(ServiceStatus))

# Strategy: generate a full registry state mapping every group_id to a random status
registry_state_strategy = st.fixed_dictionaries(
    dict.fromkeys(VALID_GROUP_IDS, service_status_strategy),
)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestServiceRegistryRoundTrip:
    """Property 2: Service registry state round-trip."""

    @given(state=registry_state_strategy)
    @settings(max_examples=100)
    def test_registry_state_survives_json_round_trip(
        self,
        state: dict[str, ServiceStatus],
    ) -> None:
        """For any valid registry state, serialize to JSON and deserialize
        back SHALL produce an equivalent state with all group statuses preserved.

        **Validates: Requirements 3.4**
        """
        # Create a temporary file for the registry
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "service_registry.json"

            # Create a registry and set all statuses from the generated state
            registry = ServiceRegistry(registry_path=registry_path)
            for group_id, status in state.items():
                registry.set_status(group_id, status)

            # Verify the JSON file was written
            assert registry_path.exists(), "Registry file should exist after set_status calls"

            # Read the raw JSON to confirm it's valid JSON
            raw_json = registry_path.read_text(encoding="utf-8")
            parsed = json.loads(raw_json)
            assert "services" in parsed, "JSON must contain 'services' key"

            # Create a NEW registry instance from the same file (simulates restart)
            restored_registry = ServiceRegistry(registry_path=registry_path)

            # Assert all statuses are preserved after round-trip
            restored_statuses = restored_registry.get_all_statuses()
            for group_id, expected_status in state.items():
                actual_status = restored_statuses[group_id]
                assert actual_status == expected_status, (
                    f"Status mismatch for '{group_id}': "
                    f"expected {expected_status.value}, got {actual_status.value}"
                )

    @given(state=registry_state_strategy)
    @settings(max_examples=100)
    def test_get_all_statuses_returns_all_groups(
        self,
        state: dict[str, ServiceStatus],
    ) -> None:
        """get_all_statuses() must return an entry for every registered
        credential group, regardless of what state was set.

        **Validates: Requirements 3.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "service_registry.json"

            registry = ServiceRegistry(registry_path=registry_path)
            for group_id, status in state.items():
                registry.set_status(group_id, status)

            all_statuses = registry.get_all_statuses()

            # Every known group must be present
            for group_id in VALID_GROUP_IDS:
                assert (
                    group_id in all_statuses
                ), f"Group '{group_id}' missing from get_all_statuses()"

            # The count must match
            assert len(all_statuses) == len(VALID_GROUP_IDS)
