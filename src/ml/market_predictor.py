"""
Market Trend Predictor for LOHI-TRADE.

Uses historical indicator patterns to predict short-term market direction.
Learns from past candle sequences to forecast whether the next N candles
will trend up, down, or sideways.

This complements the signal-level ML by providing a market-regime filter:
- Trending up → favor BUY signals
- Trending down → favor SELL signals
- Sideways → reduce position sizes or skip

Uses a RandomForestClassifier on rolling window features.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

REGIME_UP = "TRENDING_UP"
REGIME_DOWN = "TRENDING_DOWN"
REGIME_SIDEWAYS = "SIDEWAYS"

# Rolling window for pattern features
LOOKBACK_CANDLES = 20
FORECAST_CANDLES = 5

# Minimum samples before training
MIN_PATTERN_SAMPLES = 50


@dataclass
class MarketRegime:
    """Current market regime prediction."""
    regime: str = REGIME_SIDEWAYS
    confidence: float = 0.0
    predicted_at: Optional[datetime] = None
    features_used: int = 0


@dataclass
class PatternSample:
    """A historical pattern sample for training."""
    features: np.ndarray
    label: int  # 0=down, 1=sideways, 2=up
    symbol: str = ""
    timestamp: Optional[datetime] = None


def extract_pattern_features(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
) -> Optional[np.ndarray]:
    """
    Extract pattern features from a window of candles.

    Features (12 total):
    - returns_mean, returns_std (momentum + volatility)
    - high_low_range_mean (average candle range)
    - close_position (where close sits in high-low range)
    - volume_trend (slope of volume)
    - up_candle_ratio (fraction of up candles)
    - max_drawdown, max_runup
    - consecutive_up, consecutive_down
    - range_expansion (last 5 vs first 5 range)
    - momentum_acceleration (second derivative of returns)

    Args:
        closes: Array of close prices, length >= LOOKBACK_CANDLES.
        highs: Array of high prices.
        lows: Array of low prices.
        volumes: Array of volumes.

    Returns:
        Feature array of shape (12,) or None if insufficient data.
    """
    n = len(closes)
    if n < LOOKBACK_CANDLES:
        return None

    c = closes[-LOOKBACK_CANDLES:]
    h = highs[-LOOKBACK_CANDLES:]
    lo = lows[-LOOKBACK_CANDLES:]
    v = volumes[-LOOKBACK_CANDLES:]

    returns = np.diff(c) / c[:-1]
    returns = np.nan_to_num(returns, nan=0.0)

    hl_range = h - lo
    hl_range_safe = np.where(hl_range == 0, 1e-8, hl_range)

    close_pos = np.mean((c - lo) / hl_range_safe)

    # Volume trend (linear regression slope)
    v_norm = v / (np.mean(v) + 1e-8)
    x = np.arange(len(v_norm))
    vol_trend = float(np.polyfit(x, v_norm, 1)[0]) if len(v_norm) > 1 else 0.0

    up_candles = np.sum(returns > 0) / max(len(returns), 1)

    # Max drawdown and runup
    cum_returns = np.cumsum(returns)
    peak = np.maximum.accumulate(cum_returns)
    drawdown = peak - cum_returns
    max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    trough = np.minimum.accumulate(cum_returns)
    runup = cum_returns - trough
    max_ru = float(np.max(runup)) if len(runup) > 0 else 0.0

    # Consecutive up/down
    consec_up = 0
    consec_down = 0
    for r in reversed(returns):
        if r > 0:
            consec_up += 1
        else:
            break
    for r in reversed(returns):
        if r < 0:
            consec_down += 1
        else:
            break

    # Range expansion
    half = LOOKBACK_CANDLES // 2
    first_range = float(np.mean(hl_range[:half]))
    second_range = float(np.mean(hl_range[half:]))
    range_exp = (second_range - first_range) / (first_range + 1e-8)

    # Momentum acceleration
    if len(returns) >= 4:
        first_half_mom = float(np.mean(returns[: len(returns) // 2]))
        second_half_mom = float(np.mean(returns[len(returns) // 2 :]))
        mom_accel = second_half_mom - first_half_mom
    else:
        mom_accel = 0.0

    features = np.array([
        float(np.mean(returns)),
        float(np.std(returns)),
        float(np.mean(hl_range)),
        close_pos,
        vol_trend,
        up_candles,
        max_dd,
        max_ru,
        float(consec_up),
        float(consec_down),
        range_exp,
        mom_accel,
    ], dtype=np.float64)

    return np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)


def compute_regime_label(
    future_closes: np.ndarray,
    current_close: float,
    threshold_pct: float = 0.3,
) -> int:
    """
    Compute regime label from future price movement.

    Args:
        future_closes: Next N close prices.
        current_close: Current close price.
        threshold_pct: Percentage threshold for up/down classification.

    Returns:
        0=down, 1=sideways, 2=up
    """
    if len(future_closes) == 0 or current_close <= 0:
        return 1  # sideways default

    future_return = (future_closes[-1] - current_close) / current_close * 100

    if future_return > threshold_pct:
        return 2  # up
    elif future_return < -threshold_pct:
        return 0  # down
    return 1  # sideways


class MarketPredictor:
    """
    Predicts market regime using historical candle patterns.

    Trains a RandomForestClassifier on rolling window features
    extracted from historical candle data.
    """

    def __init__(self, min_samples: int = MIN_PATTERN_SAMPLES) -> None:
        self._model = None
        self._samples: List[PatternSample] = []
        self._min_samples = min_samples
        self._is_trained = False

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def add_sample(self, sample: PatternSample) -> None:
        """Add a historical pattern sample."""
        self._samples.append(sample)

    def train_from_candles(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
        symbol: str = "",
    ) -> int:
        """
        Build training samples from a full candle history and train.

        Slides a window across the data, extracting features and labels.

        Returns:
            Number of samples generated.
        """
        n = len(closes)
        required = LOOKBACK_CANDLES + FORECAST_CANDLES
        if n < required:
            logger.warning(f"Not enough candles: {n} < {required}")
            return 0

        count = 0
        for i in range(LOOKBACK_CANDLES, n - FORECAST_CANDLES):
            features = extract_pattern_features(
                closes[: i + 1], highs[: i + 1], lows[: i + 1], volumes[: i + 1]
            )
            if features is None:
                continue

            future = closes[i + 1 : i + 1 + FORECAST_CANDLES]
            label = compute_regime_label(future, closes[i])

            self._samples.append(
                PatternSample(features=features, label=label, symbol=symbol)
            )
            count += 1

        if count > 0:
            self.train()

        return count

    def train(self) -> bool:
        """
        Train the regime classifier.

        Returns True if training succeeded.
        """
        from sklearn.ensemble import RandomForestClassifier

        if len(self._samples) < self._min_samples:
            logger.warning(
                f"Not enough pattern samples: {len(self._samples)}/{self._min_samples}"
            )
            return False

        X = np.array([s.features for s in self._samples])
        y = np.array([s.label for s in self._samples])

        unique = np.unique(y)
        if len(unique) < 2:
            logger.warning("Only one regime class in data, skipping training")
            return False

        model = RandomForestClassifier(
            n_estimators=50,
            max_depth=6,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X, y)

        self._model = model
        self._is_trained = True

        logger.info(
            f"MarketPredictor trained on {len(self._samples)} samples, "
            f"classes={unique.tolist()}"
        )
        return True

    def predict(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
    ) -> MarketRegime:
        """
        Predict current market regime.

        Args:
            closes, highs, lows, volumes: Recent candle arrays.

        Returns:
            MarketRegime with prediction and confidence.
        """
        if not self._is_trained or self._model is None:
            return MarketRegime()

        features = extract_pattern_features(closes, highs, lows, volumes)
        if features is None:
            return MarketRegime()

        X = features.reshape(1, -1)
        proba = self._model.predict_proba(X)[0]
        pred_class = int(self._model.predict(X)[0])

        regime_map = {0: REGIME_DOWN, 1: REGIME_SIDEWAYS, 2: REGIME_UP}

        return MarketRegime(
            regime=regime_map.get(pred_class, REGIME_SIDEWAYS),
            confidence=float(np.max(proba)),
            predicted_at=datetime.now(timezone.utc),
            features_used=len(features),
        )
