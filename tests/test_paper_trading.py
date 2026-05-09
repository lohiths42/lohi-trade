"""
Unit tests for the Paper Trading Engine.

Covers:
- Paper trading enabled/disabled flag
- Simulated fill uses next tick price
- Simulated fill applies slippage
- Fill delay within configured range
- No broker API calls
- Paper order IDs start with "PAPER-"
- Separate database path (paper_trades.db)
- Normal database path when disabled
- Paper notification formatting
- Paper trade logging
- Order cancel simulation
- Various order types (BUY/SELL, LIMIT/MARKET)
- Edge cases (zero slippage, min/max delay)

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
"""

import logging
from unittest.mock import patch, MagicMock

import pytest

from src.execution.paper_trading import PaperTradingEngine, DEFAULT_DB_PATH
from src.ingestion.broker_interface import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.utils.config import PaperTradingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    enabled: bool = True,
    delay_ms: list = None,
    slippage_pct: float = 0.05,
) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=enabled,
        simulated_fill_delay_ms=delay_ms or [100, 500],
        simulated_slippage_pct=slippage_pct,
    )


def _make_order(
    symbol: str = "RELIANCE",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: int = 10,
    price: float = None,
) -> Order:
    return Order(
        order_id="test-001",
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        product_type=ProductType.MIS,
        status=OrderStatus.PENDING,
        price=price,
    )


# ---------------------------------------------------------------------------
# 1. Enabled / disabled flag
# ---------------------------------------------------------------------------

class TestPaperTradingFlag:
    def test_is_enabled_true(self):
        engine = PaperTradingEngine(_make_config(enabled=True))
        assert engine.is_enabled is True

    def test_is_enabled_false(self):
        engine = PaperTradingEngine(_make_config(enabled=False))
        assert engine.is_enabled is False


# ---------------------------------------------------------------------------
# 2. Database path
# ---------------------------------------------------------------------------

class TestDatabasePath:
    def test_paper_db_path_when_enabled(self):
        engine = PaperTradingEngine(_make_config(enabled=True))
        assert engine.get_db_path() == DEFAULT_DB_PATH

    def test_normal_db_path_when_disabled(self):
        engine = PaperTradingEngine(
            _make_config(enabled=False), sqlite_path="data/lohi_trade.db"
        )
        assert engine.get_db_path() == "data/lohi_trade.db"

    def test_custom_db_path_overrides(self):
        engine = PaperTradingEngine(
            _make_config(enabled=True), db_path="/tmp/custom.db"
        )
        assert engine.get_db_path() == "/tmp/custom.db"

    def test_default_sqlite_path_when_disabled_no_override(self):
        engine = PaperTradingEngine(_make_config(enabled=False))
        assert engine.get_db_path() == "data/lohi_trade.db"


# ---------------------------------------------------------------------------
# 3. Simulated order fill
# ---------------------------------------------------------------------------

class TestSimulatedFill:
    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_sets_status_to_filled(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        result = engine.simulate_order_fill(order, 1000.0)
        assert result.status == OrderStatus.FILLED

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_uses_next_tick_price(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.BUY)
        engine.simulate_order_fill(order, 1500.0)
        assert order.filled_price == 1500.0

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_applies_positive_slippage_for_buy(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.1))
        order = _make_order(side=OrderSide.BUY)
        engine.simulate_order_fill(order, 1000.0)
        expected = round(1000.0 * (1 + 0.1 / 100.0), 2)
        assert order.filled_price == expected

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_applies_negative_slippage_for_sell(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.1))
        order = _make_order(side=OrderSide.SELL)
        engine.simulate_order_fill(order, 1000.0)
        expected = round(1000.0 * (1 - 0.1 / 100.0), 2)
        assert order.filled_price == expected

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_sets_filled_qty(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order(quantity=25)
        engine.simulate_order_fill(order, 500.0)
        assert order.filled_qty == 25

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_generates_paper_order_id(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        assert order.broker_order_id is not None
        assert order.broker_order_id.startswith("PAPER-")

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_paper_order_id_length(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        # "PAPER-" (6 chars) + 8 hex chars = 14
        assert len(order.broker_order_id) == 14

    @patch("src.execution.paper_trading.time.sleep")
    def test_fill_returns_same_order_object(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        result = engine.simulate_order_fill(order, 100.0)
        assert result is order


# ---------------------------------------------------------------------------
# 4. Fill delay
# ---------------------------------------------------------------------------

class TestFillDelay:
    @patch("src.execution.paper_trading.time.sleep")
    @patch("src.execution.paper_trading.random.randint", return_value=250)
    def test_sleep_called_with_delay_in_range(self, mock_randint, mock_sleep):
        engine = PaperTradingEngine(_make_config(delay_ms=[100, 500]))
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        mock_randint.assert_called_once_with(100, 500)
        mock_sleep.assert_called_once_with(0.25)

    @patch("src.execution.paper_trading.time.sleep")
    @patch("src.execution.paper_trading.random.randint", return_value=100)
    def test_minimum_delay(self, mock_randint, mock_sleep):
        engine = PaperTradingEngine(_make_config(delay_ms=[100, 100]))
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        mock_sleep.assert_called_once_with(0.1)

    @patch("src.execution.paper_trading.time.sleep")
    @patch("src.execution.paper_trading.random.randint", return_value=500)
    def test_maximum_delay(self, mock_randint, mock_sleep):
        engine = PaperTradingEngine(_make_config(delay_ms=[500, 500]))
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        mock_sleep.assert_called_once_with(0.5)


# ---------------------------------------------------------------------------
# 5. No broker API calls
# ---------------------------------------------------------------------------

class TestNoApiCalls:
    @patch("src.execution.paper_trading.time.sleep")
    def test_api_calls_empty_after_fill(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        engine.simulate_order_fill(order, 100.0)
        assert engine.get_api_call_count() == 0

    @patch("src.execution.paper_trading.time.sleep")
    def test_api_calls_empty_after_cancel(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        engine.simulate_order_cancel(order)
        assert engine.get_api_call_count() == 0

    @patch("src.execution.paper_trading.time.sleep")
    def test_api_calls_list_stays_empty(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        for _ in range(5):
            order = _make_order()
            engine.simulate_order_fill(order, 100.0)
        assert engine.api_calls_made == []


# ---------------------------------------------------------------------------
# 6. Order cancel simulation
# ---------------------------------------------------------------------------

class TestOrderCancel:
    def test_cancel_sets_status(self):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        result = engine.simulate_order_cancel(order)
        assert result.status == OrderStatus.CANCELLED

    def test_cancel_returns_same_order(self):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        result = engine.simulate_order_cancel(order)
        assert result is order


# ---------------------------------------------------------------------------
# 7. Notification formatting
# ---------------------------------------------------------------------------

class TestNotificationFormatting:
    def test_prepends_paper_prefix(self):
        engine = PaperTradingEngine(_make_config())
        assert engine.format_paper_notification("Trade executed") == "PAPER: Trade executed"

    def test_empty_message(self):
        engine = PaperTradingEngine(_make_config())
        assert engine.format_paper_notification("") == "PAPER: "

    def test_message_with_special_chars(self):
        engine = PaperTradingEngine(_make_config())
        msg = "BUY RELIANCE @ ₹2500 qty=10"
        assert engine.format_paper_notification(msg) == f"PAPER: {msg}"


# ---------------------------------------------------------------------------
# 8. Paper trade logging
# ---------------------------------------------------------------------------

class TestPaperTradeLogging:
    @patch("src.execution.paper_trading.time.sleep")
    def test_log_contains_paper_prefix(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order(symbol="INFY")
        with patch.object(engine, "log_paper_trade", wraps=engine.log_paper_trade) as mock_log:
            engine.simulate_order_fill(order, 1500.0)
            mock_log.assert_called_once_with(order, "FILL")

    def test_cancel_logs_with_cancel_action(self):
        engine = PaperTradingEngine(_make_config())
        order = _make_order()
        with patch.object(engine, "log_paper_trade", wraps=engine.log_paper_trade) as mock_log:
            engine.simulate_order_cancel(order)
            mock_log.assert_called_once_with(order, "CANCEL")

    @patch("src.execution.paper_trading.time.sleep")
    def test_logger_info_called_with_paper(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        order = _make_order(symbol="TCS")
        with patch("src.execution.paper_trading.logger") as mock_logger:
            engine.log_paper_trade(order, "FILL")
            mock_logger.info.assert_called_once()
            logged_msg = mock_logger.info.call_args[0][0]
            assert "PAPER" in logged_msg
            assert "TCS" in logged_msg


# ---------------------------------------------------------------------------
# 9. Various order types
# ---------------------------------------------------------------------------

class TestVariousOrderTypes:
    @patch("src.execution.paper_trading.time.sleep")
    def test_buy_market_order(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.BUY, order_type=OrderType.MARKET)
        engine.simulate_order_fill(order, 200.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_price == 200.0

    @patch("src.execution.paper_trading.time.sleep")
    def test_sell_market_order(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.SELL, order_type=OrderType.MARKET)
        engine.simulate_order_fill(order, 200.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_price == 200.0

    @patch("src.execution.paper_trading.time.sleep")
    def test_buy_limit_order(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.BUY, order_type=OrderType.LIMIT, price=195.0)
        engine.simulate_order_fill(order, 195.0)
        assert order.status == OrderStatus.FILLED

    @patch("src.execution.paper_trading.time.sleep")
    def test_sell_limit_order(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.SELL, order_type=OrderType.LIMIT, price=205.0)
        engine.simulate_order_fill(order, 205.0)
        assert order.status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @patch("src.execution.paper_trading.time.sleep")
    def test_zero_slippage(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.BUY)
        engine.simulate_order_fill(order, 999.99)
        assert order.filled_price == 999.99

    @patch("src.execution.paper_trading.time.sleep")
    def test_large_slippage(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=1.0))
        order = _make_order(side=OrderSide.BUY)
        engine.simulate_order_fill(order, 1000.0)
        expected = round(1000.0 * 1.01, 2)
        assert order.filled_price == expected

    @patch("src.execution.paper_trading.time.sleep")
    def test_very_small_price(self, mock_sleep):
        engine = PaperTradingEngine(_make_config(slippage_pct=0.0))
        order = _make_order(side=OrderSide.BUY)
        engine.simulate_order_fill(order, 0.01)
        assert order.filled_price == 0.01

    @patch("src.execution.paper_trading.time.sleep")
    def test_unique_paper_order_ids(self, mock_sleep):
        engine = PaperTradingEngine(_make_config())
        ids = set()
        for _ in range(50):
            order = _make_order()
            engine.simulate_order_fill(order, 100.0)
            ids.add(order.broker_order_id)
        assert len(ids) == 50
