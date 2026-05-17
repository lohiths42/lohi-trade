#!/usr/bin/env python3
"""
Generate ticker_map.json with 500+ company name to ticker mappings.

This script creates a comprehensive ticker mapping file for entity resolution
in news articles. It includes common name variations for major Indian companies.

Requirements: 6.2, 6.6
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.ticker_mapper import TickerMapper
from src.utils.logger import get_logger

logger = get_logger("GenerateTickerMap")


def main():
    """Generate ticker mapping file."""
    logger.info("Generating ticker_map.json...")

    # Create ticker mapper
    mapper = TickerMapper(data_dir="data", fuzzy_threshold=0.85)

    # Create default mapping with 500+ entries
    mapper.create_default_mapping()

    # Save to file
    if mapper.save_to_file("ticker_map.json"):
        logger.info(
            f"Successfully generated ticker_map.json with {mapper.get_mapping_count()} mappings"
        )
        logger.info(f"Unique tickers: {len(mapper.get_all_tickers())}")
        return 0
    else:
        logger.error("Failed to generate ticker_map.json")
        return 1


if __name__ == "__main__":
    sys.exit(main())
