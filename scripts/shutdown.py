#!/usr/bin/env python3
"""
LOHI-TRADE Shutdown Script

Gracefully shuts down the system:
1. Close all open positions (force square-off)
2. Cancel all pending orders
3. Disconnect WebSocket
4. Backup database

Also provides schedule_shutdown() for automatic 3:45 PM shutdown.

Requirements: 19.8, 19.9
"""

import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger
from src.utils.config import load_config, ConfigurationError

logger = get_logger("Shutdown")

# Market close shutdown time (15:45 IST)
SHUTDOWN_HOUR = 15
SHUTDOWN_MINUTE = 45


def close_all_positions(config) -> bool:
    """Force square-off all open positions.

    Attempts to close positions via PositionManager first, then falls back
    to OMS square_off_all_positions.

    Returns:
        True if square-off completed (even if some orders failed).
    """
    logger.info("Closing all open positions...")
    try:
        from src.state.redis_client import RedisClient
        from src.state.database import DatabaseConnectionManager
        from src.state.event_bus import EventBus
        from src.ingestion.broker_interface import BrokerCredentials
        from src.execution.oms import OrderManagementSystem

        # Set up minimal dependencies for OMS
        redis_client = RedisClient(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
        )
        redis_client.connect()

        db_manager = DatabaseConnectionManager(
            sqlite_path=config.database.sqlite_path,
            duckdb_path=config.database.duckdb_path,
        )

        event_bus = EventBus(redis_client)

        # Connect to broker
        primary_name = config.broker.primary
        broker_creds_cfg = getattr(config.broker, primary_name)
        credentials = BrokerCredentials(
            api_key=broker_creds_cfg.api_key,
            client_id=broker_creds_cfg.client_id,
            password=broker_creds_cfg.password,
        )

        if primary_name == "shoonya":
            from src.ingestion.shoonya_broker import ShoonyaBroker
            broker = ShoonyaBroker()
        else:
            from src.ingestion.angelone_broker import AngelOneBroker
            broker = AngelOneBroker()

        broker.connect(credentials)

        oms = OrderManagementSystem(
            config=config,
            broker=broker,
            db_manager=db_manager,
            event_bus=event_bus,
            redis_client=redis_client,
        )

        results = oms.square_off_all_positions()
        success_count = sum(1 for r in results if r.success)
        fail_count = sum(1 for r in results if not r.success)

        if results:
            logger.info(
                f"Square-off complete: {success_count} succeeded, {fail_count} failed"
            )
        else:
            logger.info("No open positions to close")

        redis_client.disconnect()
        db_manager.close()
        return True
    except Exception as e:
        logger.error(f"Failed to close positions: {e}")
        return False


def cancel_all_orders(config) -> bool:
    """Cancel all pending orders via the kill switch mechanism.

    Returns:
        True if cancellation completed.
    """
    logger.info("Cancelling all pending orders...")
    try:
        from src.state.redis_client import RedisClient
        from src.state.database import DatabaseConnectionManager
        from src.state.event_bus import EventBus
        from src.ingestion.broker_interface import BrokerCredentials
        from src.execution.oms import OrderManagementSystem
        from src.execution.kill_switch import KillSwitch

        redis_client = RedisClient(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
        )
        redis_client.connect()

        db_manager = DatabaseConnectionManager(
            sqlite_path=config.database.sqlite_path,
            duckdb_path=config.database.duckdb_path,
        )

        event_bus = EventBus(redis_client)

        primary_name = config.broker.primary
        broker_creds_cfg = getattr(config.broker, primary_name)
        credentials = BrokerCredentials(
            api_key=broker_creds_cfg.api_key,
            client_id=broker_creds_cfg.client_id,
            password=broker_creds_cfg.password,
        )

        if primary_name == "shoonya":
            from src.ingestion.shoonya_broker import ShoonyaBroker
            broker = ShoonyaBroker()
        else:
            from src.ingestion.angelone_broker import AngelOneBroker
            broker = AngelOneBroker()

        broker.connect(credentials)

        oms = OrderManagementSystem(
            config=config,
            broker=broker,
            db_manager=db_manager,
            event_bus=event_bus,
            redis_client=redis_client,
        )

        kill_switch = KillSwitch(
            config=config,
            redis_client=redis_client,
            oms=oms,
            db_manager=db_manager,
            event_bus=event_bus,
        )

        cancelled = kill_switch.cancel_all_pending_orders()
        logger.info(f"Cancelled {cancelled} pending orders")

        redis_client.disconnect()
        db_manager.close()
        return True
    except Exception as e:
        logger.error(f"Failed to cancel orders: {e}")
        return False


def disconnect_websocket(config) -> bool:
    """Disconnect WebSocket connections.

    Returns:
        True if disconnection completed.
    """
    logger.info("Disconnecting WebSocket...")
    try:
        primary_name = config.broker.primary
        from src.ingestion.broker_interface import BrokerCredentials

        if primary_name == "shoonya":
            from src.ingestion.shoonya_broker import ShoonyaBroker
            broker = ShoonyaBroker()
        else:
            from src.ingestion.angelone_broker import AngelOneBroker
            broker = AngelOneBroker()

        broker.disconnect()
        logger.info("WebSocket disconnected")
        return True
    except Exception as e:
        logger.error(f"Failed to disconnect WebSocket: {e}")
        return False


def backup_database(config) -> bool:
    """Backup the SQLite database.

    Returns:
        True if backup completed successfully.
    """
    logger.info("Backing up database...")
    try:
        from src.state.database_backup import DatabaseBackupManager

        backup_manager = DatabaseBackupManager(
            sqlite_path=config.database.sqlite_path,
            backup_dir=config.database.backup_path,
        )

        success = backup_manager.perform_backup_with_cleanup()
        if success:
            logger.info("Database backup completed")
        else:
            logger.error("Database backup failed")
        return success
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return False


def schedule_shutdown(config=None):
    """Schedule automatic shutdown at 3:45 PM IST.

    Starts a background thread that checks the time and triggers
    the shutdown sequence when 3:45 PM is reached.

    This function is designed to be called from the main event loop.

    Args:
        config: Config object. If None, loads from default path.

    Returns:
        The background timer thread (for testing/cancellation).

    Requirements: 19.9
    """
    if config is None:
        try:
            config = load_config()
        except ConfigurationError as e:
            logger.error(f"Cannot schedule shutdown — config error: {e}")
            return None

    stop_event = threading.Event()

    def _check_and_shutdown():
        """Poll every 30 seconds until shutdown time is reached."""
        logger.info(
            f"Automatic shutdown scheduled for {SHUTDOWN_HOUR:02d}:{SHUTDOWN_MINUTE:02d}"
        )
        while not stop_event.is_set():
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            target_minutes = SHUTDOWN_HOUR * 60 + SHUTDOWN_MINUTE

            if current_minutes >= target_minutes:
                logger.info(
                    f"Shutdown time reached ({now.strftime('%H:%M')}), "
                    "initiating shutdown sequence..."
                )
                run_shutdown(config)
                break

            stop_event.wait(30)

    thread = threading.Thread(
        target=_check_and_shutdown,
        daemon=True,
        name="auto-shutdown",
    )
    thread.start()
    thread._stop_event = stop_event  # Attach for external cancellation
    return thread


def run_shutdown(config) -> None:
    """Execute the full shutdown sequence.

    All steps are attempted even if individual steps fail.

    Args:
        config: Config object.
    """
    print("=" * 60)
    print("LOHI-TRADE System Shutdown")
    print("=" * 60)

    errors = []

    # Step 1: Close all positions
    print("\n[1/4] Closing all open positions...")
    try:
        if close_all_positions(config):
            print("    ✓ Positions closed")
        else:
            print("    ✗ Position close failed")
            errors.append("close_positions")
    except Exception as e:
        logger.error(f"Position close error: {e}")
        print(f"    ✗ Position close error: {e}")
        errors.append("close_positions")

    # Step 2: Cancel all pending orders
    print("\n[2/4] Cancelling all pending orders...")
    try:
        if cancel_all_orders(config):
            print("    ✓ Orders cancelled")
        else:
            print("    ✗ Order cancellation failed")
            errors.append("cancel_orders")
    except Exception as e:
        logger.error(f"Order cancellation error: {e}")
        print(f"    ✗ Order cancellation error: {e}")
        errors.append("cancel_orders")

    # Step 3: Disconnect WebSocket
    print("\n[3/4] Disconnecting WebSocket...")
    try:
        if disconnect_websocket(config):
            print("    ✓ WebSocket disconnected")
        else:
            print("    ✗ WebSocket disconnect failed")
            errors.append("disconnect_ws")
    except Exception as e:
        logger.error(f"WebSocket disconnect error: {e}")
        print(f"    ✗ WebSocket disconnect error: {e}")
        errors.append("disconnect_ws")

    # Step 4: Backup database
    print("\n[4/4] Backing up database...")
    try:
        if backup_database(config):
            print("    ✓ Database backed up")
        else:
            print("    ✗ Database backup failed")
            errors.append("backup_db")
    except Exception as e:
        logger.error(f"Database backup error: {e}")
        print(f"    ✗ Database backup error: {e}")
        errors.append("backup_db")

    print("\n" + "=" * 60)
    if errors:
        print(f"Shutdown completed with {len(errors)} error(s): {', '.join(errors)}")
        logger.warning(f"Shutdown completed with errors: {errors}")
    else:
        print("LOHI-TRADE shutdown complete ✓")
        logger.info("Shutdown sequence completed successfully")
    print("=" * 60)


def main() -> None:
    """Main entry point for manual shutdown."""
    try:
        config = load_config()
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Configuration error: {e}")
        sys.exit(1)

    run_shutdown(config)


if __name__ == "__main__":
    main()
