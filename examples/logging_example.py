"""
Example demonstrating the structured logging system.

This example shows how to use the logging system with:
- Component-specific loggers
- Correlation IDs for tracing
- Extra context fields
- Different log levels
"""

import logging
import tempfile
from pathlib import Path

from src.utils.logger import setup_logging, get_logger


class SimpleConfig:
    """Simple config for demonstration."""
    def get(self, key, default=None):
        config = {
            "logging.level": "INFO",
            "logging.log_dir": "data/logs",
            "logging.max_file_size_mb": 100,
            "logging.backup_count": 10
        }
        return config.get(key, default)


def main():
    """Demonstrate the logging system."""
    
    # Set up logging with simple config
    config = SimpleConfig()
    setup_logging(config)
    
    # Get a component-specific logger
    logger = get_logger("ExampleComponent")
    
    print("=" * 60)
    print("Structured Logging System Demo")
    print("=" * 60)
    print()
    
    # Basic logging
    print("1. Basic logging:")
    logger.info("Application started")
    logger.debug("Debug information", extra={"version": "1.0.0"})
    print()
    
    # Logging with correlation ID for tracing
    print("2. Logging with correlation ID for tracing:")
    logger.set_correlation_id("order-12345")
    logger.info("Processing order", extra={"symbol": "RELIANCE", "quantity": 100})
    logger.info("Order validated", extra={"price": 2500.50})
    logger.clear_correlation_id()
    print()
    
    # Logging with extra context
    print("3. Logging with extra context fields:")
    logger.info(
        "Trade executed",
        extra={
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 50,
            "price": 3500.75,
            "strategy": "mean_reversion"
        }
    )
    print()
    
    # Warning and error logging
    print("4. Warning and error logging:")
    logger.warning("Daily loss approaching limit", extra={"current_loss_pct": 1.8})
    
    try:
        # Simulate an error
        raise ValueError("Invalid order quantity")
    except ValueError as e:
        logger.error("Order validation failed", extra={"error": str(e)}, exc_info=True)
    print()
    
    # Critical logging
    print("5. Critical logging:")
    logger.critical("Kill switch activated", extra={"reason": "Daily loss limit exceeded"})
    print()
    
    print("=" * 60)
    print("Logging complete!")
    print("=" * 60)
    print()
    print("Console output above shows human-readable format.")
    print("Check data/logs/lohi_trade.log for structured JSON logs.")
    print()
    print("Each JSON log entry includes:")
    print("  - timestamp (ISO 8601 format)")
    print("  - component (component name)")
    print("  - level (log level)")
    print("  - message (log message)")
    print("  - correlation_id (if set)")
    print("  - extra fields (any additional context)")


if __name__ == "__main__":
    main()
