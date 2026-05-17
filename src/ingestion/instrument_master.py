"""Instrument master management for LOHI-TRADE.

This module handles downloading, storing, and validating instrument master data
from broker APIs. The instrument master contains symbol tokens, lot sizes, tick sizes,
and other trading details required for order placement and WebSocket subscription.

Requirements: 23.1, 23.2, 23.3, 23.4
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.ingestion.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)


class InstrumentMaster:
    """Manages instrument master data for trading symbols.

    The instrument master contains:
    - symbol: Trading symbol (e.g., "RELIANCE")
    - token: Exchange token for WebSocket subscription
    - exchange: Exchange name (NSE, BSE)
    - lot_size: Minimum trading quantity
    - tick_size: Minimum price movement
    - trading_symbol: Full trading symbol with exchange
    """

    def __init__(self, data_dir: str = "data"):
        """Initialize instrument master manager.

        Args:
            data_dir: Directory to store instrument master files

        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.instruments: dict[str, dict] = {}
        self.last_updated: datetime | None = None

    def download_from_broker(
        self, broker: BrokerInterface, symbols: list[str] | None = None
    ) -> bool:
        """Download instrument master from broker API.

        Args:
            broker: Connected broker instance
            symbols: Optional list of symbols to filter (if None, downloads all)

        Returns:
            True if download successful, False otherwise

        Requirements: 23.1, 23.2

        """
        try:
            logger.info("Downloading instrument master from broker")

            # Get full instrument list from broker
            instruments = broker.get_instrument_master()

            if not instruments:
                logger.error("No instruments received from broker")
                return False

            logger.info(f"Downloaded {len(instruments)} instruments from broker")

            # Filter to requested symbols if provided
            if symbols:
                filtered_instruments = [
                    inst
                    for inst in instruments
                    if inst.get("symbol") in symbols or inst.get("trading_symbol") in symbols
                ]
                logger.info(
                    f"Filtered to {len(filtered_instruments)} instruments for configured symbols"
                )
                instruments = filtered_instruments

            # Store instruments in memory
            self.instruments = {inst["symbol"]: inst for inst in instruments}
            self.last_updated = datetime.now()

            logger.info(f"Loaded {len(self.instruments)} instruments into memory")
            return True

        except Exception as e:
            logger.error(f"Failed to download instrument master: {e}", exc_info=True)
            return False

    def save_to_file(self, filename: str = "nifty50_tokens.json") -> bool:
        """Save instrument master to JSON file.

        Args:
            filename: Name of file to save (default: nifty50_tokens.json)

        Returns:
            True if save successful, False otherwise

        Requirements: 23.2, 23.3

        """
        try:
            filepath = self.data_dir / filename

            # Prepare data for JSON serialization
            data = {
                "last_updated": self.last_updated.isoformat() if self.last_updated else None,
                "instruments": list(self.instruments.values()),
            }

            # Write to file with pretty formatting
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved instrument master to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to save instrument master: {e}", exc_info=True)
            return False

    def load_from_file(self, filename: str = "nifty50_tokens.json") -> bool:
        """Load instrument master from JSON file.

        Args:
            filename: Name of file to load (default: nifty50_tokens.json)

        Returns:
            True if load successful, False otherwise

        Requirements: 23.3

        """
        try:
            filepath = self.data_dir / filename

            if not filepath.exists():
                logger.warning(f"Instrument master file not found: {filepath}")
                return False

            with open(filepath) as f:
                data = json.load(f)

            # Load instruments into memory
            instruments = data.get("instruments", [])
            self.instruments = {inst["symbol"]: inst for inst in instruments}

            # Parse last updated timestamp
            last_updated_str = data.get("last_updated")
            if last_updated_str:
                self.last_updated = datetime.fromisoformat(last_updated_str)

            logger.info(f"Loaded {len(self.instruments)} instruments from {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to load instrument master: {e}", exc_info=True)
            return False

    def get_instrument(self, symbol: str) -> dict | None:
        """Get instrument details for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Instrument dictionary or None if not found

        """
        return self.instruments.get(symbol)

    def get_token(self, symbol: str) -> int | None:
        """Get exchange token for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Exchange token or None if not found

        """
        inst = self.get_instrument(symbol)
        return inst.get("token") if inst else None

    def validate_symbols(self, symbols: list[str]) -> tuple[list[str], list[str]]:
        """Validate that symbols exist in instrument master.

        Args:
            symbols: List of symbols to validate

        Returns:
            Tuple of (valid_symbols, invalid_symbols)

        Requirements: 23.4

        """
        valid = []
        invalid = []

        for symbol in symbols:
            if symbol in self.instruments:
                valid.append(symbol)
            else:
                invalid.append(symbol)
                logger.warning(f"Symbol not found in instrument master: {symbol}")

        return valid, invalid

    def get_all_symbols(self) -> list[str]:
        """Get list of all available symbols.

        Returns:
            List of symbol strings

        """
        return list(self.instruments.keys())

    def get_instruments_by_exchange(self, exchange: str) -> list[dict]:
        """Get all instruments for a specific exchange.

        Args:
            exchange: Exchange name (e.g., "NSE", "BSE")

        Returns:
            List of instrument dictionaries

        """
        return [inst for inst in self.instruments.values() if inst.get("exchange") == exchange]
