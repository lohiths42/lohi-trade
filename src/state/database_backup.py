"""Database backup functionality for LOHI-TRADE system.

This module provides:
- Daily SQLite database backup at 4:00 PM IST
- Backup retention policy (30 days)
- Automatic cleanup of old backups
"""

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseBackupManager:
    """Manages database backups with retention policy.
    
    Features:
    - Creates timestamped backups of SQLite database
    - Retains backups for configurable number of days (default: 30)
    - Automatically cleans up old backups
    """

    def __init__(
        self,
        sqlite_path: str,
        backup_dir: str = "data/backups",
        retention_days: int = 30,
    ):
        """Initialize database backup manager.
        
        Args:
            sqlite_path: Path to SQLite database file
            backup_dir: Directory to store backups
            retention_days: Number of days to retain backups (default: 30)

        """
        self.sqlite_path = Path(sqlite_path)
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Backup manager initialized: db={sqlite_path}, "
            f"backup_dir={backup_dir}, retention={retention_days} days",
        )

    def create_backup(self) -> Path | None:
        """Create a backup of the SQLite database.
        
        Uses SQLite's backup API for safe online backup without locking.
        
        Returns:
            Path: Path to created backup file, or None if backup failed

        """
        if not self.sqlite_path.exists():
            logger.error(f"Database file not found: {self.sqlite_path}")
            return None

        try:
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"lohi_trade_backup_{timestamp}.db"
            backup_path = self.backup_dir / backup_filename

            # Use SQLite backup API for safe online backup
            source_conn = sqlite3.connect(str(self.sqlite_path))
            backup_conn = sqlite3.connect(str(backup_path))

            with backup_conn:
                source_conn.backup(backup_conn)

            source_conn.close()
            backup_conn.close()

            backup_size = backup_path.stat().st_size / (1024 * 1024)  # MB
            logger.info(
                f"Database backup created: {backup_filename} "
                f"({backup_size:.2f} MB)",
            )

            return backup_path

        except Exception as e:
            logger.error(f"Failed to create database backup: {e}")
            return None

    def cleanup_old_backups(self) -> int:
        """Remove backups older than retention period.
        
        Returns:
            int: Number of backups deleted

        """
        if not self.backup_dir.exists():
            return 0

        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            deleted_count = 0

            # Find all backup files
            backup_files = list(self.backup_dir.glob("lohi_trade_backup_*.db"))

            for backup_file in backup_files:
                # Get file modification time
                file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)

                if file_mtime < cutoff_date:
                    try:
                        backup_file.unlink()
                        deleted_count += 1
                        logger.info(f"Deleted old backup: {backup_file.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete backup {backup_file.name}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old backup(s)")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {e}")
            return 0

    def perform_backup_with_cleanup(self) -> bool:
        """Perform backup and cleanup old backups.
        
        This is the main method to call for scheduled backups.
        
        Returns:
            bool: True if backup was successful, False otherwise

        """
        logger.info("Starting scheduled database backup...")

        # Create new backup
        backup_path = self.create_backup()

        if backup_path is None:
            logger.error("Backup failed")
            return False

        # Cleanup old backups
        deleted_count = self.cleanup_old_backups()

        logger.info(
            f"Backup completed successfully. "
            f"Deleted {deleted_count} old backup(s).",
        )

        return True

    def list_backups(self) -> list[Path]:
        """List all available backups sorted by date (newest first).
        
        Returns:
            list[Path]: List of backup file paths

        """
        if not self.backup_dir.exists():
            return []

        backup_files = list(self.backup_dir.glob("lohi_trade_backup_*.db"))

        # Sort by modification time (newest first)
        backup_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return backup_files

    def restore_from_backup(self, backup_path: Path) -> bool:
        """Restore database from a backup file.
        
        WARNING: This will overwrite the current database!
        
        Args:
            backup_path: Path to backup file to restore from
        
        Returns:
            bool: True if restore was successful, False otherwise

        """
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False

        try:
            # Create a backup of current database before restoring
            current_backup = self.create_backup()
            if current_backup:
                logger.info(f"Created safety backup: {current_backup.name}")

            # Copy backup file to database location
            shutil.copy2(backup_path, self.sqlite_path)

            logger.info(f"Database restored from backup: {backup_path.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}")
            return False


def schedule_daily_backup(
    sqlite_path: str,
    backup_dir: str = "data/backups",
    backup_time: str = "16:00",
    retention_days: int = 30,
) -> None:
    """Schedule daily database backup at specified time.
    
    This function should be called from the main application startup.
    It will run the backup at the specified time each day.
    
    Args:
        sqlite_path: Path to SQLite database file
        backup_dir: Directory to store backups
        backup_time: Time to run backup in HH:MM format (24-hour)
        retention_days: Number of days to retain backups

    """
    import threading
    import time

    import schedule

    backup_manager = DatabaseBackupManager(
        sqlite_path=sqlite_path,
        backup_dir=backup_dir,
        retention_days=retention_days,
    )

    # Schedule backup at specified time
    schedule.every().day.at(backup_time).do(
        backup_manager.perform_backup_with_cleanup,
    )

    logger.info(f"Scheduled daily backup at {backup_time} IST")

    def run_scheduler():
        """Run the scheduler in a background thread."""
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    logger.info("Backup scheduler started")
