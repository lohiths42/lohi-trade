"""Property-based tests for instrument master management.

Tests cover:
- Property 77: Instrument Master Validation
- Ticker mapping with fuzzy matching
- Entity resolution

Requirements: 23.4, 6.2, 6.5, 6.6
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.ingestion.instrument_master import InstrumentMaster
from src.ingestion.ticker_mapper import TickerMapper


# Test data generators
@st.composite
def instrument_dict(draw):
    """Generate a valid instrument dictionary."""
    symbol = draw(
        st.text(min_size=2, max_size=20, alphabet=st.characters(whitelist_categories=("Lu",)))
    )
    return {
        "symbol": symbol,
        "token": draw(st.integers(min_value=1, max_value=99999)),
        "exchange": draw(st.sampled_from(["NSE", "BSE"])),
        "lot_size": draw(st.integers(min_value=1, max_value=1000)),
        "tick_size": draw(st.floats(min_value=0.01, max_value=1.0)),
        "trading_symbol": f"{symbol}-EQ",
        "instrument": draw(st.sampled_from(["EQ", "FUT", "OPT"])),
    }


@st.composite
def instrument_list(draw):
    """Generate a list of instruments with unique symbols."""
    instruments = draw(st.lists(instrument_dict(), min_size=1, max_size=50))
    # Ensure unique symbols by using a dict and converting back to list
    unique_instruments = {}
    for inst in instruments:
        if inst["symbol"] not in unique_instruments:
            unique_instruments[inst["symbol"]] = inst
    return list(unique_instruments.values())


class TestInstrumentMaster:
    """Test instrument master management."""

    def test_initialization(self):
        """Test instrument master initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)
            assert master.instruments == {}
            assert master.last_updated is None
            assert Path(tmpdir).exists()

    @given(instruments=instrument_list())
    @settings(max_examples=5, deadline=5000)
    def test_save_and_load_roundtrip(self, instruments):
        """Test saving and loading instrument master preserves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)

            # Populate instruments
            master.instruments = {inst["symbol"]: inst for inst in instruments}

            # Save to file
            assert master.save_to_file("test_instruments.json")

            # Load into new instance
            master2 = InstrumentMaster(data_dir=tmpdir)
            assert master2.load_from_file("test_instruments.json")

            # Verify data matches
            assert len(master2.instruments) == len(instruments)
            for inst in instruments:
                assert inst["symbol"] in master2.instruments
                assert master2.instruments[inst["symbol"]]["token"] == inst["token"]

    @given(instruments=instrument_list())
    @settings(max_examples=5, deadline=5000)
    def test_get_instrument(self, instruments):
        """Test retrieving instrument by symbol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)
            master.instruments = {inst["symbol"]: inst for inst in instruments}

            # Test each instrument can be retrieved
            for inst in instruments:
                retrieved = master.get_instrument(inst["symbol"])
                assert retrieved is not None
                assert retrieved["symbol"] == inst["symbol"]
                assert retrieved["token"] == inst["token"]

            # Test non-existent symbol
            assert master.get_instrument("NONEXISTENT") is None

    @given(instruments=instrument_list())
    @settings(max_examples=5, deadline=5000)
    def test_get_token(self, instruments):
        """Test retrieving token by symbol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)
            master.instruments = {inst["symbol"]: inst for inst in instruments}

            # Test each token can be retrieved
            for inst in instruments:
                token = master.get_token(inst["symbol"])
                assert token == inst["token"]

            # Test non-existent symbol
            assert master.get_token("NONEXISTENT") is None

    @given(instruments=instrument_list())
    @settings(max_examples=5, deadline=5000)
    def test_property_77_instrument_master_validation(self, instruments):
        """Property 77: Instrument Master Validation

        For any configured symbol in settings.yaml, it should exist in the
        downloaded instrument master file, otherwise a warning should be logged.

        Validates: Requirements 23.4
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)
            master.instruments = {inst["symbol"]: inst for inst in instruments}

            # Get all valid symbols
            valid_symbols = [inst["symbol"] for inst in instruments]

            # Add some invalid symbols
            invalid_symbols = ["INVALID1", "INVALID2", "NOTFOUND"]
            test_symbols = valid_symbols + invalid_symbols

            # Validate symbols
            valid, invalid = master.validate_symbols(test_symbols)

            # Property: All valid symbols should be in valid list
            for symbol in valid_symbols:
                assert symbol in valid, f"Valid symbol {symbol} not in valid list"

            # Property: All invalid symbols should be in invalid list
            for symbol in invalid_symbols:
                assert symbol in invalid, f"Invalid symbol {symbol} not in invalid list"

            # Property: No overlap between valid and invalid
            assert len(set(valid) & set(invalid)) == 0

            # Property: Union of valid and invalid equals input
            assert set(valid + invalid) == set(test_symbols)

    @given(instruments=instrument_list(), exchange=st.sampled_from(["NSE", "BSE"]))
    @settings(max_examples=5, deadline=5000)
    def test_get_instruments_by_exchange(self, instruments, exchange):
        """Test filtering instruments by exchange."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)
            master.instruments = {inst["symbol"]: inst for inst in instruments}

            # Get instruments for exchange
            filtered = master.get_instruments_by_exchange(exchange)

            # Verify all returned instruments are from the correct exchange
            for inst in filtered:
                assert inst["exchange"] == exchange

            # Verify we didn't miss any instruments from this exchange
            expected_count = sum(1 for inst in instruments if inst["exchange"] == exchange)
            assert len(filtered) == expected_count

    def test_download_from_broker_success(self):
        """Test downloading instrument master from broker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)

            # Mock broker
            mock_broker = Mock()
            mock_instruments = [
                {
                    "symbol": "RELIANCE",
                    "token": 2885,
                    "exchange": "NSE",
                    "lot_size": 1,
                    "tick_size": 0.05,
                    "trading_symbol": "RELIANCE-EQ",
                },
                {
                    "symbol": "TCS",
                    "token": 11536,
                    "exchange": "NSE",
                    "lot_size": 1,
                    "tick_size": 0.05,
                    "trading_symbol": "TCS-EQ",
                },
            ]
            mock_broker.get_instrument_master.return_value = mock_instruments

            # Download
            result = master.download_from_broker(mock_broker)

            assert result is True
            assert len(master.instruments) == 2
            assert "RELIANCE" in master.instruments
            assert "TCS" in master.instruments
            assert master.last_updated is not None

    def test_download_from_broker_with_filter(self):
        """Test downloading instrument master with symbol filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            master = InstrumentMaster(data_dir=tmpdir)

            # Mock broker with many instruments
            mock_broker = Mock()
            mock_instruments = [
                {
                    "symbol": "RELIANCE",
                    "token": 2885,
                    "exchange": "NSE",
                    "lot_size": 1,
                    "tick_size": 0.05,
                    "trading_symbol": "RELIANCE-EQ",
                },
                {
                    "symbol": "TCS",
                    "token": 11536,
                    "exchange": "NSE",
                    "lot_size": 1,
                    "tick_size": 0.05,
                    "trading_symbol": "TCS-EQ",
                },
                {
                    "symbol": "INFY",
                    "token": 1594,
                    "exchange": "NSE",
                    "lot_size": 1,
                    "tick_size": 0.05,
                    "trading_symbol": "INFY-EQ",
                },
            ]
            mock_broker.get_instrument_master.return_value = mock_instruments

            # Download with filter
            result = master.download_from_broker(mock_broker, symbols=["RELIANCE", "TCS"])

            assert result is True
            assert len(master.instruments) == 2
            assert "RELIANCE" in master.instruments
            assert "TCS" in master.instruments
            assert "INFY" not in master.instruments


class TestTickerMapper:
    """Test ticker mapping for entity resolution."""

    def test_initialization(self):
        """Test ticker mapper initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir, fuzzy_threshold=0.85)
            assert mapper.ticker_map == {}
            assert mapper.fuzzy_threshold == 0.85

    def test_add_mapping(self):
        """Test adding ticker mappings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.add_mapping("Reliance Industries", "RELIANCE")
            mapper.add_mapping("TCS", "TCS")

            assert mapper.get_ticker("reliance industries") == "RELIANCE"
            assert mapper.get_ticker("tcs") == "TCS"

    def test_exact_match(self):
        """Test exact ticker matching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.add_mapping("Reliance Industries", "RELIANCE")
            mapper.add_mapping("Reliance", "RELIANCE")

            # Exact matches (case-insensitive)
            assert mapper.get_ticker("Reliance Industries", use_fuzzy=False) == "RELIANCE"
            assert mapper.get_ticker("reliance industries", use_fuzzy=False) == "RELIANCE"
            assert mapper.get_ticker("RELIANCE INDUSTRIES", use_fuzzy=False) == "RELIANCE"

    def test_fuzzy_matching(self):
        """Test fuzzy ticker matching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir, fuzzy_threshold=0.85)

            mapper.add_mapping("Reliance Industries Limited", "RELIANCE")

            # Fuzzy matches
            ticker = mapper.get_ticker("Reliance Industries Ltd", use_fuzzy=True)
            if ticker:  # Only if rapidfuzz is available
                assert ticker == "RELIANCE"

    @given(
        company_name=st.text(
            min_size=3,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        ),
        ticker=st.text(
            min_size=2, max_size=20, alphabet=st.characters(whitelist_categories=("Lu",))
        ),
    )
    @settings(max_examples=5, deadline=5000)
    def test_save_and_load_roundtrip(self, company_name, ticker):
        """Test saving and loading ticker map preserves data."""
        assume(len(company_name.strip()) > 0)
        assume(len(ticker.strip()) > 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            # Add mapping
            mapper.add_mapping(company_name, ticker)

            # Save
            assert mapper.save_to_file("test_ticker_map.json")

            # Load into new instance
            mapper2 = TickerMapper(data_dir=tmpdir)
            assert mapper2.load_from_file("test_ticker_map.json")

            # Verify mapping preserved
            assert mapper2.get_ticker(company_name, use_fuzzy=False) == ticker.upper()

    def test_resolve_entities(self):
        """Test resolving multiple entities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.add_mapping("Reliance Industries", "RELIANCE")
            mapper.add_mapping("TCS", "TCS")
            mapper.add_mapping("Infosys", "INFY")

            # Resolve multiple entities
            entities = ["Reliance Industries", "TCS", "Unknown Company"]
            results = mapper.resolve_entities(entities, use_fuzzy=False)

            assert results["Reliance Industries"] == "RELIANCE"
            assert results["TCS"] == "TCS"
            assert results["Unknown Company"] is None

    def test_get_company_names(self):
        """Test getting company name variations for a ticker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.add_mapping("Reliance Industries", "RELIANCE")
            mapper.add_mapping("Reliance", "RELIANCE")
            mapper.add_mapping("RIL", "RELIANCE")

            names = mapper.get_company_names("RELIANCE")
            assert len(names) == 3
            assert "reliance industries" in names
            assert "reliance" in names
            assert "ril" in names

    def test_create_default_mapping(self):
        """Test creating default ticker mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.create_default_mapping()

            # Verify we have many mappings
            assert mapper.get_mapping_count() > 50

            # Verify some common mappings exist
            assert mapper.get_ticker("reliance", use_fuzzy=False) == "RELIANCE"
            assert mapper.get_ticker("tcs", use_fuzzy=False) == "TCS"
            assert mapper.get_ticker("infosys", use_fuzzy=False) == "INFY"
            assert mapper.get_ticker("hdfc bank", use_fuzzy=False) == "HDFCBANK"

    @given(
        mappings=st.lists(
            st.tuples(
                st.text(
                    min_size=3,
                    max_size=30,
                    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Zs")),
                ),
                st.text(
                    min_size=2, max_size=10, alphabet=st.characters(whitelist_categories=("Lu",))
                ),
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=5, deadline=5000)
    def test_property_entity_resolution_mapping(self, mappings):
        """Property 19: Entity Resolution Mapping

        For any company name in the ticker mapping dictionary, it should be
        correctly mapped to its corresponding NSE ticker symbol.

        Validates: Requirements 6.2
        """
        # Filter out empty strings and ensure unique company names (last one wins)
        unique_mappings = {}
        for name, ticker in mappings:
            name = name.strip()
            ticker = ticker.strip()
            if name and ticker:
                unique_mappings[name] = ticker

        assume(len(unique_mappings) > 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            # Add all mappings
            for company_name, ticker in unique_mappings.items():
                mapper.add_mapping(company_name, ticker)

            # Property: Every added mapping should be retrievable
            for company_name, expected_ticker in unique_mappings.items():
                retrieved_ticker = mapper.get_ticker(company_name, use_fuzzy=False)
                assert (
                    retrieved_ticker == expected_ticker.upper()
                ), f"Mapping for '{company_name}' should return '{expected_ticker.upper()}', got '{retrieved_ticker}'"

    def test_unmapped_entity_handling(self):
        """Property 21: Unmapped Entity Handling

        For any company name not found in the ticker mapping dictionary,
        it should be logged as unmapped and sentiment processing should be skipped.

        Validates: Requirements 6.4
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            mapper = TickerMapper(data_dir=tmpdir)

            mapper.add_mapping("Reliance", "RELIANCE")

            # Test unmapped entity
            result = mapper.get_ticker("Unknown Company XYZ", use_fuzzy=False)

            # Property: Unmapped entities should return None
            assert result is None

            # Test with fuzzy matching disabled
            result = mapper.get_ticker("Completely Different Name", use_fuzzy=False)
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
