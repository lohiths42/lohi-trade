"""Unit tests for ChartGenerator — matplotlib-based chart generation.

Tests cover: equity curve, daily P&L bar chart, strategy comparison,
candlestick chart with indicator overlays, theme support, empty data handling.

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.chatbot_service import ChartGenerator


@pytest.fixture
def gen():
    return ChartGenerator()


def _make_equity_data(n=30, start_equity=100000):
    """Generate sample equity curve data."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    data = []
    equity = start_equity
    for i in range(n):
        equity += (i % 5 - 2) * 500  # fluctuate
        data.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "equity": equity,
        })
    return data


def _make_pnl_data(n=15):
    """Generate sample daily P&L data with positive and negative values."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pnls = [1200, -500, 800, -300, 1500, -200, 600, -1000, 900, 400,
            -700, 1100, -150, 2000, -800]
    data = []
    for i in range(min(n, len(pnls))):
        data.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "pnl": pnls[i],
        })
    return data


def _make_strategy_data():
    """Generate sample strategy comparison data."""
    return [
        {"strategy": "Mean Reversion", "total_pnl": 15000, "win_rate": 62.5, "trade_count": 40},
        {"strategy": "Trend Following", "total_pnl": -3000, "win_rate": 45.0, "trade_count": 20},
        {"strategy": "ORB", "total_pnl": 8500, "win_rate": 55.0, "trade_count": 30},
    ]


def _make_ohlcv_data(n=30):
    """Generate sample OHLCV data."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    data = []
    price = 2500.0
    for i in range(n):
        o = price + (i % 3 - 1) * 10
        h = o + abs(i % 7) * 5 + 10
        l = o - abs(i % 5) * 5 - 5
        c = o + (i % 4 - 2) * 8
        v = 100000 + i * 5000
        data.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        })
        price = c
    return data


# ── Equity Curve Tests ───────────────────────────────────────────────────────


class TestEquityCurve:
    def test_returns_svg_bytes(self, gen):
        data = _make_equity_data()
        result = gen.equity_curve(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_light_theme(self, gen):
        data = _make_equity_data()
        result = gen.equity_curve(data, theme="light")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_empty_data_returns_svg(self, gen):
        result = gen.equity_curve([], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_single_data_point(self, gen):
        data = [{"date": "2024-01-01T00:00:00+00:00", "equity": 100000}]
        result = gen.equity_curve(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_datetime_objects_accepted(self, gen):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = [
            {"date": base, "equity": 100000},
            {"date": base + timedelta(days=1), "equity": 101000},
        ]
        result = gen.equity_curve(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_default_theme_is_dark(self, gen):
        data = _make_equity_data(5)
        result = gen.equity_curve(data)
        assert isinstance(result, bytes)
        assert b"<svg" in result


# ── Daily P&L Bar Chart Tests ────────────────────────────────────────────────


class TestDailyPnlBar:
    def test_returns_svg_bytes(self, gen):
        data = _make_pnl_data()
        result = gen.daily_pnl_bar(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_light_theme(self, gen):
        data = _make_pnl_data()
        result = gen.daily_pnl_bar(data, theme="light")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_empty_data_returns_svg(self, gen):
        result = gen.daily_pnl_bar([], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_all_positive_pnl(self, gen):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = [{"date": (base + timedelta(days=i)).isoformat(), "pnl": 500 + i * 100} for i in range(5)]
        result = gen.daily_pnl_bar(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_all_negative_pnl(self, gen):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = [{"date": (base + timedelta(days=i)).isoformat(), "pnl": -500 - i * 100} for i in range(5)]
        result = gen.daily_pnl_bar(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_many_bars(self, gen):
        """Test with >15 bars to trigger label stepping."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = [{"date": (base + timedelta(days=i)).isoformat(), "pnl": (i % 5 - 2) * 300} for i in range(25)]
        result = gen.daily_pnl_bar(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result


# ── Strategy Comparison Tests ────────────────────────────────────────────────


class TestStrategyComparison:
    def test_returns_svg_bytes(self, gen):
        data = _make_strategy_data()
        result = gen.strategy_comparison(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_light_theme(self, gen):
        data = _make_strategy_data()
        result = gen.strategy_comparison(data, theme="light")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_empty_data_returns_svg(self, gen):
        result = gen.strategy_comparison([], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_single_strategy(self, gen):
        data = [{"strategy": "ORB", "total_pnl": 5000, "win_rate": 60.0, "trade_count": 10}]
        result = gen.strategy_comparison(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_negative_pnl_strategies(self, gen):
        data = [
            {"strategy": "A", "total_pnl": -5000, "win_rate": 30.0, "trade_count": 10},
            {"strategy": "B", "total_pnl": -2000, "win_rate": 40.0, "trade_count": 5},
        ]
        result = gen.strategy_comparison(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result


# ── Candlestick Chart Tests ──────────────────────────────────────────────────


class TestCandlestick:
    def test_returns_svg_bytes(self, gen):
        data = _make_ohlcv_data()
        result = gen.candlestick(data, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_light_theme(self, gen):
        data = _make_ohlcv_data()
        result = gen.candlestick(data, theme="light")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_empty_data_returns_svg(self, gen):
        result = gen.candlestick([], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_with_sma_indicator(self, gen):
        data = _make_ohlcv_data(30)
        result = gen.candlestick(data, indicators=["SMA"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_with_ema_indicator(self, gen):
        data = _make_ohlcv_data(30)
        result = gen.candlestick(data, indicators=["EMA"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_with_rsi_indicator(self, gen):
        data = _make_ohlcv_data(30)
        result = gen.candlestick(data, indicators=["RSI"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_with_macd_indicator(self, gen):
        data = _make_ohlcv_data(50)
        result = gen.candlestick(data, indicators=["MACD"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_with_multiple_indicators(self, gen):
        data = _make_ohlcv_data(50)
        result = gen.candlestick(data, indicators=["SMA", "RSI", "MACD"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_few_data_points(self, gen):
        """Test with very few data points (less than indicator periods)."""
        data = _make_ohlcv_data(5)
        result = gen.candlestick(data, indicators=["SMA", "RSI"], theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result

    def test_no_indicators(self, gen):
        data = _make_ohlcv_data(10)
        result = gen.candlestick(data, indicators=None, theme="dark")
        assert isinstance(result, bytes)
        assert b"<svg" in result


# ── Theme Tests ──────────────────────────────────────────────────────────────


class TestTheme:
    def test_dark_theme_exists(self, gen):
        t = gen._get_theme("dark")
        assert "bg" in t
        assert "fg" in t
        assert "positive" in t
        assert "negative" in t

    def test_light_theme_exists(self, gen):
        t = gen._get_theme("light")
        assert "bg" in t
        assert "fg" in t

    def test_unknown_theme_defaults_to_dark(self, gen):
        t = gen._get_theme("unknown")
        assert t == gen.THEMES["dark"]

    def test_dark_and_light_differ(self, gen):
        dark = gen._get_theme("dark")
        light = gen._get_theme("light")
        assert dark["bg"] != light["bg"]
        assert dark["fg"] != light["fg"]


# ── Technical Indicator Computation Tests ────────────────────────────────────


class TestIndicatorComputations:
    def test_sma_basic(self, gen):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = gen._compute_sma(values, 3)
        assert abs(result[2] - 20.0) < 0.01  # (10+20+30)/3
        assert abs(result[3] - 30.0) < 0.01  # (20+30+40)/3
        assert abs(result[4] - 40.0) < 0.01  # (30+40+50)/3

    def test_ema_basic(self, gen):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = gen._compute_ema(values, 3)
        # EMA seed = SMA of first 3 = 20.0
        assert abs(result[2] - 20.0) < 0.01
        # EMA(3) = (40 - 20) * 0.5 + 20 = 30
        assert abs(result[3] - 30.0) < 0.01

    def test_rsi_returns_correct_length(self, gen):
        closes = [100 + i for i in range(30)]
        result = gen._compute_rsi(closes, 14)
        assert len(result) == len(closes)

    def test_rsi_all_gains_near_100(self, gen):
        """Monotonically increasing prices should give RSI near 100."""
        closes = [100.0 + i * 10 for i in range(30)]
        result = gen._compute_rsi(closes, 14)
        # After the initial period, RSI should be high
        assert result[-1] > 80

    def test_macd_returns_three_lists(self, gen):
        closes = [100.0 + i * 0.5 for i in range(50)]
        macd_line, signal_line, histogram = gen._compute_macd(closes)
        assert len(macd_line) == len(closes)
        assert len(signal_line) == len(closes)
        assert len(histogram) == len(closes)

    def test_macd_insufficient_data(self, gen):
        closes = [100.0, 101.0, 102.0]
        macd_line, signal_line, histogram = gen._compute_macd(closes)
        assert macd_line == []
        assert signal_line == []
        assert histogram == []
