"""Property-based tests for Feature Availability Correctness.

Verifies that the ServiceRegistry correctly computes feature availability
based on which services are configured. A feature is available if and only
if at least one of its dependency groups is in CONFIGURED status.

# Feature: easy-setup-wizard, Property 4: Feature availability correctness

**Validates: Requirements 4.1**

Properties tested:
  1. For any subset of configured services, the feature availability map
     marks a feature as available iff at least one dependency group in its
     dependency expression is in "configured" status.
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

from app.services.service_registry import (  # noqa: E402
    CREDENTIAL_GROUPS,
    FEATURE_DEPENDENCIES,
    ServiceRegistry,
    ServiceStatus,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All valid group IDs from the static CREDENTIAL_GROUPS list
VALID_GROUP_IDS = [g.group_id for g in CREDENTIAL_GROUPS]

# Strategy: generate a random subset of group IDs that are CONFIGURED.
# Non-selected groups will be left as UNCONFIGURED.
configured_subset_strategy = st.frozensets(
    st.sampled_from(VALID_GROUP_IDS),
)


# ---------------------------------------------------------------------------
# Helper: reference implementation of feature availability
# ---------------------------------------------------------------------------


def expected_feature_available(
    feature: str,
    configured_groups: frozenset[str],
) -> bool:
    """Independent reference implementation of feature availability logic.

    A feature is available iff ALL its dependency expressions are satisfied.
    Each dependency expression (e.g. "nvidia_nim|ollama") is satisfied if
    ANY of the alternatives is in the configured set.
    """
    deps = FEATURE_DEPENDENCIES.get(feature)
    if deps is None:
        return True  # Unknown features assumed available

    for dep_expr in deps:
        alternatives = [g.strip() for g in dep_expr.split("|")]
        if not any(alt in configured_groups for alt in alternatives):
            return False
    return True


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestFeatureAvailabilityCorrectness:
    """Property 4: Feature availability correctness."""

    @given(configured_groups=configured_subset_strategy)
    @settings(max_examples=200)
    def test_feature_available_iff_dependency_configured(
        self,
        configured_groups: frozenset[str],
    ) -> None:
        """For any subset of configured services, the feature availability
        map SHALL mark a feature as available if and only if at least one
        of its dependency groups is in "configured" status.

        **Validates: Requirements 4.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "service_registry.json"

            # Create registry and set statuses based on generated subset
            registry = ServiceRegistry(registry_path=registry_path)
            for group_id in VALID_GROUP_IDS:
                if group_id in configured_groups:
                    registry.set_status(group_id, ServiceStatus.CONFIGURED)
                else:
                    registry.set_status(group_id, ServiceStatus.UNCONFIGURED)

            # Get the feature availability map from the registry
            availability = registry.get_available_features()

            # Assert every feature in FEATURE_DEPENDENCIES is correctly computed
            for feature in FEATURE_DEPENDENCIES:
                expected = expected_feature_available(feature, configured_groups)
                actual = availability[feature]
                assert actual == expected, (
                    f"Feature '{feature}' availability mismatch: "
                    f"expected {expected}, got {actual}. "
                    f"Configured groups: {sorted(configured_groups)}"
                )

    @given(configured_groups=configured_subset_strategy)
    @settings(max_examples=200)
    def test_is_feature_available_matches_map(
        self,
        configured_groups: frozenset[str],
    ) -> None:
        """The is_feature_available() method SHALL return the same result
        as the corresponding entry in get_available_features() for every
        feature in FEATURE_DEPENDENCIES.

        **Validates: Requirements 4.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "service_registry.json"

            registry = ServiceRegistry(registry_path=registry_path)
            for group_id in VALID_GROUP_IDS:
                if group_id in configured_groups:
                    registry.set_status(group_id, ServiceStatus.CONFIGURED)
                else:
                    registry.set_status(group_id, ServiceStatus.UNCONFIGURED)

            availability_map = registry.get_available_features()

            for feature in FEATURE_DEPENDENCIES:
                from_method = registry.is_feature_available(feature)
                from_map = availability_map[feature]
                assert from_method == from_map, (
                    f"is_feature_available('{feature}') = {from_method} "
                    f"but get_available_features()['{feature}'] = {from_map}. "
                    f"Configured groups: {sorted(configured_groups)}"
                )
