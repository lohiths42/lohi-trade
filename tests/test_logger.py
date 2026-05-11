"""Property-based tests for structured logging system.

Tests cover:
- Structured logging format (Property 70)
- Component name injection
- Correlation ID support
- Log level filtering
- Rotating file handler
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.utils.logger import (
    ComponentLogger,
    ConsoleFormatter,
    StructuredFormatter,
    setup_logging,
)


class TestStructuredFormatter:
    """Test structured JSON formatter."""

    def test_basic_log_format(self):
        """Test that basic log entry contains required fields."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="TestComponent",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.component = "TestComponent"

        result = formatter.format(record)
        log_data = json.loads(result)

        assert "timestamp" in log_data
        assert "component" in log_data
        assert "level" in log_data
        assert "message" in log_data
        assert log_data["component"] == "TestComponent"
        assert log_data["level"] == "INFO"
        assert log_data["message"] == "Test message"

    def test_log_with_correlation_id(self):
        """Test that correlation ID is included when present."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="TestComponent",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.component = "TestComponent"
        record.correlation_id = "test-correlation-123"

        result = formatter.format(record)
        log_data = json.loads(result)

        assert "correlation_id" in log_data
        assert log_data["correlation_id"] == "test-correlation-123"

    def test_log_with_extra_fields(self):
        """Test that extra fields are included in log output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="TestComponent",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.component = "TestComponent"
        record.symbol = "RELIANCE"
        record.price = 2500.50

        result = formatter.format(record)
        log_data = json.loads(result)

        assert "symbol" in log_data
        assert "price" in log_data
        assert log_data["symbol"] == "RELIANCE"
        assert log_data["price"] == 2500.50

    def test_log_with_exception(self):
        """Test that exception information is included."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

            record = logging.LogRecord(
                name="TestComponent",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )
            record.component = "TestComponent"

            result = formatter.format(record)
            log_data = json.loads(result)

            assert "exception" in log_data
            assert "ValueError" in log_data["exception"]
            assert "Test exception" in log_data["exception"]


class TestConsoleFormatter:
    """Test console formatter."""

    def test_console_format(self):
        """Test that console format is human-readable."""
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="TestComponent",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.component = "TestComponent"

        result = formatter.format(record)

        assert "TestComponent" in result
        assert "INFO" in result
        assert "Test message" in result

    def test_console_format_with_correlation_id(self):
        """Test that correlation ID appears in console output."""
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="TestComponent",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.component = "TestComponent"
        record.correlation_id = "test-123"

        result = formatter.format(record)

        assert "CID: test-123" in result


class TestComponentLogger:
    """Test component-specific logger."""

    def test_component_name_injection(self):
        """Test that component name is automatically injected."""
        logger = ComponentLogger("TestComponent")

        # Capture log output
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"
            handler = logging.FileHandler(log_file)
            handler.setFormatter(StructuredFormatter())
            logger.logger.addHandler(handler)
            logger.logger.setLevel(logging.INFO)

            logger.info("Test message")

            handler.close()

            # Read and verify log
            with open(log_file) as f:
                log_line = f.readline()
                log_data = json.loads(log_line)

                assert log_data["component"] == "TestComponent"
                assert log_data["message"] == "Test message"

    def test_correlation_id_support(self):
        """Test correlation ID setting and clearing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"

            # Create a fresh logger for this test
            logger = ComponentLogger("TestComponent_CorrelationID")
            handler = logging.FileHandler(log_file)
            handler.setFormatter(StructuredFormatter())
            logger.logger.addHandler(handler)
            logger.logger.setLevel(logging.INFO)

            try:
                # Log with correlation ID
                logger.set_correlation_id("order-123")
                logger.info("Message with correlation")

                # Log without correlation ID
                logger.clear_correlation_id()
                logger.info("Message without correlation")
            finally:
                handler.flush()
                handler.close()
                logger.logger.removeHandler(handler)

            # Read and verify logs
            with open(log_file) as f:
                lines = f.readlines()

                log1 = json.loads(lines[0])
                assert "correlation_id" in log1
                assert log1["correlation_id"] == "order-123"

                log2 = json.loads(lines[1])
                assert "correlation_id" not in log2

    def test_extra_context_fields(self):
        """Test that extra context fields are included."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"

            # Create a fresh logger for this test
            logger = ComponentLogger("TestComponent_ExtraFields")
            handler = logging.FileHandler(log_file)
            handler.setFormatter(StructuredFormatter())
            logger.logger.addHandler(handler)
            logger.logger.setLevel(logging.INFO)

            try:
                logger.info("Test message", extra={"symbol": "RELIANCE", "price": 2500})
            finally:
                handler.flush()
                handler.close()
                logger.logger.removeHandler(handler)

            with open(log_file) as f:
                log_line = f.readline()
                log_data = json.loads(log_line)

                assert log_data["symbol"] == "RELIANCE"
                assert log_data["price"] == 2500

    def test_all_log_levels(self):
        """Test that all log levels work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"

            # Create a fresh logger for this test
            logger = ComponentLogger("TestComponent_AllLevels")
            handler = logging.FileHandler(log_file)
            handler.setFormatter(StructuredFormatter())
            logger.logger.addHandler(handler)
            logger.logger.setLevel(logging.DEBUG)

            try:
                logger.debug("Debug message")
                logger.info("Info message")
                logger.warning("Warning message")
                logger.error("Error message")
                logger.critical("Critical message")
            finally:
                handler.flush()
                handler.close()
                logger.logger.removeHandler(handler)

            with open(log_file) as f:
                lines = f.readlines()
                assert len(lines) == 5

                levels = [json.loads(line)["level"] for line in lines]
                assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class TestLoggingSetup:
    """Test logging system setup."""

    def test_setup_creates_log_directory(self):
        """Test that setup creates log directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"

            # Create a minimal config
            config_dict = {
                "logging": {
                    "level": "INFO",
                    "log_dir": str(log_dir),
                    "max_file_size_mb": 100,
                    "backup_count": 10,
                },
            }

            # Mock Config class
            class MockConfig:
                def get(self, key, default=None):
                    keys = key.split(".")
                    value = config_dict
                    for k in keys:
                        value = value.get(k, default)
                        if value is None:
                            return default
                    return value

            setup_logging(MockConfig())

            assert log_dir.exists()
            assert (log_dir / "lohi_trade.log").exists()

    def test_setup_respects_log_level(self):
        """Test that setup respects configured log level."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"

            config_dict = {
                "logging": {
                    "level": "WARNING",
                    "log_dir": str(log_dir),
                    "max_file_size_mb": 100,
                    "backup_count": 10,
                },
            }

            class MockConfig:
                def get(self, key, default=None):
                    keys = key.split(".")
                    value = config_dict
                    for k in keys:
                        value = value.get(k, default)
                        if value is None:
                            return default
                    return value

            setup_logging(MockConfig())

            logger = logging.getLogger()
            assert logger.level == logging.WARNING


# Property-Based Tests

@settings(max_examples=5)
@given(
    component_name=st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_-",
    )),
    message=st.text(min_size=1, max_size=200),
    level=st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
)
def test_property_structured_logging_format(component_name, message, level):
    """Feature: lohi-trade, Property 70: Structured Logging Format
    
    For any log entry, it should include timestamp, component name, log level,
    and message in structured format.
    
    Validates: Requirements 21.2
    """
    # Skip empty or whitespace-only strings
    assume(component_name.strip())
    assume(message.strip())

    logger = ComponentLogger(component_name)

    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "test.log"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(StructuredFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.DEBUG)

        try:
            # Log the message at the specified level
            log_method = getattr(logger, level.lower())
            log_method(message)
        finally:
            handler.flush()
            handler.close()
            logger.logger.removeHandler(handler)

        # Read and verify the log entry
        with open(log_file) as f:
            log_line = f.readline()

            # Should be valid JSON
            log_data = json.loads(log_line)

            # Verify required fields are present
            assert "timestamp" in log_data, "Log entry must include timestamp"
            assert "component" in log_data, "Log entry must include component name"
            assert "level" in log_data, "Log entry must include log level"
            assert "message" in log_data, "Log entry must include message"

            # Verify field values
            assert log_data["component"] == component_name
            assert log_data["level"] == level
            assert log_data["message"] == message

            # Verify timestamp is valid ISO 8601 format
            datetime.fromisoformat(log_data["timestamp"])


@settings(max_examples=5)
@given(
    component_name=st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_-",
    )),
    correlation_id=st.text(min_size=1, max_size=100),
    message=st.text(min_size=1, max_size=200),
)
def test_property_correlation_id_tracing(component_name, correlation_id, message):
    """Feature: lohi-trade, Property: Correlation ID Tracing
    
    For any log entry with a correlation ID set, the correlation ID should be
    included in the structured log output for tracing.
    
    Validates: Requirements 21.2
    """
    assume(component_name.strip())
    assume(correlation_id.strip())
    assume(message.strip())

    logger = ComponentLogger(component_name)

    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "test.log"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(StructuredFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)

        try:
            # Set correlation ID and log
            logger.set_correlation_id(correlation_id)
            logger.info(message)
        finally:
            handler.flush()
            handler.close()
            logger.logger.removeHandler(handler)

        # Verify correlation ID is in the log
        with open(log_file) as f:
            log_line = f.readline()
            log_data = json.loads(log_line)

            assert "correlation_id" in log_data
            assert log_data["correlation_id"] == correlation_id


@settings(max_examples=5)
@given(
    component_name=st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_-",
    )),
    extra_fields=st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="_",
        )).filter(lambda k: k not in [
            # Reserved LogRecord attributes that cannot be overwritten
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "message", "pathname", "process", "processName",
            "relativeCreated", "thread", "threadName", "exc_info",
            "exc_text", "stack_info", "component", "correlation_id",
            "taskName",
        ]),
        values=st.one_of(
            st.text(min_size=0, max_size=50),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.booleans(),
        ),
        min_size=1,
        max_size=5,
    ),
)
def test_property_extra_context_fields(component_name, extra_fields):
    """Feature: lohi-trade, Property: Extra Context Fields
    
    For any log entry with extra context fields, all extra fields should be
    included in the structured log output.
    
    Validates: Requirements 21.2
    """
    assume(component_name.strip())
    assume(all(k.strip() for k in extra_fields.keys()))

    logger = ComponentLogger(component_name)

    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "test.log"
        handler = logging.FileHandler(log_file)
        handler.setFormatter(StructuredFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)

        try:
            logger.info("Test message", extra=extra_fields)
        finally:
            handler.flush()
            handler.close()
            logger.logger.removeHandler(handler)

        # Verify all extra fields are in the log
        with open(log_file) as f:
            log_line = f.readline()
            log_data = json.loads(log_line)

            for key, value in extra_fields.items():
                assert key in log_data
                assert log_data[key] == value

