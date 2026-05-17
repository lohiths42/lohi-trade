"""Property-based tests for HistoricalDataManager.

Property 75: Historical Data Storage
  For any downloaded data, it should be queryable from DuckDB with correct OHLCV values.

Property 76: Historical Data Backfill
  For any missing date range, the backfill should download and store data for all missing dates.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.data.historical_data import HistoricalDataManager

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

reasonable_float = st.floats(
    min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False
)
reasonable_volume = st.integers(min_value=1, max_value=10**9)


@st.composite
def ohlcv_row(draw):
    """Generate a single valid OHLCV row."""
    low = draw(st.floats(min_value=1.0, max_value=50_000.0, allow_nan=False, allow_infinity=False))
    high = draw(
        st.floats(min_value=low, max_value=low + 5000.0, allow_nan=False, allow_infinity=False)
    )
    open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
    volume = draw(reasonable_volume)
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


@st.composite
def daily_dataset(draw):
    """Generate a DataFrame of daily OHLCV data for a single symbol."""
    symbol = draw(st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFC", "ICICI"]))
    n_rows = draw(st.integers(min_value=1, max_value=20))
    start = draw(st.dates(min_value=date(2022, 1, 3), max_value=date(2024, 12, 1)))
    dates = pd.bdate_range(start, periods=n_rows).date.tolist()
    rows = [draw(ohlcv_row()) for _ in range(n_rows)]

    df = pd.DataFrame(rows)
    df["symbol"] = symbol
    df["date"] = dates
    df = df[["symbol", "date", "open", "high", "low", "close", "volume"]]
    return df


@st.composite
def date_range_pair(draw):
    """Generate a valid (start_date, end_date) pair with start <= end."""
    d1 = draw(st.dates(min_value=date(2022, 1, 3), max_value=date(2024, 11, 1)))
    gap = draw(st.integers(min_value=1, max_value=60))
    d2 = d1 + timedelta(days=gap)
    return d1, d2


# ---------------------------------------------------------------------------
# Helpers – use tempfile instead of tmp_path to avoid fixture issues
# ---------------------------------------------------------------------------


def _fresh_db():
    """Create a fresh in-memory DuckDB connection wrapped in a mock db_manager."""
    conn = duckdb.connect(":memory:")
    mgr = MagicMock()
    mgr.connect_duckdb.return_value = conn
    return mgr


def _make_config(symbols=None):
    cfg = MagicMock()
    cfg.symbols = symbols or ["RELIANCE"]
    return cfg


# ---------------------------------------------------------------------------
# Property 75: Historical Data Storage
# ---------------------------------------------------------------------------


class TestProperty75HistoricalDataStorage:
    """Property 75: For any downloaded data stored in DuckDB, querying it back
    must return the exact same OHLCV values.
    """

    @given(data=daily_dataset())
    @settings(max_examples=50, deadline=None)
    def test_stored_data_is_queryable_with_correct_values(self, data):
        mgr = _fresh_db()
        hdm = HistoricalDataManager(_make_config(), mgr)

        hdm.store_to_duckdb(data, "historical_daily")

        symbol = data["symbol"].iloc[0]
        start = data["date"].min()
        end = data["date"].max()

        result = hdm.get_historical_data(symbol, start, end, timeframe="daily")

        # Every stored row must be present
        assert len(result) == len(data)

        # OHLCV values must match exactly
        result_sorted = result.sort_values("date").reset_index(drop=True)
        data_sorted = data.sort_values("date").reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            for i in range(len(data_sorted)):
                assert abs(result_sorted[col].iloc[i] - data_sorted[col].iloc[i]) < 1e-6, (
                    f"Mismatch in {col} at row {i}: "
                    f"stored={data_sorted[col].iloc[i]}, queried={result_sorted[col].iloc[i]}"
                )

    @given(data=daily_dataset())
    @settings(max_examples=25, deadline=None)
    def test_duplicate_insert_preserves_count(self, data):
        mgr = _fresh_db()
        hdm = HistoricalDataManager(_make_config(), mgr)

        hdm.store_to_duckdb(data, "historical_daily")
        hdm.store_to_duckdb(data, "historical_daily")

        symbol = data["symbol"].iloc[0]
        start = data["date"].min()
        end = data["date"].max()
        result = hdm.get_historical_data(symbol, start, end, timeframe="daily")
        assert len(result) == len(data)


# ---------------------------------------------------------------------------
# Property 76: Historical Data Backfill
# ---------------------------------------------------------------------------


class TestProperty76HistoricalDataBackfill:
    """Property 76: For any missing date range, the backfill should download
    and store data for all missing dates.
    """

    @given(date_pair=date_range_pair())
    @settings(max_examples=50, deadline=None)
    def test_backfill_fills_all_missing_dates(self, date_pair):
        start, end = date_pair
        mgr = _fresh_db()
        hdm = HistoricalDataManager(_make_config(), mgr)

        # Detect missing dates before backfill
        missing_before = hdm.detect_missing_dates("RELIANCE", start, end)
        assume(len(missing_before) > 0)

        # Mock download to return data for all missing dates
        def fake_download(symbols, s, e):
            dates = pd.bdate_range(s, e).date.tolist()
            n = len(dates)
            if n == 0:
                return pd.DataFrame(
                    columns=["symbol", "date", "open", "high", "low", "close", "volume"]
                )
            return pd.DataFrame(
                {
                    "symbol": ["RELIANCE"] * n,
                    "date": dates,
                    "open": [100.0] * n,
                    "high": [105.0] * n,
                    "low": [95.0] * n,
                    "close": [102.0] * n,
                    "volume": [1000] * n,
                }
            )

        with patch.object(hdm, "download_daily_data", side_effect=fake_download):
            hdm.backfill_missing("RELIANCE", missing_before)

        # After backfill, no dates should be missing
        missing_after = hdm.detect_missing_dates("RELIANCE", start, end)
        assert (
            len(missing_after) == 0
        ), f"Still missing {len(missing_after)} dates after backfill: {missing_after[:5]}"

    @given(date_pair=date_range_pair())
    @settings(max_examples=25, deadline=None)
    def test_backfill_is_idempotent(self, date_pair):
        start, end = date_pair
        mgr = _fresh_db()
        hdm = HistoricalDataManager(_make_config(), mgr)

        missing = hdm.detect_missing_dates("RELIANCE", start, end)
        assume(len(missing) > 0)

        def fake_download(symbols, s, e):
            dates = pd.bdate_range(s, e).date.tolist()
            n = len(dates)
            if n == 0:
                return pd.DataFrame(
                    columns=["symbol", "date", "open", "high", "low", "close", "volume"]
                )
            return pd.DataFrame(
                {
                    "symbol": ["RELIANCE"] * n,
                    "date": dates,
                    "open": [100.0] * n,
                    "high": [105.0] * n,
                    "low": [95.0] * n,
                    "close": [102.0] * n,
                    "volume": [1000] * n,
                }
            )

        with patch.object(hdm, "download_daily_data", side_effect=fake_download):
            hdm.backfill_missing("RELIANCE", missing)
            # Run again – should be a no-op
            remaining = hdm.detect_missing_dates("RELIANCE", start, end)
            second_result = hdm.backfill_missing("RELIANCE", remaining)

        assert second_result == 0

    @given(data=daily_dataset())
    @settings(max_examples=25, deadline=None)
    def test_partial_data_triggers_correct_backfill(self, data):
        """Store partial data, then backfill should only fill the gaps."""
        mgr = _fresh_db()
        hdm = HistoricalDataManager(_make_config(), mgr)

        symbol = data["symbol"].iloc[0]
        # Store only first half
        half = len(data) // 2
        assume(half >= 1)
        hdm.store_to_duckdb(data.iloc[:half], "historical_daily")

        start = data["date"].min()
        end = data["date"].max()
        missing = hdm.detect_missing_dates(symbol, start, end)

        # Missing should be the dates not in the first half
        stored_dates = set(data["date"].iloc[:half].tolist())
        all_bdays = set(pd.bdate_range(start, end).date.tolist())
        expected_missing = sorted(all_bdays - stored_dates)
        assert missing == expected_missing
