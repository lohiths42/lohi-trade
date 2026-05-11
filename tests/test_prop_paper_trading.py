"""Property-based tests for the Paper Trading Engine.

Uses hypothesis to verify paper trading properties across randomly
generated orders and prices.

Properties tested:
- Property 65: Paper Mode API Bypass     (Validates: Requirements 16.2)
- Property 66: Paper Fill Simulation      (Validates: Requirements 16.3)
- Property 67: Paper Fill Delay           (Validates: Requirements 16.4)
- Property 68: Paper Trade Logging        (Validates: Requirements 16.6)
"""

from unittest.mock import patch

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.execution.paper_trading import PaperTradingEngine
from src.ingestion.broker_interface import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.utils.config import PaperTradingConfig

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

order_sides = st.sampled_from([OrderSide.BUY, OrderSide.SELL])
order_types = st.sampled_from([OrderType.MARKET, OrderType.LIMIT])
symbols = st.sampled_from(["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"])
quantities = st.integers(min_value=1, max_value=10000)
prices = st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)
slippage_pcts = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)


def _make_order(
    symbol: str = "RELIANCE",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: int = 10,
) -> Order:
    return Order(
        order_id="prop-test-001",
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        product_type=ProductType.MIS,
        status=OrderStatus.PENDING,
    )


def _make_config(
    slippage_pct: float = 0.05,
    delay_ms: list = None,
) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=True,
        simulated_fill_delay_ms=delay_ms or [100, 500],
        simulated_slippage_pct=slippage_pct,
    )


# ---------------------------------------------------------------------------
# Property 65: Paper Mode API Bypass
# ---------------------------------------------------------------------------

class TestProperty65PaperModeAPIBypass:
    """For any order in paper trading mode, no actual broker API call
    should be made.  ``api_calls_made`` must always be empty after
    ``simulate_order_fill``.
    """

    @given(
        symbol=symbols,
        side=order_sides,
        order_type=order_types,
        quantity=quantities,
        tick_price=prices,
    )
    @settings(max_examples=25)
    def test_no_api_calls_after_fill(self, symbol, side, order_type, quantity, tick_price):
        with patch("src.execution.paper_trading.time.sleep"):
            engine = PaperTradingEngine(_make_config())
            order = _make_order(symbol=symbol, side=side, order_type=order_type, quantity=quantity)
            engine.simulate_order_fill(order, tick_price)
            assert engine.get_api_call_count() == 0
            assert engine.api_calls_made == []

    @given(
        symbol=symbols,
        side=order_sides,
    )
    @settings(max_examples=25)
    def test_no_api_calls_after_cancel(self, symbol, side):
        engine = PaperTradingEngine(_make_config())
        order = _make_order(symbol=symbol, side=side)
        engine.simulate_order_cancel(order)
        assert engine.get_api_call_count() == 0


# ---------------------------------------------------------------------------
# Property 66: Paper Fill Simulation
# ---------------------------------------------------------------------------

class TestProperty66PaperFillSimulation:
    """For any paper order, the fill price should be based on the next
    available tick price, within slippage tolerance.
    """

    @given(
        tick_price=prices,
        slippage=slippage_pcts,
        side=order_sides,
    )
    @settings(max_examples=25)
    def test_fill_price_within_slippage(self, tick_price, slippage, side):
        with patch("src.execution.paper_trading.time.sleep"):
            config = _make_config(slippage_pct=slippage)
            engine = PaperTradingEngine(config)
            order = _make_order(side=side)
            engine.simulate_order_fill(order, tick_price)

            if side == OrderSide.BUY:
                expected = round(tick_price * (1 + slippage / 100.0), 2)
            else:
                expected = round(tick_price * (1 - slippage / 100.0), 2)

            assert order.filled_price == expected

    @given(tick_price=prices, side=order_sides)
    @settings(max_examples=25)
    def test_zero_slippage_exact_price(self, tick_price, side):
        with patch("src.execution.paper_trading.time.sleep"):
            config = _make_config(slippage_pct=0.0)
            engine = PaperTradingEngine(config)
            order = _make_order(side=side)
            engine.simulate_order_fill(order, tick_price)
            assert order.filled_price == round(tick_price, 2)

    @given(
        tick_price=prices,
        side=order_sides,
        quantity=quantities,
    )
    @settings(max_examples=25)
    def test_fill_qty_matches_order_qty(self, tick_price, side, quantity):
        with patch("src.execution.paper_trading.time.sleep"):
            engine = PaperTradingEngine(_make_config())
            order = _make_order(side=side, quantity=quantity)
            engine.simulate_order_fill(order, tick_price)
            assert order.filled_qty == quantity

    @given(tick_price=prices)
    @settings(max_examples=25)
    def test_order_status_is_filled(self, tick_price):
        with patch("src.execution.paper_trading.time.sleep"):
            engine = PaperTradingEngine(_make_config())
            order = _make_order()
            engine.simulate_order_fill(order, tick_price)
            assert order.status == OrderStatus.FILLED

    @given(tick_price=prices)
    @settings(max_examples=25)
    def test_paper_order_id_format(self, tick_price):
        with patch("src.execution.paper_trading.time.sleep"):
            engine = PaperTradingEngine(_make_config())
            order = _make_order()
            engine.simulate_order_fill(order, tick_price)
            assert order.broker_order_id.startswith("PAPER-")
            hex_part = order.broker_order_id[6:]
            assert len(hex_part) == 8
            int(hex_part, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# Property 67: Paper Fill Delay
# ---------------------------------------------------------------------------

class TestProperty67PaperFillDelay:
    """For any paper order, the fill delay should be between the
    configured min and max (default 100-500 ms).  We mock ``time.sleep``
    and verify the argument is in range.
    """

    @given(
        tick_price=prices,
        min_delay=st.integers(min_value=50, max_value=300),
        max_delay=st.integers(min_value=300, max_value=1000),
    )
    @settings(max_examples=25)
    def test_sleep_duration_in_range(self, tick_price, min_delay, max_delay):
        assume(min_delay <= max_delay)
        config = _make_config(delay_ms=[min_delay, max_delay])
        engine = PaperTradingEngine(config)

        with patch("src.execution.paper_trading.time.sleep") as mock_sleep:
            order = _make_order()
            engine.simulate_order_fill(order, tick_price)

            mock_sleep.assert_called_once()
            actual_delay = mock_sleep.call_args[0][0]
            assert min_delay / 1000.0 <= actual_delay <= max_delay / 1000.0

    @given(tick_price=prices)
    @settings(max_examples=25)
    def test_default_delay_range(self, tick_price):
        config = _make_config(delay_ms=[100, 500])
        engine = PaperTradingEngine(config)

        with patch("src.execution.paper_trading.time.sleep") as mock_sleep:
            order = _make_order()
            engine.simulate_order_fill(order, tick_price)

            actual_delay = mock_sleep.call_args[0][0]
            assert 0.1 <= actual_delay <= 0.5


# ---------------------------------------------------------------------------
# Property 68: Paper Trade Logging
# ---------------------------------------------------------------------------

class TestProperty68PaperTradeLogging:
    """For any trade in paper trading mode, the notification should
    include the ``PAPER`` prefix.
    """

    @given(message=st.text(min_size=0, max_size=500))
    @settings(max_examples=25)
    def test_notification_always_has_paper_prefix(self, message):
        engine = PaperTradingEngine(_make_config())
        result = engine.format_paper_notification(message)
        assert result.startswith("PAPER: ")
        assert result == f"PAPER: {message}"

    @given(
        symbol=symbols,
        side=order_sides,
        tick_price=prices,
    )
    @settings(max_examples=25)
    def test_log_paper_trade_includes_paper(self, symbol, side, tick_price):
        with patch("src.execution.paper_trading.time.sleep"):
            engine = PaperTradingEngine(_make_config())
            order = _make_order(symbol=symbol, side=side)

            with patch("src.execution.paper_trading.logger") as mock_logger:
                engine.simulate_order_fill(order, tick_price)
                mock_logger.info.assert_called()
                logged_msg = mock_logger.info.call_args[0][0]
                assert "PAPER" in logged_msg
