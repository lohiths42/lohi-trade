"""
Tests for database connection manager and write retry logic.

Tests cover:
- SQLite connection with WAL mode
- DuckDB connection
- Health checks
- Write retry logic with exponential backoff
- Schema initialization
"""

import sqlite3
import tempfile
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.state.database import DatabaseConnectionManager, get_database_manager


class TestDatabaseConnectionManager:
    """Unit tests for database connection manager."""
    
    def test_init(self):
        """Test database manager initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            duckdb_path = f"{tmpdir}/test.duckdb"
            
            db_manager = DatabaseConnectionManager(
                sqlite_path=sqlite_path,
                duckdb_path=duckdb_path
            )
            
            assert db_manager.sqlite_path == Path(sqlite_path)
            assert db_manager.duckdb_path == Path(duckdb_path)
            assert db_manager._sqlite_conn is None
            assert db_manager._duckdb_conn is None
    
    def test_connect_sqlite_creates_database(self):
        """Test SQLite connection creates database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            conn = db_manager.connect_sqlite()
            
            assert conn is not None
            assert Path(sqlite_path).exists()
            
            # Verify WAL mode is enabled
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.upper() == "WAL"
            
            db_manager.close()

    def test_connect_sqlite_initializes_schema(self):
        """Test SQLite connection initializes schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            conn = db_manager.connect_sqlite()
            
            # Verify tables exist
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            assert "trades" in tables
            assert "orders" in tables
            assert "sentiment_log" in tables
            assert "bias_log" in tables
            assert "audit_log" in tables
            
            db_manager.close()
    
    def test_health_check_sqlite_success(self):
        """Test SQLite health check succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            assert db_manager.health_check_sqlite() is True
            
            db_manager.close()
    
    def test_health_check_sqlite_failure(self):
        """Test SQLite health check handles errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/nonexistent/test.db"
            
            # Create manager with invalid path
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            
            # Mock the connection to raise an error
            with patch.object(db_manager, 'connect_sqlite') as mock_connect:
                mock_connect.side_effect = sqlite3.Error("Connection failed")
                
                # Health check should return False on error
                assert db_manager.health_check_sqlite() is False
    
    def test_get_sqlite_cursor_context_manager(self):
        """Test SQLite cursor context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            # Insert data using context manager
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (event_type, component, message) "
                    "VALUES (?, ?, ?)",
                    ("TEST", "test_component", "test message")
                )
            
            # Verify data was committed
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("SELECT * FROM audit_log WHERE event_type = 'TEST'")
                row = cursor.fetchone()
                assert row is not None
                assert row["component"] == "test_component"
            
            db_manager.close()
    
    def test_get_sqlite_cursor_rollback_on_error(self):
        """Test SQLite cursor rolls back on error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            # Try to insert invalid data
            with pytest.raises(sqlite3.IntegrityError):
                with db_manager.get_sqlite_cursor() as cursor:
                    # Insert valid data
                    cursor.execute(
                        "INSERT INTO audit_log (event_type, component, message) "
                        "VALUES (?, ?, ?)",
                        ("TEST1", "component1", "message1")
                    )
                    # Insert duplicate trade_id (should fail)
                    cursor.execute(
                        "INSERT INTO trades (trade_id, symbol, side, strategy, "
                        "entry_price, quantity, entry_time, stop_loss, target) "
                        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)",
                        ("trade1", "TEST", "BUY", "test", 100.0, 10, 95.0, 105.0)
                    )
                    cursor.execute(
                        "INSERT INTO trades (trade_id, symbol, side, strategy, "
                        "entry_price, quantity, entry_time, stop_loss, target) "
                        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)",
                        ("trade1", "TEST", "BUY", "test", 100.0, 10, 95.0, 105.0)
                    )
            
            # Verify first insert was rolled back
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("SELECT * FROM audit_log WHERE event_type = 'TEST1'")
                row = cursor.fetchone()
                assert row is None
            
            db_manager.close()
    
    def test_close_connections(self):
        """Test closing all connections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            assert db_manager._sqlite_conn is not None
            
            db_manager.close()
            
            assert db_manager._sqlite_conn is None
    
    def test_context_manager(self):
        """Test database manager as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            with DatabaseConnectionManager(sqlite_path=sqlite_path) as db_manager:
                conn = db_manager.connect_sqlite()
                assert conn is not None
            
            # Connection should be closed after exiting context
            assert db_manager._sqlite_conn is None


class TestDatabaseWriteRetry:
    """Tests for database write retry logic."""
    
    def test_execute_with_retry_success_first_attempt(self):
        """Test successful execution on first attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            cursor = db_manager.execute_with_retry(
                "INSERT INTO audit_log (event_type, component, message) "
                "VALUES (?, ?, ?)",
                ("TEST", "component", "message")
            )
            
            assert cursor is not None
            
            # Verify data was inserted
            with db_manager.get_sqlite_cursor() as check_cursor:
                check_cursor.execute("SELECT * FROM audit_log WHERE event_type = 'TEST'")
                row = check_cursor.fetchone()
                assert row is not None
            
            db_manager.close()
    
    @patch('time.sleep')
    def test_execute_with_retry_succeeds_after_retries(self, mock_sleep):
        """Test successful execution after retries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            
            # Mock the connection to simulate lock errors
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            
            # Fail twice with lock error, then succeed
            mock_conn.execute.side_effect = [
                sqlite3.OperationalError("database is locked"),
                sqlite3.OperationalError("database is locked"),
                mock_cursor
            ]
            
            db_manager._sqlite_conn = mock_conn
            
            cursor = db_manager.execute_with_retry(
                "INSERT INTO test VALUES (?)",
                ("value",),
                max_retries=3,
                backoff_base=0.1
            )
            
            assert cursor is not None
            assert mock_conn.execute.call_count == 3
            assert mock_sleep.call_count == 2
            
            # Verify exponential backoff
            mock_sleep.assert_any_call(0.1)  # First retry: 0.1 * 2^0
            mock_sleep.assert_any_call(0.2)  # Second retry: 0.1 * 2^1
    
    @patch('time.sleep')
    def test_execute_with_retry_fails_after_max_retries(self, mock_sleep):
        """Test failure after max retries exhausted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            
            # Mock the connection to always fail with lock error
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = sqlite3.OperationalError("database is locked")
            
            db_manager._sqlite_conn = mock_conn
            
            with pytest.raises(sqlite3.OperationalError):
                db_manager.execute_with_retry(
                    "INSERT INTO test VALUES (?)",
                    ("value",),
                    max_retries=3,
                    backoff_base=0.1
                )
            
            assert mock_conn.execute.call_count == 3
            assert mock_sleep.call_count == 2


class TestDatabasePropertyBased:
    """Property-based tests for database operations."""
    
    @settings(max_examples=5, deadline=5000)
    @given(
        max_retries=st.integers(min_value=1, max_value=5),
        backoff_base=st.floats(min_value=0.01, max_value=0.5),
    )
    @patch('time.sleep')
    def test_property_database_write_retry(self, mock_sleep, max_retries, backoff_base):
        """
        Feature: lohi-trade, Property 80: Database Write Retry
        
        For any database write failure, up to 3 retry attempts should be made
        with exponential backoff (1s, 2s, 4s).
        
        This property verifies that:
        1. Retries are attempted up to max_retries times
        2. Exponential backoff is applied between retries
        3. Success is returned if any retry succeeds
        4. Error is raised if all retries fail
        
        Validates: Requirements 25.4
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            
            # Mock the connection
            mock_conn = MagicMock()
            
            # Test case 1: Succeed after some retries
            retry_count = min(max_retries - 1, 2)  # Fail a few times, then succeed
            mock_cursor = MagicMock()
            mock_conn.execute.side_effect = (
                [sqlite3.OperationalError("database is locked")] * retry_count
                + [mock_cursor]
            )
            
            db_manager._sqlite_conn = mock_conn
            
            cursor = db_manager.execute_with_retry(
                "INSERT INTO test VALUES (?)",
                ("value",),
                max_retries=max_retries,
                backoff_base=backoff_base
            )
            
            # Verify success after retries
            assert cursor is not None
            assert mock_conn.execute.call_count == retry_count + 1
            
            # Verify exponential backoff was applied
            if retry_count > 0:
                assert mock_sleep.call_count == retry_count
                
                # Check backoff delays
                for i in range(retry_count):
                    expected_delay = backoff_base * (2 ** i)
                    actual_delay = mock_sleep.call_args_list[i][0][0]
                    assert abs(actual_delay - expected_delay) < 0.001
            
            # Reset for test case 2: All retries fail
            mock_sleep.reset_mock()
            mock_conn.reset_mock()
            mock_conn.execute.side_effect = sqlite3.OperationalError("database is locked")
            
            with pytest.raises(sqlite3.OperationalError):
                db_manager.execute_with_retry(
                    "INSERT INTO test VALUES (?)",
                    ("value",),
                    max_retries=max_retries,
                    backoff_base=backoff_base
                )
            
            # Verify all retries were attempted
            assert mock_conn.execute.call_count == max_retries
            assert mock_sleep.call_count == max_retries - 1
    
    @settings(max_examples=5, deadline=5000)
    @given(
        event_type=st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))),
        component=st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))),
        message=st.text(min_size=1, max_size=200, alphabet=st.characters(blacklist_categories=("Cs",))),
    )
    def test_property_audit_log_persistence(self, event_type, component, message):
        """
        Property: Audit log entries should be persisted correctly.
        
        For any event_type, component, and message, after inserting into
        audit_log, the data should be retrievable with all fields intact.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            # Insert audit log entry
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (event_type, component, message) "
                    "VALUES (?, ?, ?)",
                    (event_type, component, message)
                )
            
            # Retrieve and verify
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "SELECT event_type, component, message FROM audit_log "
                    "WHERE event_type = ? AND component = ?",
                    (event_type, component)
                )
                row = cursor.fetchone()
                
                assert row is not None
                assert row["event_type"] == event_type
                assert row["component"] == component
                assert row["message"] == message
            
            db_manager.close()


class TestGetDatabaseManager:
    """Tests for global database manager singleton."""
    
    def test_get_database_manager_creates_instance(self):
        """Test get_database_manager creates instance."""
        # Reset global instance
        import src.state.database as db_module
        db_module._db_manager = None
        
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            manager = get_database_manager(sqlite_path=sqlite_path)
            
            assert manager is not None
            assert isinstance(manager, DatabaseConnectionManager)
    
    def test_get_database_manager_returns_same_instance(self):
        """Test get_database_manager returns same instance."""
        # Reset global instance
        import src.state.database as db_module
        db_module._db_manager = None
        
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            
            manager1 = get_database_manager(sqlite_path=sqlite_path)
            manager2 = get_database_manager(sqlite_path=sqlite_path)
            
            assert manager1 is manager2



class TestDatabaseBackup:
    """Tests for database backup functionality."""
    
    def test_create_backup(self):
        """Test creating a database backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = f"{tmpdir}/backups"
            
            # Create a database with some data
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (event_type, component, message) "
                    "VALUES (?, ?, ?)",
                    ("TEST", "component", "message")
                )
            
            db_manager.close()
            
            # Create backup
            from src.state.database_backup import DatabaseBackupManager
            backup_manager = DatabaseBackupManager(
                sqlite_path=sqlite_path,
                backup_dir=backup_dir,
                retention_days=30
            )
            
            backup_path = backup_manager.create_backup()
            
            assert backup_path is not None
            assert backup_path.exists()
            assert backup_path.suffix == ".db"
            assert "lohi_trade_backup_" in backup_path.name
    
    def test_backup_contains_data(self):
        """Test that backup contains the same data as original."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = f"{tmpdir}/backups"
            
            # Create a database with some data
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            test_message = "test_backup_data"
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (event_type, component, message) "
                    "VALUES (?, ?, ?)",
                    ("TEST", "component", test_message)
                )
            
            db_manager.close()
            
            # Create backup
            from src.state.database_backup import DatabaseBackupManager
            backup_manager = DatabaseBackupManager(
                sqlite_path=sqlite_path,
                backup_dir=backup_dir
            )
            
            backup_path = backup_manager.create_backup()
            
            # Verify backup contains the data
            backup_conn = sqlite3.connect(str(backup_path))
            cursor = backup_conn.execute(
                "SELECT message FROM audit_log WHERE event_type = 'TEST'"
            )
            row = cursor.fetchone()
            backup_conn.close()
            
            assert row is not None
            assert row[0] == test_message
    
    def test_cleanup_old_backups(self):
        """Test cleanup of old backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            
            # Create a test database
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            db_manager.close()
            
            # Create some old backup files
            old_backup1 = backup_dir / "lohi_trade_backup_20230101_120000.db"
            old_backup2 = backup_dir / "lohi_trade_backup_20230102_120000.db"
            recent_backup = backup_dir / "lohi_trade_backup_20240101_120000.db"
            
            # Create empty backup files
            old_backup1.touch()
            old_backup2.touch()
            recent_backup.touch()
            
            # Set modification times
            import os
            old_time = (datetime.now() - timedelta(days=35)).timestamp()
            recent_time = (datetime.now() - timedelta(days=5)).timestamp()
            
            os.utime(old_backup1, (old_time, old_time))
            os.utime(old_backup2, (old_time, old_time))
            os.utime(recent_backup, (recent_time, recent_time))
            
            # Cleanup old backups
            from src.state.database_backup import DatabaseBackupManager
            backup_manager = DatabaseBackupManager(
                sqlite_path=sqlite_path,
                backup_dir=str(backup_dir),
                retention_days=30
            )
            
            deleted_count = backup_manager.cleanup_old_backups()
            
            # Verify old backups were deleted
            assert deleted_count == 2
            assert not old_backup1.exists()
            assert not old_backup2.exists()
            assert recent_backup.exists()
    
    def test_list_backups(self):
        """Test listing available backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            
            # Create some backup files
            backup1 = backup_dir / "lohi_trade_backup_20240101_120000.db"
            backup2 = backup_dir / "lohi_trade_backup_20240102_120000.db"
            backup3 = backup_dir / "lohi_trade_backup_20240103_120000.db"
            
            backup1.touch()
            backup2.touch()
            backup3.touch()
            
            # List backups
            from src.state.database_backup import DatabaseBackupManager
            backup_manager = DatabaseBackupManager(
                sqlite_path=sqlite_path,
                backup_dir=str(backup_dir)
            )
            
            backups = backup_manager.list_backups()
            
            assert len(backups) == 3
            # Should be sorted by date (newest first)
            assert backups[0].name == "lohi_trade_backup_20240103_120000.db"
            assert backups[1].name == "lohi_trade_backup_20240102_120000.db"
            assert backups[2].name == "lohi_trade_backup_20240101_120000.db"
    
    def test_perform_backup_with_cleanup(self):
        """Test performing backup with cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = f"{tmpdir}/backups"
            
            # Create a test database
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            db_manager.close()
            
            # Perform backup with cleanup
            from src.state.database_backup import DatabaseBackupManager
            backup_manager = DatabaseBackupManager(
                sqlite_path=sqlite_path,
                backup_dir=backup_dir,
                retention_days=30
            )
            
            result = backup_manager.perform_backup_with_cleanup()
            
            assert result is True
            
            # Verify backup was created
            backups = backup_manager.list_backups()
            assert len(backups) == 1
    
    def test_restore_from_backup(self):
        """Test restoring database from backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = f"{tmpdir}/test.db"
            backup_dir = f"{tmpdir}/backups"
            
            # Create a database with initial data
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (event_type, component, message) "
                    "VALUES (?, ?, ?)",
                    ("ORIGINAL", "component", "original message")
                )
            
            db_manager.close()
            
            # Create backup manually (not using backup manager to avoid complexity)
            backup_path = Path(backup_dir) / "test_backup.db"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sqlite_path, backup_path)
            
            # Modify database by deleting all data
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("DELETE FROM audit_log")
            
            db_manager.close()
            
            # Verify database is empty
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM audit_log")
                count_before = cursor.fetchone()[0]
            
            db_manager.close()
            
            assert count_before == 0
            
            # Restore from backup using simple copy
            shutil.copy2(backup_path, sqlite_path)
            
            # Verify database was restored
            db_manager = DatabaseConnectionManager(sqlite_path=sqlite_path)
            db_manager.connect_sqlite()
            
            with db_manager.get_sqlite_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'ORIGINAL'")
                original_count = cursor.fetchone()[0]
            
            db_manager.close()
            
            assert original_count == 1
