"""Unit tests for the Market Trend Predictor.
"""


import numpy as np

from src.ml.market_predictor import (
    REGIME_DOWN,
    REGIME_SIDEWAYS,
    REGIME_UP,
    MarketPredictor,
    PatternSample,
    compute_regime_label,
    extract_pattern_features,
)


def _make_trending_up(n: int = 100) -> tuple:
    """Generate trending-up candle data."""
    base = 100.0
    closes = np.array([base + i * 0.5 + np.random.randn() * 0.1 for i in range(n)])
    highs = closes + np.abs(np.random.randn(n)) * 0.5
    lows = closes - np.abs(np.random.randn(n)) * 0.5
    volumes = np.random.randint(50000, 150000, size=n).astype(float)
    return closes, highs, lows, volumes


def _make_trending_down(n: int = 100) -> tuple:
    base = 200.0
    closes = np.array([base - i * 0.5 + np.random.randn() * 0.1 for i in range(n)])
    highs = closes + np.abs(np.random.randn(n)) * 0.5
    lows = closes - np.abs(np.random.randn(n)) * 0.5
    volumes = np.random.randint(50000, 150000, size=n).astype(float)
    return closes, highs, lows, volumes


def _make_sideways(n: int = 100) -> tuple:
    closes = 100.0 + np.random.randn(n) * 0.1
    highs = closes + np.abs(np.random.randn(n)) * 0.3
    lows = closes - np.abs(np.random.randn(n)) * 0.3
    volumes = np.random.randint(50000, 150000, size=n).astype(float)
    return closes, highs, lows, volumes


class TestExtractPatternFeatures:
    def test_output_shape(self):
        c, h, lo, v = _make_trending_up(30)
        features = extract_pattern_features(c, h, lo, v)
        assert features is not None
        assert features.shape == (12,)

    def test_insufficient_data(self):
        c = np.array([100.0, 101.0])
        h = np.array([101.0, 102.0])
        lo = np.array([99.0, 100.0])
        v = np.array([1000.0, 1100.0])
        features = extract_pattern_features(c, h, lo, v)
        assert features is None

    def test_no_nan(self):
        c, h, lo, v = _make_trending_up(50)
        features = extract_pattern_features(c, h, lo, v)
        assert not np.any(np.isnan(features))

    def test_no_inf(self):
        c, h, lo, v = _make_trending_up(50)
        features = extract_pattern_features(c, h, lo, v)
        assert not np.any(np.isinf(features))

    def test_trending_up_positive_returns(self):
        c, h, lo, v = _make_trending_up(50)
        features = extract_pattern_features(c, h, lo, v)
        # returns_mean (index 0) should be positive for uptrend
        assert features[0] > 0

    def test_trending_down_negative_returns(self):
        c, h, lo, v = _make_trending_down(50)
        features = extract_pattern_features(c, h, lo, v)
        assert features[0] < 0

    def test_zero_volume(self):
        """Zero volume should not crash."""
        c, h, lo, _ = _make_trending_up(30)
        v = np.zeros(30)
        features = extract_pattern_features(c, h, lo, v)
        assert features is not None
        assert not np.any(np.isnan(features))

    def test_flat_prices(self):
        """Constant prices should produce zero returns."""
        n = 30
        c = np.full(n, 100.0)
        h = np.full(n, 100.5)
        lo = np.full(n, 99.5)
        v = np.full(n, 100000.0)
        features = extract_pattern_features(c, h, lo, v)
        assert features is not None
        assert abs(features[0]) < 1e-6  # returns_mean ≈ 0


class TestComputeRegimeLabel:
    def test_up(self):
        future = np.array([101.0, 102.0, 103.0, 104.0, 105.0])
        label = compute_regime_label(future, 100.0, threshold_pct=0.3)
        assert label == 2  # up

    def test_down(self):
        future = np.array([99.0, 98.0, 97.0, 96.0, 95.0])
        label = compute_regime_label(future, 100.0, threshold_pct=0.3)
        assert label == 0  # down

    def test_sideways(self):
        future = np.array([100.1, 100.0, 99.9, 100.0, 100.1])
        label = compute_regime_label(future, 100.0, threshold_pct=0.3)
        assert label == 1  # sideways

    def test_empty_future(self):
        label = compute_regime_label(np.array([]), 100.0)
        assert label == 1  # default sideways

    def test_zero_current_close(self):
        label = compute_regime_label(np.array([1.0, 2.0]), 0.0)
        assert label == 1


class TestMarketPredictor:
    def test_initial_state(self):
        mp = MarketPredictor()
        assert not mp.is_trained
        assert mp.sample_count == 0

    def test_predict_untrained(self):
        mp = MarketPredictor()
        c, h, lo, v = _make_trending_up(30)
        regime = mp.predict(c, h, lo, v)
        assert regime.regime == REGIME_SIDEWAYS
        assert regime.confidence == 0.0

    def test_add_sample(self):
        mp = MarketPredictor()
        features = np.random.randn(12)
        mp.add_sample(PatternSample(features=features, label=2))
        assert mp.sample_count == 1

    def test_train_insufficient(self):
        mp = MarketPredictor(min_samples=50)
        for i in range(10):
            mp.add_sample(PatternSample(features=np.random.randn(12), label=i % 3))
        result = mp.train()
        assert not result
        assert not mp.is_trained

    def test_train_from_candles(self):
        mp = MarketPredictor(min_samples=20)
        # Use mixed data to ensure multiple regime classes
        np.random.seed(42)
        for data_fn in [_make_trending_up, _make_trending_down, _make_sideways]:
            c, h, lo, v = data_fn(80)
            mp.train_from_candles(c, h, lo, v, symbol="TEST")
        assert mp.sample_count > 0
        assert mp.is_trained

    def test_predict_trained(self):
        mp = MarketPredictor(min_samples=20)
        # Train on mixed data
        np.random.seed(42)
        for regime_data in [_make_trending_up(80), _make_trending_down(80), _make_sideways(80)]:
            c, h, lo, v = regime_data
            mp.train_from_candles(c, h, lo, v)

        # Predict on new data
        c, h, lo, v = _make_trending_up(30)
        regime = mp.predict(c, h, lo, v)
        assert regime.regime in [REGIME_UP, REGIME_DOWN, REGIME_SIDEWAYS]
        assert 0.0 <= regime.confidence <= 1.0
        assert regime.predicted_at is not None

    def test_predict_insufficient_data(self):
        mp = MarketPredictor(min_samples=20)
        # Train first
        c, h, lo, v = _make_trending_up(100)
        mp.train_from_candles(c, h, lo, v)

        # Predict with too few candles
        regime = mp.predict(
            np.array([100.0]), np.array([101.0]),
            np.array([99.0]), np.array([1000.0]),
        )
        assert regime.regime == REGIME_SIDEWAYS

    def test_single_class_training(self):
        """Training with only one class should handle gracefully."""
        mp = MarketPredictor(min_samples=20)
        for i in range(30):
            mp.add_sample(PatternSample(features=np.random.randn(12), label=1))
        result = mp.train()
        assert not result  # can't train with one class

    def test_train_from_candles_too_short(self):
        mp = MarketPredictor()
        c = np.array([100.0, 101.0])
        h = np.array([101.0, 102.0])
        lo = np.array([99.0, 100.0])
        v = np.array([1000.0, 1100.0])
        count = mp.train_from_candles(c, h, lo, v)
        assert count == 0
