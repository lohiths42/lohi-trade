"""Structured logging system for LOHI-TRADE.

This module provides a structured logging system with JSON formatting,
rotating file handlers, and console output for development.

Requirements: 21.1, 21.2, 21.8
"""

import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.utils.config import Config, get_config


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs logs in structured JSON format.

    Each log entry includes:
    - timestamp: ISO 8601 format with timezone
    - component: Name of the component generating the log
    - level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - message: Human-readable log message
    - Additional context fields if provided
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Args:
            record: The log record to format

        Returns:
            JSON-formatted log string

        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "component": getattr(record, "component", record.name),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Add correlation ID if present
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields from the record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "component",
                "correlation_id",
            ]:
                log_data[key] = value

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for console output during development."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record for console output.

        Args:
            record: The log record to format

        Returns:
            Formatted log string

        """
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        component = getattr(record, "component", record.name)
        level = record.levelname
        message = record.getMessage()

        # Add correlation ID if present
        correlation = ""
        if hasattr(record, "correlation_id"):
            correlation = f" [CID: {record.correlation_id}]"

        log_line = f"{timestamp} | {component:20s} | {level:8s} | {message}{correlation}"

        # Add exception info if present
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)

        return log_line


def setup_logging(config: Config | None = None) -> None:
    """Set up the logging system with structured JSON file logging and console output.

    Creates:
    - Rotating file handler with JSON formatting (100MB max, 10 files)
    - Console handler with human-readable formatting for development

    Args:
        config: Configuration object. If None, loads default config.

    Requirements: 21.1, 21.2

    """
    if config is None:
        config = get_config()

    # Support both the typed Config object and the legacy test/mocking style
    # that exposes configuration via get("logging.*").
    if hasattr(config, "logging"):
        logging_config = config.logging
        log_level = logging_config.level
        log_dir = Path(logging_config.log_dir)
        max_file_size_mb = logging_config.max_file_size_mb
        backup_count = logging_config.backup_count
    else:
        log_level = config.get("logging.level", "INFO")
        log_dir = Path(config.get("logging.log_dir", "data/logs"))
        max_file_size_mb = config.get("logging.max_file_size_mb", 100)
        backup_count = config.get("logging.backup_count", 10)

    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create rotating file handler with structured JSON format
    log_file = log_dir / "lohi_trade.log"
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=max_file_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(file_handler)

    # Create console handler with human-readable format for development
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # Log initialization
    root_logger.info(
        "Logging system initialized",
        extra={
            "component": "LoggingSystem",
            "log_level": log_level,
            "log_file": str(log_file),
            "max_file_size_mb": max_file_size_mb,
            "backup_count": backup_count,
        },
    )


class ComponentLogger:
    """Logger wrapper that automatically injects component name and supports correlation IDs.

    This class provides a convenient interface for component-specific logging
    with automatic component name injection and correlation ID support for tracing.

    Requirements: 21.2
    """

    def __init__(self, component_name: str):
        """Initialize a component-specific logger.

        Args:
            component_name: Name of the component (e.g., "WebSocketClient", "RMS")

        """
        self.component_name = component_name
        self.logger = logging.getLogger(component_name)
        self._correlation_id: str | None = None

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set a correlation ID for tracing related log entries.

        Args:
            correlation_id: Unique identifier for tracing (e.g., order_id, signal_id)

        """
        self._correlation_id = correlation_id

    def clear_correlation_id(self) -> None:
        """Clear the current correlation ID."""
        self._correlation_id = None

    def _add_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add component name and correlation ID to extra context.

        Args:
            extra: Additional context fields

        Returns:
            Context dictionary with component and correlation ID

        """
        context = extra.copy() if extra else {}
        context["component"] = self.component_name

        if self._correlation_id:
            context["correlation_id"] = self._correlation_id

        return context

    def debug(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log a debug message."""
        self.logger.debug(message, extra=self._add_context(extra))

    def info(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log an info message."""
        self.logger.info(message, extra=self._add_context(extra))

    def warning(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log a warning message."""
        self.logger.warning(message, extra=self._add_context(extra))

    def error(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
        exc_info: bool = False,
    ) -> None:
        """Log an error message.

        Args:
            message: Error message
            extra: Additional context fields
            exc_info: If True, include exception information

        """
        self.logger.error(message, extra=self._add_context(extra), exc_info=exc_info)

    def critical(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
        exc_info: bool = False,
    ) -> None:
        """Log a critical message.

        Args:
            message: Critical message
            extra: Additional context fields
            exc_info: If True, include exception information

        """
        self.logger.critical(message, extra=self._add_context(extra), exc_info=exc_info)


def get_logger(component_name: str) -> ComponentLogger:
    """Get a component-specific logger with automatic context injection.

    This factory function creates a ComponentLogger instance that automatically
    injects the component name into all log entries and supports correlation IDs
    for tracing related events across the system.

    Args:
        component_name: Name of the component (e.g., "WebSocketClient", "RMS")

    Returns:
        ComponentLogger instance for the component

    Example:
        >>> logger = get_logger("CandleBuilder")
        >>> logger.set_correlation_id("order-123")
        >>> logger.info("Candle completed", extra={"symbol": "RELIANCE"})
        >>> logger.clear_correlation_id()

    Requirements: 21.2

    """
    return ComponentLogger(component_name)
