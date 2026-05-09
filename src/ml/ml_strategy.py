"""
ML-Enhanced Trading Strategy for LOHI-TRADE.

Wraps the existing rule-based strategies with an ML quality filter.
When the ML model is trained, it scores each candidate signal and
only passes through signals above a confidence threshold.

When the model is not yet trained (cold start), it passes all signals
through and collects training data from outcomes.

Integrates with:
- IndicatorEngine (technical features)
- BiasCalculator (sentiment features)
- ModelTrainer (prediction + feedback)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

from src.ml.feature_engine import (
    SentimentFeatures,
    extract_features,
    extract_label,
    FeatureVector,
)
from src.ml.model_trainer import ModelTrainer, TrainingSample
from src.soldier.indicator_engine import IndicatorSet
from src.soldier.strategy_engine import Signal, Strategy, create_signal
from src.utils.logger import get_logger

logger = get_logger("MLStrategy")

DEFAULT_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class MLStrategyConfig:
    """Configuration for the ML strategy."""
    enabled: bool = True
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    min_training_samples: int = 30
    passthrough_when_untrained: bool = True


class MLStrategy(Strategy):
    """
    ML-enhanced strategy that filters signals from base strategies.

    In trained mode: only passes signals where ML model predicts
    probability of profit > confidence_threshold.

    In untrained mode (cold start): passes all signals through
    to collect training data.
    """

    def __init__(
        self,
        base_strategies: List[Strategy],
        model_trainer: ModelTrainer,
        config: Optional[MLStrategyConfig] = None,
    ) -> None:
        self._base_strategies = base_strategies
        self._trainer = model_trainer
        self._config = config or MLStrategyConfig()
        self._sentiment_cache: dict = {}  # symbol → SentimentFeatures
        self._pending_signals: dict = {}  # signal_id → FeatureVector

        logger.info(
            f"MLStrategy initialized with {len(base_strategies)} base strategies, "
            f"threshold={self._config.confidence_threshold}, "
            f"trained={self._trainer.is_trained}"
        )

    @property
    def name(self) -> str:
        return "MLEnhanced"

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def update_sentiment(self, symbol: str, sentiment: SentimentFeatures) -> None:
        """Update cached sentiment for a symbol."""
        self._sentiment_cache[symbol] = sentiment

    def generate_signal(
        self, indicators: IndicatorSet, candles: pd.DataFrame
    ) -> Optional[Signal]:
        """
        Run base strategies and filter through ML model.

        1. Run each enabled base strategy
        2. For the first signal found, extract features
        3. If model is trained, predict quality and filter
        4. If model is untrained, pass through (cold start)
        """
        if not self._config.enabled:
            return None

        # Get close price from latest candle
        if candles.empty:
            return None
        close_price = float(candles.iloc[-1]["close"])

        # Run base strategies
        candidate_signal: Optional[Signal] = None
        for strategy in self._base_strategies:
            if not strategy.enabled:
                continue
            signal = strategy.generate_signal(indicators, candles)
            if signal is not None:
                candidate_signal = signal
                break

        if candidate_signal is None:
            return None

        # Extract features
        sentiment = self._sentiment_cache.get(
            indicators.symbol, SentimentFeatures()
        )
        fv = extract_features(indicators, close_price, sentiment)

        # ML filtering
        if self._trainer.is_trained:
            prob, pred_class = self._trainer.predict(fv.features)

            if prob < self._config.confidence_threshold:
                logger.info(
                    f"ML filter rejected signal: {candidate_signal.symbol} "
                    f"{candidate_signal.strategy} prob={prob:.3f} "
                    f"< threshold={self._config.confidence_threshold}"
                )
                return None

            logger.info(
                f"ML filter approved signal: {candidate_signal.symbol} "
                f"{candidate_signal.strategy} prob={prob:.3f}"
            )
        elif not self._config.passthrough_when_untrained:
            logger.debug("ML model not trained and passthrough disabled")
            return None

        # Cache feature vector for feedback when trade completes
        self._pending_signals[candidate_signal.signal_id] = fv

        return candidate_signal

    def record_outcome(
        self,
        signal_id: str,
        entry_price: float,
        exit_price: float,
        side: str,
        atr: float,
    ) -> bool:
        """
        Record a completed trade outcome for model training.

        Called when a trade exits. Pairs the stored feature vector
        with the outcome label and feeds it to the trainer.

        Returns True if the model was retrained.
        """
        fv = self._pending_signals.pop(signal_id, None)
        if fv is None:
            logger.debug(f"No pending features for signal {signal_id}")
            return False

        label = extract_label(entry_price, exit_price, side, atr)

        sample = TrainingSample(
            features=fv.features,
            label=label,
            symbol=fv.symbol,
            timestamp=fv.timestamp,
        )

        retrained = self._trainer.add_sample(sample)

        logger.info(
            f"Recorded outcome: signal={signal_id[:8]}… "
            f"label={label:.3f} retrained={retrained}"
        )
        return retrained
