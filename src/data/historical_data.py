"""
Historical data management for LOHI-TRADE system.

This module provides:
- Download historical daily data for Nifty 50 using yfinance
- Download historical intraday data (1m candles) using broker API
- Store data in DuckDB for efficient analytical queries
- Store data in Parquet format partitioned by date
- Detect and backfill missing date ranges
- Schedule daily updates at 6:00 PM IST

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7
"""

import logging
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False


logger = logging.getLogger(__name__)


# NSE symbol suffix for yfinance
NSE_SUFFIX = ".NS"

# Minimum data retention
MIN_DAILY_YEARS = 2
MIN_INTRADAY_DAYS = 30


class HistoricalDataManager:
    """
    Manages historical OHLCV data download, storage, and retrieval.

    Supports:
    - Daily data via yfinance (2+ years)
    - Intraday 1m data via broker API (30 days)
    - DuckDB storage for analytical queries
    - Parquet storage partitioned by date
    - Gap detection and backfill
    - Scheduled daily updates at 6:00 PM IST
    """

    def __init__(
        self,
        config: Any,
        db_manager: Any,
        broker: Any = None,
    ):
        """
        Initialize HistoricalDataManager.

        Args:
            config: Application configuration object.
            db_manager: DatabaseConnectionManager with connect_duckdb().
            broker: Optional BrokerInterface for intraday data.
        """
        self.config = config
        self.db_manager = db_manager
        self.broker = broker
        self._scheduler_thread: Optional[threading.Thread] = None
        self._scheduler_running = False

        # Ensure DuckDB tables exist
        self._init_duckdb_tables()

    # ------------------------------------------------------------------
    # DuckDB table initialisation
    # ------------------------------------------------------------------

    def _init_duckdb_tables(self) -> None:
        """Create historical_daily and historical_intraday tables if missing."""
        conn = self.db_manager.connect_duckdb()
        if conn is None:
            return

        conn.execute("""
            CREATE TABLE IF NOT EXISTS historical_daily (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (symbol, date)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS historical_intraday (
                symbol VARCHAR,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (symbol, timestamp)
            )
        """)

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def download_daily_data(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Download daily OHLCV data for *symbols* using yfinance.

        Args:
            symbols: List of NSE symbols (e.g. ["RELIANCE", "TCS"]).
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            DataFrame with columns [symbol, date, open, high, low, close, volume].
        """
        if not YFINANCE_AVAILABLE:
            logger.warning("yfinance not available – returning empty DataFrame")
            return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])

        all_frames: List[pd.DataFrame] = []

        for symbol in symbols:
            try:
                yf_symbol = f"{symbol}{NSE_SUFFIX}"
                ticker = yf.Ticker(yf_symbol)
                df = ticker.history(
                    start=start_date.isoformat(),
                    end=(end_date + timedelta(days=1)).isoformat(),
                    interval="1d",
                    auto_adjust=True,
                )
                if df.empty:
                    logger.warning(f"No daily data for {symbol}")
                    continue

                df = df.reset_index()
                df = df.rename(columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                })
                df["symbol"] = symbol
                df["date"] = pd.to_datetime(df["date"]).dt.date
                df = df[["symbol", "date", "open", "high", "low", "close", "volume"]]
                all_frames.append(df)
                logger.info(f"Downloaded {len(df)} daily rows for {symbol}")
            except Exception as exc:
                logger.error(f"Failed to download daily data for {symbol}: {exc}")

        if not all_frames:
            return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])

        return pd.concat(all_frames, ignore_index=True)

    def download_intraday_data(
        self,
        symbols: List[str],
        days: int = 30,
    ) -> pd.DataFrame:
        """
        Download 1-minute intraday candles via the broker API.

        Args:
            symbols: List of NSE symbols.
            days: Number of past days to fetch (default 30).

        Returns:
            DataFrame with columns [symbol, timestamp, open, high, low, close, volume].
        """
        if self.broker is None:
            logger.warning("No broker configured – cannot download intraday data")
            return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

        all_frames: List[pd.DataFrame] = []
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        for symbol in symbols:
            try:
                # Broker is expected to expose get_historical_data(symbol, start, end, interval)
                data = self.broker.get_historical_data(
                    symbol=symbol,
                    start=start_dt,
                    end=end_dt,
                    interval="1m",
                )
                if data is None or (isinstance(data, pd.DataFrame) and data.empty):
                    logger.warning(f"No intraday data for {symbol}")
                    continue

                if isinstance(data, list):
                    data = pd.DataFrame(data)

                data["symbol"] = symbol
                # Normalise column names
                rename_map = {
                    "Timestamp": "timestamp",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
                data = data.rename(columns={k: v for k, v in rename_map.items() if k in data.columns})
                data = data[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]
                all_frames.append(data)
                logger.info(f"Downloaded {len(data)} intraday rows for {symbol}")
            except Exception as exc:
                logger.error(f"Failed to download intraday data for {symbol}: {exc}")

        if not all_frames:
            return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

        return pd.concat(all_frames, ignore_index=True)

    # ------------------------------------------------------------------
    # Storage – DuckDB
    # ------------------------------------------------------------------

    def store_to_duckdb(self, data: pd.DataFrame, table_name: str) -> int:
        """
        Insert *data* into a DuckDB table, skipping duplicates.

        Args:
            data: DataFrame whose columns match the target table.
            table_name: 'historical_daily' or 'historical_intraday'.

        Returns:
            Number of rows inserted.
        """
        if data.empty:
            return 0

        conn = self.db_manager.connect_duckdb()
        if conn is None:
            logger.warning("DuckDB not available – skipping store")
            return 0

        before = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        # Use INSERT OR IGNORE semantics via a temp table
        conn.execute("CREATE TEMPORARY TABLE _tmp AS SELECT * FROM data")
        if table_name == "historical_daily":
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT t.* FROM _tmp t
                WHERE NOT EXISTS (
                    SELECT 1 FROM {table_name} h
                    WHERE h.symbol = t.symbol AND h.date = t.date
                )
            """)
        else:
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT t.* FROM _tmp t
                WHERE NOT EXISTS (
                    SELECT 1 FROM {table_name} h
                    WHERE h.symbol = t.symbol AND h.timestamp = t.timestamp
                )
            """)
        conn.execute("DROP TABLE _tmp")

        after = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        inserted = after - before
        logger.info(f"Stored {inserted} rows into {table_name}")
        return inserted

    # ------------------------------------------------------------------
    # Storage – Parquet
    # ------------------------------------------------------------------

    def store_to_parquet(
        self,
        data: pd.DataFrame,
        base_path: str,
        partition_by: str = "date",
    ) -> List[str]:
        """
        Write *data* as Parquet files partitioned by *partition_by* column.

        Args:
            data: DataFrame to persist.
            base_path: Root directory (e.g. "data/historical/daily").
            partition_by: Column name used for partitioning (default "date").

        Returns:
            List of partition directory paths written.
        """
        if data.empty:
            return []

        base = Path(base_path)
        base.mkdir(parents=True, exist_ok=True)

        written_paths: List[str] = []

        if partition_by not in data.columns:
            # Fall back to writing a single file
            out = base / "data.parquet"
            data.to_parquet(str(out), index=False)
            written_paths.append(str(out))
            return written_paths

        # Ensure partition column is string for directory naming
        data = data.copy()
        data["_partition"] = data[partition_by].astype(str)

        for partition_val, group in data.groupby("_partition"):
            part_dir = base / f"{partition_by}={partition_val}"
            part_dir.mkdir(parents=True, exist_ok=True)
            out = part_dir / "data.parquet"
            group.drop(columns=["_partition"]).to_parquet(str(out), index=False)
            written_paths.append(str(part_dir))

        logger.info(f"Wrote {len(written_paths)} partitions to {base_path}")
        return written_paths

    # ------------------------------------------------------------------
    # Gap detection & backfill
    # ------------------------------------------------------------------

    def detect_missing_dates(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """
        Return business days in [start_date, end_date] that have no daily row.

        Args:
            symbol: Trading symbol.
            start_date: Range start (inclusive).
            end_date: Range end (inclusive).

        Returns:
            Sorted list of missing business-day dates.
        """
        conn = self.db_manager.connect_duckdb()
        if conn is None:
            # If no DB, treat all business days as missing
            all_days = pd.bdate_range(start_date, end_date).date.tolist()
            return sorted(all_days)

        rows = conn.execute(
            "SELECT DISTINCT date FROM historical_daily "
            "WHERE symbol = ? AND date BETWEEN ? AND ? ORDER BY date",
            [symbol, start_date, end_date],
        ).fetchall()

        existing = {r[0] for r in rows}
        all_bdays = set(pd.bdate_range(start_date, end_date).date.tolist())
        missing = sorted(all_bdays - existing)
        return missing

    def backfill_missing(
        self,
        symbol: str,
        missing_dates: List[date],
    ) -> int:
        """
        Download and store daily data for each contiguous range in *missing_dates*.

        Args:
            symbol: Trading symbol.
            missing_dates: Sorted list of dates to backfill.

        Returns:
            Total number of rows stored.
        """
        if not missing_dates:
            return 0

        total = 0
        # Group into contiguous ranges to minimise API calls
        ranges = self._contiguous_ranges(sorted(missing_dates))

        for rng_start, rng_end in ranges:
            df = self.download_daily_data([symbol], rng_start, rng_end)
            if not df.empty:
                stored = self.store_to_duckdb(df, "historical_daily")
                total += stored

        logger.info(f"Backfilled {total} rows for {symbol}")
        return total

    @staticmethod
    def _contiguous_ranges(dates: List[date]) -> List[tuple]:
        """Group sorted dates into (start, end) contiguous ranges."""
        if not dates:
            return []
        ranges = []
        start = dates[0]
        prev = dates[0]
        for d in dates[1:]:
            if (d - prev).days > 3:  # allow weekends
                ranges.append((start, prev))
                start = d
            prev = d
        ranges.append((start, prev))
        return ranges

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_historical_data(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str = "daily",
    ) -> pd.DataFrame:
        """
        Query stored historical data from DuckDB.

        Args:
            symbol: Trading symbol.
            start_date: Range start (inclusive).
            end_date: Range end (inclusive).
            timeframe: 'daily' or 'intraday'.

        Returns:
            DataFrame with OHLCV data.
        """
        conn = self.db_manager.connect_duckdb()
        if conn is None:
            return pd.DataFrame()

        if timeframe == "daily":
            df = conn.execute(
                "SELECT * FROM historical_daily "
                "WHERE symbol = ? AND date BETWEEN ? AND ? ORDER BY date",
                [symbol, start_date, end_date],
            ).fetchdf()
        else:
            start_ts = datetime.combine(start_date, datetime.min.time())
            end_ts = datetime.combine(end_date, datetime.max.time())
            df = conn.execute(
                "SELECT * FROM historical_intraday "
                "WHERE symbol = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                [symbol, start_ts, end_ts],
            ).fetchdf()

        return df

    # ------------------------------------------------------------------
    # Scheduled daily update
    # ------------------------------------------------------------------

    def schedule_daily_update(self) -> None:
        """
        Schedule a background thread that triggers a data update at 6:00 PM IST daily.

        The thread checks every 60 seconds whether it is past 18:00 IST and
        has not yet run today.  Call ``stop_scheduler()`` to terminate.
        """
        if self._scheduler_running:
            return

        self._scheduler_running = True

        def _run():
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            last_run_date: Optional[date] = None

            while self._scheduler_running:
                now_ist = datetime.now(ist)
                today = now_ist.date()

                if now_ist.hour >= 18 and last_run_date != today:
                    try:
                        self._run_daily_update()
                        last_run_date = today
                        logger.info("Daily historical data update completed")
                    except Exception as exc:
                        logger.error(f"Daily update failed: {exc}")

                # Sleep 60 s between checks
                import time
                time.sleep(60)

        self._scheduler_thread = threading.Thread(target=_run, daemon=True)
        self._scheduler_thread.start()
        logger.info("Historical data daily update scheduler started")

    def stop_scheduler(self) -> None:
        """Stop the background scheduler thread."""
        self._scheduler_running = False

    def _run_daily_update(self) -> None:
        """Execute the daily update: download latest daily data and backfill gaps."""
        symbols = getattr(self.config, "symbols", [])
        if not symbols:
            return

        today = date.today()
        start = today - timedelta(days=7)  # last week to catch any gaps

        df = self.download_daily_data(symbols, start, today)
        if not df.empty:
            self.store_to_duckdb(df, "historical_daily")

        # Backfill any remaining gaps in the 2-year window
        two_years_ago = today - timedelta(days=MIN_DAILY_YEARS * 365)
        for symbol in symbols:
            missing = self.detect_missing_dates(symbol, two_years_ago, today)
            if missing:
                self.backfill_missing(symbol, missing)
