"""Historical Data Service for LOHI-TRADE.

Downloads, stores, and queries historical OHLCV data for all NSE/BSE
securities. Stores as Parquet on S3 partitioned by symbol and year.
Maintains 10 years for large-cap, 5 years for mid/small-cap.
Provides corporate action adjustment and revert for price continuity.

Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7
"""

from dataclasses import dataclass
from datetime import date, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

from src.ingestion.corporate_actions_collector import (
    CorporateAction,
    CorporateActionType,
)
from src.utils.logger import get_logger

logger = get_logger("HistoricalDataService")

IST = timezone(timedelta(hours=5, minutes=30))


class Timeframe(Enum):
    """Supported query timeframes (Req 28.4)."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class MarketCapCategory(Enum):
    """Market cap categories for retention policy (Req 28.2)."""

    LARGE_CAP = "large-cap"
    MID_CAP = "mid-cap"
    SMALL_CAP = "small-cap"


@dataclass
class OHLCV:
    """A single OHLCV bar."""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OHLCV":
        d = data["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        return cls(
            symbol=data["symbol"],
            date=d,
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data["volume"]),
        )


class S3Client(Protocol):
    """Protocol for S3 operations (allows injection for testing)."""

    def upload_bytes(self, bucket: str, key: str, data: bytes) -> None: ...
    def download_bytes(self, bucket: str, key: str) -> bytes | None: ...
    def list_keys(self, bucket: str, prefix: str) -> list[str]: ...
    def delete_key(self, bucket: str, key: str) -> None: ...


class DataSource(Protocol):
    """Protocol for historical data download sources."""

    def download_daily_ohlcv(
        self, symbol: str, start_date: date, end_date: date,
    ) -> list[OHLCV]: ...


class HistoricalDataService:
    """Service for downloading, storing, and querying historical OHLCV data.

    - Downloads daily OHLCV from NSE/BSE archives or Yahoo Finance (Req 28.1, 28.5)
    - Stores as Parquet on S3, partitioned by symbol and year (Req 28.3)
    - Maintains 10 years for large-cap, 5 years for mid/small-cap (Req 28.2)
    - Adjusts/reverts prices for corporate actions (Req 28.6, 28.7)
    - Provides query API by symbol, date range, timeframe (Req 28.4)

    Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7
    """

    LARGE_CAP_YEARS = 10
    MID_SMALL_CAP_YEARS = 5

    S3_BUCKET = "lohi-trade-data"
    S3_PREFIX = "historical"

    def __init__(
        self,
        s3_client: S3Client,
        data_source: DataSource,
        security_metadata: dict[str, dict[str, Any]] | None = None,
    ):
        """Args:
        s3_client: S3 client for Parquet storage.
        data_source: Source for downloading OHLCV data.
        security_metadata: symbol -> {"market_cap_category": "large-cap"|"mid-cap"|"small-cap", ...}

        """
        self.s3_client = s3_client
        self.data_source = data_source
        self._security_metadata: dict[str, dict[str, Any]] = security_metadata or {}

        # Stats
        self._total_bars_downloaded: int = 0
        self._total_bars_stored: int = 0
        self._backfill_errors: int = 0

    # ------------------------------------------------------------------
    # S3 key helpers
    # ------------------------------------------------------------------

    def _s3_key(self, symbol: str, year: int) -> str:
        """S3 key: historical/{symbol}/{year}.parquet"""
        return f"{self.S3_PREFIX}/{symbol}/{year}.parquet"

    # ------------------------------------------------------------------
    # Parquet serialization (lightweight, using csv as interchange)
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_bars(bars: list[OHLCV]) -> bytes:
        """Serialize OHLCV bars to a simple CSV-based Parquet-like format.

        In production this would use pyarrow/pandas to write real Parquet.
        Here we use CSV bytes so the service is testable without heavy deps.
        """
        if not bars:
            return b""
        lines = ["symbol,date,open,high,low,close,volume"]
        for b in bars:
            lines.append(
                f"{b.symbol},{b.date.isoformat()},{b.open},{b.high},"
                f"{b.low},{b.close},{b.volume}",
            )
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _deserialize_bars(data: bytes) -> list[OHLCV]:
        """Deserialize bars from CSV bytes."""
        if not data:
            return []
        text = data.decode("utf-8").strip()
        if not text:
            return []
        lines = text.split("\n")
        if len(lines) <= 1:
            return []
        bars: list[OHLCV] = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            bars.append(OHLCV(
                symbol=parts[0],
                date=date.fromisoformat(parts[1]),
                open=float(parts[2]),
                high=float(parts[3]),
                low=float(parts[4]),
                close=float(parts[5]),
                volume=int(parts[6]),
            ))
        return bars

    # ------------------------------------------------------------------
    # Retention policy (Req 28.2)
    # ------------------------------------------------------------------

    def get_retention_years(self, symbol: str) -> int:
        """Return how many years of data to maintain for a symbol.

        Large-cap: 10 years, mid/small-cap: 5 years (Req 28.2).
        Defaults to 5 years if category unknown.
        """
        meta = self._security_metadata.get(symbol, {})
        category = meta.get("market_cap_category", "")
        if category == MarketCapCategory.LARGE_CAP.value:
            return self.LARGE_CAP_YEARS
        return self.MID_SMALL_CAP_YEARS

    # ------------------------------------------------------------------
    # Backfill (Req 28.1, 28.5)
    # ------------------------------------------------------------------

    def backfill_historical(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """Download daily OHLCV and store as Parquet on S3.

        Downloads from the configured data source (NSE/BSE archives or
        Yahoo Finance) and stores partitioned by symbol and year.

        Args:
            symbol: Trading symbol.
            start_date: Start of backfill range (inclusive).
            end_date: End of backfill range (inclusive).

        Returns:
            Number of bars stored.

        Requirements: 28.1, 28.3, 28.5

        """
        logger.info(
            f"Backfilling {symbol} from {start_date} to {end_date}",
        )
        try:
            bars = self.data_source.download_daily_ohlcv(symbol, start_date, end_date)
            if not bars:
                logger.warning(f"No data returned for {symbol}")
                return 0

            self._total_bars_downloaded += len(bars)

            # Group by year for partitioned storage (Req 28.3)
            by_year: dict[int, list[OHLCV]] = {}
            for bar in bars:
                by_year.setdefault(bar.date.year, []).append(bar)

            stored = 0
            for year, year_bars in by_year.items():
                # Merge with existing data for that year
                existing = self._load_year(symbol, year)
                merged = self._merge_bars(existing, year_bars)
                merged.sort(key=lambda b: b.date)

                data = self._serialize_bars(merged)
                key = self._s3_key(symbol, year)
                self.s3_client.upload_bytes(self.S3_BUCKET, key, data)
                stored += len(year_bars)

            self._total_bars_stored += stored
            logger.info(f"Stored {stored} bars for {symbol}")
            return stored

        except Exception as e:
            self._backfill_errors += 1
            logger.error(f"Backfill failed for {symbol}: {e}", exc_info=True)
            return 0

    def _load_year(self, symbol: str, year: int) -> list[OHLCV]:
        """Load existing bars for a symbol/year from S3."""
        key = self._s3_key(symbol, year)
        data = self.s3_client.download_bytes(self.S3_BUCKET, key)
        if data is None:
            return []
        return self._deserialize_bars(data)

    @staticmethod
    def _merge_bars(existing: list[OHLCV], new: list[OHLCV]) -> list[OHLCV]:
        """Merge new bars into existing, deduplicating by date."""
        date_map: dict[date, OHLCV] = {}
        for bar in existing:
            date_map[bar.date] = bar
        for bar in new:
            date_map[bar.date] = bar  # new overwrites existing
        return list(date_map.values())

    # ------------------------------------------------------------------
    # Corporate action adjustments (Req 28.6, 28.7)
    # ------------------------------------------------------------------

    @staticmethod
    def adjust_for_corporate_actions(
        raw_data: list[OHLCV],
        actions: list[CorporateAction],
    ) -> list[OHLCV]:
        """Apply split/bonus adjustments to historical prices for continuity.

        Adjustments are applied chronologically: for each action with an
        ex_date, all bars *before* the ex_date are adjusted.

        - SPLIT with ratio "new:old": multiply prices by old/new
        - BONUS with ratio "bonus:existing": multiply prices by
          existing/(bonus+existing)

        Args:
            raw_data: Raw OHLCV bars (not modified in place).
            actions: Corporate actions to apply.

        Returns:
            New list of adjusted OHLCV bars.

        Requirements: 28.6

        """
        if not raw_data or not actions:
            return [OHLCV(
                symbol=b.symbol, date=b.date,
                open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume,
            ) for b in raw_data]

        # Sort actions by ex_date descending (apply most recent first)
        applicable = [
            a for a in actions
            if a.ex_date is not None
            and a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS)
        ]
        applicable.sort(key=lambda a: a.ex_date, reverse=True)

        # Deep copy
        adjusted = [
            OHLCV(
                symbol=b.symbol, date=b.date,
                open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume,
            )
            for b in raw_data
        ]

        for action in applicable:
            factor = HistoricalDataService._compute_adjustment_factor(action)
            if factor is None or factor == 1.0:
                continue
            for bar in adjusted:
                if bar.date < action.ex_date:
                    bar.open = bar.open * factor
                    bar.high = bar.high * factor
                    bar.low = bar.low * factor
                    bar.close = bar.close * factor

        return adjusted

    @staticmethod
    def revert_adjustments(
        adjusted_data: list[OHLCV],
        actions: list[CorporateAction],
    ) -> list[OHLCV]:
        """Revert corporate action adjustments to recover original raw data.

        This is the inverse of adjust_for_corporate_actions. Applying
        adjust then revert produces the original raw data (round-trip
        property, Req 28.7).

        Args:
            adjusted_data: Previously adjusted OHLCV bars.
            actions: Same corporate actions used for adjustment.

        Returns:
            New list of reverted OHLCV bars matching original raw data.

        Requirements: 28.7

        """
        if not adjusted_data or not actions:
            return [OHLCV(
                symbol=b.symbol, date=b.date,
                open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume,
            ) for b in adjusted_data]

        applicable = [
            a for a in actions
            if a.ex_date is not None
            and a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS)
        ]
        # Revert in chronological order (oldest first) — reverse of adjust
        applicable.sort(key=lambda a: a.ex_date)

        reverted = [
            OHLCV(
                symbol=b.symbol, date=b.date,
                open=b.open, high=b.high, low=b.low, close=b.close,
                volume=b.volume,
            )
            for b in adjusted_data
        ]

        for action in applicable:
            factor = HistoricalDataService._compute_adjustment_factor(action)
            if factor is None or factor == 0.0 or factor == 1.0:
                continue
            inverse = 1.0 / factor
            for bar in reverted:
                if bar.date < action.ex_date:
                    bar.open = bar.open * inverse
                    bar.high = bar.high * inverse
                    bar.low = bar.low * inverse
                    bar.close = bar.close * inverse

        return reverted

    @staticmethod
    def _compute_adjustment_factor(action: CorporateAction) -> float | None:
        """Compute the price multiplication factor for an action.

        SPLIT "new:old" → factor = old/new  (prices go down)
        BONUS "bonus:existing" → factor = existing/(bonus+existing)
        """
        ratio_str = action.details.get("ratio", "")
        if not ratio_str or ":" not in str(ratio_str):
            return None
        try:
            parts = str(ratio_str).split(":")
            left = float(parts[0])
            right = float(parts[1])
        except (ValueError, IndexError):
            return None

        if action.action_type == CorporateActionType.SPLIT:
            if left == 0:
                return None
            return right / left
        if action.action_type == CorporateActionType.BONUS:
            total = left + right
            if total == 0:
                return None
            return right / total
        return None

    # ------------------------------------------------------------------
    # Query API (Req 28.4)
    # ------------------------------------------------------------------

    def query(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.DAILY,
    ) -> list[OHLCV]:
        """Query historical data by symbol, date range, and timeframe.

        Args:
            symbol: Trading symbol.
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            timeframe: DAILY, WEEKLY, or MONTHLY.

        Returns:
            List of OHLCV bars for the requested range and timeframe.

        Requirements: 28.4

        """
        # Determine which years to load
        start_year = start_date.year
        end_year = end_date.year

        all_bars: list[OHLCV] = []
        for year in range(start_year, end_year + 1):
            year_bars = self._load_year(symbol, year)
            all_bars.extend(year_bars)

        # Filter to date range
        filtered = [
            b for b in all_bars
            if start_date <= b.date <= end_date
        ]
        filtered.sort(key=lambda b: b.date)

        if timeframe == Timeframe.DAILY:
            return filtered
        if timeframe == Timeframe.WEEKLY:
            return self._resample_weekly(filtered)
        if timeframe == Timeframe.MONTHLY:
            return self._resample_monthly(filtered)
        return filtered

    @staticmethod
    def _resample_weekly(bars: list[OHLCV]) -> list[OHLCV]:
        """Resample daily bars to weekly OHLCV."""
        if not bars:
            return []
        result: list[OHLCV] = []
        current_week: list[OHLCV] | None = None
        current_iso_week: tuple | None = None

        for bar in bars:
            iso = bar.date.isocalendar()
            week_key = (iso[0], iso[1])
            if current_iso_week != week_key:
                if current_week:
                    result.append(HistoricalDataService._aggregate_bars(current_week))
                current_week = [bar]
                current_iso_week = week_key
            else:
                current_week.append(bar)

        if current_week:
            result.append(HistoricalDataService._aggregate_bars(current_week))
        return result

    @staticmethod
    def _resample_monthly(bars: list[OHLCV]) -> list[OHLCV]:
        """Resample daily bars to monthly OHLCV."""
        if not bars:
            return []
        result: list[OHLCV] = []
        current_month: list[OHLCV] | None = None
        current_key: tuple | None = None

        for bar in bars:
            month_key = (bar.date.year, bar.date.month)
            if current_key != month_key:
                if current_month:
                    result.append(HistoricalDataService._aggregate_bars(current_month))
                current_month = [bar]
                current_key = month_key
            else:
                current_month.append(bar)

        if current_month:
            result.append(HistoricalDataService._aggregate_bars(current_month))
        return result

    @staticmethod
    def _aggregate_bars(bars: list[OHLCV]) -> OHLCV:
        """Aggregate multiple daily bars into a single OHLCV bar."""
        return OHLCV(
            symbol=bars[0].symbol,
            date=bars[-1].date,  # use last date in period
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_bars_downloaded(self) -> int:
        return self._total_bars_downloaded

    @property
    def total_bars_stored(self) -> int:
        return self._total_bars_stored

    @property
    def backfill_errors(self) -> int:
        return self._backfill_errors

    @property
    def security_metadata(self) -> dict[str, dict[str, Any]]:
        return dict(self._security_metadata)

    def update_security_metadata(
        self, metadata: dict[str, dict[str, Any]],
    ) -> None:
        """Update security metadata (market cap categories etc.)."""
        self._security_metadata.update(metadata)
