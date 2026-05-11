#!/usr/bin/env python3
"""
LOHI-TRADE Paper Trading Simulation

Runs a full end-to-end simulation with synthetic market data and fake money.
Uses the real trading pipeline: ticks → candles → indicators → strategies →
signals → RMS → position sizing → paper fills → position management.

All data flows into the production SQLite DB and Redis streams so the
frontend dashboard shows live activity.

Usage:
    python scripts/paper_simulation.py [--speed 10] [--days 5] [--capital 200000]
"""

import argparse
import json
import math
import os
import random
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np
import pandas as pd
import yfinance as yf

from src.soldier.candle_builder import CandleBuilder, Candle
from src.soldier.indicator_engine import IndicatorEngine, IndicatorSet
from src.soldier.strategy_engine import (
    MeanReversionStrategy,
    TrendFollowingStrategy,
    OpeningRangeBreakoutStrategy,
    Signal,
    create_signal,
)
from src.ingestion.broker_interface import Tick, OrderSide, OrderStatus, OrderType
from src.execution.paper_trading import PaperTradingEngine
from src.execution.position_sizer import PositionSizer
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("PaperSimulation")

# ─── Realistic NSE stock profiles ────────────────────────────────────────────

STOCK_PROFILES = {
    "RELIANCE":   {"base": 2450, "volatility": 0.012, "volume_base": 50000, "sector": "Energy"},
    "TCS":        {"base": 3550, "volatility": 0.010, "volume_base": 30000, "sector": "IT"},
    "HDFCBANK":   {"base": 1620, "volatility": 0.009, "volume_base": 60000, "sector": "Banking"},
    "INFY":       {"base": 1480, "volatility": 0.011, "volume_base": 40000, "sector": "IT"},
    "ICICIBANK":  {"base": 1050, "volatility": 0.010, "volume_base": 55000, "sector": "Banking"},
    "HINDUNILVR": {"base": 2380, "volatility": 0.007, "volume_base": 20000, "sector": "FMCG"},
    "ITC":        {"base": 435,  "volatility": 0.008, "volume_base": 80000, "sector": "FMCG"},
    "SBIN":       {"base": 780,  "volatility": 0.013, "volume_base": 90000, "sector": "Banking"},
    "BHARTIARTL": {"base": 1150, "volatility": 0.011, "volume_base": 35000, "sector": "Telecom"},
    "KOTAKBANK":  {"base": 1780, "volatility": 0.009, "volume_base": 25000, "sector": "Banking"},
}

# News headlines for sentiment simulation
NEWS_TEMPLATES = {
    "BULLISH": [
        "{symbol}: Strong quarterly results beat street estimates",
        "{symbol}: FII buying continues, stock hits 52-week high",
        "{symbol}: Upgraded to BUY by major brokerage",
        "{symbol}: New product launch expected to boost revenue",
        "{symbol}: Management raises full-year guidance",
    ],
    "BEARISH": [
        "{symbol}: Profit margins under pressure from rising costs",
        "{symbol}: Key executive departure raises concerns",
        "{symbol}: Downgraded by analysts on valuation concerns",
        "{symbol}: Regulatory headwinds may impact growth",
        "{symbol}: Weak demand outlook for next quarter",
    ],
    "NEUTRAL": [
        "{symbol}: Trading flat ahead of quarterly results",
        "{symbol}: Sector rotation keeps stock range-bound",
        "{symbol}: Mixed signals from global markets",
    ],
}

NEWS_SOURCES = ["MoneyControl", "Economic Times", "LiveMint", "Business Standard", "CNBC-TV18"]


# ─── Market Data Generator ───────────────────────────────────────────────────

class MarketDataGenerator:
    """Generates realistic synthetic tick data using geometric Brownian motion."""

    def __init__(self, symbols: List[str], seed: int = 42):
        self._rng = np.random.default_rng(seed)
        self._prices: Dict[str, float] = {}
        self._cum_volumes: Dict[str, int] = {}
        self._intraday_trends: Dict[str, float] = {}

        for sym in symbols:
            profile = STOCK_PROFILES.get(sym, {"base": 1000, "volatility": 0.01, "volume_base": 30000})
            # Randomize starting price within ±3% of base
            self._prices[sym] = profile["base"] * (1 + self._rng.uniform(-0.03, 0.03))
            self._cum_volumes[sym] = 0
        self._patterns: Dict = {}

    def reset_day(self, date: datetime):
        """Reset daily state — reset prices to realistic base with gap, new intraday trend."""
        for sym in self._prices:
            profile = STOCK_PROFILES.get(sym, {"base": 1000, "volatility": 0.01, "volume_base": 30000})
            # Reset to base price with a small daily gap (±1.5%) to prevent compounding drift
            gap = self._rng.normal(0, 0.008)
            self._prices[sym] = profile["base"] * (1 + gap)
            # Each day has a slight directional bias
            self._intraday_trends[sym] = self._rng.normal(0, 0.002)
            self._cum_volumes[sym] = 0
        self._patterns = {}

    def generate_tick(self, symbol: str, timestamp: datetime) -> Tick:
        """Generate a single tick with realistic price movement and occasional patterns."""
        profile = STOCK_PROFILES.get(symbol, {"base": 1000, "volatility": 0.01, "volume_base": 30000})
        vol = profile["volatility"]

        # Time-of-day volume pattern (U-shaped: high at open/close, low midday)
        minutes_from_open = (timestamp.hour - 9) * 60 + timestamp.minute - 15
        total_minutes = 375  # 9:15 to 15:30
        t_norm = max(0, min(1, minutes_from_open / total_minutes))
        volume_multiplier = 2.0 - 1.5 * math.sin(math.pi * t_norm)  # U-shape

        # Inject occasional patterns to trigger strategies
        pattern_key = (symbol, timestamp.strftime("%Y%m%d"))
        if pattern_key not in self._patterns:
            # Decide pattern for this symbol-day:
            # 20% dip-and-recover (mean reversion), 15% momentum, 25% choppy, 40% normal
            r = self._rng.random()
            if r < 0.20:
                dip_start = self._rng.integers(60, 200)
                self._patterns[pattern_key] = ("dip", dip_start)
            elif r < 0.35:
                mom_start = self._rng.integers(30, 150)
                self._patterns[pattern_key] = ("momentum", mom_start)
            elif r < 0.60:
                # Choppy: random reversals that whipsaw strategies
                self._patterns[pattern_key] = ("choppy", 0)
            else:
                self._patterns[pattern_key] = ("normal", 0)

        pattern_type, pattern_start = self._patterns[pattern_key]

        # Apply pattern-based drift
        drift = self._intraday_trends.get(symbol, 0) / total_minutes
        extra_drift = 0.0

        if pattern_type == "dip" and abs(minutes_from_open - pattern_start) < 30:
            phase = minutes_from_open - pattern_start
            if phase < 0:
                pass
            elif phase < 15:
                # Sharp drop phase
                extra_drift = -vol * 1.2
                volume_multiplier *= 2.0
            else:
                # Recovery phase
                extra_drift = vol * 0.8
                volume_multiplier *= 1.5

        elif pattern_type == "momentum" and minutes_from_open > pattern_start:
            duration = minutes_from_open - pattern_start
            if duration < 40:
                # Moderate uptrend, decaying over time
                extra_drift = vol * 0.25 * max(0, 1 - duration / 60)
                volume_multiplier *= 1.2
            elif duration < 60:
                # Momentum fades, slight pullback
                extra_drift = -vol * 0.1
                volume_multiplier *= 0.9

        elif pattern_type == "choppy":
            # Random direction changes every ~10 minutes to whipsaw
            phase = (minutes_from_open // 10) % 4
            if phase == 0:
                extra_drift = vol * 0.3
            elif phase == 1:
                extra_drift = -vol * 0.4
            elif phase == 2:
                extra_drift = vol * 0.2
            else:
                extra_drift = -vol * 0.15
            volume_multiplier *= 0.8

        # GBM step with pattern drift + mean-reversion anchor
        shock = self._rng.normal(0, vol / math.sqrt(total_minutes))
        price_change = self._prices[symbol] * (drift + extra_drift + shock)
        self._prices[symbol] = max(1.0, self._prices[symbol] + price_change)

        # Mean-revert toward base price to prevent unrealistic drift (max ±5% from base)
        base = STOCK_PROFILES.get(symbol, {"base": 1000})["base"]
        deviation = (self._prices[symbol] - base) / base
        if abs(deviation) > 0.03:
            revert_force = -deviation * 0.02 * base
            self._prices[symbol] += revert_force

        # Volume per tick
        tick_volume = max(1, int(self._rng.poisson(profile["volume_base"] * volume_multiplier / 60)))
        self._cum_volumes[symbol] = self._cum_volumes.get(symbol, 0) + tick_volume

        return Tick(
            symbol=symbol,
            token=hash(symbol) % 100000,
            ltp=round(self._prices[symbol], 2),
            volume=tick_volume,
            timestamp=timestamp,
            exchange="NSE",
        )

    def get_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)


# ─── Real Market Data Generator (yfinance) ───────────────────────────────────

class RealMarketDataGenerator:
    """Replays real historical intraday data from Yahoo Finance as ticks.

    Downloads 1-minute OHLCV data for NSE stocks (via .NS suffix) and replays
    each bar as a tick.  Data is cached locally under ``data/market_cache/`` so
    subsequent runs don't re-download.

    Falls back to the synthetic ``MarketDataGenerator`` for any symbol/day where
    real data is unavailable.
    """

    CACHE_DIR = Path(PROJECT_ROOT) / "data" / "market_cache"
    # yfinance allows up to 7 days of 1m data per request, 60 days total
    YF_SUFFIX = ".NS"

    def __init__(self, symbols: List[str], seed: int = 42):
        self._symbols = symbols
        self._rng = np.random.default_rng(seed)
        self._prices: Dict[str, float] = {}
        self._cum_volumes: Dict[str, int] = {}
        # Per-symbol per-day: list of (timestamp, open, high, low, close, volume)
        self._day_bars: Dict[str, List[Dict]] = {}
        self._bar_index: Dict[str, int] = {}
        # Synthetic fallback
        self._fallback = MarketDataGenerator(symbols, seed)
        self._using_fallback: Dict[str, bool] = {}
        # Ensure cache dir exists
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Pre-download data for all symbols
        self._all_data: Dict[str, pd.DataFrame] = {}
        self._download_all()

    # ── Download helpers ──────────────────────────────────────────────────

    def _download_all(self):
        """Download intraday data for all symbols (cached)."""
        for sym in self._symbols:
            ticker = sym + self.YF_SUFFIX
            cache_file = self.CACHE_DIR / f"{sym}_1m.parquet"

            # Use cache if fresh (< 12 hours old)
            if cache_file.exists():
                age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
                if age_hours < 12:
                    try:
                        df = pd.read_parquet(cache_file)
                        if len(df) > 0:
                            self._all_data[sym] = df
                            logger.info(f"[RealData] Loaded {len(df)} bars from cache for {sym}")
                            continue
                    except Exception:
                        pass

            # Download from yfinance — max 7 days of 1m data per call
            try:
                logger.info(f"[RealData] Downloading 1m data for {ticker} ...")
                yf_ticker = yf.Ticker(ticker)
                df = yf_ticker.history(period="5d", interval="1m")
                if df is not None and len(df) > 100:
                    # Normalize columns
                    df = df.reset_index()
                    # yfinance returns 'Datetime' or 'Date' column
                    dt_col = "Datetime" if "Datetime" in df.columns else "Date"
                    df = df.rename(columns={dt_col: "datetime"})
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    # Remove timezone info for simpler handling
                    if df["datetime"].dt.tz is not None:
                        df["datetime"] = df["datetime"].dt.tz_localize(None)
                    df = df[["datetime", "Open", "High", "Low", "Close", "Volume"]].copy()
                    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
                    df = df.dropna()
                    # Save cache
                    df.to_parquet(cache_file, index=False)
                    self._all_data[sym] = df
                    logger.info(f"[RealData] Got {len(df)} bars for {sym}")
                else:
                    logger.warning(f"[RealData] No data for {ticker}, will use synthetic fallback")
            except Exception as e:
                logger.warning(f"[RealData] Failed to download {ticker}: {e}, using synthetic fallback")

    def _get_day_data(self, symbol: str, date: datetime) -> Optional[List[Dict]]:
        """Extract bars for a specific date from the downloaded data."""
        if symbol not in self._all_data:
            return None
        df = self._all_data[symbol]
        day_str = date.strftime("%Y-%m-%d")
        mask = df["datetime"].dt.strftime("%Y-%m-%d") == day_str
        day_df = df[mask].sort_values("datetime")
        if len(day_df) < 30:  # Need at least 30 bars for a meaningful day
            return None
        return day_df.to_dict("records")

    # ── Public interface (same as MarketDataGenerator) ────────────────────

    def reset_day(self, date: datetime):
        """Load real data for this date, or fall back to synthetic."""
        self._fallback.reset_day(date)
        for sym in self._symbols:
            bars = self._get_day_data(sym, date)
            if bars:
                self._day_bars[sym] = bars
                self._bar_index[sym] = 0
                self._prices[sym] = bars[0]["open"]
                self._cum_volumes[sym] = 0
                self._using_fallback[sym] = False
                logger.info(f"[RealData] {sym} {date.strftime('%Y-%m-%d')}: {len(bars)} real bars")
            else:
                self._day_bars[sym] = []
                self._bar_index[sym] = 0
                self._using_fallback[sym] = True
                self._prices[sym] = self._fallback.get_price(sym)
                self._cum_volumes[sym] = 0

    def generate_tick(self, symbol: str, timestamp: datetime) -> Tick:
        """Return a tick from real data or fall back to synthetic."""
        if self._using_fallback.get(symbol, True):
            tick = self._fallback.generate_tick(symbol, timestamp)
            self._prices[symbol] = tick.ltp
            return tick

        bars = self._day_bars.get(symbol, [])
        idx = self._bar_index.get(symbol, 0)

        if idx >= len(bars):
            # Exhausted real bars — hold last price
            price = self._prices.get(symbol, 0)
            return Tick(
                symbol=symbol,
                token=hash(symbol) % 100000,
                ltp=round(price, 2),
                volume=0,
                timestamp=timestamp,
                exchange="NSE",
            )

        bar = bars[idx]

        # Advance bar index based on simulated time matching real bar time
        # Each bar is 1 minute; advance when sim time passes the bar's timestamp
        bar_time = bar["datetime"]
        if isinstance(bar_time, pd.Timestamp):
            bar_time = bar_time.to_pydatetime()
        # Replace date portion to match simulation date (real data may be from different date)
        bar_time = timestamp.replace(
            hour=bar_time.hour, minute=bar_time.minute, second=bar_time.second
        )

        if timestamp >= bar_time + timedelta(minutes=1):
            self._bar_index[symbol] = min(idx + 1, len(bars) - 1)
            idx = self._bar_index[symbol]
            bar = bars[idx]

        # Interpolate within the bar: simulate tick as a point between OHLC
        # Use a simple pattern: O → H → L → C within each minute
        seconds_in_bar = timestamp.second % 60
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        if seconds_in_bar < 15:
            price = o + (h - o) * (seconds_in_bar / 15)
        elif seconds_in_bar < 30:
            price = h + (l - h) * ((seconds_in_bar - 15) / 15)
        elif seconds_in_bar < 45:
            price = l + (c - l) * ((seconds_in_bar - 30) / 15)
        else:
            # Add small noise near close
            noise = self._rng.normal(0, abs(c - o) * 0.01 + 0.01)
            price = c + noise

        price = max(0.01, round(price, 2))
        self._prices[symbol] = price

        # Volume: distribute bar volume across ticks (12 ticks per minute at 5s interval)
        bar_vol = int(bar.get("volume", 0))
        tick_vol = max(1, bar_vol // 12 + int(self._rng.integers(0, max(1, bar_vol // 50))))
        self._cum_volumes[symbol] = self._cum_volumes.get(symbol, 0) + tick_vol

        return Tick(
            symbol=symbol,
            token=hash(symbol) % 100000,
            ltp=price,
            volume=tick_vol,
            timestamp=timestamp,
            exchange="NSE",
        )

    def get_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)


# ─── Sentiment / Bias Simulator ──────────────────────────────────────────────

class SentimentSimulator:
    """Generates synthetic news and bias data with per-symbol daily regimes.

    Each trading day, every symbol is assigned a sentiment regime:
      - BULLISH (30%): 70% bullish articles, 15% neutral, 15% bearish
      - BEARISH (30%): 70% bearish articles, 15% neutral, 15% bullish
      - NEUTRAL (40%): 35% bullish, 35% bearish, 30% neutral

    This creates realistic clustering where some stocks have strong directional
    sentiment that actually triggers the bias filter on signals.
    """

    # Per-regime article sentiment probabilities [BULLISH, BEARISH, NEUTRAL]
    REGIME_PROBS = {
        "BULLISH": [0.70, 0.15, 0.15],
        "BEARISH": [0.15, 0.70, 0.15],
        "NEUTRAL": [0.35, 0.35, 0.30],
    }

    def __init__(self, symbols: List[str], rng: np.random.Generator):
        self._symbols = symbols
        self._rng = rng
        self._article_counter = 5000
        # Per-symbol daily regime — assigned in reset_day()
        self._regimes: Dict[str, str] = {}

    def reset_day(self):
        """Assign fresh sentiment regimes for each symbol for the new day."""
        for sym in self._symbols:
            self._regimes[sym] = str(self._rng.choice(
                ["BULLISH", "BEARISH", "NEUTRAL"], p=[0.30, 0.30, 0.40]
            ))
        regime_summary = {s: r for s, r in self._regimes.items() if r != "NEUTRAL"}
        if regime_summary:
            logger.info(f"[Sentiment] Daily regimes: {regime_summary}")

    def generate_news_batch(self, timestamp: datetime) -> List[Dict[str, Any]]:
        """Generate a batch of 3-8 news articles, biased by per-symbol regime."""
        articles = []
        count = self._rng.integers(3, 9)
        for _ in range(count):
            symbol = str(self._rng.choice(self._symbols))
            regime = self._regimes.get(symbol, "NEUTRAL")
            probs = self.REGIME_PROBS[regime]
            sentiment = str(self._rng.choice(["BULLISH", "BEARISH", "NEUTRAL"], p=probs))

            templates = NEWS_TEMPLATES[sentiment]
            title = self._rng.choice(templates).format(symbol=symbol)

            # Stronger scores for regime-aligned articles
            if sentiment == "BULLISH":
                raw_score = self._rng.uniform(0.15, 0.55)
            elif sentiment == "BEARISH":
                raw_score = self._rng.uniform(-0.55, -0.15)
            else:
                raw_score = self._rng.uniform(-0.08, 0.08)

            boost = self._rng.uniform(0.02, 0.18) * (
                1 if sentiment == "BULLISH" else -1 if sentiment == "BEARISH" else 0
            )
            self._article_counter += 1
            articles.append({
                "article_id": f"ART{self._article_counter}",
                "ticker": symbol,
                "sentiment": sentiment,
                "confidence": round(float(self._rng.uniform(0.55, 0.95)), 3),
                "raw_score": round(float(raw_score), 3),
                "boosted_score": round(float(raw_score + boost), 3),
                "news_title": title,
                "news_source": str(self._rng.choice(NEWS_SOURCES)),
                "created_at": timestamp.isoformat(),
            })
        return articles

    def compute_bias(self, symbol: str, articles: List[Dict]) -> Dict[str, Any]:
        """Compute bias from recent articles for a symbol."""
        sym_articles = [a for a in articles if a["ticker"] == symbol]
        if not sym_articles:
            return {"ticker": symbol, "bias": "NEUTRAL", "score": 0.0, "confidence": 0.5, "article_count": 0}
        # Use only the most recent 20 articles per symbol for sharper signal
        recent = sym_articles[-20:]
        avg_score = np.mean([a["boosted_score"] for a in recent])
        avg_conf = np.mean([a["confidence"] for a in recent])
        bias = "BULLISH" if avg_score > 0.12 else ("BEARISH" if avg_score < -0.12 else "NEUTRAL")
        return {
            "ticker": symbol,
            "bias": bias,
            "score": round(float(avg_score), 3),
            "confidence": round(float(avg_conf), 3),
            "article_count": len(recent),
        }


# ─── Database Writer ─────────────────────────────────────────────────────────

class SimulationDB:
    """Writes simulation data directly to the production SQLite DB."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        from src.state.database_schema import get_sqlite_schema
        self._conn.executescript(get_sqlite_schema())
        self._conn.commit()

    def clear_simulation_data(self):
        """Clear previous simulation data."""
        for table in ["trades", "orders", "sentiment_log", "bias_log", "audit_log"]:
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()
        logger.info("Cleared previous simulation data")

    def insert_trade(self, trade: Dict[str, Any]):
        self._conn.execute(
            "INSERT INTO trades (trade_id, symbol, side, strategy, entry_price, quantity, "
            "entry_time, stop_loss, target) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade["trade_id"], trade["symbol"], trade["side"], trade["strategy"],
             trade["entry_price"], trade["quantity"], trade["entry_time"],
             trade["stop_loss"], trade["target"]),
        )
        self._conn.commit()

    def close_trade(self, trade_id: str, exit_price: float, exit_time: str,
                    realized_pnl: float, exit_reason: str):
        self._conn.execute(
            "UPDATE trades SET exit_price=?, exit_time=?, realized_pnl=?, exit_reason=? "
            "WHERE trade_id=?",
            (exit_price, exit_time, realized_pnl, exit_reason, trade_id),
        )
        self._conn.commit()

    def insert_order(self, order: Dict[str, Any]):
        self._conn.execute(
            "INSERT INTO orders (order_id, trade_id, symbol, side, order_type, quantity, "
            "price, trigger_price, status, broker_order_id, filled_qty, filled_price, "
            "rejection_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order["order_id"], order.get("trade_id"), order["symbol"], order["side"],
             order["order_type"], order["quantity"], order.get("price"),
             order.get("trigger_price"), order["status"], order.get("broker_order_id"),
             order.get("filled_qty", 0), order.get("filled_price"),
             order.get("rejection_reason"), order["created_at"], order["updated_at"]),
        )
        self._conn.commit()

    def insert_news(self, article: Dict[str, Any]):
        self._conn.execute(
            "INSERT INTO sentiment_log (article_id, ticker, sentiment, confidence, "
            "raw_score, boosted_score, news_title, news_source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (article["article_id"], article["ticker"], article["sentiment"],
             article["confidence"], article["raw_score"], article["boosted_score"],
             article["news_title"], article["news_source"], article["created_at"]),
        )
        self._conn.commit()

    def insert_bias(self, bias: Dict[str, Any], timestamp: str):
        self._conn.execute(
            "INSERT INTO bias_log (ticker, bias, score, confidence, article_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (bias["ticker"], bias["bias"], bias["score"], bias["confidence"],
             bias["article_count"], timestamp),
        )
        self._conn.commit()

    def insert_audit(self, event_type: str, component: str, message: str,
                     metadata: Optional[str] = None, timestamp: Optional[str] = None):
        self._conn.execute(
            "INSERT INTO audit_log (event_type, component, message, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_type, component, message, metadata, timestamp or datetime.now().isoformat()),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()


# ─── Redis Publisher ─────────────────────────────────────────────────────────

class RedisPublisher:
    """Publishes simulation events to Redis streams for the gateway."""

    def __init__(self):
        self._redis = None
        try:
            import redis
            self._redis = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
            self._redis.ping()
            logger.info("Redis connected for live event publishing")
        except Exception as e:
            logger.warning(f"Redis not available, skipping live events: {e}")
            self._redis = None

    def publish_tick(self, tick: Tick):
        if not self._redis:
            return
        try:
            self._redis.xadd(f"stream:ticks:{tick.symbol}", {
                "symbol": tick.symbol, "ltp": str(tick.ltp),
                "volume": str(tick.volume), "timestamp": tick.timestamp.isoformat(),
            }, maxlen=500)
        except Exception:
            pass

    def publish_signal(self, signal_data: Dict):
        if not self._redis:
            return
        try:
            self._redis.xadd("stream:signals", {k: str(v) for k, v in signal_data.items()}, maxlen=200)
        except Exception:
            pass

    def publish_position_update(self, data: Dict):
        if not self._redis:
            return
        try:
            self._redis.xadd("stream:positions", {k: str(v) for k, v in data.items()}, maxlen=200)
        except Exception:
            pass

    def publish_bias(self, data: Dict):
        if not self._redis:
            return
        try:
            self._redis.xadd(f"stream:bias:{data['ticker']}", {k: str(v) for k, v in data.items()}, maxlen=100)
        except Exception:
            pass


# ─── Position Tracker (lightweight, no broker dependency) ────────────────────

@dataclass
class SimPosition:
    """Lightweight position for simulation."""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    trailing_stop: float
    strategy: str
    entry_time: datetime
    current_price: float = 0.0
    unrealized_pnl: float = 0.0

    def update_price(self, price: float):
        self.current_price = price
        if self.side == "BUY":
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
            # Trailing stop: move up by 50% of profit
            if price > self.entry_price:
                new_stop = self.entry_price + 0.5 * (price - self.entry_price)
                if new_stop > self.trailing_stop:
                    self.trailing_stop = new_stop
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity
            if price < self.entry_price:
                new_stop = self.entry_price - 0.5 * (self.entry_price - price)
                if new_stop < self.trailing_stop:
                    self.trailing_stop = new_stop

    def check_exit(self, price: float) -> Optional[str]:
        """Check if position should exit. Returns exit reason or None."""
        if self.side == "BUY":
            if price <= self.trailing_stop:
                return "STOP_LOSS"
            if price >= self.target:
                return "TARGET"
        else:
            if price >= self.trailing_stop:
                return "STOP_LOSS"
            if price <= self.target:
                return "TARGET"
        return None


# ─── Main Simulation Engine ──────────────────────────────────────────────────

class PaperSimulation:
    """Orchestrates the full paper trading simulation."""

    def __init__(self, config, db: SimulationDB, redis_pub: RedisPublisher,
                 speed: float = 1.0, days: int = 5, use_real_data: bool = False):
        self._config = config
        self._db = db
        self._redis = redis_pub
        self._speed = speed
        self._days = days
        self._use_real_data = use_real_data

        self._symbols = config.symbols[:8]  # Use first 8 symbols
        self._capital = config.capital.total
        self._risk_pct = config.capital.risk_per_trade_pct
        self._max_positions = config.risk_limits.max_open_positions
        self._max_orders_day = config.risk_limits.max_orders_per_day
        self._max_daily_loss_pct = config.capital.max_daily_loss_pct

        # Components — use real data generator if requested
        if use_real_data:
            logger.info("Using REAL historical market data from Yahoo Finance")
            self._market = RealMarketDataGenerator(self._symbols)
        else:
            self._market = MarketDataGenerator(self._symbols)
        self._candle_builder = CandleBuilder(timeframes=["1m", "5m"])
        self._indicator_engine = IndicatorEngine()
        self._sentiment = SentimentSimulator(self._symbols, np.random.default_rng(123))

        # Register candle completion callback
        self._pending_indicators: List[IndicatorSet] = []
        self._candle_builder.on_candle_complete(self._on_candle_complete)

        # Strategy setup
        self._strategies = []
        if config.strategies.mean_reversion.enabled:
            self._strategies.append(MeanReversionStrategy(config.strategies.mean_reversion))
        if config.strategies.trend_following.enabled:
            self._strategies.append(TrendFollowingStrategy(config.strategies.trend_following))
        if config.strategies.opening_range_breakout.enabled:
            self._strategies.append(OpeningRangeBreakoutStrategy(config.strategies.opening_range_breakout))

        # Position sizer
        self._position_sizer = PositionSizer(config)

        # Paper trading engine
        self._paper_engine = PaperTradingEngine(config.paper_trading)

        # State
        self._open_positions: Dict[str, SimPosition] = {}
        self._all_news: List[Dict] = []
        self._daily_pnl = 0.0
        self._daily_orders = 0
        self._total_trades = 0
        self._total_pnl = 0.0
        self._wins = 0
        self._losses = 0
        self._kill_switch_active = False

        # Track symbols with open positions to prevent duplicates
        self._position_symbols: set = set()

    def _on_candle_complete(self, candle: Candle):
        """Callback when a candle completes — compute indicators."""
        if candle.timeframe != "1m":
            return
        indicators = self._indicator_engine.add_candle(candle)
        if indicators:
            self._pending_indicators.append(indicators)

    def run(self):
        """Run the full simulation."""
        data_source = "REAL (Yahoo Finance)" if self._use_real_data else "Synthetic (GBM)"
        print("\n" + "=" * 70)
        print("  LOHI-TRADE Paper Trading Simulation")
        print(f"  Capital: ₹{self._capital:,.0f} | Symbols: {len(self._symbols)}")
        print(f"  Data Source: {data_source}")
        print(f"  Strategies: {', '.join(s.name for s in self._strategies)}")
        print(f"  Days: {self._days} | Speed: {self._speed}x")
        print("=" * 70 + "\n")

        self._db.clear_simulation_data()
        self._db.insert_audit("INFO", "simulation", "Paper trading simulation started",
                              json.dumps({"capital": self._capital, "days": self._days,
                                          "data_source": data_source}))

        if self._use_real_data:
            # Use actual trading dates from the downloaded data
            trading_dates = self._get_real_trading_dates()
        else:
            trading_dates = []

        if self._use_real_data and trading_dates:
            # Replay real trading dates (up to self._days)
            for date in trading_dates[:self._days]:
                self._simulate_day(date)
        else:
            # Synthetic mode: generate dates going back from today
            start_date = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=self._days)
            for day_offset in range(self._days):
                current_date = start_date + timedelta(days=day_offset)
                if current_date.weekday() >= 5:
                    continue
                self._simulate_day(current_date)

        self._print_summary()

    def _get_real_trading_dates(self) -> List[datetime]:
        """Extract unique trading dates from downloaded real data."""
        if not isinstance(self._market, RealMarketDataGenerator):
            return []
        all_dates = set()
        for sym, df in self._market._all_data.items():
            dates = df["datetime"].dt.normalize().unique()
            for d in dates:
                all_dates.add(pd.Timestamp(d).to_pydatetime().replace(hour=9, minute=15, second=0, microsecond=0))
        return sorted(all_dates)

    def _simulate_day(self, date: datetime):
        """Simulate one full trading day."""
        self._daily_pnl = 0.0
        self._daily_orders = 0
        self._kill_switch_active = False
        self._candle_builder.reset()
        self._indicator_engine.reset()  # Reset indicator state between days

        self._market.reset_day(date)
        self._sentiment.reset_day()  # Assign fresh sentiment regimes per symbol

        day_str = date.strftime("%Y-%m-%d")
        print(f"\n{'─' * 50}")
        print(f"  📅 {day_str} ({date.strftime('%A')})")
        print(f"{'─' * 50}")

        self._db.insert_audit("INFO", "simulation", f"Trading day started: {day_str}",
                              timestamp=date.replace(hour=9, minute=15).isoformat())

        # Generate pre-market news burst (larger batch to establish initial bias)
        for _ in range(3):
            pre_market_news = self._sentiment.generate_news_batch(date.replace(hour=8, minute=30))
            for article in pre_market_news:
                self._db.insert_news(article)
                self._all_news.append(article)

        # Compute and store initial bias
        for sym in self._symbols:
            bias = self._sentiment.compute_bias(sym, self._all_news[-50:])
            self._db.insert_bias(bias, date.replace(hour=9, minute=0).isoformat())
            self._redis.publish_bias(bias)

        # Market hours: 9:15 to 15:30 (375 minutes)
        market_open = date.replace(hour=9, minute=15, second=0)
        market_close = date.replace(hour=15, minute=30, second=0)
        square_off_time = date.replace(hour=15, minute=15, second=0)

        # ORB: capture opening range (9:15-9:30)
        orb_ranges: Dict[str, Tuple[float, float]] = {}

        current_time = market_open
        tick_interval = timedelta(seconds=5)  # One tick every 5 seconds per symbol
        candles_completed = 0
        signals_generated = 0

        while current_time <= market_close:
            if self._kill_switch_active:
                break

            # Generate ticks for all symbols
            for sym in self._symbols:
                tick = self._market.generate_tick(sym, current_time)
                self._redis.publish_tick(tick)
                self._candle_builder.process_tick(tick)

                # Track ORB range
                if current_time < date.replace(hour=9, minute=30):
                    if sym not in orb_ranges:
                        orb_ranges[sym] = (tick.ltp, tick.ltp)
                    else:
                        h, l = orb_ranges[sym]
                        orb_ranges[sym] = (max(h, tick.ltp), min(l, tick.ltp))
                elif current_time == date.replace(hour=9, minute=30):
                    # Set ORB ranges on strategies
                    for strat in self._strategies:
                        if isinstance(strat, OpeningRangeBreakoutStrategy):
                            for s, (h, l) in orb_ranges.items():
                                strat.set_opening_range(s, h, l)

                # Update open positions
                self._update_positions(sym, tick.ltp, current_time)

            # Process any completed candle indicators and try signals
            while self._pending_indicators:
                indicators = self._pending_indicators.pop(0)
                candles_completed += 1
                signal = self._try_generate_signal(indicators, indicators.symbol, current_time)
                if signal:
                    signals_generated += 1

            # Square off at 15:15
            if current_time >= square_off_time and self._open_positions:
                self._square_off_all(current_time)

            # Generate news every ~15 simulated minutes
            minutes_elapsed = (current_time - market_open).total_seconds() / 60
            if int(minutes_elapsed) % 15 == 0 and current_time.second == 0:
                news_batch = self._sentiment.generate_news_batch(current_time)
                for article in news_batch:
                    self._db.insert_news(article)
                    self._all_news.append(article)

                # Recompute bias every 30 min
                for sym in self._symbols:
                    bias = self._sentiment.compute_bias(sym, self._all_news[-100:])
                    self._db.insert_bias(bias, current_time.isoformat())
                    self._redis.publish_bias(bias)

            # Check daily loss kill switch
            if self._daily_pnl < -(self._capital * self._max_daily_loss_pct / 100):
                self._kill_switch_active = True
                self._db.insert_audit("ERROR", "kill_switch",
                    f"Kill switch activated: daily loss ₹{self._daily_pnl:,.0f} exceeds limit",
                    timestamp=current_time.isoformat())
                print(f"  🛑 KILL SWITCH: Daily loss ₹{self._daily_pnl:,.0f}")
                self._square_off_all(current_time)

            # Advance time
            current_time += tick_interval

            # Sleep for real-time feel (adjusted by speed)
            if self._speed < 100:
                time.sleep(0.01 / self._speed)

        # End of day: force close any remaining positions
        if self._open_positions:
            self._square_off_all(market_close)

        # Clear ORB ranges
        for strat in self._strategies:
            if isinstance(strat, OpeningRangeBreakoutStrategy):
                strat.clear_opening_ranges()

        self._db.insert_audit("INFO", "simulation",
            f"Day ended: P&L ₹{self._daily_pnl:,.0f}, Orders: {self._daily_orders}",
            timestamp=market_close.isoformat())

        print(f"  📊 Day P&L: {'₹' + f'{self._daily_pnl:+,.0f}' if self._daily_pnl != 0 else '₹0'} | "
              f"Trades: {self._daily_orders} | Signals: {signals_generated}")

    def _try_generate_signal(self, indicators: IndicatorSet, symbol: str,
                             timestamp: datetime) -> Optional[Signal]:
        """Try to generate a signal from indicators."""
        if self._kill_switch_active:
            return None
        if len(self._open_positions) >= self._max_positions:
            return None
        if self._daily_orders >= self._max_orders_day:
            return None
        if symbol in self._position_symbols:
            return None

        # Check trading hours (9:30 - 15:10)
        current_min = timestamp.hour * 60 + timestamp.minute
        if current_min < 9 * 60 + 30 or current_min > 15 * 60 + 10:
            return None

        # Build candle DataFrame for strategies
        candle_window = self._indicator_engine._candle_windows.get((symbol, "1m"), [])
        if len(candle_window) < 26:
            return None

        df = self._indicator_engine._candles_to_dataframe(candle_window)

        # Try each strategy
        for strategy in self._strategies:
            signal = strategy.generate_signal(indicators, df)
            if signal:
                # Check bias filter
                recent_bias = self._get_latest_bias(symbol)
                if recent_bias:
                    if signal.side == "BUY" and recent_bias == "BEARISH":
                        print(f"  🚫 BIAS BLOCK: {symbol} BUY rejected — BEARISH sentiment [{signal.strategy}]")
                        self._db.insert_audit("INFO", "rms",
                            f"Signal rejected: {symbol} BUY blocked by BEARISH bias",
                            timestamp=timestamp.isoformat())
                        continue
                    if signal.side == "SELL" and recent_bias == "BULLISH":
                        print(f"  🚫 BIAS BLOCK: {symbol} SELL rejected — BULLISH sentiment [{signal.strategy}]")
                        self._db.insert_audit("INFO", "rms",
                            f"Signal rejected: {symbol} SELL blocked by BULLISH bias",
                            timestamp=timestamp.isoformat())
                        continue

                # Position sizing
                size_result = self._position_sizer.calculate_quantity(signal)
                if not size_result.is_valid:
                    continue

                signal.quantity = size_result.quantity
                self._execute_paper_trade(signal, timestamp)

                self._redis.publish_signal({
                    "symbol": signal.symbol, "strategy": signal.strategy,
                    "side": signal.side, "price": signal.entry_price,
                    "timestamp": timestamp.isoformat(),
                })

                return signal

        return None

    def _get_latest_bias(self, symbol: str) -> Optional[str]:
        """Get latest bias for a symbol from recent news (last ~30 articles per symbol)."""
        sym_articles = [a for a in self._all_news if a["ticker"] == symbol][-30:]
        if not sym_articles:
            return None
        avg_score = np.mean([a["boosted_score"] for a in sym_articles])
        if avg_score > 0.12:
            return "BULLISH"
        elif avg_score < -0.12:
            return "BEARISH"
        return "NEUTRAL"

    def _execute_paper_trade(self, signal: Signal, timestamp: datetime):
        """Execute a paper trade from a signal."""
        trade_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"

        # Apply paper trading slippage
        slippage = signal.entry_price * self._paper_engine._config.simulated_slippage_pct / 100
        if signal.side == "BUY":
            fill_price = round(signal.entry_price + slippage, 2)
        else:
            fill_price = round(signal.entry_price - slippage, 2)

        # Create position
        position = SimPosition(
            trade_id=trade_id,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=fill_price,
            quantity=signal.quantity,
            stop_loss=signal.stop_loss,
            target=signal.target,
            trailing_stop=signal.stop_loss,
            strategy=signal.strategy,
            entry_time=timestamp,
            current_price=fill_price,
        )

        self._open_positions[trade_id] = position
        self._position_symbols.add(signal.symbol)

        # Write to DB
        self._db.insert_trade({
            "trade_id": trade_id, "symbol": signal.symbol, "side": signal.side,
            "strategy": signal.strategy, "entry_price": fill_price,
            "quantity": signal.quantity, "entry_time": timestamp.isoformat(),
            "stop_loss": signal.stop_loss, "target": signal.target,
        })

        order_id = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
        self._db.insert_order({
            "order_id": order_id, "trade_id": trade_id, "symbol": signal.symbol,
            "side": signal.side, "order_type": "MARKET", "quantity": signal.quantity,
            "price": fill_price, "status": "FILLED", "broker_order_id": f"PAPER-{order_id}",
            "filled_qty": signal.quantity, "filled_price": fill_price,
            "created_at": timestamp.isoformat(), "updated_at": timestamp.isoformat(),
        })

        self._daily_orders += 1
        self._db.insert_audit("INFO", "soldier",
            f"Position opened: {trade_id} {signal.symbol} {signal.side} "
            f"qty={signal.quantity} @ ₹{fill_price:,.2f} [{signal.strategy}]",
            timestamp=timestamp.isoformat())

        print(f"  {'🟢' if signal.side == 'BUY' else '🔴'} {signal.side} {signal.symbol} "
              f"qty={signal.quantity} @ ₹{fill_price:,.2f} "
              f"SL=₹{signal.stop_loss:,.2f} TGT=₹{signal.target:,.2f} [{signal.strategy}]")

        # Show current holdings summary
        total_shares = sum(p.quantity for p in self._open_positions.values())
        total_invested = sum(p.entry_price * p.quantity for p in self._open_positions.values())
        holdings = ", ".join(f"{p.symbol}×{p.quantity}" for p in self._open_positions.values())
        print(f"    📦 Holdings: {len(self._open_positions)} pos | {total_shares} shares | "
              f"₹{total_invested:,.0f} invested [{holdings}]")

    def _update_positions(self, symbol: str, price: float, timestamp: datetime):
        """Update positions for a symbol and check exits."""
        to_close = []
        for trade_id, pos in self._open_positions.items():
            if pos.symbol != symbol:
                continue
            pos.update_price(price)
            exit_reason = pos.check_exit(price)
            if exit_reason:
                to_close.append((trade_id, price, exit_reason))

        for trade_id, exit_price, reason in to_close:
            self._close_position(trade_id, exit_price, reason, timestamp)

    def _close_position(self, trade_id: str, exit_price: float, reason: str,
                        timestamp: datetime):
        """Close a position and record P&L."""
        pos = self._open_positions.pop(trade_id, None)
        if not pos:
            return

        self._position_symbols.discard(pos.symbol)

        if pos.side == "BUY":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pnl = round(pnl, 2)
        self._daily_pnl += pnl
        self._total_pnl += pnl
        self._total_trades += 1
        if pnl >= 0:
            self._wins += 1
        else:
            self._losses += 1

        self._db.close_trade(trade_id, exit_price, timestamp.isoformat(), pnl, reason)

        # Exit order
        exit_order_id = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
        exit_side = "SELL" if pos.side == "BUY" else "BUY"
        self._db.insert_order({
            "order_id": exit_order_id, "trade_id": trade_id, "symbol": pos.symbol,
            "side": exit_side, "order_type": "MARKET", "quantity": pos.quantity,
            "price": exit_price, "status": "FILLED",
            "broker_order_id": f"PAPER-{exit_order_id}",
            "filled_qty": pos.quantity, "filled_price": exit_price,
            "created_at": timestamp.isoformat(), "updated_at": timestamp.isoformat(),
        })

        emoji = "✅" if pnl >= 0 else "❌"
        self._db.insert_audit(
            "INFO" if pnl >= 0 else "WARNING", "execution",
            f"Position closed: {trade_id} {pos.symbol} {reason} "
            f"P&L=₹{pnl:+,.2f} (entry=₹{pos.entry_price:,.2f} exit=₹{exit_price:,.2f})",
            timestamp=timestamp.isoformat())

        print(f"  {emoji} CLOSE {pos.symbol} [{reason}] P&L: ₹{pnl:+,.2f} "
              f"(₹{pos.entry_price:,.2f} → ₹{exit_price:,.2f})")

        # Show remaining holdings
        if self._open_positions:
            total_shares = sum(p.quantity for p in self._open_positions.values())
            holdings = ", ".join(f"{p.symbol}×{p.quantity}" for p in self._open_positions.values())
            print(f"    📦 Remaining: {len(self._open_positions)} pos | {total_shares} shares [{holdings}]")
        else:
            print(f"    📦 No open positions")

    def _square_off_all(self, timestamp: datetime):
        """Force close all open positions."""
        for trade_id in list(self._open_positions.keys()):
            pos = self._open_positions[trade_id]
            price = self._market.get_price(pos.symbol)
            self._close_position(trade_id, price, "SQUARE_OFF", timestamp)

    def _print_summary(self):
        """Print final simulation summary."""
        win_rate = (self._wins / self._total_trades * 100) if self._total_trades > 0 else 0

        print("\n" + "=" * 70)
        print("  📈 SIMULATION COMPLETE")
        print("=" * 70)
        print(f"  Starting Capital:  ₹{self._capital:>12,.0f}")
        print(f"  Final P&L:         ₹{self._total_pnl:>+12,.2f}")
        print(f"  Return:            {self._total_pnl / self._capital * 100:>+11.2f}%")
        print(f"  Total Trades:      {self._total_trades:>12}")
        print(f"  Wins / Losses:     {self._wins:>5} / {self._losses}")
        print(f"  Win Rate:          {win_rate:>11.1f}%")
        print(f"  Avg P&L per Trade: ₹{(self._total_pnl / max(1, self._total_trades)):>+12,.2f}")
        print("=" * 70)
        print(f"\n  Data written to: {self._db._db_path}")
        print(f"  Open http://localhost:3000 to view results in the dashboard\n")

        self._db.insert_audit("INFO", "simulation",
            f"Simulation complete: P&L=₹{self._total_pnl:+,.2f}, "
            f"Trades={self._total_trades}, WinRate={win_rate:.1f}%")


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOHI-TRADE Paper Trading Simulation")
    parser.add_argument("--speed", type=float, default=50,
                        help="Simulation speed multiplier (default: 50)")
    parser.add_argument("--days", type=int, default=5,
                        help="Number of trading days to simulate (default: 5)")
    parser.add_argument("--capital", type=float, default=None,
                        help="Starting capital (default: from config)")
    parser.add_argument("--db", type=str, default="data/lohi_trade.db",
                        help="SQLite database path")
    parser.add_argument("--real-data", action="store_true", default=False,
                        help="Use real historical data from Yahoo Finance instead of synthetic")
    args = parser.parse_args()

    # Set dummy broker env vars for paper trading (no real broker needed)
    dummy_vars = [
        "SHOONYA_API_KEY", "SHOONYA_CLIENT_ID", "SHOONYA_PASSWORD",
        "ANGELONE_API_KEY", "ANGELONE_CLIENT_ID", "ANGELONE_PASSWORD",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    ]
    for var in dummy_vars:
        if not os.environ.get(var):
            os.environ[var] = "PAPER_MODE_DUMMY"

    # Load config
    config = load_config()

    # Override capital if specified
    if args.capital:
        config.capital.total = args.capital

    # Force paper trading mode
    config.paper_trading.enabled = True

    db = SimulationDB(args.db)
    redis_pub = RedisPublisher()

    sim = PaperSimulation(config, db, redis_pub, speed=args.speed, days=args.days,
                          use_real_data=args.real_data)

    try:
        sim.run()
    except KeyboardInterrupt:
        print("\n\n  Simulation interrupted by user")
    finally:
        db.close()


if __name__ == "__main__":
    main()
