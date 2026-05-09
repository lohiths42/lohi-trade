"""
Broker Manager for LOHI-TRADE.

Manages primary/backup broker switching with health monitoring.
Monitors the active broker's health and automatically switches to the
backup broker on repeated failures, maintaining data continuity.

Requirements: 1.5
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from src.ingestion.broker_interface import (
    BrokerCredentials,
    BrokerError,
    BrokerInterface,
    Order,
    Tick,
)
from src.utils.logger import get_logger

logger = get_logger("BrokerManager")


class BrokerState(Enum):
    """State of a broker connection."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class BrokerHealth:
    """Tracks health metrics for a broker."""
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state: BrokerState = BrokerState.DISCONNECTED


class BrokerManager:
    """
    Manages primary and backup broker connections with automatic failover.

    Monitors the active broker's health by tracking consecutive failures.
    When the failure threshold is exceeded, switches to the backup broker.
    Provides the same BrokerInterface methods by delegating to the active broker.

    Requirements: 1.5
    """

    # Number of consecutive failures before switching brokers
    DEFAULT_FAILURE_THRESHOLD = 3
    # Seconds to wait before attempting to recover the failed broker
    DEFAULT_RECOVERY_CHECK_INTERVAL = 60

    def __init__(
        self,
        primary_broker: BrokerInterface,
        backup_broker: BrokerInterface,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_check_interval: float = DEFAULT_RECOVERY_CHECK_INTERVAL,
    ):
        """
        Initialize the broker manager.

        Args:
            primary_broker: The primary broker adapter (e.g., Shoonya)
            backup_broker: The backup broker adapter (e.g., Angel One)
            failure_threshold: Consecutive failures before switching
            recovery_check_interval: Seconds between recovery checks for failed broker
        """
        self._primary = primary_broker
        self._backup = backup_broker
        self._failure_threshold = failure_threshold
        self._recovery_check_interval = recovery_check_interval

        self._health: Dict[str, BrokerHealth] = {
            "primary": BrokerHealth(),
            "backup": BrokerHealth(),
        }

        self._active_broker_key = "primary"
        self._lock = threading.RLock()

        # Credentials stored for reconnection
        self._primary_credentials: Optional[BrokerCredentials] = None
        self._backup_credentials: Optional[BrokerCredentials] = None

        # Recovery monitoring
        self._recovery_thread: Optional[threading.Thread] = None
        self._recovery_stop_event = threading.Event()

        # Callbacks
        self._on_switch_callbacks: List[Callable[[str, str, str], None]] = []

    @property
    def active_broker(self) -> BrokerInterface:
        """Return the currently active broker."""
        with self._lock:
            if self._active_broker_key == "primary":
                return self._primary
            return self._backup

    @property
    def active_broker_name(self) -> str:
        """Return the name of the currently active broker ('primary' or 'backup')."""
        with self._lock:
            return self._active_broker_key

    @property
    def health(self) -> Dict[str, BrokerHealth]:
        """Return health metrics for both brokers."""
        return self._health

    def on_switch(self, callback: Callable[[str, str, str], None]) -> None:
        """
        Register a callback for broker switch events.

        Args:
            callback: Called with (from_broker, to_broker, reason)
        """
        self._on_switch_callbacks.append(callback)

    def connect(
        self,
        primary_credentials: BrokerCredentials,
        backup_credentials: BrokerCredentials,
    ) -> bool:
        """
        Connect to the primary broker. Stores backup credentials for failover.

        Args:
            primary_credentials: Credentials for the primary broker
            backup_credentials: Credentials for the backup broker

        Returns:
            True if primary broker connected successfully
        """
        self._primary_credentials = primary_credentials
        self._backup_credentials = backup_credentials

        try:
            result = self._primary.connect(primary_credentials)
            if result:
                self._health["primary"].state = BrokerState.CONNECTED
                self._health["primary"].last_success_time = datetime.now()
                logger.info("Primary broker connected successfully")
                return True
            else:
                self._health["primary"].state = BrokerState.FAILED
                logger.warning("Primary broker connection returned False, attempting backup")
                return self._switch_to_backup("Primary broker connection failed")
        except Exception as e:
            self._health["primary"].state = BrokerState.FAILED
            logger.error(f"Primary broker connection error: {e}", exc_info=True)
            return self._switch_to_backup(f"Primary broker connection error: {e}")

    def disconnect(self) -> None:
        """Disconnect both brokers and stop recovery monitoring."""
        self._stop_recovery_monitor()

        for broker, key in [(self._primary, "primary"), (self._backup, "backup")]:
            try:
                broker.disconnect()
                self._health[key].state = BrokerState.DISCONNECTED
            except Exception as e:
                logger.warning(f"Error disconnecting {key} broker: {e}")

        logger.info("All brokers disconnected")

    def is_connected(self) -> bool:
        """Check if the active broker is connected."""
        return self.active_broker.is_connected()

    def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> bool:
        """
        Subscribe to tick data via the active broker.

        Args:
            symbols: Symbols to subscribe to
            on_tick: Tick callback

        Returns:
            True if subscription succeeded
        """
        return self._execute_with_failover(
            lambda broker: broker.subscribe(symbols, on_tick),
            "subscribe",
        )

    def unsubscribe(self, symbols: List[str]) -> bool:
        """Unsubscribe from tick data via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.unsubscribe(symbols),
            "unsubscribe",
        )

    def place_order(self, order: Order) -> str:
        """Place an order via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.place_order(order),
            "place_order",
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.cancel_order(broker_order_id),
            "cancel_order",
        )

    def get_order_status(self, broker_order_id: str) -> Order:
        """Get order status via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.get_order_status(broker_order_id),
            "get_order_status",
        )

    def get_positions(self) -> List[dict]:
        """Get positions via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.get_positions(),
            "get_positions",
        )

    def get_instrument_master(self) -> List[dict]:
        """Get instrument master via the active broker."""
        return self._execute_with_failover(
            lambda broker: broker.get_instrument_master(),
            "get_instrument_master",
        )

    # ---- Internal methods ----

    def _execute_with_failover(self, operation: Callable, operation_name: str):
        """
        Execute an operation on the active broker with automatic failover.

        On success, records a healthy heartbeat. On failure, increments the
        failure counter and switches brokers if the threshold is exceeded.

        Args:
            operation: Callable that takes a BrokerInterface and returns a result
            operation_name: Name of the operation for logging

        Returns:
            Result of the operation

        Raises:
            BrokerError: If both brokers fail
        """
        try:
            result = operation(self.active_broker)
            self._record_success()
            return result
        except Exception as first_error:
            self._record_failure(operation_name, first_error)

            with self._lock:
                health = self._health[self._active_broker_key]
                if health.consecutive_failures >= self._failure_threshold:
                    switched = self._switch_to_other_broker(
                        f"{operation_name} failed {health.consecutive_failures} times consecutively"
                    )
                    if switched:
                        # Retry on the new active broker
                        try:
                            result = operation(self.active_broker)
                            self._record_success()
                            return result
                        except Exception as second_error:
                            self._record_failure(operation_name, second_error)
                            raise BrokerError(
                                f"Both brokers failed for {operation_name}: "
                                f"primary={first_error}, backup={second_error}"
                            ) from second_error

            raise BrokerError(
                f"{operation_name} failed on active broker: {first_error}"
            ) from first_error

    def _record_success(self) -> None:
        """Record a successful operation on the active broker."""
        with self._lock:
            health = self._health[self._active_broker_key]
            health.consecutive_failures = 0
            health.total_successes += 1
            health.last_success_time = datetime.now()
            health.state = BrokerState.CONNECTED

    def _record_failure(self, operation_name: str, error: Exception) -> None:
        """Record a failed operation on the active broker."""
        with self._lock:
            health = self._health[self._active_broker_key]
            health.consecutive_failures += 1
            health.total_failures += 1
            health.last_failure_time = datetime.now()

            if health.consecutive_failures >= self._failure_threshold:
                health.state = BrokerState.FAILED
            else:
                health.state = BrokerState.DEGRADED

        logger.warning(
            f"Broker operation '{operation_name}' failed "
            f"(consecutive: {health.consecutive_failures}): {error}",
            extra={"broker": self._active_broker_key},
        )

    def _switch_to_backup(self, reason: str) -> bool:
        """
        Switch from primary to backup broker and connect it.

        Args:
            reason: Why the switch is happening

        Returns:
            True if backup broker connected successfully
        """
        if self._backup_credentials is None:
            logger.error("Cannot switch to backup: no backup credentials stored")
            return False

        try:
            result = self._backup.connect(self._backup_credentials)
            if result:
                with self._lock:
                    old_key = self._active_broker_key
                    self._active_broker_key = "backup"
                    self._health["backup"].state = BrokerState.CONNECTED
                    self._health["backup"].last_success_time = datetime.now()
                    self._health["backup"].consecutive_failures = 0

                logger.info(f"Switched to backup broker. Reason: {reason}")
                self._notify_switch(old_key, "backup", reason)
                self._start_recovery_monitor()
                return True
            else:
                logger.error("Backup broker connection returned False")
                return False
        except Exception as e:
            logger.error(f"Backup broker connection failed: {e}", exc_info=True)
            self._health["backup"].state = BrokerState.FAILED
            return False

    def _switch_to_other_broker(self, reason: str) -> bool:
        """
        Switch to whichever broker is not currently active.

        Args:
            reason: Why the switch is happening

        Returns:
            True if the switch succeeded
        """
        with self._lock:
            current = self._active_broker_key
            target = "backup" if current == "primary" else "primary"
            target_broker = self._backup if target == "backup" else self._primary
            target_creds = (
                self._backup_credentials if target == "backup" else self._primary_credentials
            )

        if target_creds is None:
            logger.error(f"Cannot switch to {target}: no credentials stored")
            return False

        # Check if target is already connected
        try:
            if target_broker.is_connected():
                with self._lock:
                    self._active_broker_key = target
                    self._health[target].state = BrokerState.CONNECTED
                    self._health[target].consecutive_failures = 0
                logger.info(f"Switched to {target} broker (already connected). Reason: {reason}")
                self._notify_switch(current, target, reason)
                self._start_recovery_monitor()
                return True
        except Exception:
            pass

        # Try to connect the target broker
        try:
            result = target_broker.connect(target_creds)
            if result:
                with self._lock:
                    self._active_broker_key = target
                    self._health[target].state = BrokerState.CONNECTED
                    self._health[target].last_success_time = datetime.now()
                    self._health[target].consecutive_failures = 0

                logger.info(f"Switched to {target} broker. Reason: {reason}")
                self._notify_switch(current, target, reason)
                self._start_recovery_monitor()
                return True
            else:
                logger.error(f"{target} broker connection returned False")
                return False
        except Exception as e:
            logger.error(f"{target} broker connection failed: {e}", exc_info=True)
            self._health[target].state = BrokerState.FAILED
            return False

    def _notify_switch(self, from_broker: str, to_broker: str, reason: str) -> None:
        """Notify all registered callbacks about a broker switch."""
        for callback in self._on_switch_callbacks:
            try:
                callback(from_broker, to_broker, reason)
            except Exception as e:
                logger.warning(f"Switch callback error: {e}")

    # ---- Recovery monitoring ----

    def _start_recovery_monitor(self) -> None:
        """Start a background thread that periodically checks if the failed broker recovers."""
        self._stop_recovery_monitor()
        self._recovery_stop_event.clear()
        self._recovery_thread = threading.Thread(
            target=self._recovery_monitor_loop,
            daemon=True,
            name="broker-recovery-monitor",
        )
        self._recovery_thread.start()
        logger.info("Recovery monitor started")

    def _stop_recovery_monitor(self) -> None:
        """Stop the recovery monitor thread."""
        if self._recovery_thread and self._recovery_thread.is_alive():
            self._recovery_stop_event.set()
            self._recovery_thread.join(timeout=5)
            logger.info("Recovery monitor stopped")

    def _recovery_monitor_loop(self) -> None:
        """
        Periodically check if the previously failed broker has recovered.

        If the failed broker reconnects successfully, switch back to primary
        (if it was the one that failed).
        """
        while not self._recovery_stop_event.is_set():
            self._recovery_stop_event.wait(self._recovery_check_interval)
            if self._recovery_stop_event.is_set():
                break

            with self._lock:
                # Only try to recover if we're on backup and primary failed
                if self._active_broker_key != "backup":
                    continue
                if self._primary_credentials is None:
                    continue

            try:
                if self._primary.is_connected():
                    logger.info("Primary broker recovered (already connected)")
                    with self._lock:
                        self._active_broker_key = "primary"
                        self._health["primary"].state = BrokerState.CONNECTED
                        self._health["primary"].consecutive_failures = 0
                    self._notify_switch("backup", "primary", "Primary broker recovered")
                    break

                result = self._primary.connect(self._primary_credentials)
                if result:
                    logger.info("Primary broker recovered after reconnection")
                    with self._lock:
                        self._active_broker_key = "primary"
                        self._health["primary"].state = BrokerState.CONNECTED
                        self._health["primary"].consecutive_failures = 0
                        self._health["primary"].last_success_time = datetime.now()
                    self._notify_switch("backup", "primary", "Primary broker recovered")
                    break
            except Exception as e:
                logger.debug(f"Primary broker recovery check failed: {e}")
