"""Feature Engineering for ML-based trading signals.

Extracts numerical feature vectors from IndicatorSet + sentiment data
for use by the ML model. All features are normalized to prevent scale bias.

Features:
- Technical: RSI, MACD histogram, BB %B, EMA crossover, Supertrend, ATR ratio, volume ratio
- Sentiment: bias score, confidence, article count
- Derived: momentum (price vs VWAP), volatility regime, trend strength
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from src.soldier.indicator_engine import IndicatorSet

logger = logging.getLogger(__name__)

# Feature names in fixed order for model input
FEATURE_NAMES: list[str] = [
    "rsi_14",
    "rsi_zone",           # -1=oversold, 0=neutral, 1=overbought
    "macd_hist",
    "macd_crossover",     # 1=bullish, -1=bearish, 0=flat
    "bb_percent_b",       # (close - lower) / (upper - lower)
    "bb_width",           # (upper - lower) / middle
    "ema_crossover",      # (ema_9 - ema_21) / ema_21
    "supertrend_dir",     # 1=bullish, -1=bearish
    "atr_ratio",          # atr / close price
    "volume_ratio",       # current volume / avg volume
    "momentum",           # (close - vwap) / vwap
    "trend_strength",     # abs(ema_9 - ema_21) / atr
    "volatility_regime",  # bb_width z-score proxy
    "sentiment_score",    # bias score from Commander (-1 to 1)
    "sentiment_confidence",
    "sentiment_article_count",
    # Extended TA features
    "stoch_k",            # Stochastic %K normalized
    "stoch_zone",         # -1=oversold, 0=neutral, 1=overbought
    "adx_strength",       # ADX / 100 (0-1 range)
    "di_crossover",       # (+DI - -DI) / 100
    "williams_r_zone",    # -1=oversold, 0=neutral, 1=overbought
    "cci_zone",           # -1=oversold, 0=neutral, 1=overbought
    "mfi_zone",           # -1=oversold, 0=neutral, 1=overbought
    "psar_direction",     # 1=bullish, -1=bearish
    "ema_trend_alignment",# 1 if ema9>ema21>ema50, -1 if reversed, 0 otherwise
    "ichimoku_cloud_pos", # 1=above cloud, -1=below, 0=inside
    "ichimoku_tk_cross",  # 1=tenkan>kijun, -1=tenkan<kijun
    "pivot_position",     # (close - pivot) / atr
    "confluence_score",   # count of bullish indicators / total
]

NUM_FEATURES = len(FEATURE_NAMES)


@dataclass
class SentimentFeatures:
    """Sentiment data to merge with technical features."""

    score: float = 0.0          # -1.0 (bearish) to 1.0 (bullish)
    confidence: float = 0.0     # 0.0 to 1.0
    article_count: int = 0


@dataclass
class FeatureVector:
    """Complete feature vector for ML model input."""

    symbol: str
    timestamp: datetime
    features: np.ndarray        # shape (NUM_FEATURES,)
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    close_price: float = 0.0    # for reference, not a feature

    def to_dict(self) -> dict[str, float]:
        """Return features as name→value dict."""
        return dict(zip(self.feature_names, self.features.tolist()))


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Safe division avoiding ZeroDivisionError."""
    if b == 0 or np.isnan(b) or np.isinf(b):
        return default
    result = a / b
    return default if np.isnan(result) or np.isinf(result) else result


def _rsi_zone(rsi: float) -> float:
    """Classify RSI into zones: -1=oversold(<30), 0=neutral, 1=overbought(>70)."""
    if rsi < 30:
        return -1.0
    if rsi > 70:
        return 1.0
    return 0.0


def _macd_crossover(macd: float, signal: float) -> float:
    """Detect MACD crossover direction."""
    diff = macd - signal
    if abs(diff) < 1e-6:
        return 0.0
    return 1.0 if diff > 0 else -1.0


def _stoch_zone(stoch_k: float) -> float:
    """Classify Stochastic %K: -1=oversold(<20), 0=neutral, 1=overbought(>80)."""
    if stoch_k < 20:
        return -1.0
    if stoch_k > 80:
        return 1.0
    return 0.0


def _williams_r_zone(wr: float) -> float:
    """Classify Williams %R: -1=oversold(<-80), 0=neutral, 1=overbought(>-20)."""
    if wr < -80:
        return -1.0
    if wr > -20:
        return 1.0
    return 0.0


def _cci_zone(cci: float) -> float:
    """Classify CCI: -1=oversold(<-100), 0=neutral, 1=overbought(>100)."""
    if cci < -100:
        return -1.0
    if cci > 100:
        return 1.0
    return 0.0


def _mfi_zone(mfi: float) -> float:
    """Classify MFI: -1=oversold(<20), 0=neutral, 1=overbought(>80)."""
    if mfi < 20:
        return -1.0
    if mfi > 80:
        return 1.0
    return 0.0


def _ema_trend_alignment(ema_9: float, ema_21: float, ema_50: float) -> float:
    """1 if ema9>ema21>ema50 (bullish stack), -1 if reversed, 0 otherwise."""
    if ema_9 > ema_21 > ema_50:
        return 1.0
    if ema_9 < ema_21 < ema_50:
        return -1.0
    return 0.0


def _ichimoku_cloud_position(close: float, senkou_a: float, senkou_b: float) -> float:
    """1=above cloud, -1=below cloud, 0=inside cloud."""
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    if close > cloud_top:
        return 1.0
    if close < cloud_bottom:
        return -1.0
    return 0.0


def _confluence_score(indicators: "IndicatorSet", close: float) -> float:
    """Count bullish indicators / total (0-1 range)."""
    bullish = 0
    total = 10
    if indicators.ema_9 > indicators.ema_21:
        bullish += 1
    if indicators.supertrend_direction == 1:
        bullish += 1
    if indicators.macd > indicators.macd_signal:
        bullish += 1
    if indicators.rsi_14 > 50:
        bullish += 1
    if close > indicators.vwap:
        bullish += 1
    if indicators.adx > 20 and indicators.plus_di > indicators.minus_di:
        bullish += 1
    if indicators.stoch_k > 50:
        bullish += 1
    if indicators.psar_direction == 1:
        bullish += 1
    if indicators.ichimoku_tenkan > indicators.ichimoku_kijun:
        bullish += 1
    if indicators.cci > 0:
        bullish += 1
    return bullish / total


def extract_features(
    indicators: IndicatorSet,
    close_price: float,
    sentiment: SentimentFeatures | None = None,
) -> FeatureVector:
    """Extract a feature vector from indicators and sentiment.

    Args:
        indicators: Technical indicators from IndicatorEngine.
        close_price: Current close price of the candle.
        sentiment: Optional sentiment features from Commander.

    Returns:
        FeatureVector with normalized features.

    """
    if sentiment is None:
        sentiment = SentimentFeatures()

    bb_range = indicators.bb_upper - indicators.bb_lower
    bb_percent_b = _safe_div(close_price - indicators.bb_lower, bb_range, 0.5)
    bb_width = _safe_div(bb_range, indicators.bb_middle, 0.0)
    ema_cross = _safe_div(
        indicators.ema_9 - indicators.ema_21, indicators.ema_21, 0.0,
    )
    atr_ratio = _safe_div(indicators.atr_14, close_price, 0.0)
    volume_ratio = _safe_div(
        indicators.volume_avg_20, indicators.volume_avg_20, 1.0,
    )
    momentum = _safe_div(close_price - indicators.vwap, indicators.vwap, 0.0)
    trend_strength = _safe_div(
        abs(indicators.ema_9 - indicators.ema_21), indicators.atr_14, 0.0,
    )

    features = np.array([
        indicators.rsi_14,
        _rsi_zone(indicators.rsi_14),
        indicators.macd_hist,
        _macd_crossover(indicators.macd, indicators.macd_signal),
        bb_percent_b,
        bb_width,
        ema_cross,
        float(indicators.supertrend_direction),
        atr_ratio,
        volume_ratio,
        momentum,
        trend_strength,
        bb_width,  # volatility_regime (same as bb_width, acts as proxy)
        sentiment.score,
        sentiment.confidence,
        float(sentiment.article_count),
        # Extended TA features
        indicators.stoch_k / 100.0,  # normalize to 0-1
        _stoch_zone(indicators.stoch_k),
        indicators.adx / 100.0,  # normalize to 0-1
        (indicators.plus_di - indicators.minus_di) / 100.0,
        _williams_r_zone(indicators.williams_r),
        _cci_zone(indicators.cci),
        _mfi_zone(indicators.mfi),
        float(indicators.psar_direction),
        _ema_trend_alignment(indicators.ema_9, indicators.ema_21, indicators.ema_50),
        _ichimoku_cloud_position(
            close_price, indicators.ichimoku_senkou_a, indicators.ichimoku_senkou_b,
        ),
        1.0 if indicators.ichimoku_tenkan > indicators.ichimoku_kijun else -1.0,
        _safe_div(close_price - indicators.pivot, indicators.atr_14, 0.0),
        _confluence_score(indicators, close_price),
    ], dtype=np.float64)

    # Clamp any NaN/Inf to 0
    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)

    return FeatureVector(
        symbol=indicators.symbol,
        timestamp=indicators.timestamp,
        features=features,
        close_price=close_price,
    )


def extract_label(
    entry_price: float,
    exit_price: float,
    side: str,
    atr: float,
) -> float:
    """Compute a continuous label from trade outcome for training.

    Returns a value in [-1, 1]:
      - Positive = profitable trade (scaled by ATR)
      - Negative = losing trade
      - 0 = breakeven

    Args:
        entry_price: Trade entry price.
        exit_price: Trade exit price.
        side: 'BUY' or 'SELL'.
        atr: ATR at entry time for normalization.

    Returns:
        Normalized profit/loss label.

    """
    if side == "BUY":
        raw_pnl = exit_price - entry_price
    else:
        raw_pnl = entry_price - exit_price

    if atr <= 0:
        return 0.0

    # Normalize by ATR and clamp to [-1, 1]
    normalized = raw_pnl / (2.0 * atr)
    return float(np.clip(normalized, -1.0, 1.0))
