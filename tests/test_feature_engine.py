"""
Unit tests for the ML Feature Engine.
"""

import numpy as np
import pytest
from datetime import datetime

from src.ml.feature_engine import (
    extract_features,
    extract_label,
    SentimentFeatures,
    FeatureVector,
    NUM_FEATURES,
    FEATURE_NAMES,
    _safe_div,
    _rsi_zone,
    _macd_crossover,
)
from src.soldier.indicator_engine import IndicatorSet


def _make_indicators(**overrides) -> IndicatorSet:
    """Create a default IndicatorSet with optional overrides."""
    defaults = dict(
        symbol="RELIANCE",
        timeframe="1m",
        timestamp=datetime(2025, 1, 15, 10, 30),
        rsi_14=50.0,
        macd=0.5,
        macd_signal=0.3,
        macd_hist=0.2,
        bb_upper=110.0,
        bb_middle=100.0,
        bb_lower=90.0,
        vwap=100.0,
        ema_9=101.0,
        ema_21=99.0,
        supertrend=98.0,
        supertrend_direction=1,
        atr_14=5.0,
        volume_avg_20=100000.0,
    )
    defaults.update(overrides)
    return IndicatorSet(**defaults)


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(10.0, 2.0) == 5.0

    def test_zero_denominator(self):
        assert _safe_div(10.0, 0.0) == 0.0

    def test_nan_denominator(self):
        assert _safe_div(10.0, float("nan")) == 0.0

    def test_inf_denominator(self):
        assert _safe_div(10.0, float("inf")) == 0.0

    def test_custom_default(self):
        assert _safe_div(10.0, 0.0, default=99.0) == 99.0


class TestRSIZone:
    def test_oversold(self):
        assert _rsi_zone(20.0) == -1.0
        assert _rsi_zone(29.9) == -1.0

    def test_overbought(self):
        assert _rsi_zone(80.0) == 1.0
        assert _rsi_zone(70.1) == 1.0

    def test_neutral(self):
        assert _rsi_zone(50.0) == 0.0
        assert _rsi_zone(30.0) == 0.0
        assert _rsi_zone(70.0) == 0.0


class TestMACDCrossover:
    def test_bullish(self):
        assert _macd_crossover(1.0, 0.5) == 1.0

    def test_bearish(self):
        assert _macd_crossover(0.5, 1.0) == -1.0

    def test_flat(self):
        assert _macd_crossover(1.0, 1.0) == 0.0


class TestExtractFeatures:
    def test_output_shape(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        assert fv.features.shape == (NUM_FEATURES,)

    def test_feature_names_match(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        assert len(fv.feature_names) == NUM_FEATURES
        assert fv.feature_names == FEATURE_NAMES

    def test_symbol_preserved(self):
        ind = _make_indicators(symbol="INFY")
        fv = extract_features(ind, close_price=100.0)
        assert fv.symbol == "INFY"

    def test_close_price_stored(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=123.45)
        assert fv.close_price == 123.45

    def test_no_nan_in_features(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        assert not np.any(np.isnan(fv.features))

    def test_no_inf_in_features(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        assert not np.any(np.isinf(fv.features))

    def test_with_sentiment(self):
        ind = _make_indicators()
        sent = SentimentFeatures(score=0.8, confidence=0.9, article_count=5)
        fv = extract_features(ind, close_price=100.0, sentiment=sent)
        d = fv.to_dict()
        assert d["sentiment_score"] == 0.8
        assert d["sentiment_confidence"] == 0.9
        assert d["sentiment_article_count"] == 5.0

    def test_without_sentiment_defaults_zero(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        d = fv.to_dict()
        assert d["sentiment_score"] == 0.0
        assert d["sentiment_confidence"] == 0.0

    def test_rsi_feature(self):
        ind = _make_indicators(rsi_14=25.0)
        fv = extract_features(ind, close_price=100.0)
        d = fv.to_dict()
        assert d["rsi_14"] == 25.0
        assert d["rsi_zone"] == -1.0

    def test_bb_percent_b(self):
        # close=100, lower=90, upper=110 → %B = (100-90)/(110-90) = 0.5
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        d = fv.to_dict()
        assert abs(d["bb_percent_b"] - 0.5) < 0.01

    def test_supertrend_direction(self):
        ind = _make_indicators(supertrend_direction=-1)
        fv = extract_features(ind, close_price=100.0)
        d = fv.to_dict()
        assert d["supertrend_dir"] == -1.0

    def test_zero_close_price(self):
        """Edge case: zero close price should not crash."""
        ind = _make_indicators()
        fv = extract_features(ind, close_price=0.0)
        assert not np.any(np.isnan(fv.features))

    def test_to_dict(self):
        ind = _make_indicators()
        fv = extract_features(ind, close_price=100.0)
        d = fv.to_dict()
        assert isinstance(d, dict)
        assert len(d) == NUM_FEATURES
        for name in FEATURE_NAMES:
            assert name in d


class TestExtractLabel:
    def test_profitable_buy(self):
        label = extract_label(100.0, 110.0, "BUY", 5.0)
        assert label > 0

    def test_losing_buy(self):
        label = extract_label(100.0, 90.0, "BUY", 5.0)
        assert label < 0

    def test_profitable_sell(self):
        label = extract_label(100.0, 90.0, "SELL", 5.0)
        assert label > 0

    def test_losing_sell(self):
        label = extract_label(100.0, 110.0, "SELL", 5.0)
        assert label < 0

    def test_breakeven(self):
        label = extract_label(100.0, 100.0, "BUY", 5.0)
        assert label == 0.0

    def test_clamped_to_range(self):
        # Huge profit should clamp to 1.0
        label = extract_label(100.0, 200.0, "BUY", 1.0)
        assert label == 1.0

        # Huge loss should clamp to -1.0
        label = extract_label(100.0, 0.0, "BUY", 1.0)
        assert label == -1.0

    def test_zero_atr(self):
        label = extract_label(100.0, 110.0, "BUY", 0.0)
        assert label == 0.0

    def test_normalized_by_atr(self):
        # 10 point profit with ATR=10 → 10/(2*10) = 0.5
        label = extract_label(100.0, 110.0, "BUY", 10.0)
        assert abs(label - 0.5) < 0.01
