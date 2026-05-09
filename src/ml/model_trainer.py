"""
ML Model Trainer with feedback loop for LOHI-TRADE.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.ml.feature_engine import NUM_FEATURES, FEATURE_NAMES

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = "data/ml_models"
MIN_TRAINING_SAMPLES = 30
RETRAIN_THRESHOLD = 20  # retrain after this many new samples


@dataclass
class ModelMetrics:
    """Performance metrics for the trained model."""
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    sample_count: int = 0
    trained_at: Optional[datetime] = None
    feature_importances: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "sample_count": self.sample_count,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "top_features": dict(
                sorted(self.feature_importances.items(), key=lambda x: -x[1])[:5]
            ),
        }


@dataclass
class TrainingSample:
    """A single training example: features + outcome label."""
    features: np.ndarray   # shape (NUM_FEATURES,)
    label: float           # continuous in [-1, 1], binarized for classification
    symbol: str = ""
    timestamp: Optional[datetime] = None


class ModelTrainer:
    """
    Trains and manages the ML model for signal quality prediction.

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

        self._model: Optional[Any] = None
        self._samples: List[TrainingSample] = []
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
        """
        Add a training sample from a completed trade.

        Returns True if the model was retrained.
        """
        self._samples.append(sample)
        self._new_samples_since_train += 1

        logger.debug(
            f"Added training sample: symbol={sample.symbol}, "
            f"label={sample.label:.3f}, total={len(self._samples)}"
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
        """
        Train the model on all accumulated samples.

        Uses GradientBoostingClassifier with binary labels:
          label > 0 → class 1 (profitable)
          label <= 0 → class 0 (unprofitable)

        Returns:
            ModelMetrics with performance on a holdout split.
        """
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

        if len(self._samples) < self._min_samples:
            logger.warning(
                f"Not enough samples to train: {len(self._samples)}/{self._min_samples}"
            )
            return self._metrics

        X = np.array([s.features for s in self._samples])
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
                f"need at least 2 for stratified split. Skipping training."
            )
            return self._metrics

        test_size = min(0.2, max(5, len(self._samples) // 5) / len(self._samples))
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )

        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=3,
            random_state=42,
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)

        self._metrics = ModelMetrics(
            accuracy=float(accuracy_score(y_test, y_pred)),
            precision=float(precision_score(y_test, y_pred, zero_division=0)),
            recall=float(recall_score(y_test, y_pred, zero_division=0)),
            f1_score=float(f1_score(y_test, y_pred, zero_division=0)),
            sample_count=len(self._samples),
            trained_at=datetime.now(timezone.utc),
            feature_importances=dict(
                zip(FEATURE_NAMES, model.feature_importances_.tolist())
            ),
        )

        self._model = model
        self._is_trained = True
        self._new_samples_since_train = 0

        self._save_model()

        logger.info(
            f"Model trained: accuracy={self._metrics.accuracy:.3f}, "
            f"f1={self._metrics.f1_score:.3f}, samples={len(self._samples)}"
        )
        return self._metrics

    def predict(self, features: np.ndarray) -> Tuple[float, float]:
        """
        Predict signal quality.

        Args:
            features: Feature vector of shape (NUM_FEATURES,).

        Returns:
            Tuple of (probability_profitable, predicted_class).
            If model is not trained, returns (0.5, 0) as neutral.
        """
        if not self._is_trained or self._model is None:
            return 0.5, 0.0

        X = features.reshape(1, -1)
        proba = self._model.predict_proba(X)[0]

        # proba[1] = probability of class 1 (profitable)
        prob_profitable = float(proba[1]) if len(proba) > 1 else 0.5
        predicted_class = float(self._model.predict(X)[0])

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
                    f"Loaded model with {len(self._samples)} samples from {self._model_dir}"
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
