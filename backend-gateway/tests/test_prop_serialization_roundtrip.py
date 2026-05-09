"""Property-based tests for serialization round-trip.

**Validates: Requirements 21.3**

Property 19: Serialization round-trip — serializing trade query results to JSON
    then deserializing back produces equivalent objects.
"""

import json

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.chatbot_service import (
    ChatbotService,
    PerformanceSummary,
    SignalExplanation,
    StockInfo,
    TradeDetail,
)


# ── Strategies ───────────────────────────────────────────────────────────────

# Finite floats that survive JSON round-trip (no NaN/Inf)
finite_floats = st.floats(
    min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False,
)

# Non-negative finite floats for prices/quantities
positive_floats = st.floats(
    min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False,
)

# Simple text for string fields (printable, no surrogates)
simple_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="\x00"),
    min_size=1,
    max_size=50,
)

iso_datetime_text = st.datetimes(
    min_value=__import__("datetime").datetime(2000, 1, 1),
    max_value=__import__("datetime").datetime(2030, 12, 31),
).map(lambda dt: dt.isoformat())

optional_iso_datetime = st.one_of(st.none(), iso_datetime_text)

optional_float = st.one_of(st.none(), finite_floats)

# Strategy: arbitrary TradeDetail instances
trade_detail_strategy = st.builds(
    TradeDetail,
    trade_id=simple_text,
    symbol=st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
    strategy=st.sampled_from(["mean_reversion", "trend_following", "orb", "momentum", "scalping"]),
    entry_price=positive_floats,
    exit_price=st.one_of(st.none(), positive_floats),
    quantity=st.integers(min_value=1, max_value=100000),
    realized_pnl=optional_float,
    entry_time=iso_datetime_text,
    exit_time=optional_iso_datetime,
    holding_period=st.one_of(st.none(), st.sampled_from(["1h", "4h", "1d", "3d", "1w"])),
)

# Strategy: arbitrary PerformanceSummary instances
performance_summary_strategy = st.builds(
    PerformanceSummary,
    total_pnl=finite_floats,
    trade_count=st.integers(min_value=0, max_value=100000),
    win_count=st.integers(min_value=0, max_value=100000),
    loss_count=st.integers(min_value=0, max_value=100000),
    win_rate=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    avg_profit=finite_floats,
    best_trade_pnl=finite_floats,
    best_trade_symbol=st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
    worst_trade_pnl=finite_floats,
    worst_trade_symbol=st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
    sharpe_ratio=optional_float,
)

# Strategy: arbitrary SignalExplanation instances
signal_explanation_strategy = st.builds(
    SignalExplanation,
    symbol=st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
    signal_type=st.sampled_from(["BUY", "SELL", "HOLD"]),
    strategy=st.sampled_from(["mean_reversion", "trend_following", "orb"]),
    indicator_values=st.dictionaries(
        keys=st.sampled_from(["rsi", "sma_20", "ema_50", "macd", "volume"]),
        values=finite_floats,
        min_size=1,
        max_size=5,
    ),
    bias_state=st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL"]),
    signal_time=iso_datetime_text,
)

# Strategy: arbitrary StockInfo instances
stock_info_strategy = st.builds(
    StockInfo,
    symbol=st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
    recent_sentiment=st.lists(
        st.fixed_dictionaries({
            "sentiment": st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL"]),
            "score": st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        }),
        min_size=0,
        max_size=5,
    ),
    bias_status=st.one_of(st.none(), st.sampled_from(["BULLISH", "BEARISH", "NEUTRAL"])),
    open_positions=st.lists(
        st.fixed_dictionaries({
            "symbol": st.from_regex(r"[A-Z]{2,10}", fullmatch=True),
            "quantity": st.integers(min_value=1, max_value=10000),
        }),
        min_size=0,
        max_size=3,
    ),
    recent_trades=st.lists(
        st.fixed_dictionaries({
            "pnl": finite_floats,
        }),
        min_size=0,
        max_size=5,
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _assert_trade_detail_equivalent(original: TradeDetail, restored: TradeDetail):
    """Assert two TradeDetail instances are equivalent after round-trip."""
    assert restored.trade_id == original.trade_id
    assert restored.symbol == original.symbol
    assert restored.strategy == original.strategy
    assert restored.entry_price == original.entry_price
    assert restored.exit_price == original.exit_price
    assert restored.quantity == original.quantity
    assert restored.realized_pnl == original.realized_pnl
    assert restored.entry_time == original.entry_time
    assert restored.exit_time == original.exit_time
    assert restored.holding_period == original.holding_period


def _assert_performance_summary_equivalent(
    original: PerformanceSummary, restored: PerformanceSummary
):
    """Assert two PerformanceSummary instances are equivalent after round-trip."""
    assert restored.total_pnl == original.total_pnl
    assert restored.trade_count == original.trade_count
    assert restored.win_count == original.win_count
    assert restored.loss_count == original.loss_count
    assert restored.win_rate == original.win_rate
    assert restored.avg_profit == original.avg_profit
    assert restored.best_trade_pnl == original.best_trade_pnl
    assert restored.best_trade_symbol == original.best_trade_symbol
    assert restored.worst_trade_pnl == original.worst_trade_pnl
    assert restored.worst_trade_symbol == original.worst_trade_symbol
    assert restored.sharpe_ratio == original.sharpe_ratio


def _assert_signal_explanation_equivalent(
    original: SignalExplanation, restored: SignalExplanation
):
    """Assert two SignalExplanation instances are equivalent after round-trip."""
    assert restored.symbol == original.symbol
    assert restored.signal_type == original.signal_type
    assert restored.strategy == original.strategy
    assert restored.indicator_values == original.indicator_values
    assert restored.bias_state == original.bias_state
    assert restored.signal_time == original.signal_time


def _assert_stock_info_equivalent(original: StockInfo, restored: StockInfo):
    """Assert two StockInfo instances are equivalent after round-trip."""
    assert restored.symbol == original.symbol
    assert restored.recent_sentiment == original.recent_sentiment
    assert restored.bias_status == original.bias_status
    assert restored.open_positions == original.open_positions
    assert restored.recent_trades == original.recent_trades


# ── Property 19: Serialization round-trip ────────────────────────────────────


class TestSerializationRoundTripProperty:
    """**Validates: Requirements 21.3**

    Property 19: Serialization round-trip — serializing trade query results
    to JSON then deserializing back produces equivalent objects.
    """

    @given(trade=trade_detail_strategy)
    @settings(max_examples=100)
    def test_trade_detail_round_trip(self, trade: TradeDetail):
        """Serializing a TradeDetail to JSON then deserializing back
        produces an equivalent TradeDetail."""
        json_str = ChatbotService.serialize_query_results(trade)
        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        # Deserialize back to TradeDetail
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=TradeDetail
        )
        assert isinstance(restored, TradeDetail)
        _assert_trade_detail_equivalent(trade, restored)

    @given(summary=performance_summary_strategy)
    @settings(max_examples=100)
    def test_performance_summary_round_trip(self, summary: PerformanceSummary):
        """Serializing a PerformanceSummary to JSON then deserializing back
        produces an equivalent PerformanceSummary."""
        json_str = ChatbotService.serialize_query_results(summary)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=PerformanceSummary
        )
        assert isinstance(restored, PerformanceSummary)
        _assert_performance_summary_equivalent(summary, restored)

    @given(signal=signal_explanation_strategy)
    @settings(max_examples=100)
    def test_signal_explanation_round_trip(self, signal: SignalExplanation):
        """Serializing a SignalExplanation to JSON then deserializing back
        produces an equivalent SignalExplanation."""
        json_str = ChatbotService.serialize_query_results(signal)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=SignalExplanation
        )
        assert isinstance(restored, SignalExplanation)
        _assert_signal_explanation_equivalent(signal, restored)

    @given(info=stock_info_strategy)
    @settings(max_examples=100)
    def test_stock_info_round_trip(self, info: StockInfo):
        """Serializing a StockInfo to JSON then deserializing back
        produces an equivalent StockInfo."""
        json_str = ChatbotService.serialize_query_results(info)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=StockInfo
        )
        assert isinstance(restored, StockInfo)
        _assert_stock_info_equivalent(info, restored)

    @given(trades=st.lists(trade_detail_strategy, min_size=1, max_size=10))
    @settings(max_examples=50)
    def test_list_of_trade_details_round_trip(self, trades: list):
        """Serializing a list of TradeDetails to JSON then deserializing back
        produces equivalent TradeDetail objects."""
        json_str = ChatbotService.serialize_query_results(trades)
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == len(trades)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=TradeDetail
        )
        assert isinstance(restored, list)
        assert len(restored) == len(trades)
        for original, result in zip(trades, restored):
            assert isinstance(result, TradeDetail)
            _assert_trade_detail_equivalent(original, result)
