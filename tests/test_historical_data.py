"""Unit tests for HistoricalDataManager.

Covers:
- Daily data download (yfinance)
- Intraday data download (broker API)
- DuckDB storage and retrieval
- Parquet storage
- Gap detection and backfill
- Scheduled daily update
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd

from src.data.historical_data import HistoricalDataManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_manager(tmp_path: Path) -> MagicMock:
    """Create a real DuckDB-backed db_manager mock."""
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)
    mgr = MagicMock()
    mgr.connect_duckdb.return_value = conn
    mgr._conn = conn  # keep reference for cleanup
    return mgr


def _make_config(symbols=None):
    cfg = MagicMock()
    cfg.symbols = symbols or ["RELIANCE", "TCS"]
    return cfg


def _sample_daily_df(symbol="RELIANCE", days=5, start=None):
    """Return a small daily OHLCV DataFrame."""
    start = start or date(2024, 1, 2)
    dates = pd.bdate_range(start, periods=days).date.tolist()
    return pd.DataFrame(
        {
            "symbol": [symbol] * days,
            "date": dates,
            "open": [100.0 + i for i in range(days)],
            "high": [105.0 + i for i in range(days)],
            "low": [95.0 + i for i in range(days)],
            "close": [102.0 + i for i in range(days)],
            "volume": [1000 * (i + 1) for i in range(days)],
        }
    )


def _sample_intraday_df(symbol="RELIANCE", rows=10):
    """Return a small intraday OHLCV DataFrame."""
    base = datetime(2024, 1, 2, 9, 15)
    timestamps = [base + timedelta(minutes=i) for i in range(rows)]
    return pd.DataFrame(
        {
            "symbol": [symbol] * rows,
            "timestamp": timestamps,
            "open": [100.0 + i * 0.1 for i in range(rows)],
            "high": [100.5 + i * 0.1 for i in range(rows)],
            "low": [99.5 + i * 0.1 for i in range(rows)],
            "close": [100.2 + i * 0.1 for i in range(rows)],
            "volume": [500 + i * 10 for i in range(rows)],
        }
    )


# ---------------------------------------------------------------------------
# DuckDB table initialisation
# ---------------------------------------------------------------------------


class TestDuckDBInit:
    def test_tables_created(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        conn = mgr.connect_duckdb()
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        assert "historical_daily" in tables
        assert "historical_intraday" in tables

    def test_init_with_no_duckdb(self):
        mgr = MagicMock()
        mgr.connect_duckdb.return_value = None
        # Should not raise
        hdm = HistoricalDataManager(_make_config(), mgr)


# ---------------------------------------------------------------------------
# store_to_duckdb
# ---------------------------------------------------------------------------


class TestStoreToDuckDB:
    def test_store_daily_data(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df(days=3)
        inserted = hdm.store_to_duckdb(df, "historical_daily")
        assert inserted == 3

    def test_store_skips_duplicates(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df(days=3)
        hdm.store_to_duckdb(df, "historical_daily")
        inserted2 = hdm.store_to_duckdb(df, "historical_daily")
        assert inserted2 == 0

    def test_store_empty_dataframe(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
        assert hdm.store_to_duckdb(empty, "historical_daily") == 0

    def test_store_intraday_data(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_intraday_df(rows=5)
        inserted = hdm.store_to_duckdb(df, "historical_intraday")
        assert inserted == 5

    def test_store_no_duckdb(self):
        mgr = MagicMock()
        mgr.connect_duckdb.return_value = None
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df(days=2)
        assert hdm.store_to_duckdb(df, "historical_daily") == 0


# ---------------------------------------------------------------------------
# get_historical_data (query)
# ---------------------------------------------------------------------------


class TestGetHistoricalData:
    def test_query_daily(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df("RELIANCE", days=5)
        hdm.store_to_duckdb(df, "historical_daily")

        result = hdm.get_historical_data("RELIANCE", date(2024, 1, 2), date(2024, 1, 8))
        assert len(result) == 5
        assert list(result.columns) == ["symbol", "date", "open", "high", "low", "close", "volume"]

    def test_query_daily_filters_symbol(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df1 = _sample_daily_df("RELIANCE", days=3)
        df2 = _sample_daily_df("TCS", days=3)
        hdm.store_to_duckdb(pd.concat([df1, df2], ignore_index=True), "historical_daily")

        result = hdm.get_historical_data("TCS", date(2024, 1, 2), date(2024, 1, 8))
        assert all(result["symbol"] == "TCS")

    def test_query_intraday(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_intraday_df("RELIANCE", rows=10)
        hdm.store_to_duckdb(df, "historical_intraday")

        result = hdm.get_historical_data(
            "RELIANCE",
            date(2024, 1, 2),
            date(2024, 1, 2),
            timeframe="intraday",
        )
        assert len(result) == 10

    def test_query_no_duckdb(self):
        mgr = MagicMock()
        mgr.connect_duckdb.return_value = None
        hdm = HistoricalDataManager(_make_config(), mgr)
        result = hdm.get_historical_data("RELIANCE", date(2024, 1, 1), date(2024, 1, 5))
        assert result.empty


# ---------------------------------------------------------------------------
# store_to_parquet
# ---------------------------------------------------------------------------


class TestStoreToParquet:
    def test_partitioned_write(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df(days=3)
        base = str(tmp_path / "parquet_out")
        paths = hdm.store_to_parquet(df, base, partition_by="date")
        assert len(paths) == 3
        for p in paths:
            assert Path(p).exists()
            assert (Path(p) / "data.parquet").exists()

    def test_empty_dataframe(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
        paths = hdm.store_to_parquet(empty, str(tmp_path / "empty"))
        assert paths == []

    def test_fallback_no_partition_column(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        base = str(tmp_path / "no_part")
        paths = hdm.store_to_parquet(df, base, partition_by="missing_col")
        assert len(paths) == 1
        assert paths[0].endswith("data.parquet")


# ---------------------------------------------------------------------------
# detect_missing_dates
# ---------------------------------------------------------------------------


class TestDetectMissingDates:
    def test_all_missing(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        missing = hdm.detect_missing_dates("RELIANCE", date(2024, 1, 2), date(2024, 1, 5))
        # 2 Jan (Tue) – 5 Jan (Fri) = 4 business days
        assert len(missing) == 4

    def test_some_present(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        # Store 2 of 4 days
        df = _sample_daily_df("RELIANCE", days=2, start=date(2024, 1, 2))
        hdm.store_to_duckdb(df, "historical_daily")
        missing = hdm.detect_missing_dates("RELIANCE", date(2024, 1, 2), date(2024, 1, 5))
        assert len(missing) == 2

    def test_none_missing(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        df = _sample_daily_df("RELIANCE", days=4, start=date(2024, 1, 2))
        hdm.store_to_duckdb(df, "historical_daily")
        missing = hdm.detect_missing_dates("RELIANCE", date(2024, 1, 2), date(2024, 1, 5))
        assert missing == []

    def test_no_duckdb(self):
        mgr = MagicMock()
        mgr.connect_duckdb.return_value = None
        hdm = HistoricalDataManager(_make_config(), mgr)
        missing = hdm.detect_missing_dates("RELIANCE", date(2024, 1, 2), date(2024, 1, 5))
        # Should return all business days
        assert len(missing) == 4


# ---------------------------------------------------------------------------
# backfill_missing
# ---------------------------------------------------------------------------


class TestBackfillMissing:
    @patch.object(HistoricalDataManager, "download_daily_data")
    def test_backfill_downloads_and_stores(self, mock_dl, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        missing = [date(2024, 1, 4), date(2024, 1, 5)]
        mock_dl.return_value = _sample_daily_df("RELIANCE", days=2, start=date(2024, 1, 4))
        total = hdm.backfill_missing("RELIANCE", missing)
        assert total == 2
        mock_dl.assert_called_once()

    def test_backfill_empty_list(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        assert hdm.backfill_missing("RELIANCE", []) == 0

    @patch.object(HistoricalDataManager, "download_daily_data")
    def test_backfill_handles_no_data(self, mock_dl, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        mock_dl.return_value = pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume"],
        )
        total = hdm.backfill_missing("RELIANCE", [date(2024, 1, 4)])
        assert total == 0


# ---------------------------------------------------------------------------
# download_daily_data (mocked yfinance)
# ---------------------------------------------------------------------------


class TestDownloadDailyData:
    @patch("src.data.historical_data.yf")
    def test_downloads_for_symbols(self, mock_yf, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)

        mock_ticker = MagicMock()
        hist_df = pd.DataFrame(
            {
                "Date": pd.date_range("2024-01-02", periods=3, freq="B"),
                "Open": [100, 101, 102],
                "High": [105, 106, 107],
                "Low": [95, 96, 97],
                "Close": [102, 103, 104],
                "Volume": [1000, 2000, 3000],
            }
        ).set_index("Date")
        # yfinance returns DatetimeIndex-indexed DF
        hist_df.index.name = "Date"
        mock_ticker.history.return_value = hist_df
        mock_yf.Ticker.return_value = mock_ticker

        result = hdm.download_daily_data(["RELIANCE"], date(2024, 1, 2), date(2024, 1, 4))
        assert len(result) == 3
        assert "symbol" in result.columns
        assert result["symbol"].iloc[0] == "RELIANCE"

    @patch("src.data.historical_data.yf")
    def test_handles_empty_response(self, mock_yf, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        result = hdm.download_daily_data(["RELIANCE"], date(2024, 1, 2), date(2024, 1, 4))
        assert result.empty

    @patch("src.data.historical_data.yf")
    def test_handles_exception(self, mock_yf, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        mock_yf.Ticker.side_effect = Exception("API error")

        result = hdm.download_daily_data(["RELIANCE"], date(2024, 1, 2), date(2024, 1, 4))
        assert result.empty


# ---------------------------------------------------------------------------
# download_intraday_data
# ---------------------------------------------------------------------------


class TestDownloadIntradayData:
    def test_no_broker(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr, broker=None)
        result = hdm.download_intraday_data(["RELIANCE"])
        assert result.empty

    def test_broker_returns_dataframe(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        broker = MagicMock()
        broker.get_historical_data.return_value = _sample_intraday_df("RELIANCE", rows=5)
        hdm = HistoricalDataManager(_make_config(), mgr, broker=broker)
        result = hdm.download_intraday_data(["RELIANCE"], days=5)
        assert len(result) == 5

    def test_broker_returns_none(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        broker = MagicMock()
        broker.get_historical_data.return_value = None
        hdm = HistoricalDataManager(_make_config(), mgr, broker=broker)
        result = hdm.download_intraday_data(["RELIANCE"])
        assert result.empty

    def test_broker_raises_exception(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        broker = MagicMock()
        broker.get_historical_data.side_effect = Exception("Broker error")
        hdm = HistoricalDataManager(_make_config(), mgr, broker=broker)
        result = hdm.download_intraday_data(["RELIANCE"])
        assert result.empty


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TestScheduler:
    def test_schedule_starts_thread(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        hdm.schedule_daily_update()
        assert hdm._scheduler_running is True
        assert hdm._scheduler_thread is not None
        assert hdm._scheduler_thread.is_alive()
        hdm.stop_scheduler()

    def test_stop_scheduler(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        hdm.schedule_daily_update()
        hdm.stop_scheduler()
        assert hdm._scheduler_running is False

    def test_double_schedule_is_noop(self, tmp_path):
        mgr = _make_db_manager(tmp_path)
        hdm = HistoricalDataManager(_make_config(), mgr)
        hdm.schedule_daily_update()
        thread1 = hdm._scheduler_thread
        hdm.schedule_daily_update()
        assert hdm._scheduler_thread is thread1
        hdm.stop_scheduler()


# ---------------------------------------------------------------------------
# _contiguous_ranges helper
# ---------------------------------------------------------------------------


class TestContiguousRanges:
    def test_single_date(self):
        result = HistoricalDataManager._contiguous_ranges([date(2024, 1, 2)])
        assert result == [(date(2024, 1, 2), date(2024, 1, 2))]

    def test_contiguous_weekdays(self):
        dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
        result = HistoricalDataManager._contiguous_ranges(dates)
        assert len(result) == 1

    def test_gap_splits_ranges(self):
        dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 15), date(2024, 1, 16)]
        result = HistoricalDataManager._contiguous_ranges(dates)
        assert len(result) == 2

    def test_empty(self):
        assert HistoricalDataManager._contiguous_ranges([]) == []
