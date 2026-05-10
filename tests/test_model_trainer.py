"""Unit tests for the ML Model Trainer.
"""

import shutil
import tempfile
from datetime import UTC, datetime

import numpy as np
import pytest

from src.ml.feature_engine import NUM_FEATURES
from src.ml.model_trainer import (
    ModelMetrics,
    ModelTrainer,
    TrainingSample,
)


def _make_sample(label: float, seed: int = 0) -> TrainingSample:
    """Create a training sample with deterministic features."""
    rng = np.random.RandomState(seed)
    features = rng.randn(NUM_FEATURES)
    # Make features correlate with label for learnable patterns
    if label > 0:
        features[0] = abs(features[0])  # RSI positive
        features[3] = 1.0               # MACD bullish
    else:
        features[0] = -abs(features[0])
        features[3] = -1.0
    return TrainingSample(
        features=features,
        label=label,
        symbol="TEST",
        timestamp=datetime.now(UTC),
    )


def _generate_samples(n: int, positive_ratio: float = 0.6) -> list:
    """Generate n training samples with given positive ratio."""
    samples = []
    n_positive = int(n * positive_ratio)
    for i in range(n_positive):
        samples.append(_make_sample(label=0.5, seed=i))
    for i in range(n - n_positive):
        samples.append(_make_sample(label=-0.5, seed=1000 + i))
    return samples


@pytest.fixture
def tmp_model_dir():
    """Create a temporary directory for model storage."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestModelTrainer:
    def test_initial_state(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir)
        assert not trainer.is_trained
        assert trainer.sample_count == 0
        assert trainer.metrics.accuracy == 0.0

    def test_add_sample(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir)
        sample = _make_sample(0.5)
        trainer.add_sample(sample)
        assert trainer.sample_count == 1

    def test_train_insufficient_samples(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir, min_samples=30)
        for i in range(10):
            trainer.add_sample(_make_sample(0.5, seed=i))
        metrics = trainer.train()
        assert not trainer.is_trained
        assert metrics.sample_count == 0

    def test_train_sufficient_samples(self, tmp_model_dir):
        trainer = ModelTrainer(
            model_dir=tmp_model_dir, min_samples=20, retrain_threshold=9999,
        )
        samples = _generate_samples(40)
        for s in samples:
            trainer.add_sample(s)
        metrics = trainer.train()
        assert trainer.is_trained
        assert metrics.sample_count == 40
        assert metrics.accuracy > 0
        assert metrics.trained_at is not None

    def test_predict_untrained(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir)
        features = np.zeros(NUM_FEATURES)
        prob, pred = trainer.predict(features)
        assert prob == 0.5
        assert pred == 0.0

    def test_predict_trained(self, tmp_model_dir):
        trainer = ModelTrainer(
            model_dir=tmp_model_dir, min_samples=20, retrain_threshold=9999,
        )
        samples = _generate_samples(40)
        for s in samples:
            trainer.add_sample(s)
        trainer.train()

        features = np.zeros(NUM_FEATURES)
        features[0] = 2.0   # strong positive RSI
        features[3] = 1.0   # bullish MACD
        prob, pred = trainer.predict(features)
        assert 0.0 <= prob <= 1.0

    def test_auto_retrain(self, tmp_model_dir):
        trainer = ModelTrainer(
            model_dir=tmp_model_dir, min_samples=20, retrain_threshold=10,
        )
        # Add 20 samples (enough to train)
        samples = _generate_samples(20)
        for s in samples:
            trainer.add_sample(s)
        trainer.train()
        assert trainer.is_trained

        # Add 10 more → should auto-retrain
        for i in range(10):
            retrained = trainer.add_sample(_make_sample(0.3, seed=2000 + i))
        # The 10th sample should trigger retrain
        assert trainer.metrics.sample_count == 30

    def test_save_and_load(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir, min_samples=20)
        samples = _generate_samples(30)
        for s in samples:
            trainer.add_sample(s)
        trainer.train()
        assert trainer.is_trained

        # Create new trainer pointing to same dir
        trainer2 = ModelTrainer(model_dir=tmp_model_dir)
        assert trainer2.is_trained
        assert trainer2.sample_count == 30

    def test_reset(self, tmp_model_dir):
        trainer = ModelTrainer(model_dir=tmp_model_dir, min_samples=20)
        samples = _generate_samples(30)
        for s in samples:
            trainer.add_sample(s)
        trainer.train()
        assert trainer.is_trained

        trainer.reset()
        assert not trainer.is_trained
        assert trainer.sample_count == 0

    def test_single_class_data(self, tmp_model_dir):
        """Training with only one class should not crash."""
        trainer = ModelTrainer(model_dir=tmp_model_dir, min_samples=20)
        for i in range(30):
            trainer.add_sample(_make_sample(0.5, seed=i))
        metrics = trainer.train()
        # Should handle gracefully (all positive labels)
        assert not trainer.is_trained  # can't train with one class

    def test_feature_importances(self, tmp_model_dir):
        trainer = ModelTrainer(
            model_dir=tmp_model_dir, min_samples=20, retrain_threshold=9999,
        )
        samples = _generate_samples(40)
        for s in samples:
            trainer.add_sample(s)
        metrics = trainer.train()
        assert len(metrics.feature_importances) == NUM_FEATURES
        assert all(v >= 0 for v in metrics.feature_importances.values())

    def test_metrics_to_dict(self):
        m = ModelMetrics(
            accuracy=0.85,
            precision=0.9,
            recall=0.8,
            f1_score=0.85,
            sample_count=100,
            trained_at=datetime(2025, 1, 1, tzinfo=UTC),
            feature_importances={"rsi_14": 0.3, "macd_hist": 0.2},
        )
        d = m.to_dict()
        assert d["accuracy"] == 0.85
        assert d["sample_count"] == 100
        assert "top_features" in d
