"""ML Model Trainer with feedback loop for LOHI-TRADE.

Trains a gradient-boosted decision tree (scikit-learn) on historical
trade outcomes. Supports:
- Incremental training as new trades complete
- Model persistence (save/load)
- Performance tracking (accuracy, precision, recall)
- Automatic retraining when enough new data accumulates

The model predicts signal quality: a score in [0, 1] where
  >0.5 = likely profitable signal
  <0.5 = likely unprofitable signal
"""

import json
import logging
import pickle
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from src.ml.feature_engine import FEATURE_NAMES

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = "data/ml_models"
MIN_TRAINING_SAMPLES = 30
RETRAIN_THRESHOLD = 20  # retrain after this many new samples


class _FallbackGradientBoostingClassifier:
    """Lightweight binary classifier used when scikit-learn is unavailable."""

    def __init__(self, **_kwargs) -> None:
        self.classes_ = np.array([0, 1])
        self._class_centroids: dict[int, np.ndarray] = {}
        self.feature_importances_ = np.array([], dtype=float)

    def fit(self, x: np.ndarray, y: np.ndarray):
        self._class_centroids = {int(cls): x[y == cls].mean(axis=0) for cls in np.unique(y)}
        positive = self._class_centroids.get(1)
        negative = self._class_centroids.get(0)
        if positive is None or negative is None:
            raise ValueError("Fallback classifier requires both classes")

        importances = np.abs(positive - negative)
        total = float(importances.sum())
        if total <= 0:
            self.feature_importances_ = np.full(x.shape[1], 1.0 / x.shape[1])
        else:
            self.feature_importances_ = importances / total
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        negative = self._class_centroids[0]
        positive = self._class_centroids[1]
        probabilities: list[list[float]] = []
        for row in x:
            dist_negative = float(np.linalg.norm(row - negative))
            dist_positive = float(np.linalg.norm(row - positive))
            score_negative = 1.0 / (dist_negative + 1e-8)
            score_positive = 1.0 / (dist_positive + 1e-8)
            total = score_negative + score_positive
            probabilities.append([score_negative / total, score_positive / total])
        return np.asarray(probabilities, dtype=float)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return (self.predict_proba(x)[:, 1] >= 0.5).astype(int)


def _stratified_train_test_split(
    x: np.ndarray,
    y: np.ndarray,
    test_ratio: float = 0.2,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Deterministic stratified split without sklearn."""
    rng = np.random.default_rng(random_state)
    train_indices: list[int] = []
    test_indices: list[int] = []

    for cls in np.unique(y):
        cls_indices = np.where(y == cls)[0]
        rng.shuffle(cls_indices)
        test_count = max(1, int(round(len(cls_indices) * test_ratio)))
        test_count = min(test_count, len(cls_indices) - 1)
        test_indices.extend(cls_indices[:test_count].tolist())
        train_indices.extend(cls_indices[test_count:].tolist())

    rng.shuffle(train_indices)
    rng.shuffle(test_indices)

    return (
        x[train_indices],
        x[test_indices],
        y[train_indices],
        y[test_indices],
    )


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float, float]:
    accuracy = float(np.mean(y_true == y_pred)) if len(y_true) else 0.0
    tp = float(np.sum((y_true == 1) & (y_pred == 1)))
    fp = float(np.sum((y_true == 0) & (y_pred == 1)))
    fn = float(np.sum((y_true == 1) & (y_pred == 0)))

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall > 0 else 0.0
    return accuracy, precision, recall, f1


@dataclass
class ModelMetrics:
    """Performance metrics for the trained model."""

    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    sample_count: int = 0
    trained_at: datetime | None = None
    feature_importances: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "sample_count": self.sample_count,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "top_features": dict(
                sorted(self.feature_importances.items(), key=lambda x: -x[1])[:5],
            ),
        }


@dataclass
class TrainingSample:
    """A single training example: features + outcome label."""

    features: np.ndarray  # shape (NUM_FEATURES,)
    label: float  # continuous in [-1, 1], binarized for classification
    symbol: str = ""
    timestamp: datetime | None = None


class ModelTrainer:
    """Trains and manages the ML model for signal quality prediction.

    Uses GradientBoostingClassifier from scikit-learn. The model is
    trained on completed trade outcomes and predicts whether a new
    signal is likely to be profitable.
    """

    def __init__(
        self,
        model_dir: str = DEFAULT_MODEL_DIR,
        min_samples: int = MIN_TRAINING_SAMPLES,
        retrain_threshold: int = RETRAIN_THRESHOLD,
    ) -> None:
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._min_samples = min_samples
        self._retrain_threshold = retrain_threshold

        self._model: Any | None = None
        self._samples: list[TrainingSample] = []
        self._new_samples_since_train: int = 0
        self._metrics: ModelMetrics = ModelMetrics()
        self._is_trained: bool = False

        # Try to load existing model
        self._load_model()

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def metrics(self) -> ModelMetrics:
        return self._metrics

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def add_sample(self, sample: TrainingSample) -> bool:
        """Add a training sample from a completed trade.

        Returns True if the model was retrained.
        """
        self._samples.append(sample)
        self._new_samples_since_train += 1

        logger.debug(
            f"Added training sample: symbol={sample.symbol}, "
            f"label={sample.label:.3f}, total={len(self._samples)}",
        )

        # Auto-retrain if enough new samples
        if (
            self._new_samples_since_train >= self._retrain_threshold
            and len(self._samples) >= self._min_samples
        ):
            self.train()
            return True
        return False

    def train(self) -> ModelMetrics:
        """Train the model on all accumulated samples.

        Uses GradientBoostingClassifier with binary labels:
          label > 0 → class 1 (profitable)
          label <= 0 → class 0 (unprofitable)

        Returns:
            ModelMetrics with performance on a holdout split.

        """
        if len(self._samples) < self._min_samples:
            logger.warning(
                f"Not enough samples to train: {len(self._samples)}/{self._min_samples}",
            )
            return self._metrics

        x = np.array([s.features for s in self._samples])
        y = np.array([1 if s.label > 0 else 0 for s in self._samples])

        # Stratified split
        unique_classes, class_counts = np.unique(y, return_counts=True)
        if len(unique_classes) < 2:
            logger.warning("Only one class in training data, skipping training")
            return self._metrics

        # Ensure each class has at least 2 samples for stratified split
        if np.min(class_counts) < 2:
            logger.warning(
                f"Minority class has only {np.min(class_counts)} sample(s), "
                f"need at least 2 for stratified split. Skipping training.",
            )
            return self._metrics

        test_ratio = min(0.2, max(5, len(self._samples) // 5) / len(self._samples))
        x_train, x_test, y_train, y_test = _stratified_train_test_split(
            x,
            y,
            test_ratio=test_ratio,
            random_state=42,
        )

        try:
            from sklearn.ensemble import GradientBoostingClassifier

            model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                min_samples_leaf=3,
                random_state=42,
            )
        except ModuleNotFoundError:
            model = _FallbackGradientBoostingClassifier()

        model.fit(x_train, y_train)

        y_pred = model.predict(x_test)

        accuracy, precision, recall, f1 = _binary_metrics(y_test, y_pred)
        feature_importances = getattr(model, "feature_importances_", None)
        if feature_importances is None or len(feature_importances) != len(FEATURE_NAMES):
            positive = x[y == 1].mean(axis=0)
            negative = x[y == 0].mean(axis=0)
            feature_importances = np.abs(positive - negative)
            total = float(feature_importances.sum())
            if total <= 0:
                feature_importances = np.full(len(FEATURE_NAMES), 1.0 / len(FEATURE_NAMES))
            else:
                feature_importances = feature_importances / total

        self._metrics = ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            sample_count=len(self._samples),
            trained_at=datetime.now(UTC),
            feature_importances=dict(
                zip(FEATURE_NAMES, np.asarray(feature_importances, dtype=float).tolist()),
            ),
        )

        self._model = model
        self._is_trained = True
        self._new_samples_since_train = 0

        self._save_model()

        logger.info(
            f"Model trained: accuracy={self._metrics.accuracy:.3f}, "
            f"f1={self._metrics.f1_score:.3f}, samples={len(self._samples)}",
        )
        return self._metrics

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        """Predict signal quality.

        Args:
            features: Feature vector of shape (NUM_FEATURES,).

        Returns:
            Tuple of (probability_profitable, predicted_class).
            If model is not trained, returns (0.5, 0) as neutral.

        """
        if not self._is_trained or self._model is None:
            return 0.5, 0.0

        x = features.reshape(1, -1)
        proba = self._model.predict_proba(x)[0]

        # proba[1] = probability of class 1 (profitable)
        prob_profitable = float(proba[1]) if len(proba) > 1 else 0.5
        predicted_class = float(self._model.predict(x)[0])

        return prob_profitable, predicted_class

    def _save_model(self) -> None:
        """Persist model, samples, and metrics to disk."""
        try:
            model_path = self._model_dir / "signal_model.pkl"
            with open(model_path, "wb") as f:
                pickle.dump(self._model, f)

            samples_path = self._model_dir / "training_samples.pkl"
            with open(samples_path, "wb") as f:
                pickle.dump(self._samples, f)

            metrics_path = self._model_dir / "model_metrics.json"
            with open(metrics_path, "w") as f:
                json.dump(self._metrics.to_dict(), f, indent=2)

            logger.info(f"Model saved to {self._model_dir}")
        except Exception as e:
            logger.error(f"Failed to save model: {e}")

    def _load_model(self) -> None:
        """Load model and samples from disk if available."""
        try:
            model_path = self._model_dir / "signal_model.pkl"
            samples_path = self._model_dir / "training_samples.pkl"

            if model_path.exists() and samples_path.exists():
                with open(model_path, "rb") as f:
                    self._model = pickle.load(f)
                with open(samples_path, "rb") as f:
                    self._samples = pickle.load(f)

                self._is_trained = True
                logger.info(
                    f"Loaded model with {len(self._samples)} samples from {self._model_dir}",
                )
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            self._model = None
            self._is_trained = False

    def reset(self) -> None:
        """Clear all training data and model."""
        self._model = None
        self._samples = []
        self._new_samples_since_train = 0
        self._metrics = ModelMetrics()
        self._is_trained = False
        logger.info("Model trainer reset")
