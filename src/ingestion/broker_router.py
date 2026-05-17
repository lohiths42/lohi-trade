"""Unified broker router with per-user failover for LOHI-TRADE.

Maintains a registry of broker adapters (shoonya, angelone, kite, groww)
and routes operations to each user's preferred primary broker, automatically
failing over to their backup broker when the primary is unavailable.

All broker API interactions are logged with request/response for audit.

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.ingestion.broker_interface import (
    BrokerError,
    BrokerInterface,
    Order,
)
from src.utils.logger import get_logger

logger = get_logger("BrokerRouter")

# Supported broker names
SUPPORTED_BROKERS = {"shoonya", "angelone", "kite", "groww"}


class BrokerConnectionStatus(Enum):
    """Connection status for a broker instance. Requirement 17.7."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    TOKEN_EXPIRED = "token_expired"


@dataclass
class UserBrokerPreference:
    """Per-user primary and backup broker selection. Requirement 17.2."""

    primary_broker: str
    backup_broker: str | None = None


@dataclass
class AuditEntry:
    """Audit log entry for broker API interactions. Requirement 17.6."""

    timestamp: datetime
    user_id: str
    broker_name: str
    operation: str
    request_summary: str
    response_summary: str
    success: bool
    duration_ms: float
    failover: bool = False


class BrokerRouter:
    """Unified broker routing with per-user failover.

    Maintains a registry of broker adapters and routes operations to each
    user's primary broker, automatically failing over to their backup
    broker on API unavailability.

    Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
    """

    def __init__(self, registry: dict[str, BrokerInterface] | None = None) -> None:
        """Initialise the router with a broker registry.

        Args:
            registry: Mapping of broker name → BrokerInterface instance.
                      Keys must be from SUPPORTED_BROKERS.

        """
        self._registry: dict[str, BrokerInterface] = {}
        self._user_preferences: dict[str, UserBrokerPreference] = {}
        self._audit_log: list[AuditEntry] = []
        self._lock = threading.RLock()

        if registry:
            for name, broker in registry.items():
                self.register_broker(name, broker)

    # ── registry management ───────────────────────────────────────

    def register_broker(self, name: str, broker: BrokerInterface) -> None:
        """Register a broker adapter in the registry.

        Args:
            name: Broker name (must be in SUPPORTED_BROKERS).
            broker: BrokerInterface implementation.

        Raises:
            ValueError: If the broker name is not supported.

        """
        name = name.lower()
        if name not in SUPPORTED_BROKERS:
            raise ValueError(
                f"Unsupported broker '{name}'. Must be one of {SUPPORTED_BROKERS}",
            )
        with self._lock:
            self._registry[name] = broker
        logger.info(f"Registered broker: {name}")

    def get_registered_brokers(self) -> list[str]:
        """Return list of registered broker names."""
        with self._lock:
            return list(self._registry.keys())

    # ── user preference management ────────────────────────────────

    def set_user_preference(
        self,
        user_id: str,
        primary_broker: str,
        backup_broker: str | None = None,
    ) -> None:
        """Set a user's primary and optional backup broker.

        Args:
            user_id: Unique user identifier.
            primary_broker: Name of the primary broker.
            backup_broker: Name of the backup broker (optional).

        Raises:
            ValueError: If broker names are invalid or not registered.

        """
        primary_broker = primary_broker.lower()
        if backup_broker:
            backup_broker = backup_broker.lower()

        with self._lock:
            if primary_broker not in self._registry:
                raise ValueError(
                    f"Primary broker '{primary_broker}' is not registered",
                )
            if backup_broker and backup_broker not in self._registry:
                raise ValueError(
                    f"Backup broker '{backup_broker}' is not registered",
                )
            if backup_broker and backup_broker == primary_broker:
                raise ValueError("Backup broker must differ from primary broker")

            self._user_preferences[user_id] = UserBrokerPreference(
                primary_broker=primary_broker,
                backup_broker=backup_broker,
            )
        logger.info(
            f"User {user_id} preference set: primary={primary_broker}, " f"backup={backup_broker}",
        )

    def get_user_preference(self, user_id: str) -> UserBrokerPreference | None:
        """Return the user's broker preference, or None if not set."""
        with self._lock:
            return self._user_preferences.get(user_id)

    # ── broker status ─────────────────────────────────────────────

    def get_broker_status(self, broker_name: str) -> BrokerConnectionStatus:
        """Return the connection status of a broker.

        Requirement 17.7
        """
        broker_name = broker_name.lower()
        with self._lock:
            broker = self._registry.get(broker_name)
        if broker is None:
            return BrokerConnectionStatus.DISCONNECTED

        try:
            if broker.is_connected():
                return BrokerConnectionStatus.CONNECTED
            return BrokerConnectionStatus.DISCONNECTED
        except Exception:
            return BrokerConnectionStatus.DISCONNECTED

    def get_all_broker_statuses(self) -> dict[str, BrokerConnectionStatus]:
        """Return connection status for every registered broker."""
        with self._lock:
            names = list(self._registry.keys())
        return {name: self.get_broker_status(name) for name in names}

    # ── order routing with failover ───────────────────────────────

    def route_order(self, user_id: str, order: Order) -> str:
        """Route an order to the user's primary broker with automatic failover.

        Requirement 17.3, 17.4

        Args:
            user_id: The user placing the order.
            order: The order to place.

        Returns:
            Broker order ID from the executing broker.

        Raises:
            ValueError: If user has no broker preference set.
            BrokerError: If both primary and backup brokers fail.

        """
        pref = self._get_preference_or_raise(user_id)

        # Try primary broker
        primary_result = self._try_place_order(
            user_id,
            pref.primary_broker,
            order,
            failover=False,
        )
        if primary_result is not None:
            return primary_result

        # Primary failed — attempt failover
        if pref.backup_broker:
            logger.warning(
                f"Primary broker '{pref.primary_broker}' unavailable for user "
                f"{user_id}. Failing over to '{pref.backup_broker}'.",
            )
            backup_result = self._try_place_order(
                user_id,
                pref.backup_broker,
                order,
                failover=True,
            )
            if backup_result is not None:
                return backup_result

            raise BrokerError(
                f"Both primary ({pref.primary_broker}) and backup "
                f"({pref.backup_broker}) brokers failed for user {user_id}",
            )

        raise BrokerError(
            f"Primary broker '{pref.primary_broker}' unavailable and no "
            f"backup broker configured for user {user_id}",
        )

    # ── common broker interface contract (Req 17.5) ───────────────

    def cancel_order(
        self,
        user_id: str,
        broker_order_id: str,
    ) -> bool:
        """Cancel an order via the user's primary broker with failover."""
        return self._execute_with_failover(
            user_id,
            operation_name="cancel_order",
            request_summary=f"broker_order_id={broker_order_id}",
            fn=lambda broker: broker.cancel_order(broker_order_id),
        )

    def get_order_status(
        self,
        user_id: str,
        broker_order_id: str,
    ) -> Order:
        """Get order status via the user's primary broker with failover."""
        return self._execute_with_failover(
            user_id,
            operation_name="get_order_status",
            request_summary=f"broker_order_id={broker_order_id}",
            fn=lambda broker: broker.get_order_status(broker_order_id),
        )

    def get_positions(self, user_id: str) -> list[dict]:
        """Get positions via the user's primary broker with failover."""
        return self._execute_with_failover(
            user_id,
            operation_name="get_positions",
            request_summary="",
            fn=lambda broker: broker.get_positions(),
        )

    def get_holdings(self, user_id: str) -> list[dict]:
        """Get holdings via the user's primary broker with failover."""
        return self._execute_with_failover(
            user_id,
            operation_name="get_holdings",
            request_summary="",
            fn=lambda broker: broker.get_holdings(),
        )

    # ── audit log access ──────────────────────────────────────────

    def get_audit_log(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Return recent audit entries, optionally filtered by user.

        Requirement 17.6
        """
        with self._lock:
            entries = self._audit_log
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        return entries[-limit:]

    # ── internal helpers ──────────────────────────────────────────

    def _get_preference_or_raise(self, user_id: str) -> UserBrokerPreference:
        pref = self.get_user_preference(user_id)
        if pref is None:
            raise ValueError(f"No broker preference set for user {user_id}")
        return pref

    def _get_broker(self, broker_name: str) -> BrokerInterface:
        with self._lock:
            broker = self._registry.get(broker_name)
        if broker is None:
            raise BrokerError(f"Broker '{broker_name}' is not registered")
        return broker

    def _try_place_order(
        self,
        user_id: str,
        broker_name: str,
        order: Order,
        failover: bool,
    ) -> str | None:
        """Attempt to place an order on a specific broker. Returns order ID or None."""
        broker = self._get_broker(broker_name)
        start = datetime.now()
        request_summary = (
            f"symbol={order.symbol}, side={order.side.value}, "
            f"qty={order.quantity}, type={order.order_type.value}"
        )
        try:
            broker_order_id = broker.place_order(order)
            duration_ms = (datetime.now() - start).total_seconds() * 1000
            self._record_audit(
                user_id=user_id,
                broker_name=broker_name,
                operation="place_order",
                request_summary=request_summary,
                response_summary=f"order_id={broker_order_id}",
                success=True,
                duration_ms=duration_ms,
                failover=failover,
            )
            if failover:
                logger.info(
                    f"Failover order placed on '{broker_name}' for user "
                    f"{user_id}: {broker_order_id}",
                )
            return broker_order_id
        except Exception as exc:
            duration_ms = (datetime.now() - start).total_seconds() * 1000
            self._record_audit(
                user_id=user_id,
                broker_name=broker_name,
                operation="place_order",
                request_summary=request_summary,
                response_summary=f"error={exc}",
                success=False,
                duration_ms=duration_ms,
                failover=failover,
            )
            logger.error(
                f"place_order failed on '{broker_name}' for user {user_id}: {exc}",
            )
            return None

    def _execute_with_failover(
        self,
        user_id: str,
        operation_name: str,
        request_summary: str,
        fn,
    ):
        """Execute a broker operation with primary → backup failover.

        Used for cancel_order, get_order_status, get_positions, get_holdings.
        """
        pref = self._get_preference_or_raise(user_id)

        # Try primary
        primary_result = self._try_operation(
            user_id,
            pref.primary_broker,
            operation_name,
            request_summary,
            fn,
            failover=False,
        )
        if primary_result is not _SENTINEL:
            return primary_result

        # Failover to backup
        if pref.backup_broker:
            logger.warning(
                f"'{operation_name}' failed on primary '{pref.primary_broker}' "
                f"for user {user_id}. Failing over to '{pref.backup_broker}'.",
            )
            backup_result = self._try_operation(
                user_id,
                pref.backup_broker,
                operation_name,
                request_summary,
                fn,
                failover=True,
            )
            if backup_result is not _SENTINEL:
                return backup_result

            raise BrokerError(
                f"'{operation_name}' failed on both primary "
                f"({pref.primary_broker}) and backup ({pref.backup_broker}) "
                f"for user {user_id}",
            )

        raise BrokerError(
            f"'{operation_name}' failed on primary '{pref.primary_broker}' "
            f"and no backup configured for user {user_id}",
        )

    def _try_operation(
        self,
        user_id: str,
        broker_name: str,
        operation_name: str,
        request_summary: str,
        fn,
        failover: bool,
    ):
        """Try an operation on a broker. Returns _SENTINEL on failure."""
        broker = self._get_broker(broker_name)
        start = datetime.now()
        try:
            result = fn(broker)
            duration_ms = (datetime.now() - start).total_seconds() * 1000
            self._record_audit(
                user_id=user_id,
                broker_name=broker_name,
                operation=operation_name,
                request_summary=request_summary,
                response_summary="success",
                success=True,
                duration_ms=duration_ms,
                failover=failover,
            )
            return result
        except Exception as exc:
            duration_ms = (datetime.now() - start).total_seconds() * 1000
            self._record_audit(
                user_id=user_id,
                broker_name=broker_name,
                operation=operation_name,
                request_summary=request_summary,
                response_summary=f"error={exc}",
                success=False,
                duration_ms=duration_ms,
                failover=failover,
            )
            logger.error(
                f"'{operation_name}' failed on '{broker_name}' for user " f"{user_id}: {exc}",
            )
            return _SENTINEL

    def _record_audit(
        self,
        user_id: str,
        broker_name: str,
        operation: str,
        request_summary: str,
        response_summary: str,
        success: bool,
        duration_ms: float,
        failover: bool,
    ) -> None:
        """Append an audit entry and log it. Requirement 17.6."""
        entry = AuditEntry(
            timestamp=datetime.now(),
            user_id=user_id,
            broker_name=broker_name,
            operation=operation,
            request_summary=request_summary,
            response_summary=response_summary,
            success=success,
            duration_ms=duration_ms,
            failover=failover,
        )
        with self._lock:
            self._audit_log.append(entry)

        log_msg = (
            f"AUDIT | user={user_id} broker={broker_name} op={operation} "
            f"success={success} failover={failover} "
            f"duration={duration_ms:.1f}ms | "
            f"req=[{request_summary}] resp=[{response_summary}]"
        )
        if success:
            logger.info(log_msg)
        else:
            logger.warning(log_msg)


# Sentinel object to distinguish "operation returned None" from "operation failed"
_SENTINEL = object()
