"""Setup Service — orchestrates credential validation, persistence, and connection testing.

Coordinates the Setup Wizard's backend logic: validates credential format,
persists to .env files via CredentialStore, probes external services via
ConnectionTester, and tracks configuration state via ServiceRegistry.

Implements rollback logic: if a connection test fails after a credential
update, the previous credential values are retained (new values are not
persisted until connection succeeds or user confirms).

Requirements: 2.4, 3.1, 3.4, 6.1, 8.3, 8.5, 8.6
Design: §Setup Service
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .connection_tester import ConnectionTester, TestResult
from .credential_store import CredentialStore
from .service_registry import (
    CREDENTIAL_GROUPS,
    ServiceRegistry,
    ServiceStatus,
    _GROUPS_BY_ID,
)

logger = logging.getLogger(__name__)


# ── Response Models ─────────────────────────────────────────────────────────


@dataclass
class ServiceStatusInfo:
    """Status information for a single credential group."""

    group_id: str
    name: str
    status: str
    required: bool
    features_affected: list[str]


@dataclass
class SetupStatusResponse:
    """Full setup status response with all service statuses."""

    setup_complete: bool
    services: list[ServiceStatusInfo]


# ── Setup Service ───────────────────────────────────────────────────────────


class SetupService:
    """Orchestrates credential validation, persistence, and connection testing.

    Coordinates between CredentialStore (persistence), ServiceRegistry
    (state tracking), and ConnectionTester (external probing) to provide
    a unified setup workflow.
    """

    def __init__(
        self,
        credential_store: CredentialStore,
        service_registry: ServiceRegistry,
    ):
        self.credential_store = credential_store
        self.registry = service_registry
        self.connection_tester = ConnectionTester()

    # ── Public API ──────────────────────────────────────────────────────

    async def submit_credentials(
        self, group_id: str, credentials: dict[str, str]
    ) -> None:
        """Validate format, write to .env, update registry status.

        Validates credential format using regex patterns defined in the
        credential group. If validation passes, writes to the appropriate
        .env file and marks the group as CONFIGURED in the registry.

        Raises ValueError if the group_id is unknown or validation fails.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            raise ValueError(f"Unknown credential group: {group_id}")

        # Validate format using regex patterns (Requirement 2.4)
        errors = self.credential_store.validate_credentials(group_id, credentials)
        if errors:
            raise ValueError(f"Validation failed: {errors}")

        # Write credentials to .env file
        self.credential_store.write_credentials(group_id, credentials)

        # Update registry status to CONFIGURED (Requirement 3.4)
        self.registry.set_status(group_id, ServiceStatus.CONFIGURED)

        logger.info("Credentials submitted for group '%s'", group_id)

    async def test_connection(self, group_id: str) -> TestResult:
        """Probe external service with stored credentials.

        Reads the stored credentials for the group, calls the appropriate
        ConnectionTester method, and returns the result.

        Implements rollback logic (Requirement 8.5): if the connection test
        fails after a credential update, the previous credential values are
        restored.
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return TestResult(
                success=False,
                error=f"Unknown credential group: {group_id}",
                suggestion="Check the group_id parameter.",
            )

        # Read stored credentials for testing
        raw_credentials = self.credential_store.read_raw_credentials(group_id)

        # Call the appropriate connection tester method
        result = await self._run_connection_test(group_id, raw_credentials)

        # If test fails, implement rollback (Requirement 8.5)
        if not result.success:
            # Mark as ERROR in registry to reflect the failed state
            self.registry.set_status(group_id, ServiceStatus.ERROR)
            logger.warning(
                "Connection test failed for group '%s': %s",
                group_id,
                result.error,
            )

        return result

    async def submit_and_test(
        self, group_id: str, credentials: dict[str, str]
    ) -> TestResult:
        """Submit credentials and test connection with rollback on failure.

        This is the full workflow with rollback logic (Requirement 8.5):
        1. Save old credentials
        2. Write new credentials
        3. Test connection
        4. If test fails, restore old credentials and mark as ERROR
        5. If test succeeds, keep new credentials and mark as CONFIGURED
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            return TestResult(
                success=False,
                error=f"Unknown credential group: {group_id}",
                suggestion="Check the group_id parameter.",
            )

        # Validate format first
        errors = self.credential_store.validate_credentials(group_id, credentials)
        if errors:
            return TestResult(
                success=False,
                error=f"Validation failed: {errors}",
                suggestion="Fix the credential format and try again.",
            )

        # Save old credentials for rollback
        old_credentials = self.credential_store.read_raw_credentials(group_id)

        # Write new credentials
        self.credential_store.write_credentials(group_id, credentials)

        # Test connection with new credentials
        result = await self._run_connection_test(group_id, credentials)

        if result.success:
            # Test passed — keep new credentials, mark as CONFIGURED
            self.registry.set_status(group_id, ServiceStatus.CONFIGURED)
            logger.info(
                "Credentials updated and connection verified for group '%s'",
                group_id,
            )
        else:
            # Test failed — rollback to old credentials (Requirement 8.5)
            if any(old_credentials.values()):
                # Restore previous credentials
                self.credential_store.write_credentials(group_id, old_credentials)
                logger.warning(
                    "Connection test failed for group '%s'; rolled back to previous credentials",
                    group_id,
                )
            else:
                # No previous credentials to restore — clear the new ones
                self.credential_store.clear_credentials(group_id)
                logger.warning(
                    "Connection test failed for group '%s'; cleared credentials (no previous values)",
                    group_id,
                )
            self.registry.set_status(group_id, ServiceStatus.ERROR)

        return result

    async def skip_group(self, group_id: str) -> None:
        """Mark a credential group as SKIPPED in the registry.

        Used when the user clicks "Skip for now" on an optional group.
        (Requirement 3.1)
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            raise ValueError(f"Unknown credential group: {group_id}")

        self.registry.set_status(group_id, ServiceStatus.SKIPPED)
        logger.info("Group '%s' marked as skipped", group_id)

    async def reset_group(self, group_id: str) -> None:
        """Clear credentials and mark group as UNCONFIGURED.

        Used when the user clicks "Reset to defaults" on a configured group.
        (Requirement 8.6)
        """
        group = _GROUPS_BY_ID.get(group_id)
        if group is None:
            raise ValueError(f"Unknown credential group: {group_id}")

        # Clear credentials from .env file
        self.credential_store.clear_credentials(group_id)

        # Mark as UNCONFIGURED in registry
        self.registry.set_status(group_id, ServiceStatus.UNCONFIGURED)
        logger.info("Group '%s' reset to unconfigured", group_id)

    def get_status(self) -> SetupStatusResponse:
        """Return current setup state with all service statuses.

        Returns a SetupStatusResponse containing setup_complete flag
        and a list of ServiceStatusInfo for every registered group.
        (Requirement 3.4)
        """
        services = []
        for group in CREDENTIAL_GROUPS:
            status = self.registry.get_status(group.group_id)
            services.append(
                ServiceStatusInfo(
                    group_id=group.group_id,
                    name=group.name,
                    status=status.value,
                    required=group.required,
                    features_affected=group.features_dependent,
                )
            )

        return SetupStatusResponse(
            setup_complete=self.registry.setup_complete,
            services=services,
        )

    async def complete_setup(self) -> None:
        """Mark setup as complete in the registry with timestamp.

        Called when the user finishes the wizard (clicks "Complete Setup").
        Records setup_complete=True and the completion timestamp.
        (Requirement 8.3)
        """
        self.registry.mark_setup_complete()
        logger.info("Setup marked as complete")

    # ── Internal ────────────────────────────────────────────────────────

    async def _run_connection_test(
        self, group_id: str, credentials: dict[str, str]
    ) -> TestResult:
        """Route to the appropriate ConnectionTester method based on group_id."""
        if group_id == "nvidia_nim":
            api_key = credentials.get("NVIDIA_NIM_API_KEY", "")
            return await self.connection_tester.test_nvidia_nim(api_key)

        elif group_id == "nubra":
            phone = credentials.get("NUBRA_PHONE_NO", "")
            mpin = credentials.get("NUBRA_MPIN", "")
            totp_secret = credentials.get("NUBRA_TOTP_SECRET", "")
            return await self.connection_tester.test_nubra(phone, mpin, totp_secret)

        elif group_id == "broker_shoonya":
            api_key = credentials.get("SHOONYA_API_KEY", "")
            client_id = credentials.get("SHOONYA_CLIENT_ID", "")
            return await self.connection_tester.test_broker_shoonya(api_key, client_id)

        elif group_id == "broker_angelone":
            # Angel One uses same validation pattern as Shoonya
            api_key = credentials.get("ANGELONE_API_KEY", "")
            client_id = credentials.get("ANGELONE_CLIENT_ID", "")
            return await self.connection_tester.test_broker_shoonya(api_key, client_id)

        elif group_id == "telegram":
            bot_token = credentials.get("TELEGRAM_BOT_TOKEN", "")
            return await self.connection_tester.test_telegram(bot_token)

        elif group_id == "ollama":
            return await self.connection_tester.test_ollama()

        else:
            return TestResult(
                success=False,
                error=f"No connection test available for group: {group_id}",
                suggestion="This service does not support connection testing.",
            )
