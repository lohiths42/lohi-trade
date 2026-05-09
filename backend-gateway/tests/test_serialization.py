"""Unit tests for data serialization and validation functions.

Tests cover: serialize_query_results, deserialize_llm_response,
validate_numeric_accuracy, validate_numeric_accuracy_detailed,
and validate_trade_ids.

Requirements: 21.1, 21.2, 21.4, 21.5
"""

import json
from datetime import datetime, timezone

import pytest

from app.services.chatbot_service import (
    ChatbotService,
    PerformanceSummary,
    SignalExplanation,
    StockInfo,
    TradeDetail,
)


# ── serialize_query_results tests (Req 21.1) ────────────────────────────────


class TestSerializeQueryResults:
    """Validates: Requirements 21.1"""

    def test_serialize_list_of_dicts(self):
        results = [{"id": "t1", "pnl": 500.0}, {"id": "t2", "pnl": -100.0}]
        json_str = ChatbotService.serialize_query_results(results)
        parsed = json.loads(json_str)
        assert len(parsed) == 2
        assert parsed[0]["id"] == "t1"
        assert parsed[1]["pnl"] == -100.0

    def test_serialize_trade_detail_dataclass(self):
        trade = TradeDetail(
            trade_id="t1", symbol="RELIANCE", strategy="mean_reversion",
            entry_price=2500.0, exit_price=2550.0, quantity=10,
            realized_pnl=500.0, entry_time="2024-01-15T10:00:00",
            exit_time="2024-01-15T14:00:00", holding_period="4h",
        )
        json_str = ChatbotService.serialize_query_results(trade)
        parsed = json.loads(json_str)
        assert parsed["trade_id"] == "t1"
        assert parsed["symbol"] == "RELIANCE"
        assert parsed["entry_price"] == 2500.0
        assert parsed["exit_price"] == 2550.0
        assert parsed["realized_pnl"] == 500.0

    def test_serialize_list_of_trade_details(self):
        trades = [
            TradeDetail(
                trade_id="t1", symbol="RELIANCE", strategy="mean_reversion",
                entry_price=2500.0, exit_price=2550.0, quantity=10,
                realized_pnl=500.0, entry_time="2024-01-15T10:00:00",
                exit_time="2024-01-15T14:00:00",
            ),
            TradeDetail(
                trade_id="t2", symbol="TCS", strategy="trend_following",
                entry_price=3500.0, exit_price=3400.0, quantity=5,
                realized_pnl=-500.0, entry_time="2024-01-16T10:00:00",
                exit_time="2024-01-16T14:00:00",
            ),
        ]
        json_str = ChatbotService.serialize_query_results(trades)
        parsed = json.loads(json_str)
        assert len(parsed) == 2
        assert parsed[0]["symbol"] == "RELIANCE"
        assert parsed[1]["symbol"] == "TCS"

    def test_serialize_performance_summary(self):
        summary = PerformanceSummary(
            total_pnl=5000.0, trade_count=20, win_count=12, loss_count=8,
            win_rate=60.0, avg_profit=250.0, best_trade_pnl=1500.0,
            best_trade_symbol="RELIANCE", worst_trade_pnl=-800.0,
            worst_trade_symbol="TCS", sharpe_ratio=1.5,
        )
        json_str = ChatbotService.serialize_query_results(summary)
        parsed = json.loads(json_str)
        assert parsed["total_pnl"] == 5000.0
        assert parsed["win_rate"] == 60.0
        assert parsed["sharpe_ratio"] == 1.5

    def test_serialize_signal_explanation(self):
        signal = SignalExplanation(
            symbol="RELIANCE", signal_type="BUY", strategy="mean_reversion",
            indicator_values={"rsi": 28.5, "sma_20": 2480.0},
            bias_state="BULLISH", signal_time="2024-01-15T09:30:00",
        )
        json_str = ChatbotService.serialize_query_results(signal)
        parsed = json.loads(json_str)
        assert parsed["symbol"] == "RELIANCE"
        assert parsed["indicator_values"]["rsi"] == 28.5

    def test_serialize_stock_info(self):
        info = StockInfo(
            symbol="RELIANCE",
            recent_sentiment=[{"sentiment": "BULLISH", "score": 0.85}],
            bias_status="BULLISH",
            open_positions=[],
            recent_trades=[{"pnl": 500.0}],
        )
        json_str = ChatbotService.serialize_query_results(info)
        parsed = json.loads(json_str)
        assert parsed["symbol"] == "RELIANCE"
        assert parsed["bias_status"] == "BULLISH"
        assert len(parsed["recent_sentiment"]) == 1

    def test_serialize_handles_datetime(self):
        results = [{"time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)}]
        json_str = ChatbotService.serialize_query_results(results)
        parsed = json.loads(json_str)
        assert "2024" in parsed[0]["time"]

    def test_serialize_handles_none_values(self):
        trade = TradeDetail(
            trade_id="t1", symbol="RELIANCE", strategy="mean_reversion",
            entry_price=2500.0, exit_price=None, quantity=10,
            realized_pnl=None, entry_time="2024-01-15T10:00:00",
            exit_time=None,
        )
        json_str = ChatbotService.serialize_query_results(trade)
        parsed = json.loads(json_str)
        assert parsed["exit_price"] is None
        assert parsed["realized_pnl"] is None

    def test_serialize_empty_list(self):
        json_str = ChatbotService.serialize_query_results([])
        assert json.loads(json_str) == []

    def test_serialize_single_dict(self):
        result = {"id": "t1", "pnl": 100.0}
        json_str = ChatbotService.serialize_query_results(result)
        parsed = json.loads(json_str)
        assert parsed["id"] == "t1"


# ── deserialize_llm_response tests (Req 21.2) ───────────────────────────────


class TestDeserializeLLMResponse:
    """Validates: Requirements 21.2"""

    def test_deserialize_to_dict(self):
        result = ChatbotService.deserialize_llm_response('{"pnl": 500}')
        assert result == {"pnl": 500}

    def test_deserialize_to_trade_detail(self):
        data = {
            "trade_id": "t1", "symbol": "RELIANCE", "strategy": "mean_reversion",
            "entry_price": 2500.0, "exit_price": 2550.0, "quantity": 10,
            "realized_pnl": 500.0, "entry_time": "2024-01-15T10:00:00",
            "exit_time": "2024-01-15T14:00:00",
        }
        result = ChatbotService.deserialize_llm_response(
            json.dumps(data), expected_type=TradeDetail
        )
        assert isinstance(result, TradeDetail)
        assert result.trade_id == "t1"
        assert result.symbol == "RELIANCE"
        assert result.entry_price == 2500.0

    def test_deserialize_to_list_of_trade_details(self):
        data = [
            {
                "trade_id": "t1", "symbol": "RELIANCE", "strategy": "mr",
                "entry_price": 2500.0, "exit_price": 2550.0, "quantity": 10,
                "realized_pnl": 500.0, "entry_time": "2024-01-15T10:00:00",
                "exit_time": "2024-01-15T14:00:00",
            },
            {
                "trade_id": "t2", "symbol": "TCS", "strategy": "tf",
                "entry_price": 3500.0, "exit_price": 3400.0, "quantity": 5,
                "realized_pnl": -500.0, "entry_time": "2024-01-16T10:00:00",
                "exit_time": "2024-01-16T14:00:00",
            },
        ]
        result = ChatbotService.deserialize_llm_response(
            json.dumps(data), expected_type=TradeDetail
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(t, TradeDetail) for t in result)

    def test_deserialize_to_performance_summary(self):
        data = {
            "total_pnl": 5000.0, "trade_count": 20, "win_count": 12,
            "loss_count": 8, "win_rate": 60.0, "avg_profit": 250.0,
            "best_trade_pnl": 1500.0, "best_trade_symbol": "RELIANCE",
            "worst_trade_pnl": -800.0, "worst_trade_symbol": "TCS",
            "sharpe_ratio": 1.5,
        }
        result = ChatbotService.deserialize_llm_response(
            json.dumps(data), expected_type=PerformanceSummary
        )
        assert isinstance(result, PerformanceSummary)
        assert result.total_pnl == 5000.0
        assert result.win_rate == 60.0

    def test_deserialize_to_signal_explanation(self):
        data = {
            "symbol": "RELIANCE", "signal_type": "BUY",
            "strategy": "mean_reversion",
            "indicator_values": {"rsi": 28.5},
            "bias_state": "BULLISH", "signal_time": "2024-01-15T09:30:00",
        }
        result = ChatbotService.deserialize_llm_response(
            json.dumps(data), expected_type=SignalExplanation
        )
        assert isinstance(result, SignalExplanation)
        assert result.symbol == "RELIANCE"

    def test_deserialize_to_stock_info(self):
        data = {
            "symbol": "RELIANCE",
            "recent_sentiment": [{"sentiment": "BULLISH"}],
            "bias_status": "BULLISH",
            "open_positions": [],
            "recent_trades": [],
        }
        result = ChatbotService.deserialize_llm_response(
            json.dumps(data), expected_type=StockInfo
        )
        assert isinstance(result, StockInfo)
        assert result.symbol == "RELIANCE"

    def test_deserialize_invalid_json_returns_none(self):
        result = ChatbotService.deserialize_llm_response("not json")
        assert result is None

    def test_deserialize_none_input_returns_none(self):
        result = ChatbotService.deserialize_llm_response(None)
        assert result is None

    def test_deserialize_mismatched_type_returns_none(self):
        # Missing required fields for TradeDetail
        result = ChatbotService.deserialize_llm_response(
            '{"foo": "bar"}', expected_type=TradeDetail
        )
        assert result is None

    def test_deserialize_default_type_is_dict(self):
        result = ChatbotService.deserialize_llm_response('{"key": "value"}')
        assert isinstance(result, dict)
        assert result["key"] == "value"


# ── Round-trip serialization tests (Req 21.3) ───────────────────────────────


class TestSerializationRoundTrip:
    """Validates: Requirements 21.3"""

    def test_round_trip_trade_detail(self):
        original = TradeDetail(
            trade_id="t1", symbol="RELIANCE", strategy="mean_reversion",
            entry_price=2500.50, exit_price=2550.75, quantity=10,
            realized_pnl=502.50, entry_time="2024-01-15T10:00:00",
            exit_time="2024-01-15T14:00:00", holding_period="4h",
        )
        json_str = ChatbotService.serialize_query_results(original)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=TradeDetail
        )
        assert isinstance(restored, TradeDetail)
        assert restored.trade_id == original.trade_id
        assert restored.symbol == original.symbol
        assert restored.entry_price == original.entry_price
        assert restored.exit_price == original.exit_price
        assert restored.realized_pnl == original.realized_pnl

    def test_round_trip_performance_summary(self):
        original = PerformanceSummary(
            total_pnl=5000.0, trade_count=20, win_count=12, loss_count=8,
            win_rate=60.0, avg_profit=250.0, best_trade_pnl=1500.0,
            best_trade_symbol="RELIANCE", worst_trade_pnl=-800.0,
            worst_trade_symbol="TCS", sharpe_ratio=1.5,
        )
        json_str = ChatbotService.serialize_query_results(original)
        restored = ChatbotService.deserialize_llm_response(
            json_str, expected_type=PerformanceSummary
        )
        assert isinstance(restored, PerformanceSummary)
        assert restored.total_pnl == original.total_pnl
        assert restored.win_rate == original.win_rate
        assert restored.sharpe_ratio == original.sharpe_ratio

    def test_round_trip_list_of_dicts(self):
        original = [
            {"id": "t1", "pnl": 500.0, "symbol": "RELIANCE"},
            {"id": "t2", "pnl": -100.0, "symbol": "TCS"},
        ]
        json_str = ChatbotService.serialize_query_results(original)
        restored = ChatbotService.deserialize_llm_response(json_str)
        assert restored == original


# ── validate_numeric_accuracy tests (Req 21.4) ──────────────────────────────


class TestValidateNumericAccuracy:
    """Validates: Requirements 21.4"""

    def test_all_values_within_tolerance(self):
        llm = {"pnl": 500.005, "price": 2500.001}
        db = {"pnl": 500.0, "price": 2500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_value_exceeds_tolerance(self):
        llm = {"pnl": 501.0}
        db = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is False

    def test_exact_match(self):
        llm = {"pnl": 500.0, "price": 2500.0}
        db = {"pnl": 500.0, "price": 2500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_at_tolerance_boundary(self):
        llm = {"pnl": 500.01}
        db = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_just_over_tolerance(self):
        llm = {"pnl": 500.011}
        db = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is False

    def test_custom_tolerance(self):
        llm = {"pnl": 505.0}
        db = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db, tolerance=10.0) is True
        assert ChatbotService.validate_numeric_accuracy(llm, db, tolerance=1.0) is False

    def test_missing_key_in_db_skipped(self):
        llm = {"pnl": 500.0, "extra": 999.0}
        db = {"pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_non_numeric_values_skipped(self):
        llm = {"name": "RELIANCE", "pnl": 500.0}
        db = {"name": "RELIANCE", "pnl": 500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_empty_dicts(self):
        assert ChatbotService.validate_numeric_accuracy({}, {}) is True

    def test_negative_values(self):
        llm = {"pnl": -500.005}
        db = {"pnl": -500.0}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True

    def test_string_numeric_values(self):
        llm = {"pnl": "500.005"}
        db = {"pnl": "500.0"}
        assert ChatbotService.validate_numeric_accuracy(llm, db) is True


# ── validate_numeric_accuracy_detailed tests (Req 21.4) ─────────────────────


class TestValidateNumericAccuracyDetailed:
    """Validates: Requirements 21.4"""

    def test_no_discrepancies(self):
        llm = {"pnl": 500.005, "price": 2500.001}
        db = {"pnl": 500.0, "price": 2500.0}
        result = ChatbotService.validate_numeric_accuracy_detailed(llm, db)
        assert result == []

    def test_returns_discrepancies(self):
        llm = {"pnl": 501.0, "price": 2500.0}
        db = {"pnl": 500.0, "price": 2500.0}
        result = ChatbotService.validate_numeric_accuracy_detailed(llm, db)
        assert len(result) == 1
        assert result[0]["key"] == "pnl"
        assert result[0]["llm_value"] == 501.0
        assert result[0]["db_value"] == 500.0
        assert result[0]["difference"] == 1.0

    def test_multiple_discrepancies(self):
        llm = {"pnl": 510.0, "price": 2600.0}
        db = {"pnl": 500.0, "price": 2500.0}
        result = ChatbotService.validate_numeric_accuracy_detailed(llm, db)
        assert len(result) == 2

    def test_non_numeric_skipped(self):
        llm = {"name": "RELIANCE", "pnl": 500.0}
        db = {"name": "RELIANCE", "pnl": 500.0}
        result = ChatbotService.validate_numeric_accuracy_detailed(llm, db)
        assert result == []


# ── validate_trade_ids tests (Req 21.5) ─────────────────────────────────────


class TestValidateTradeIds:
    """Validates: Requirements 21.5"""

    def test_all_ids_valid(self):
        trade_ids = ["t1", "t2", "t3"]
        user_ids = ["t1", "t2", "t3", "t4", "t5"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert invalid == []

    def test_some_ids_invalid(self):
        trade_ids = ["t1", "t2", "t99"]
        user_ids = ["t1", "t2", "t3"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert invalid == ["t99"]

    def test_all_ids_invalid(self):
        trade_ids = ["t99", "t100"]
        user_ids = ["t1", "t2", "t3"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert set(invalid) == {"t99", "t100"}

    def test_empty_trade_ids(self):
        invalid = ChatbotService.validate_trade_ids([], ["t1", "t2"])
        assert invalid == []

    def test_empty_user_trade_ids(self):
        invalid = ChatbotService.validate_trade_ids(["t1"], [])
        assert invalid == ["t1"]

    def test_both_empty(self):
        invalid = ChatbotService.validate_trade_ids([], [])
        assert invalid == []

    def test_numeric_ids_as_strings(self):
        trade_ids = [1, 2, 3]
        user_ids = ["1", "2", "3"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert invalid == []

    def test_uuid_style_ids(self):
        trade_ids = ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
        user_ids = ["a1b2c3d4-e5f6-7890-abcd-ef1234567890", "other-id"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert invalid == []

    def test_duplicate_invalid_ids(self):
        trade_ids = ["t99", "t99"]
        user_ids = ["t1", "t2"]
        invalid = ChatbotService.validate_trade_ids(trade_ids, user_ids)
        assert invalid == ["t99", "t99"]
