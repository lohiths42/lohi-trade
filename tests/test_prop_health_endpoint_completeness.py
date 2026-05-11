"""Property-based tests for Health Endpoint Completeness.

Verifies that SetupService.get_status() returns a SetupStatusResponse
containing an entry for every registered service with its correct
configured/available status and the list of features it affects.

# Feature: easy-setup-wizard, Property 5: Health endpoint completeness

**Validates: Requirements 4.6**

Properties tested:
  1. For any valid service registry state, the get_status() response
     SHALL contain an entry for every registered credential group with
     its correct status and features_affected list.
"""

import sys
import tempfile
from pathlib import Path

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
    CREDENTIAL_GROUPS,
    ServiceRegistry,
    ServiceStatus,
)
from app.services.setup_service import SetupService  # noqa: E402

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All valid group IDs from the static CREDENTIAL_GROUPS list
VALID_GROUP_IDS = [g.group_id for g in CREDENTIAL_GROUPS]

# Strategy: generate a random mapping of group_id → ServiceStatus
# Each group gets a randomly chosen status value.
service_status_strategy = st.sampled_from(list(ServiceStatus))

registry_state_strategy = st.fixed_dictionaries(
    dict.fromkeys(VALID_GROUP_IDS, service_status_strategy),
)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestHealthEndpointCompleteness:
    """Property 5: Health endpoint completeness."""

    @given(registry_state=registry_state_strategy)
    @settings(max_examples=200)
    def test_get_status_contains_all_services_with_correct_status(
        self, registry_state: dict[str, ServiceStatus],
    ) -> None:
        """For any valid service registry state, get_status() SHALL contain
        an entry for every registered service with correct status and
        features_affected list.

        **Validates: Requirements 4.6**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            registry_path = tmp_path / "service_registry.json"

            # Create registry and set statuses based on generated state
            registry = ServiceRegistry(registry_path=registry_path)
            for group_id, status in registry_state.items():
                registry.set_status(group_id, status)

            # Create credential store (needed by SetupService)
            credential_store = CredentialStore(repo_root=tmp_path)

            # Create SetupService and call get_status()
            setup_service = SetupService(
                credential_store=credential_store,
                service_registry=registry,
            )
            response = setup_service.get_status()

            # Build lookup from response for easy assertion
            response_by_group_id = {
                svc.group_id: svc for svc in response.services
            }

            # Assert: every registered group appears in the response
            assert len(response.services) == len(CREDENTIAL_GROUPS), (
                f"Expected {len(CREDENTIAL_GROUPS)} services in response, "
                f"got {len(response.services)}"
            )

            for group in CREDENTIAL_GROUPS:
                # Assert: group is present in response
                assert group.group_id in response_by_group_id, (
                    f"Group '{group.group_id}' missing from get_status() response. "
                    f"Registry state: {registry_state}"
                )

                svc_info = response_by_group_id[group.group_id]

                # Assert: status matches what was set in the registry
                expected_status = registry_state[group.group_id].value
                assert svc_info.status == expected_status, (
                    f"Group '{group.group_id}' status mismatch: "
                    f"expected '{expected_status}', got '{svc_info.status}'. "
                    f"Registry state: {registry_state}"
                )

                # Assert: features_affected matches the group's features_dependent
                assert svc_info.features_affected == group.features_dependent, (
                    f"Group '{group.group_id}' features_affected mismatch: "
                    f"expected {group.features_dependent}, "
                    f"got {svc_info.features_affected}. "
                    f"Registry state: {registry_state}"
                )

                # Assert: name matches the group definition
                assert svc_info.name == group.name, (
                    f"Group '{group.group_id}' name mismatch: "
                    f"expected '{group.name}', got '{svc_info.name}'"
                )

                # Assert: required flag matches the group definition
                assert svc_info.required == group.required, (
                    f"Group '{group.group_id}' required mismatch: "
                    f"expected {group.required}, got {svc_info.required}"
                )
