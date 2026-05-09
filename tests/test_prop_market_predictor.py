"""
Property-based tests for the Market Predictor using Hypothesis.

Tests invariants:
- Pattern features always have shape (12,) when enough data
- No NaN/Inf in pattern features
- Regime labels always in {0, 1, 2}
- Untrained predictor always returns SIDEWAYS
- Predictions always have valid confidence [0, 1]
"""

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.ml.market_predictor import (
    MarketPredictor,
    PatternSample,
    extract_pattern_features,
    compute_regime_label,
    LOOKBACK_CANDLES,
    FORECAST_CANDLES,
    REGIME_UP,
    REGIME_DOWN,
    REGIME_SIDEWAYS,
)


positive_float = st.floats(
    min_value=0.01, max_value=1e4, allow_nan=False, allow_infinity=False
)
price_float = st.floats(
    min_value=1.0, max_value=1e4, allow_nan=False, allow_infinity=False
)
volume_float = st.floats(
    min_value=0.0, max_value=1e8, allow_nan=False, allow_infinity=False
)
threshold_pct = st.floats(
    min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False
)


@st.composite
def candle_arrays(draw, min_len=LOOKBACK_CANDLES, max_len=100):
    """Generate random candle OHLCV arrays."""
    n = draw(st.integers(min_value=min_len, max_value=max_len))
    base = draw(price_float)
    # Random walk for closes
    changes = np.array([
        draw(st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False))
        for _ in range(n)
    ])
    closes = base + np.cumsum(changes)
    closes = np.maximum(closes, 0.01)  # keep positive

    spread = np.array([
        draw(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
        for _ in range(n)
    ])
    highs = closes + spread
    lows = closes - np.minimum(spread * 0.5, closes - 0.01)

    volumes = np.array([
        draw(st.floats(min_value=100.0, max_value=1e6, allow_nan=False, allow_infinity=False))
        for _ in range(n)
    ])

    return closes, highs, lows, volumes


@st.composite
def short_candle_arrays(draw):
    """Generate candle arrays shorter than LOOKBACK_CANDLES."""
    n = draw(st.integers(min_value=1, max_value=LOOKBACK_CANDLES - 1))
    closes = np.random.rand(n) * 100 + 50
    highs = closes + np.random.rand(n) * 2
    lows = closes - np.random.rand(n) * 2
    lows = np.maximum(lows, 0.01)
    volumes = np.random.rand(n) * 100000
    return closes, highs, lows, volumes


class TestExtractPatternFeaturesProperties:
    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=80))
    @settings(max_examples=25)
    def test_output_shape(self, data):
        """Pattern features always have shape (12,) with sufficient data."""
        closes, highs, lows, volumes = data
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is not None
        assert features.shape == (12,)

    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=80))
    @settings(max_examples=25)
    def test_no_nan(self, data):
        """Pattern features never contain NaN."""
        closes, highs, lows, volumes = data
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is not None
        assert not np.any(np.isnan(features))

    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=80))
    @settings(max_examples=25)
    def test_no_inf(self, data):
        """Pattern features never contain Inf."""
        closes, highs, lows, volumes = data
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is not None
        assert not np.any(np.isinf(features))

    @given(data=short_candle_arrays())
    def test_insufficient_data_returns_none(self, data):
        """Insufficient data always returns None."""
        closes, highs, lows, volumes = data
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is None

    @given(n=st.integers(min_value=LOOKBACK_CANDLES, max_value=60))
    def test_zero_volume_safe(self, n):
        """Zero volume arrays never cause NaN/Inf."""
        closes = np.random.rand(n) * 100 + 50
        highs = closes + 1.0
        lows = closes - 1.0
        volumes = np.zeros(n)
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is not None
        assert not np.any(np.isnan(features))

    @given(n=st.integers(min_value=LOOKBACK_CANDLES, max_value=60))
    def test_flat_prices_safe(self, n):
        """Constant prices never cause NaN/Inf."""
        price = 100.0
        closes = np.full(n, price)
        highs = np.full(n, price + 0.5)
        lows = np.full(n, price - 0.5)
        volumes = np.full(n, 100000.0)
        features = extract_pattern_features(closes, highs, lows, volumes)
        assert features is not None
        assert not np.any(np.isnan(features))
        assert not np.any(np.isinf(features))


class TestComputeRegimeLabelProperties:
    @given(
        future=st.lists(
            price_float, min_size=1, max_size=20
        ).map(np.array),
        current=price_float,
        threshold=threshold_pct,
    )
    def test_label_in_valid_set(self, future, current, threshold):
        """Regime label is always in {0, 1, 2}."""
        label = compute_regime_label(future, current, threshold)
        assert label in {0, 1, 2}

    @given(current=price_float, threshold=threshold_pct)
    def test_empty_future_is_sideways(self, current, threshold):
        """Empty future array always returns sideways (1)."""
        label = compute_regime_label(np.array([]), current, threshold)
        assert label == 1

    @given(threshold=threshold_pct)
    def test_zero_current_is_sideways(self, threshold):
        """Zero current close always returns sideways (1)."""
        label = compute_regime_label(np.array([1.0, 2.0]), 0.0, threshold)
        assert label == 1

    @given(
        current=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        gain_pct=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_large_gain_is_up(self, current, gain_pct):
        """Large positive future return always labels as UP."""
        future_price = current * (1 + gain_pct / 100)
        label = compute_regime_label(np.array([future_price]), current, threshold_pct=0.3)
        if gain_pct > 0.3:
            assert label == 2

    @given(
        current=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        loss_pct=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_large_loss_is_down(self, current, loss_pct):
        """Large negative future return always labels as DOWN."""
        future_price = current * (1 - loss_pct / 100)
        label = compute_regime_label(np.array([future_price]), current, threshold_pct=0.3)
        if loss_pct > 0.3:
            assert label == 0


def _build_trained_predictor():
    """Build a trained MarketPredictor with diverse samples."""
    mp = MarketPredictor(min_samples=20)
    rng = np.random.RandomState(42)
    for label in [0, 1, 2]:
        for _ in range(20):
            mp.add_sample(PatternSample(
                features=rng.randn(12), label=label
            ))
    mp.train()
    return mp


class TestMarketPredictorProperties:
    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=50))
    def test_untrained_always_sideways(self, data):
        """Untrained predictor always returns SIDEWAYS with 0 confidence."""
        mp = MarketPredictor()
        closes, highs, lows, volumes = data
        regime = mp.predict(closes, highs, lows, volumes)
        assert regime.regime == REGIME_SIDEWAYS
        assert regime.confidence == 0.0

    @given(sample_count=st.integers(min_value=1, max_value=30))
    def test_add_sample_increments_count(self, sample_count):
        """Adding samples always increments count correctly."""
        mp = MarketPredictor()
        for i in range(sample_count):
            mp.add_sample(PatternSample(
                features=np.random.randn(12), label=i % 3
            ))
        assert mp.sample_count == sample_count

    @given(n_samples=st.integers(min_value=1, max_value=40))
    @settings(deadline=5000)
    def test_insufficient_samples_never_trains(self, n_samples):
        """With fewer than min_samples, predictor never becomes trained."""
        assume(n_samples < 50)
        mp = MarketPredictor(min_samples=50)
        for i in range(n_samples):
            mp.add_sample(PatternSample(
                features=np.random.randn(12), label=i % 3
            ))
        result = mp.train()
        assert not result
        assert not mp.is_trained

    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=50))
    @settings(max_examples=25, deadline=30000)
    def test_trained_prediction_valid_regime(self, data):
        """Trained predictor always returns a valid regime string."""
        mp = _build_trained_predictor()
        assert mp.is_trained

        closes, highs, lows, volumes = data
        regime = mp.predict(closes, highs, lows, volumes)
        assert regime.regime in {REGIME_UP, REGIME_DOWN, REGIME_SIDEWAYS}
        assert 0.0 <= regime.confidence <= 1.0

    @given(data=candle_arrays(min_len=LOOKBACK_CANDLES, max_len=50))
    @settings(max_examples=25, deadline=30000)
    def test_trained_confidence_in_range(self, data):
        """Trained predictor confidence is always in [0, 1]."""
        mp = _build_trained_predictor()
        assert mp.is_trained

        closes, highs, lows, volumes = data
        regime = mp.predict(closes, highs, lows, volumes)
        assert 0.0 <= regime.confidence <= 1.0
