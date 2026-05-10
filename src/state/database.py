"""Database connection manager for LOHI-TRADE system.

This module provides connection management for:
- SQLite: Operational data (trades, orders, sentiment, audit logs)
- DuckDB: Historical OHLCV data for backtesting

Features:
- SQLite with WAL mode for concurrent reads/writes
- Connection pooling and health checks
- Automatic schema initialization
- Write retry logic with exponential backoff
"""

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    logging.warning("DuckDB not available. Historical data features will be disabled.")

from src.state.database_schema import get_sqlite_schema

logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """Manages database connections for SQLite and DuckDB.
    
    Provides:
    - SQLite connection with WAL mode for concurrent access
    - DuckDB connection for analytical queries on historical data
    - Connection pooling and health checks
    - Automatic schema initialization
    """

    def __init__(
        self,
        sqlite_path: str = "data/lohi_trade.db",
        duckdb_path: str = "data/historical.duckdb",
    ):
        """Initialize database connection manager.
        
        Args:
            sqlite_path: Path to SQLite database file
            duckdb_path: Path to DuckDB database file

        """
        self.sqlite_path = Path(sqlite_path)
        self.duckdb_path = Path(duckdb_path)

        # Ensure data directory exists
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)

        self._sqlite_conn: sqlite3.Connection | None = None
        self._duckdb_conn: Any | None = None

        logger.info(f"Database manager initialized: SQLite={sqlite_path}, DuckDB={duckdb_path}")

    def connect_sqlite(self) -> sqlite3.Connection:
        """Establish SQLite connection with WAL mode.
        
        WAL (Write-Ahead Logging) mode allows concurrent reads while writing,
        which is essential for real-time trading system.
        
        Returns:
            sqlite3.Connection: Active SQLite connection

        """
        if self._sqlite_conn is None:
            try:
                self._sqlite_conn = sqlite3.connect(
                    str(self.sqlite_path),
                    check_same_thread=False,  # Allow multi-threaded access
                    timeout=30.0,  # Wait up to 30 seconds for locks
                )

                # Enable WAL mode for concurrent access
                self._sqlite_conn.execute("PRAGMA journal_mode=WAL")

                # Enable foreign key constraints
                self._sqlite_conn.execute("PRAGMA foreign_keys=ON")

                # Set row factory to return dict-like rows
                self._sqlite_conn.row_factory = sqlite3.Row

                logger.info("SQLite connection established with WAL mode")

                # Initialize schema
                self._initialize_sqlite_schema()

            except sqlite3.Error as e:
                logger.error(f"Failed to connect to SQLite: {e}")
                raise

        return self._sqlite_conn

    def connect_duckdb(self) -> Any | None:
        """Establish DuckDB connection for historical data.
        
        Returns:
            duckdb.Connection: Active DuckDB connection, or None if unavailable

        """
        if not DUCKDB_AVAILABLE:
            logger.warning("DuckDB not available, skipping connection")
            return None

        if self._duckdb_conn is None:
            try:
                self._duckdb_conn = duckdb.connect(str(self.duckdb_path))
                logger.info("DuckDB connection established")
            except Exception as e:
                logger.error(f"Failed to connect to DuckDB: {e}")
                raise

        return self._duckdb_conn

    def _initialize_sqlite_schema(self) -> None:
        """Initialize SQLite schema by creating all tables and indexes.
        """
        try:
            schema = get_sqlite_schema()
            self._sqlite_conn.executescript(schema)
            self._sqlite_conn.commit()
            logger.info("SQLite schema initialized successfully")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize SQLite schema: {e}")
            raise

    def health_check_sqlite(self) -> bool:
        """Perform health check on SQLite connection.
        
        Returns:
            bool: True if connection is healthy, False otherwise

        """
        try:
            conn = self.connect_sqlite()
            cursor = conn.execute("SELECT 1")
            result = cursor.fetchone()
            return result is not None
        except Exception as e:
            logger.error(f"SQLite health check failed: {e}")
            return False

    def health_check_duckdb(self) -> bool:
        """Perform health check on DuckDB connection.
        
        Returns:
            bool: True if connection is healthy, False otherwise

        """
        if not DUCKDB_AVAILABLE:
            return False

        try:
            conn = self.connect_duckdb()
            if conn is None:
                return False
            result = conn.execute("SELECT 1").fetchone()
            return result is not None
        except Exception as e:
            logger.error(f"DuckDB health check failed: {e}")
            return False

    @contextmanager
    def get_sqlite_cursor(self):
        """Context manager for SQLite cursor with automatic commit/rollback.
        
        Usage:
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("INSERT INTO trades ...")
        
        Yields:
            sqlite3.Cursor: Database cursor

        """
        conn = self.connect_sqlite()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed, rolled back: {e}")
            raise
        finally:
            cursor.close()

    def execute_with_retry(
        self,
        query: str,
        params: tuple = (),
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> sqlite3.Cursor | None:
        """Execute SQLite query with retry logic and exponential backoff.
        
        Implements retry pattern for handling database lock contention:
        - Retry 1: Wait 1 second
        - Retry 2: Wait 2 seconds
        - Retry 3: Wait 4 seconds
        
        Args:
            query: SQL query to execute
            params: Query parameters
            max_retries: Maximum number of retry attempts (default: 3)
            backoff_base: Base delay for exponential backoff in seconds (default: 1.0)
        
        Returns:
            sqlite3.Cursor: Cursor with query results, or None if all retries failed

        """
        conn = self.connect_sqlite()

        for attempt in range(max_retries):
            try:
                cursor = conn.execute(query, params)
                conn.commit()
                return cursor
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    # Database is locked, retry with exponential backoff
                    delay = backoff_base * (2 ** attempt)
                    logger.warning(
                        f"Database locked, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{max_retries})",
                    )
                    time.sleep(delay)
                else:
                    # Not a lock error or final attempt
                    logger.error(f"Database operation failed after {attempt + 1} attempts: {e}")
                    raise
            except sqlite3.Error as e:
                logger.error(f"Database error on attempt {attempt + 1}: {e}")
                raise

        return None

    def close(self) -> None:
        """Close all database connections.
        """
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
                self._sqlite_conn = None
                logger.info("SQLite connection closed")
            except Exception as e:
                logger.error(f"Error closing SQLite connection: {e}")

        if self._duckdb_conn:
            try:
                self._duckdb_conn.close()
                self._duckdb_conn = None
                logger.info("DuckDB connection closed")
            except Exception as e:
                logger.error(f"Error closing DuckDB connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Global database manager instance
_db_manager: DatabaseConnectionManager | None = None


def get_database_manager(
    sqlite_path: str = "data/lohi_trade.db",
    duckdb_path: str = "data/historical.duckdb",
) -> DatabaseConnectionManager:
    """Get or create global database manager instance.
    
    Args:
        sqlite_path: Path to SQLite database file
        duckdb_path: Path to DuckDB database file
    
    Returns:
        DatabaseConnectionManager: Global database manager instance

    """
    global _db_manager

    if _db_manager is None:
        _db_manager = DatabaseConnectionManager(sqlite_path, duckdb_path)

    return _db_manager
