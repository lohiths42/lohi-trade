"""Tests for the Historical Data Service.

Covers: backfill_historical, S3 partitioned storage, retention policy,
adjust_for_corporate_actions, revert_adjustments (round-trip), and
query API with daily/weekly/monthly timeframes.

Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7
"""

from datetime import date
from typing import Any

import pytest

from src.ingestion.corporate_actions_collector import (
    CorporateAction,
    CorporateActionType,
)
from src.ingestion.historical_data_service import (
    OHLCV,
    HistoricalDataService,
    Timeframe,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeS3Client:
    """In-memory S3 client for testing."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def upload_bytes(self, bucket: str, key: str, data: bytes) -> None:
        self.store[f"{bucket}/{key}"] = data

    def download_bytes(self, bucket: str, key: str) -> bytes | None:
        return self.store.get(f"{bucket}/{key}")

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        full_prefix = f"{bucket}/{prefix}"
        return [k[len(bucket) + 1 :] for k in self.store if k.startswith(full_prefix)]

    def delete_key(self, bucket: str, key: str) -> None:
        self.store.pop(f"{bucket}/{key}", None)


class FakeDataSource:
    """Configurable data source for testing."""

    def __init__(self, bars: list[OHLCV] | None = None):
        self.bars = bars or []
        self.calls: list[tuple] = []

    def download_daily_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[OHLCV]:
        self.calls.append((symbol, start_date, end_date))
        return [b for b in self.bars if b.symbol == symbol and start_date <= b.date <= end_date]


class FailingDataSource:
    """Data source that always raises."""

    def download_daily_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[OHLCV]:
        raise ConnectionError("Source unavailable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(
    symbol: str = "RELIANCE",
    d: date = date(2024, 6, 15),
    o: float = 100.0,
    h: float = 110.0,
    l: float = 95.0,
    c: float = 105.0,
    v: int = 10000,
) -> OHLCV:
    return OHLCV(symbol=symbol, date=d, open=o, high=h, low=l, close=c, volume=v)


def _action(
    symbol: str = "RELIANCE",
    action_type: CorporateActionType = CorporateActionType.SPLIT,
    ex_date: date = date(2024, 6, 10),
    ratio: str = "2:1",
) -> CorporateAction:
    return CorporateAction(
        symbol=symbol,
        action_type=action_type,
        ex_date=ex_date,
        details={"ratio": ratio},
    )


def _make_service(
    bars: list[OHLCV] | None = None,
    metadata: dict[str, dict[str, Any]] | None = None,
) -> tuple:
    s3 = FakeS3Client()
    source = FakeDataSource(bars or [])
    svc = HistoricalDataService(
        s3_client=s3,
        data_source=source,
        security_metadata=metadata,
    )
    return svc, s3, source


# ---------------------------------------------------------------------------
# Tests: OHLCV dataclass
# ---------------------------------------------------------------------------


class TestOHLCV:
    def test_to_dict(self):
        bar = _bar()
        d = bar.to_dict()
        assert d["symbol"] == "RELIANCE"
        assert d["date"] == "2024-06-15"
        assert d["open"] == 100.0
        assert d["volume"] == 10000

    def test_from_dict_round_trip(self):
        original = _bar()
        restored = OHLCV.from_dict(original.to_dict())
        assert restored.symbol == original.symbol
        assert restored.date == original.date
        assert restored.open == original.open
        assert restored.close == original.close
        assert restored.volume == original.volume

    def test_from_dict_with_date_object(self):
        d = {
            "symbol": "TCS",
            "date": date(2024, 1, 1),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 500,
        }
        bar = OHLCV.from_dict(d)
        assert bar.date == date(2024, 1, 1)


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_serialize_deserialize_round_trip(self):
        bars = [
            _bar(d=date(2024, 1, 1), o=100, h=110, l=95, c=105, v=1000),
            _bar(d=date(2024, 1, 2), o=105, h=115, l=100, c=112, v=2000),
        ]
        data = HistoricalDataService._serialize_bars(bars)
        restored = HistoricalDataService._deserialize_bars(data)
        assert len(restored) == 2
        assert restored[0].date == date(2024, 1, 1)
        assert restored[1].close == 112.0

    def test_serialize_empty(self):
        assert HistoricalDataService._serialize_bars([]) == b""

    def test_deserialize_empty(self):
        assert HistoricalDataService._deserialize_bars(b"") == []

    def test_deserialize_header_only(self):
        data = b"symbol,date,open,high,low,close,volume"
        assert HistoricalDataService._deserialize_bars(data) == []


# ---------------------------------------------------------------------------
# Tests: Retention policy (Req 28.2)
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_large_cap_10_years(self):
        """Large-cap securities get 10 years retention. (Req 28.2)"""
        svc, _, _ = _make_service(
            metadata={"RELIANCE": {"market_cap_category": "large-cap"}},
        )
        assert svc.get_retention_years("RELIANCE") == 10

    def test_mid_cap_5_years(self):
        """Mid-cap securities get 5 years retention. (Req 28.2)"""
        svc, _, _ = _make_service(
            metadata={"MIDCAP": {"market_cap_category": "mid-cap"}},
        )
        assert svc.get_retention_years("MIDCAP") == 5

    def test_small_cap_5_years(self):
        """Small-cap securities get 5 years retention. (Req 28.2)"""
        svc, _, _ = _make_service(
            metadata={"SMALL": {"market_cap_category": "small-cap"}},
        )
        assert svc.get_retention_years("SMALL") == 5

    def test_unknown_defaults_to_5(self):
        """Unknown category defaults to 5 years."""
        svc, _, _ = _make_service()
        assert svc.get_retention_years("UNKNOWN") == 5


# ---------------------------------------------------------------------------
# Tests: Backfill (Req 28.1, 28.3, 28.5)
# ---------------------------------------------------------------------------


class TestBackfill:
    def test_backfill_stores_on_s3(self):
        """Backfill downloads and stores bars on S3. (Req 28.1, 28.3)"""
        bars = [
            _bar(d=date(2024, 3, 1)),
            _bar(d=date(2024, 3, 2)),
        ]
        svc, s3, source = _make_service(bars=bars)
        count = svc.backfill_historical("RELIANCE", date(2024, 3, 1), date(2024, 3, 2))

        assert count == 2
        assert svc.total_bars_downloaded == 2
        assert svc.total_bars_stored == 2
        # Verify S3 key follows partition scheme
        key = f"{HistoricalDataService.S3_BUCKET}/{svc._s3_key('RELIANCE', 2024)}"
        assert key in s3.store

    def test_backfill_partitions_by_year(self):
        """Bars spanning multiple years are stored in separate partitions. (Req 28.3)"""
        bars = [
            _bar(d=date(2023, 12, 31)),
            _bar(d=date(2024, 1, 1)),
        ]
        svc, s3, _ = _make_service(bars=bars)
        svc.backfill_historical("RELIANCE", date(2023, 12, 31), date(2024, 1, 1))

        key_2023 = f"{HistoricalDataService.S3_BUCKET}/{svc._s3_key('RELIANCE', 2023)}"
        key_2024 = f"{HistoricalDataService.S3_BUCKET}/{svc._s3_key('RELIANCE', 2024)}"
        assert key_2023 in s3.store
        assert key_2024 in s3.store

    def test_backfill_merges_with_existing(self):
        """Backfill merges new data with existing S3 data."""
        existing = [_bar(d=date(2024, 1, 1), c=100.0)]
        svc, s3, _ = _make_service()
        # Pre-populate S3
        key = svc._s3_key("RELIANCE", 2024)
        s3.upload_bytes(svc.S3_BUCKET, key, svc._serialize_bars(existing))

        new_bars = [_bar(d=date(2024, 1, 2), c=110.0)]
        svc.data_source = FakeDataSource(new_bars)
        svc.backfill_historical("RELIANCE", date(2024, 1, 2), date(2024, 1, 2))

        loaded = svc._load_year("RELIANCE", 2024)
        assert len(loaded) == 2

    def test_backfill_overwrites_duplicate_dates(self):
        """New data for same date overwrites existing."""
        existing = [_bar(d=date(2024, 1, 1), c=100.0)]
        svc, s3, _ = _make_service()
        key = svc._s3_key("RELIANCE", 2024)
        s3.upload_bytes(svc.S3_BUCKET, key, svc._serialize_bars(existing))

        new_bars = [_bar(d=date(2024, 1, 1), c=999.0)]
        svc.data_source = FakeDataSource(new_bars)
        svc.backfill_historical("RELIANCE", date(2024, 1, 1), date(2024, 1, 1))

        loaded = svc._load_year("RELIANCE", 2024)
        assert len(loaded) == 1
        assert loaded[0].close == 999.0

    def test_backfill_no_data_returns_zero(self):
        """Backfill with no data from source returns 0."""
        svc, _, _ = _make_service()
        count = svc.backfill_historical("RELIANCE", date(2024, 1, 1), date(2024, 1, 1))
        assert count == 0

    def test_backfill_error_increments_counter(self):
        """Source errors are caught and counted."""
        s3 = FakeS3Client()
        source = FailingDataSource()
        svc = HistoricalDataService(s3_client=s3, data_source=source)

        count = svc.backfill_historical("RELIANCE", date(2024, 1, 1), date(2024, 1, 1))
        assert count == 0
        assert svc.backfill_errors == 1

    def test_backfill_calls_data_source(self):
        """Backfill calls the data source with correct params. (Req 28.5)"""
        bars = [_bar(d=date(2024, 5, 1))]
        svc, _, source = _make_service(bars=bars)
        svc.backfill_historical("RELIANCE", date(2024, 5, 1), date(2024, 5, 1))

        assert len(source.calls) == 1
        assert source.calls[0] == ("RELIANCE", date(2024, 5, 1), date(2024, 5, 1))


# ---------------------------------------------------------------------------
# Tests: Corporate action adjustments (Req 28.6)
# ---------------------------------------------------------------------------


class TestAdjustForCorporateActions:
    def test_split_adjusts_pre_ex_date_bars(self):
        """Split 2:1 halves prices for bars before ex-date. (Req 28.6)"""
        bars = [
            _bar(d=date(2024, 6, 1), o=200, h=220, l=190, c=210),
            _bar(d=date(2024, 6, 15), o=100, h=110, l=95, c=105),
        ]
        actions = [_action(ex_date=date(2024, 6, 10), ratio="2:1")]
        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)

        # Bar before ex-date: prices * (1/2)
        assert adjusted[0].open == pytest.approx(100.0)
        assert adjusted[0].high == pytest.approx(110.0)
        assert adjusted[0].close == pytest.approx(105.0)
        # Bar on/after ex-date: unchanged
        assert adjusted[1].open == pytest.approx(100.0)

    def test_split_does_not_modify_original(self):
        """Adjustment returns new list, original unchanged."""
        bars = [_bar(d=date(2024, 6, 1), o=200)]
        actions = [_action(ex_date=date(2024, 6, 10), ratio="2:1")]
        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)

        assert bars[0].open == 200.0
        assert adjusted[0].open == pytest.approx(100.0)

    def test_bonus_adjusts_pre_ex_date_bars(self):
        """Bonus 1:1 halves prices for bars before ex-date. (Req 28.6)"""
        bars = [
            _bar(d=date(2024, 6, 1), o=1000, h=1100, l=950, c=1050),
            _bar(d=date(2024, 6, 15), o=500, h=550, l=475, c=525),
        ]
        actions = [
            _action(
                action_type=CorporateActionType.BONUS,
                ex_date=date(2024, 6, 10),
                ratio="1:1",
            )
        ]
        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)

        # factor = 1/(1+1) = 0.5
        assert adjusted[0].open == pytest.approx(500.0)
        assert adjusted[0].close == pytest.approx(525.0)
        # After ex-date: unchanged
        assert adjusted[1].open == pytest.approx(500.0)

    def test_no_actions_returns_copy(self):
        """Empty actions list returns a copy of raw data."""
        bars = [_bar(d=date(2024, 1, 1), o=100)]
        result = HistoricalDataService.adjust_for_corporate_actions(bars, [])
        assert len(result) == 1
        assert result[0].open == 100.0
        assert result[0] is not bars[0]

    def test_empty_bars_returns_empty(self):
        result = HistoricalDataService.adjust_for_corporate_actions([], [_action()])
        assert result == []

    def test_dividend_action_ignored(self):
        """Dividend actions don't affect prices."""
        bars = [_bar(d=date(2024, 6, 1), o=100)]
        actions = [_action(action_type=CorporateActionType.DIVIDEND, ratio="10:0")]
        result = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        assert result[0].open == 100.0

    def test_action_without_ex_date_ignored(self):
        """Actions with no ex_date are skipped."""
        bars = [_bar(d=date(2024, 6, 1), o=100)]
        action = CorporateAction(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            ex_date=None,
            details={"ratio": "2:1"},
        )
        result = HistoricalDataService.adjust_for_corporate_actions(bars, [action])
        assert result[0].open == 100.0

    def test_invalid_ratio_ignored(self):
        """Invalid ratio string is skipped."""
        bars = [_bar(d=date(2024, 6, 1), o=100)]
        actions = [_action(ratio="invalid")]
        result = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        assert result[0].open == 100.0

    def test_multiple_actions_applied(self):
        """Multiple corporate actions are applied correctly."""
        bars = [
            _bar(d=date(2024, 1, 1), o=1000),
            _bar(d=date(2024, 4, 1), o=500),
            _bar(d=date(2024, 7, 1), o=250),
        ]
        actions = [
            _action(ex_date=date(2024, 3, 1), ratio="2:1"),  # split
            _action(
                action_type=CorporateActionType.BONUS,
                ex_date=date(2024, 6, 1),
                ratio="1:1",
            ),
        ]
        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)

        # Bar at 2024-01-01: before both actions
        # Bonus (ex 2024-06-01): factor = 1/(1+1) = 0.5
        # Split (ex 2024-03-01): factor = 1/2 = 0.5
        # Combined: 1000 * 0.5 * 0.5 = 250
        assert adjusted[0].open == pytest.approx(250.0)

        # Bar at 2024-04-01: after split, before bonus
        # Only bonus applies: 500 * 0.5 = 250
        assert adjusted[1].open == pytest.approx(250.0)

        # Bar at 2024-07-01: after both actions, unchanged
        assert adjusted[2].open == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# Tests: Revert adjustments (Req 28.7)
# ---------------------------------------------------------------------------


class TestRevertAdjustments:
    def test_round_trip_split(self):
        """Adjust then revert produces original data for split. (Req 28.7)"""
        bars = [
            _bar(d=date(2024, 6, 1), o=200, h=220, l=190, c=210),
            _bar(d=date(2024, 6, 15), o=100, h=110, l=95, c=105),
        ]
        actions = [_action(ex_date=date(2024, 6, 10), ratio="2:1")]

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        reverted = HistoricalDataService.revert_adjustments(adjusted, actions)

        for orig, rev in zip(bars, reverted):
            assert rev.open == pytest.approx(orig.open, rel=1e-9)
            assert rev.high == pytest.approx(orig.high, rel=1e-9)
            assert rev.low == pytest.approx(orig.low, rel=1e-9)
            assert rev.close == pytest.approx(orig.close, rel=1e-9)
            assert rev.volume == orig.volume

    def test_round_trip_bonus(self):
        """Adjust then revert produces original data for bonus. (Req 28.7)"""
        bars = [
            _bar(d=date(2024, 6, 1), o=1000, h=1100, l=950, c=1050),
            _bar(d=date(2024, 6, 15), o=500, h=550, l=475, c=525),
        ]
        actions = [
            _action(
                action_type=CorporateActionType.BONUS,
                ex_date=date(2024, 6, 10),
                ratio="1:1",
            )
        ]

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        reverted = HistoricalDataService.revert_adjustments(adjusted, actions)

        for orig, rev in zip(bars, reverted):
            assert rev.open == pytest.approx(orig.open, rel=1e-9)
            assert rev.close == pytest.approx(orig.close, rel=1e-9)

    def test_round_trip_multiple_actions(self):
        """Adjust then revert with multiple actions. (Req 28.7)"""
        bars = [
            _bar(d=date(2024, 1, 1), o=1000),
            _bar(d=date(2024, 4, 1), o=500),
            _bar(d=date(2024, 7, 1), o=250),
        ]
        actions = [
            _action(ex_date=date(2024, 3, 1), ratio="2:1"),
            _action(
                action_type=CorporateActionType.BONUS,
                ex_date=date(2024, 6, 1),
                ratio="1:1",
            ),
        ]

        adjusted = HistoricalDataService.adjust_for_corporate_actions(bars, actions)
        reverted = HistoricalDataService.revert_adjustments(adjusted, actions)

        for orig, rev in zip(bars, reverted):
            assert rev.open == pytest.approx(orig.open, rel=1e-9)

    def test_revert_empty_data(self):
        result = HistoricalDataService.revert_adjustments([], [_action()])
        assert result == []

    def test_revert_no_actions(self):
        bars = [_bar(d=date(2024, 1, 1), o=100)]
        result = HistoricalDataService.revert_adjustments(bars, [])
        assert result[0].open == 100.0
        assert result[0] is not bars[0]


# ---------------------------------------------------------------------------
# Tests: Query API (Req 28.4)
# ---------------------------------------------------------------------------


class TestQueryAPI:
    def _populate(self, svc, s3):
        """Populate S3 with sample daily data for Jan 2024."""
        bars = []
        for day in range(1, 32):
            try:
                d = date(2024, 1, day)
            except ValueError:
                continue
            # Skip weekends
            if d.weekday() >= 5:
                continue
            bars.append(_bar(d=d, o=100 + day, h=110 + day, l=90 + day, c=105 + day, v=1000 * day))
        key = svc._s3_key("RELIANCE", 2024)
        s3.upload_bytes(svc.S3_BUCKET, key, svc._serialize_bars(bars))
        return bars

    def test_query_daily(self):
        """Query with daily timeframe returns filtered bars. (Req 28.4)"""
        svc, s3, _ = _make_service()
        stored = self._populate(svc, s3)

        result = svc.query("RELIANCE", date(2024, 1, 1), date(2024, 1, 10))
        assert len(result) > 0
        for bar in result:
            assert date(2024, 1, 1) <= bar.date <= date(2024, 1, 10)

    def test_query_weekly(self):
        """Query with weekly timeframe aggregates bars. (Req 28.4)"""
        svc, s3, _ = _make_service()
        self._populate(svc, s3)

        result = svc.query(
            "RELIANCE",
            date(2024, 1, 1),
            date(2024, 1, 31),
            timeframe=Timeframe.WEEKLY,
        )
        # January 2024 has ~5 trading weeks
        assert 3 <= len(result) <= 5

    def test_query_monthly(self):
        """Query with monthly timeframe aggregates bars. (Req 28.4)"""
        svc, s3, _ = _make_service()
        self._populate(svc, s3)

        result = svc.query(
            "RELIANCE",
            date(2024, 1, 1),
            date(2024, 1, 31),
            timeframe=Timeframe.MONTHLY,
        )
        assert len(result) == 1

    def test_query_empty_range(self):
        """Query for a range with no data returns empty."""
        svc, _, _ = _make_service()
        result = svc.query("RELIANCE", date(2020, 1, 1), date(2020, 1, 31))
        assert result == []

    def test_query_spans_multiple_years(self):
        """Query spanning two years loads from both partitions."""
        svc, s3, _ = _make_service()
        bars_2023 = [_bar(d=date(2023, 12, 29), c=100)]
        bars_2024 = [_bar(d=date(2024, 1, 2), c=200)]
        s3.upload_bytes(
            svc.S3_BUCKET, svc._s3_key("RELIANCE", 2023), svc._serialize_bars(bars_2023)
        )
        s3.upload_bytes(
            svc.S3_BUCKET, svc._s3_key("RELIANCE", 2024), svc._serialize_bars(bars_2024)
        )

        result = svc.query("RELIANCE", date(2023, 12, 1), date(2024, 1, 31))
        assert len(result) == 2

    def test_weekly_aggregation_ohlcv(self):
        """Weekly bars have correct OHLCV aggregation."""
        svc, s3, _ = _make_service()
        # Mon-Fri of one week
        bars = [
            _bar(d=date(2024, 1, 1), o=100, h=110, l=95, c=105, v=1000),
            _bar(d=date(2024, 1, 2), o=105, h=120, l=100, c=115, v=2000),
            _bar(d=date(2024, 1, 3), o=115, h=125, l=90, c=108, v=1500),
        ]
        s3.upload_bytes(svc.S3_BUCKET, svc._s3_key("RELIANCE", 2024), svc._serialize_bars(bars))

        result = svc.query("RELIANCE", date(2024, 1, 1), date(2024, 1, 3), Timeframe.WEEKLY)
        assert len(result) == 1
        week_bar = result[0]
        assert week_bar.open == 100.0  # first bar's open
        assert week_bar.high == 125.0  # max high
        assert week_bar.low == 90.0  # min low
        assert week_bar.close == 108.0  # last bar's close
        assert week_bar.volume == 4500  # sum of volumes

    def test_query_results_sorted_by_date(self):
        """Query results are sorted chronologically."""
        svc, s3, _ = _make_service()
        bars = [
            _bar(d=date(2024, 1, 3)),
            _bar(d=date(2024, 1, 1)),
            _bar(d=date(2024, 1, 2)),
        ]
        s3.upload_bytes(svc.S3_BUCKET, svc._s3_key("RELIANCE", 2024), svc._serialize_bars(bars))

        result = svc.query("RELIANCE", date(2024, 1, 1), date(2024, 1, 3))
        dates = [b.date for b in result]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Tests: Properties and metadata
# ---------------------------------------------------------------------------


class TestServiceProperties:
    def test_initial_stats(self):
        svc, _, _ = _make_service()
        assert svc.total_bars_downloaded == 0
        assert svc.total_bars_stored == 0
        assert svc.backfill_errors == 0

    def test_update_security_metadata(self):
        svc, _, _ = _make_service()
        svc.update_security_metadata({"TCS": {"market_cap_category": "large-cap"}})
        assert svc.get_retention_years("TCS") == 10

    def test_s3_key_format(self):
        """S3 key follows partition scheme: historical/{symbol}/{year}.parquet"""
        svc, _, _ = _make_service()
        key = svc._s3_key("RELIANCE", 2024)
        assert key == "historical/RELIANCE/2024.parquet"


# ---------------------------------------------------------------------------
# Tests: Adjustment factor computation
# ---------------------------------------------------------------------------


class TestComputeAdjustmentFactor:
    def test_split_factor(self):
        action = _action(ratio="5:1")
        factor = HistoricalDataService._compute_adjustment_factor(action)
        assert factor == pytest.approx(0.2)

    def test_bonus_factor(self):
        action = _action(action_type=CorporateActionType.BONUS, ratio="1:2")
        factor = HistoricalDataService._compute_adjustment_factor(action)
        # existing/(bonus+existing) = 2/(1+2) = 2/3
        assert factor == pytest.approx(2.0 / 3.0)

    def test_invalid_ratio_returns_none(self):
        action = _action(ratio="bad")
        assert HistoricalDataService._compute_adjustment_factor(action) is None

    def test_missing_ratio_returns_none(self):
        action = CorporateAction(
            symbol="X",
            action_type=CorporateActionType.SPLIT,
            details={},
        )
        assert HistoricalDataService._compute_adjustment_factor(action) is None

    def test_zero_split_numerator_returns_none(self):
        action = _action(ratio="0:1")
        assert HistoricalDataService._compute_adjustment_factor(action) is None

    def test_zero_bonus_total_returns_none(self):
        action = _action(action_type=CorporateActionType.BONUS, ratio="0:0")
        assert HistoricalDataService._compute_adjustment_factor(action) is None

    def test_dividend_returns_none(self):
        action = _action(action_type=CorporateActionType.DIVIDEND, ratio="10:0")
        assert HistoricalDataService._compute_adjustment_factor(action) is None
