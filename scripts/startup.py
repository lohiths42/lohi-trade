#!/usr/bin/env python3
"""
LOHI-TRADE Startup Script

Initializes all system components in the correct order:
1. Start Redis container (docker-compose up -d)
2. Perform health checks (Redis ping, database connection, broker login)
3. Auto-login to broker API
4. Download instrument master
5. Subscribe to WebSocket feeds

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7
"""

import subprocess
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import ConfigurationError, load_config
from src.utils.logger import get_logger

logger = get_logger("Startup")

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_REDIS_ERROR = 2
EXIT_DB_ERROR = 3
EXIT_BROKER_ERROR = 4
EXIT_INSTRUMENT_ERROR = 5


def start_redis() -> bool:
    """Start Redis container via docker-compose.

    Returns:
        True if Redis started successfully.
    """
    logger.info("Starting Redis container...")
    try:
        result = subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"docker-compose up failed: {result.stderr.strip()}")
            return False
        logger.info("Redis container started")
        # Give Redis a moment to become ready
        time.sleep(2)
        return True
    except FileNotFoundError:
        logger.warning("docker-compose not found, trying 'docker compose'")
        try:
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error(f"docker compose up failed: {result.stderr.strip()}")
                return False
            logger.info("Redis container started")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Failed to start Redis container: {e}")
            return False
    except Exception as e:
        logger.error(f"Failed to start Redis container: {e}")
        return False


def health_check_redis(config) -> bool:
    """Perform Redis health check.

    Returns:
        True if Redis is reachable.
    """
    logger.info("Checking Redis health...")
    try:
        from src.state.redis_client import RedisClient

        redis_client = RedisClient(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            max_retries=3,
            retry_delay=1.0,
        )
        redis_client.connect()
        if redis_client.ping():
            logger.info("Redis health check passed")
            return True
        else:
            logger.error("Redis ping failed")
            return False
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False


def health_check_database(config) -> bool:
    """Perform database health check.

    Returns:
        True if database connections are healthy.
    """
    logger.info("Checking database health...")
    try:
        from src.state.database import DatabaseConnectionManager

        db_manager = DatabaseConnectionManager(
            sqlite_path=config.database.sqlite_path,
            duckdb_path=config.database.duckdb_path,
        )
        sqlite_ok = db_manager.health_check_sqlite()
        if not sqlite_ok:
            logger.error("SQLite health check failed")
            return False
        logger.info("SQLite health check passed")

        duckdb_ok = db_manager.health_check_duckdb()
        if duckdb_ok:
            logger.info("DuckDB health check passed")
        else:
            logger.warning("DuckDB health check failed (non-critical)")

        db_manager.close()
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def broker_login(config):
    """Auto-login to broker API.

    Returns:
        Tuple of (broker_instance, credentials) or (None, None) on failure.
    """
    logger.info("Logging in to broker API...")
    try:
        from src.ingestion.broker_interface import BrokerCredentials

        primary_name = config.broker.primary
        broker_creds_cfg = getattr(config.broker, primary_name)

        credentials = BrokerCredentials(
            api_key=broker_creds_cfg.api_key,
            client_id=broker_creds_cfg.client_id,
            password=broker_creds_cfg.password,
        )

        # Import the appropriate broker adapter
        if primary_name == "shoonya":
            from src.ingestion.shoonya_broker import ShoonyaBroker

            broker = ShoonyaBroker()
        else:
            from src.ingestion.angelone_broker import AngelOneBroker

            broker = AngelOneBroker()

        success = broker.connect(credentials)
        if success:
            logger.info(f"Broker login successful ({primary_name})")
            return broker, credentials
        else:
            logger.error(f"Broker login failed ({primary_name})")
            return None, None
    except Exception as e:
        logger.error(f"Broker login failed: {e}")
        return None, None


def download_instruments(config, broker) -> bool:
    """Download instrument master from broker.

    Returns:
        True if download successful.
    """
    logger.info("Downloading instrument master...")
    try:
        from src.ingestion.instrument_master import InstrumentMaster

        instrument_master = InstrumentMaster(data_dir="data")
        success = instrument_master.download_from_broker(broker, symbols=config.symbols)
        if success:
            instrument_master.save_to_file()
            logger.info(
                f"Instrument master downloaded: {len(instrument_master.instruments)} instruments"
            )
            return True
        else:
            logger.error("Instrument master download returned no data")
            return False
    except Exception as e:
        logger.error(f"Instrument master download failed: {e}")
        return False


def subscribe_websocket(config, broker) -> bool:
    """Subscribe to WebSocket feeds for configured symbols.

    Returns:
        True if subscription successful.
    """
    logger.info("Subscribing to WebSocket feeds...")
    try:
        symbols = config.symbols
        if not symbols:
            logger.warning("No symbols configured for WebSocket subscription")
            return True

        # Use broker's subscribe method with a no-op callback for startup verification
        # The actual tick handler will be set up by the main event loop
        success = broker.subscribe(symbols, lambda tick: None)
        if success:
            logger.info(f"WebSocket subscribed to {len(symbols)} symbols")
            return True
        else:
            logger.error("WebSocket subscription failed")
            return False
    except Exception as e:
        logger.error(f"WebSocket subscription failed: {e}")
        return False


def main() -> int:
    """Main startup sequence.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    print("=" * 60)
    print("LOHI-TRADE System Startup")
    print("=" * 60)

    # Step 1: Load configuration
    print("\n[1/6] Loading configuration...")
    try:
        config = load_config()
        logger.info("Configuration loaded successfully")
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        print(f"    ✗ Configuration error: {e}")
        return EXIT_CONFIG_ERROR

    # Step 2: Start Redis container
    print("\n[2/6] Starting Redis container...")
    if not start_redis():
        logger.error("Failed to start Redis — aborting startup")
        print("    ✗ Redis startup failed")
        return EXIT_REDIS_ERROR
    print("    ✓ Redis started")

    # Step 3: Health checks
    print("\n[3/6] Performing health checks...")
    if not health_check_redis(config):
        logger.error("Redis health check failed — aborting startup")
        print("    ✗ Redis health check failed")
        return EXIT_REDIS_ERROR
    print("    ✓ Redis OK")

    if not health_check_database(config):
        logger.error("Database health check failed — aborting startup")
        print("    ✗ Database health check failed")
        return EXIT_DB_ERROR
    print("    ✓ Database OK")

    # Step 4: Broker login
    print("\n[4/6] Logging in to broker API...")
    broker, credentials = broker_login(config)
    if broker is None:
        logger.error("Broker login failed — aborting startup")
        print("    ✗ Broker login failed")
        return EXIT_BROKER_ERROR
    print(f"    ✓ Broker login OK ({config.broker.primary})")

    # Step 5: Download instrument master
    print("\n[5/6] Downloading instrument master...")
    if not download_instruments(config, broker):
        logger.error("Instrument master download failed — aborting startup")
        print("    ✗ Instrument master download failed")
        return EXIT_INSTRUMENT_ERROR
    print("    ✓ Instrument master downloaded")

    # Step 6: Subscribe to WebSocket feeds
    print("\n[6/6] Subscribing to WebSocket feeds...")
    if not subscribe_websocket(config, broker):
        logger.warning("WebSocket subscription failed (non-critical)")
        print("    ⚠ WebSocket subscription failed (non-critical)")
    else:
        print("    ✓ WebSocket feeds subscribed")

    print("\n" + "=" * 60)
    print("LOHI-TRADE startup complete ✓")
    print("=" * 60)
    logger.info("Startup sequence completed successfully")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
