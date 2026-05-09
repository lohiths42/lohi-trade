"""
Property-based tests for the ML Feature Engine using Hypothesis.

Tests invariants that must hold for ALL possible inputs:
- Feature vectors always have correct shape
- No NaN/Inf in output regardless of input
- Labels always in [-1, 1]
- RSI zones are deterministic
- Feature dict keys match FEATURE_NAMES
"""

import numpy as np
import pytest
from datetime import datetime
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.ml.feature_engine import (
    extract_features,
    extract_label,
    SentimentFeatures,
    NUM_FEATURES,
    FEATURE_NAMES,
    _safe_div,
    _rsi_zone,
    _macd_crossover,
)
from src.soldier.indicator_engine import IndicatorSet


# --- Custom Hypothesis strategies ---

finite_float = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
positive_float = st.floats(
    min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False
)
rsi_float = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
price_float = st.floats(min_value=0.01, max_value=1e5, allow_nan=False, allow_infinity=False)
volume_float = st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False)
direction_int = st.sampled_from([-1, 1])
side_str = st.sampled_from(["BUY", "SELL"])


@st.composite
def indicator_sets(draw):
    """Generate random but valid IndicatorSet instances."""
    bb_lower = draw(price_float)
    bb_middle = bb_lower + draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
    bb_upper = bb_middle + draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
    return IndicatorSet(
        symbol="TEST",
        timeframe="1m",
        timestamp=datetime(2025, 1, 15, 10, 30),
        rsi_14=draw(rsi_float),
        macd=draw(finite_float),
        macd_signal=draw(finite_float),
        macd_hist=draw(finite_float),
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        vwap=draw(price_float),
        ema_9=draw(price_float),
        ema_21=draw(price_float),
        supertrend=draw(price_float),
        supertrend_direction=draw(direction_int),
        atr_14=draw(positive_float),
        volume_avg_20=draw(volume_float),
    )


@st.composite
def sentiment_features(draw):
    """Generate random SentimentFeatures."""
    return SentimentFeatures(
        score=draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        article_count=draw(st.integers(min_value=0, max_value=100)),
    )


# --- Property tests for _safe_div ---

class TestSafeDivProperties:
    @given(
        a=finite_float,
        b=st.floats(min_value=0.001, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    def test_safe_div_finite_result(self, a, b):
        """Division of finite numbers always produces a finite result."""
        result = _safe_div(a, b)
        assert np.isfinite(result)

    @given(a=finite_float)
    def test_safe_div_zero_denom_returns_default(self, a):
        """Zero denominator always returns the default value."""
        assert _safe_div(a, 0.0) == 0.0
        assert _safe_div(a, 0.0, default=42.0) == 42.0

    @given(a=finite_float, default=finite_float)
    def test_safe_div_nan_denom_returns_default(self, a, default):
        """NaN denominator always returns the default value."""
        assert _safe_div(a, float("nan"), default) == default

    @given(a=finite_float, default=finite_float)
    def test_safe_div_inf_denom_returns_default(self, a, default):
        """Inf denominator always returns the default value."""
        assert _safe_div(a, float("inf"), default) == default
        assert _safe_div(a, float("-inf"), default) == default


# --- Property tests for _rsi_zone ---

class TestRSIZoneProperties:
    @given(rsi=st.floats(min_value=0.0, max_value=29.99, allow_nan=False, allow_infinity=False))
    def test_oversold_zone(self, rsi):
        """RSI < 30 always maps to -1 (oversold)."""
        assert _rsi_zone(rsi) == -1.0

    @given(rsi=st.floats(min_value=70.01, max_value=100.0, allow_nan=False, allow_infinity=False))
    def test_overbought_zone(self, rsi):
        """RSI > 70 always maps to 1 (overbought)."""
        assert _rsi_zone(rsi) == 1.0

    @given(rsi=st.floats(min_value=30.0, max_value=70.0, allow_nan=False, allow_infinity=False))
    def test_neutral_zone(self, rsi):
        """RSI in [30, 70] always maps to 0 (neutral)."""
        assert _rsi_zone(rsi) == 0.0

    @given(rsi=rsi_float)
    def test_output_in_valid_set(self, rsi):
        """RSI zone output is always one of {-1, 0, 1}."""
        assert _rsi_zone(rsi) in {-1.0, 0.0, 1.0}


# --- Property tests for _macd_crossover ---

class TestMACDCrossoverProperties:
    @given(macd=finite_float, signal=finite_float)
    def test_output_in_valid_set(self, macd, signal):
        """MACD crossover output is always one of {-1, 0, 1}."""
        assert _macd_crossover(macd, signal) in {-1.0, 0.0, 1.0}

    @given(
        macd=st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
        signal=st.floats(min_value=-1e6, max_value=-0.001, allow_nan=False, allow_infinity=False),
    )
    def test_bullish_when_macd_above_signal(self, macd, signal):
        """When MACD is clearly above signal, crossover is bullish."""
        assert _macd_crossover(macd, signal) == 1.0

    @given(
        macd=st.floats(min_value=-1e6, max_value=-0.001, allow_nan=False, allow_infinity=False),
        signal=st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    def test_bearish_when_macd_below_signal(self, macd, signal):
        """When MACD is clearly below signal, crossover is bearish."""
        assert _macd_crossover(macd, signal) == -1.0


# --- Property tests for extract_features ---

class TestExtractFeaturesProperties:
    @given(indicators=indicator_sets(), close_price=price_float)
    @settings(max_examples=25)
    def test_output_shape_invariant(self, indicators, close_price):
        """Feature vector always has exactly NUM_FEATURES elements."""
        fv = extract_features(indicators, close_price)
        assert fv.features.shape == (NUM_FEATURES,)

    @given(indicators=indicator_sets(), close_price=price_float)
    @settings(max_examples=25)
    def test_no_nan_invariant(self, indicators, close_price):
        """Feature vector never contains NaN."""
        fv = extract_features(indicators, close_price)
        assert not np.any(np.isnan(fv.features))

    @given(indicators=indicator_sets(), close_price=price_float)
    @settings(max_examples=25)
    def test_no_inf_invariant(self, indicators, close_price):
        """Feature vector never contains Inf."""
        fv = extract_features(indicators, close_price)
        assert not np.any(np.isinf(fv.features))

    @given(
        indicators=indicator_sets(),
        close_price=price_float,
        sentiment=sentiment_features(),
    )
    @settings(max_examples=25)
    def test_sentiment_preserved(self, indicators, close_price, sentiment):
        """Sentiment features are always preserved in the output."""
        fv = extract_features(indicators, close_price, sentiment)
        d = fv.to_dict()
        assert d["sentiment_score"] == sentiment.score
        assert d["sentiment_confidence"] == sentiment.confidence
        assert d["sentiment_article_count"] == float(sentiment.article_count)

    @given(indicators=indicator_sets(), close_price=price_float)
    def test_to_dict_keys_match(self, indicators, close_price):
        """Feature dict keys always match FEATURE_NAMES."""
        fv = extract_features(indicators, close_price)
        d = fv.to_dict()
        assert set(d.keys()) == set(FEATURE_NAMES)

    @given(indicators=indicator_sets(), close_price=price_float)
    def test_symbol_preserved(self, indicators, close_price):
        """Symbol is always preserved from indicators."""
        fv = extract_features(indicators, close_price)
        assert fv.symbol == indicators.symbol

    @given(indicators=indicator_sets(), close_price=price_float)
    def test_close_price_stored(self, indicators, close_price):
        """Close price is always stored in the feature vector."""
        fv = extract_features(indicators, close_price)
        assert fv.close_price == close_price

    @given(indicators=indicator_sets())
    def test_zero_close_price_safe(self, indicators):
        """Zero close price never causes NaN/Inf."""
        fv = extract_features(indicators, 0.0)
        assert not np.any(np.isnan(fv.features))
        assert not np.any(np.isinf(fv.features))


# --- Property tests for extract_label ---

class TestExtractLabelProperties:
    @given(
        entry=price_float,
        exit_price=price_float,
        side=side_str,
        atr=positive_float,
    )
    def test_label_in_range(self, entry, exit_price, side, atr):
        """Label is always in [-1, 1]."""
        label = extract_label(entry, exit_price, side, atr)
        assert -1.0 <= label <= 1.0

    @given(price=price_float, side=side_str, atr=positive_float)
    def test_breakeven_is_zero(self, price, side, atr):
        """Same entry and exit always produces label 0."""
        label = extract_label(price, price, side, atr)
        assert label == 0.0

    @given(entry=price_float, exit_price=price_float, side=side_str)
    def test_zero_atr_returns_zero(self, entry, exit_price, side):
        """Zero ATR always returns label 0."""
        label = extract_label(entry, exit_price, side, 0.0)
        assert label == 0.0

    @given(
        entry=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        profit=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        atr=positive_float,
    )
    def test_buy_profit_positive_label(self, entry, profit, atr):
        """Profitable BUY always has positive label."""
        label = extract_label(entry, entry + profit, "BUY", atr)
        assert label > 0

    @given(
        entry=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        profit=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        atr=positive_float,
    )
    def test_sell_profit_positive_label(self, entry, profit, atr):
        """Profitable SELL always has positive label."""
        label = extract_label(entry, entry - profit, "SELL", atr)
        assert label > 0

    @given(
        entry=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        loss=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        atr=positive_float,
    )
    def test_buy_loss_negative_label(self, entry, loss, atr):
        """Losing BUY always has negative label."""
        label = extract_label(entry, entry - loss, "BUY", atr)
        assert label < 0

    @given(
        entry=price_float,
        exit_price=price_float,
        atr=positive_float,
    )
    def test_buy_sell_symmetry(self, entry, exit_price, atr):
        """BUY and SELL labels are negatives of each other."""
        buy_label = extract_label(entry, exit_price, "BUY", atr)
        sell_label = extract_label(entry, exit_price, "SELL", atr)
        assert abs(buy_label + sell_label) < 1e-10
