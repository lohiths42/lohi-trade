"""
Property-based tests for the ML Model Trainer using Hypothesis.

Tests invariants:
- Predictions always in [0, 1] probability range
- Untrained model always returns neutral (0.5, 0)
- Sample count always matches additions
- Metrics values always in valid ranges
- Training never crashes regardless of feature distributions
"""

import numpy as np
import pytest
import tempfile
import shutil
from datetime import datetime, timezone
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.ml.model_trainer import (
    ModelTrainer,
    TrainingSample,
    ModelMetrics,
)
from src.ml.feature_engine import NUM_FEATURES


finite_float = st.floats(
    min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False
)
label_float = st.floats(
    min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def feature_vectors(draw):
    """Generate random feature vectors of correct shape."""
    return np.array(
        [draw(finite_float) for _ in range(NUM_FEATURES)], dtype=np.float64
    )


@st.composite
def training_samples(draw):
    """Generate random training samples."""
    features = draw(feature_vectors())
    label = draw(label_float)
    return TrainingSample(
        features=features,
        label=label,
        symbol="TEST",
        timestamp=datetime.now(timezone.utc),
    )


def _make_balanced_samples(n: int) -> list:
    """Generate n balanced training samples deterministically."""
    rng = np.random.RandomState(42)
    samples = []
    n_pos = n // 2
    for i in range(n):
        features = rng.randn(NUM_FEATURES)
        if i < n_pos:
            features[0] = abs(features[0]) + 0.5
            features[3] = 1.0
            label = 0.5
        else:
            features[0] = -abs(features[0]) - 0.5
            features[3] = -1.0
            label = -0.5
        samples.append(TrainingSample(
            features=features, label=label, symbol="TEST",
            timestamp=datetime.now(timezone.utc),
        ))
    return samples


class TestModelTrainerProperties:
    @given(features=feature_vectors())
    def test_untrained_always_neutral(self, features):
        """Untrained model always returns (0.5, 0.0)."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d)
            prob, pred = trainer.predict(features)
            assert prob == 0.5
            assert pred == 0.0

    @given(sample=training_samples())
    def test_add_sample_increments_count(self, sample):
        """Adding a sample always increments the count by 1."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, retrain_threshold=9999)
            before = trainer.sample_count
            trainer.add_sample(sample)
            assert trainer.sample_count == before + 1

    @given(
        samples=st.lists(training_samples(), min_size=1, max_size=20),
    )
    def test_sample_count_matches_additions(self, samples):
        """Sample count always equals number of added samples."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, retrain_threshold=9999)
            for s in samples:
                trainer.add_sample(s)
            assert trainer.sample_count == len(samples)

    @given(features=feature_vectors())
    @settings(max_examples=25, deadline=30000)
    def test_trained_prediction_in_range(self, features):
        """Trained model predictions are always in [0, 1]."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=20, retrain_threshold=9999)
            for s in _make_balanced_samples(40):
                trainer.add_sample(s)
            trainer.train()
            assert trainer.is_trained

            prob, pred = trainer.predict(features)
            assert 0.0 <= prob <= 1.0
            assert pred in {0.0, 1.0}

    def test_metrics_in_valid_ranges(self):
        """All metrics are always in [0, 1] after training."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=20, retrain_threshold=9999)
            for s in _make_balanced_samples(40):
                trainer.add_sample(s)
            metrics = trainer.train()
            assert trainer.is_trained
            assert 0.0 <= metrics.accuracy <= 1.0
            assert 0.0 <= metrics.precision <= 1.0
            assert 0.0 <= metrics.recall <= 1.0
            assert 0.0 <= metrics.f1_score <= 1.0
            assert metrics.sample_count == 40
            assert metrics.trained_at is not None

    def test_feature_importances_sum_to_one(self):
        """Feature importances always sum to approximately 1.0."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=20, retrain_threshold=9999)
            for s in _make_balanced_samples(40):
                trainer.add_sample(s)
            metrics = trainer.train()
            assert trainer.is_trained
            total = sum(metrics.feature_importances.values())
            assert abs(total - 1.0) < 0.01

    def test_feature_importances_non_negative(self):
        """All feature importances are always >= 0."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=20, retrain_threshold=9999)
            for s in _make_balanced_samples(40):
                trainer.add_sample(s)
            metrics = trainer.train()
            assert trainer.is_trained
            assert all(v >= 0 for v in metrics.feature_importances.values())

    def test_save_load_preserves_sample_count(self):
        """Save/load cycle always preserves sample count."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=20, retrain_threshold=9999)
            samples = _make_balanced_samples(40)
            for s in samples:
                trainer.add_sample(s)
            trainer.train()
            assert trainer.is_trained

            trainer2 = ModelTrainer(model_dir=d)
            assert trainer2.sample_count == 40
            assert trainer2.is_trained

    def test_reset_always_clears(self):
        """Reset always returns trainer to initial state."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, retrain_threshold=9999)
            for i in range(5):
                trainer.add_sample(TrainingSample(
                    features=np.random.randn(NUM_FEATURES),
                    label=0.5 if i % 2 == 0 else -0.5,
                ))
            trainer.reset()
            assert not trainer.is_trained
            assert trainer.sample_count == 0
            assert trainer.metrics.accuracy == 0.0

    @given(n_samples=st.integers(min_value=1, max_value=25))
    def test_insufficient_samples_never_trains(self, n_samples):
        """With fewer than min_samples, model never becomes trained."""
        with tempfile.TemporaryDirectory() as d:
            trainer = ModelTrainer(model_dir=d, min_samples=30, retrain_threshold=9999)
            for i in range(n_samples):
                trainer.add_sample(TrainingSample(
                    features=np.random.randn(NUM_FEATURES),
                    label=0.5 if i % 2 == 0 else -0.5,
                ))
            trainer.train()
            assert not trainer.is_trained


class TestMetricsProperties:
    @given(
        accuracy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        precision=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        recall=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        f1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        count=st.integers(min_value=0, max_value=10000),
    )
    def test_to_dict_roundtrip(self, accuracy, precision, recall, f1, count):
        """to_dict always produces a valid dict with expected keys."""
        m = ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            sample_count=count,
        )
        d = m.to_dict()
        assert "accuracy" in d
        assert "precision" in d
        assert "recall" in d
        assert "f1_score" in d
        assert "sample_count" in d
        assert d["sample_count"] == count
