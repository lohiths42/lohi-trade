"""Tests for the Zerodha Kite Connect broker adapter.

Covers: OAuth2 session creation, order placement parameter mapping,
order status polling, daily token refresh, retry logic, WebSocket lifecycle,
and all BrokerInterface methods.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8
"""

import struct
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.broker_interface import (
    AuthenticationError,
    BrokerCredentials,
    ConnectionError,
    Order,
    OrderNotFoundError,
    OrderRejectionError,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.ingestion.kite_broker import (
    _MAX_RETRIES,
    _ORDER_TYPE_MAP,
    _PRODUCT_TYPE_MAP,
    _STATUS_MAP,
    KiteBroker,
    _kite_error,
    _reverse_order_type,
    _reverse_product_type,
    _safe_float,
)

# ── fixtures ──────────────────────────────────────────────────────


def _make_credentials(**overrides) -> BrokerCredentials:
    defaults = dict(
        api_key="test_api_key",
        client_id="AB1234",
        password="test_api_secret",
        totp_secret="test_request_token",
    )
    defaults.update(overrides)
    return BrokerCredentials(**defaults)


def _make_order(**overrides) -> Order:
    defaults = dict(
        order_id="int-001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        product_type=ProductType.CNC,
        status=OrderStatus.PENDING,
        price=2500.0,
        trigger_price=None,
    )
    defaults.update(overrides)
    return Order(**defaults)


def _connected_broker() -> KiteBroker:
    """Return a KiteBroker that is already 'connected' (tokens set)."""
    broker = KiteBroker()
    broker._api_key = "key"
    broker._api_secret = "secret"
    broker._access_token = "access_tok"
    broker._user_id = "AB1234"
    broker._connected = True
    return broker


# ── helper function tests ─────────────────────────────────────────


class TestHelpers:
    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_valid(self):
        assert _safe_float("123.45") == 123.45
        assert _safe_float(0) == 0.0

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None

    def test_reverse_order_type_known(self):
        assert _reverse_order_type("MARKET") == OrderType.MARKET
        assert _reverse_order_type("LIMIT") == OrderType.LIMIT
        assert _reverse_order_type("SL") == OrderType.SL
        assert _reverse_order_type("SL-M") == OrderType.SL_M

    def test_reverse_order_type_unknown(self):
        assert _reverse_order_type("UNKNOWN") == OrderType.MARKET

    def test_reverse_product_type_known(self):
        assert _reverse_product_type("MIS") == ProductType.MIS
        assert _reverse_product_type("CNC") == ProductType.CNC
        assert _reverse_product_type("NRML") == ProductType.NRML

    def test_reverse_product_type_unknown(self):
        assert _reverse_product_type("XYZ") == ProductType.MIS

    def test_kite_error_token(self):
        err = _kite_error("TokenException", "expired")
        assert isinstance(err, AuthenticationError)

    def test_kite_error_order(self):
        err = _kite_error("OrderException", "rejected")
        assert isinstance(err, OrderRejectionError)

    def test_kite_error_input(self):
        err = _kite_error("InputException", "bad param")
        assert isinstance(err, OrderRejectionError)

    def test_kite_error_general(self):
        err = _kite_error("GeneralException", "oops")
        assert isinstance(err, ConnectionError)


# ── connect / disconnect ──────────────────────────────────────────


class TestConnect:
    @patch("src.ingestion.kite_broker.KiteBroker._start_token_refresh_scheduler")
    @patch("src.ingestion.kite_broker.requests.post")
    def test_connect_success(self, mock_post, mock_scheduler):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"access_token": "tok123"},
            }),
        )
        broker = KiteBroker()
        result = broker.connect(_make_credentials())
        assert result is True
        assert broker.is_connected()
        assert broker._access_token == "tok123"
        mock_scheduler.assert_called_once()

    @patch("src.ingestion.kite_broker.requests.post")
    def test_connect_missing_request_token(self, mock_post):
        broker = KiteBroker()
        creds = _make_credentials(totp_secret=None)
        with pytest.raises(AuthenticationError, match="request_token"):
            broker.connect(creds)

    @patch("src.ingestion.kite_broker.requests.post")
    def test_connect_api_error(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "error",
                "error_type": "TokenException",
                "message": "Invalid request token",
            }),
        )
        broker = KiteBroker()
        with pytest.raises(AuthenticationError):
            broker.connect(_make_credentials())

    @patch("src.ingestion.kite_broker.requests.post")
    def test_connect_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError("timeout")
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.connect(_make_credentials())

    def test_disconnect(self):
        broker = _connected_broker()
        broker.disconnect()
        assert not broker.is_connected()
        assert broker._access_token is None

    def test_is_connected_false_by_default(self):
        broker = KiteBroker()
        assert not broker.is_connected()


# ── place_order ───────────────────────────────────────────────────


class TestPlaceOrder:
    @patch("src.ingestion.kite_broker.requests.post")
    def test_place_limit_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"order_id": "220101000001"},
            }),
        )
        broker = _connected_broker()
        order = _make_order()
        oid = broker.place_order(order)
        assert oid == "220101000001"

        # Verify Kite params
        call_data = mock_post.call_args
        posted = call_data.kwargs.get("data") or call_data[1].get("data")
        assert posted["tradingsymbol"] == "RELIANCE"
        assert posted["transaction_type"] == "BUY"
        assert posted["order_type"] == "LIMIT"
        assert posted["product"] == "CNC"
        assert posted["quantity"] == "10"
        assert posted["price"] == "2500.0"

    @patch("src.ingestion.kite_broker.requests.post")
    def test_place_market_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"order_id": "220101000002"},
            }),
        )
        broker = _connected_broker()
        order = _make_order(order_type=OrderType.MARKET, price=None)
        oid = broker.place_order(order)
        assert oid == "220101000002"

        posted = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert posted["order_type"] == "MARKET"
        assert posted["price"] == "0"

    @patch("src.ingestion.kite_broker.requests.post")
    def test_place_sl_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"order_id": "220101000003"},
            }),
        )
        broker = _connected_broker()
        order = _make_order(
            order_type=OrderType.SL,
            price=2480.0,
            trigger_price=2490.0,
        )
        oid = broker.place_order(order)
        assert oid == "220101000003"

        posted = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert posted["order_type"] == "SL"
        assert posted["trigger_price"] == "2490.0"

    @patch("src.ingestion.kite_broker.requests.post")
    def test_place_slm_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"order_id": "220101000004"},
            }),
        )
        broker = _connected_broker()
        order = _make_order(
            order_type=OrderType.SL_M,
            price=None,
            trigger_price=2490.0,
        )
        oid = broker.place_order(order)
        assert oid == "220101000004"

        posted = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert posted["order_type"] == "SL-M"

    def test_place_order_not_connected(self):
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.place_order(_make_order())

    @patch("src.ingestion.kite_broker.requests.post")
    def test_place_order_rejected(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "error",
                "error_type": "OrderException",
                "message": "Insufficient margin",
            }),
        )
        broker = _connected_broker()
        with pytest.raises(OrderRejectionError, match="Insufficient margin"):
            broker.place_order(_make_order())


# ── get_order_status ──────────────────────────────────────────────


class TestGetOrderStatus:
    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_order_status_complete(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": [
                    {
                        "tradingsymbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "CNC",
                        "quantity": 10,
                        "filled_quantity": 10,
                        "average_price": 2500.5,
                        "price": 2500.0,
                        "trigger_price": 0,
                        "status": "COMPLETE",
                        "status_message": None,
                    },
                ],
            }),
        )
        broker = _connected_broker()
        order = broker.get_order_status("oid-1")
        assert order.status == OrderStatus.FILLED
        assert order.filled_qty == 10
        assert order.filled_price == 2500.5
        assert order.symbol == "RELIANCE"

    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_order_status_rejected(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": [
                    {
                        "tradingsymbol": "INFY",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "MIS",
                        "quantity": 5,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 0,
                        "trigger_price": 0,
                        "status": "REJECTED",
                        "status_message": "Insufficient margin",
                    },
                ],
            }),
        )
        broker = _connected_broker()
        order = broker.get_order_status("oid-2")
        assert order.status == OrderStatus.REJECTED
        assert order.rejection_reason == "Insufficient margin"
        assert order.side == OrderSide.SELL

    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_order_status_not_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "error",
                "error_type": "GeneralException",
                "message": "No order found",
            }),
        )
        broker = _connected_broker()
        with pytest.raises(OrderNotFoundError):
            broker.get_order_status("bad-id")

    def test_get_order_status_not_connected(self):
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.get_order_status("oid-1")


# ── poll_order_status ─────────────────────────────────────────────


class TestPollOrderStatus:
    @patch("src.ingestion.kite_broker.time.sleep")
    @patch.object(KiteBroker, "get_order_status")
    def test_poll_reaches_terminal(self, mock_status, mock_sleep):
        pending = Order(
            order_id="", symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=1,
            product_type=ProductType.MIS, status=OrderStatus.PENDING,
        )
        filled = Order(
            order_id="", symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=1,
            product_type=ProductType.MIS, status=OrderStatus.FILLED,
        )
        mock_status.side_effect = [pending, pending, filled]

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0)
        assert result.status == OrderStatus.FILLED
        assert mock_status.call_count == 3

    @patch("src.ingestion.kite_broker.time.sleep")
    @patch.object(KiteBroker, "get_order_status")
    def test_poll_cancelled(self, mock_status, mock_sleep):
        cancelled = Order(
            order_id="", symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=1,
            product_type=ProductType.MIS, status=OrderStatus.CANCELLED,
        )
        mock_status.return_value = cancelled

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0)
        assert result.status == OrderStatus.CANCELLED

    @patch("src.ingestion.kite_broker.time.sleep")
    @patch.object(KiteBroker, "get_order_status")
    def test_poll_max_polls_exceeded(self, mock_status, mock_sleep):
        pending = Order(
            order_id="", symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=1,
            product_type=ProductType.MIS, status=OrderStatus.PENDING,
        )
        mock_status.return_value = pending

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0, max_polls=3)
        assert result.status == OrderStatus.PENDING
        # 3 polls + 1 final call
        assert mock_status.call_count == 4


# ── cancel_order ──────────────────────────────────────────────────


class TestCancelOrder:
    @patch("src.ingestion.kite_broker.requests.delete")
    def test_cancel_success(self, mock_delete):
        mock_delete.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"order_id": "oid-1"},
            }),
        )
        broker = _connected_broker()
        assert broker.cancel_order("oid-1") is True

    @patch("src.ingestion.kite_broker.requests.delete")
    def test_cancel_failure(self, mock_delete):
        mock_delete.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "error",
                "error_type": "GeneralException",
                "message": "Something went wrong",
            }),
        )
        broker = _connected_broker()
        assert broker.cancel_order("oid-1") is False

    def test_cancel_not_connected(self):
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.cancel_order("oid-1")


# ── get_positions ─────────────────────────────────────────────────


class TestGetPositions:
    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_positions_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {
                    "net": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "quantity": 10,
                            "average_price": 2500.0,
                            "last_price": 2520.0,
                            "pnl": 200.0,
                        },
                    ],
                    "day": [],
                },
            }),
        )
        broker = _connected_broker()
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE"
        assert positions[0]["quantity"] == 10

    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_positions_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": {"net": [], "day": []},
            }),
        )
        broker = _connected_broker()
        assert broker.get_positions() == []

    def test_get_positions_not_connected(self):
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.get_positions()


# ── get_holdings ──────────────────────────────────────────────────


class TestGetHoldings:
    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_holdings_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "status": "success",
                "data": [
                    {
                        "tradingsymbol": "TCS",
                        "quantity": 5,
                        "average_price": 3400.0,
                        "last_price": 3450.0,
                        "pnl": 250.0,
                        "isin": "INE467B01029",
                    },
                ],
            }),
        )
        broker = _connected_broker()
        holdings = broker.get_holdings()
        assert len(holdings) == 1
        assert holdings[0]["symbol"] == "TCS"
        assert holdings[0]["isin"] == "INE467B01029"


# ── retry logic ───────────────────────────────────────────────────


class TestRetryLogic:
    @patch("src.ingestion.kite_broker.time.sleep")
    @patch("src.ingestion.kite_broker.requests.post")
    def test_post_retries_on_503(self, mock_post, mock_sleep):
        """Transient 503 should be retried up to _MAX_RETRIES times (Req 15.8)."""
        fail_resp = MagicMock(status_code=503, json=MagicMock(return_value={"status": "error", "message": "unavailable"}))
        ok_resp = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "success", "data": {"order_id": "ok"}}),
        )
        mock_post.side_effect = [fail_resp, ok_resp]

        broker = _connected_broker()
        result = broker._kite_post("/orders/regular", {"test": "1"})
        assert result["order_id"] == "ok"
        assert mock_post.call_count == 2

    @patch("src.ingestion.kite_broker.time.sleep")
    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_retries_on_network_error(self, mock_get, mock_sleep):
        """Network errors should be retried (Req 15.8)."""
        import requests as req
        mock_get.side_effect = [
            req.exceptions.ConnectionError("timeout"),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"status": "success", "data": {"ok": True}}),
            ),
        ]
        broker = _connected_broker()
        result = broker._kite_get("/test")
        assert result["ok"] is True
        assert mock_get.call_count == 2

    @patch("src.ingestion.kite_broker.time.sleep")
    @patch("src.ingestion.kite_broker.requests.post")
    def test_post_exhausts_retries(self, mock_post, mock_sleep):
        """After _MAX_RETRIES+1 attempts, should raise ConnectionError."""
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError("down")

        broker = _connected_broker()
        with pytest.raises(ConnectionError):
            broker._kite_post("/fail", {})
        assert mock_post.call_count == _MAX_RETRIES + 1


# ── daily token refresh ──────────────────────────────────────────


class TestDailyTokenRefresh:
    def test_refresh_token_daily_invalidates_session(self):
        """Req 15.3: daily refresh should invalidate session and mark disconnected."""
        broker = _connected_broker()
        with patch.object(broker, "_kite_delete"):
            broker._refresh_token_daily()
        assert broker._access_token is None
        assert not broker.is_connected()

    def test_refresh_token_daily_handles_error(self):
        """Even if session invalidation fails, broker should be disconnected."""
        broker = _connected_broker()
        with patch.object(broker, "_kite_delete", side_effect=Exception("fail")):
            broker._refresh_token_daily()
        assert not broker.is_connected()


# ── WebSocket / subscribe ─────────────────────────────────────────


class TestWebSocket:
    @patch.object(KiteBroker, "_init_websocket")
    @patch.object(KiteBroker, "get_instrument_master")
    def test_subscribe_resolves_tokens(self, mock_instruments, mock_ws):
        mock_instruments.return_value = [
            {"symbol": "RELIANCE", "token": 738561},
            {"symbol": "TCS", "token": 2953217},
        ]
        broker = _connected_broker()
        broker._ws = MagicMock()

        result = broker.subscribe(["RELIANCE", "TCS"], lambda t: None)
        assert result is True
        assert broker._subscribed_symbols["RELIANCE"] == 738561
        assert broker._subscribed_symbols["TCS"] == 2953217

    @patch.object(KiteBroker, "_init_websocket")
    @patch.object(KiteBroker, "get_instrument_master")
    def test_subscribe_unknown_symbol(self, mock_instruments, mock_ws):
        mock_instruments.return_value = [
            {"symbol": "RELIANCE", "token": 738561},
        ]
        broker = _connected_broker()
        broker._ws = MagicMock()

        result = broker.subscribe(["RELIANCE", "UNKNOWN"], lambda t: None)
        assert result is True
        assert "UNKNOWN" not in broker._subscribed_symbols

    def test_subscribe_not_connected(self):
        broker = KiteBroker()
        with pytest.raises(ConnectionError):
            broker.subscribe(["X"], lambda t: None)

    def test_unsubscribe(self):
        broker = _connected_broker()
        broker._ws = MagicMock()
        broker._subscribed_symbols = {"RELIANCE": 738561, "TCS": 2953217}

        result = broker.unsubscribe(["RELIANCE"])
        assert result is True
        assert "RELIANCE" not in broker._subscribed_symbols
        assert "TCS" in broker._subscribed_symbols

    def test_unsubscribe_no_ws(self):
        broker = _connected_broker()
        broker._ws = None
        assert broker.unsubscribe(["X"]) is False

    def test_handle_binary_tick(self):
        """Simplified binary tick parsing test."""
        broker = _connected_broker()
        broker._subscribed_symbols = {"RELIANCE": 738561}
        received_ticks = []
        broker._tick_callback = lambda t: received_ticks.append(t)

        # Build a minimal binary packet: 4 bytes token + 4 bytes LTP*100
        token_bytes = struct.pack(">I", 738561)
        ltp_bytes = struct.pack(">I", 250050)  # 2500.50
        data = token_bytes + ltp_bytes

        broker._handle_binary_tick(data)
        assert len(received_ticks) == 1
        assert received_ticks[0].symbol == "RELIANCE"
        assert received_ticks[0].ltp == 2500.50

    def test_handle_binary_tick_no_callback(self):
        broker = _connected_broker()
        broker._tick_callback = None
        # Should not raise
        broker._handle_binary_tick(b"\x00" * 8)

    def test_token_to_symbol(self):
        broker = _connected_broker()
        broker._subscribed_symbols = {"RELIANCE": 100, "TCS": 200}
        assert broker._token_to_symbol(100) == "RELIANCE"
        assert broker._token_to_symbol(200) == "TCS"
        assert broker._token_to_symbol(999) is None


# ── instrument master ─────────────────────────────────────────────


class TestInstrumentMaster:
    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_instrument_master_success(self, mock_get):
        csv_content = (
            "instrument_token,exchange_token,tradingsymbol,name,last_price,"
            "expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
            "738561,2885,RELIANCE,RELIANCE INDUSTRIES,2500.0,,0.0,0.05,1,EQ,NSE,NSE\n"
        )
        mock_get.return_value = MagicMock(status_code=200, text=csv_content)

        broker = _connected_broker()
        instruments = broker.get_instrument_master()
        assert len(instruments) == 1
        assert instruments[0]["symbol"] == "RELIANCE"
        assert instruments[0]["token"] == 738561

    @patch("src.ingestion.kite_broker.requests.get")
    def test_get_instrument_master_failure(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        broker = _connected_broker()
        assert broker.get_instrument_master() == []


# ── order type mapping completeness ──────────────────────────────


class TestOrderTypeMapping:
    def test_all_order_types_mapped(self):
        for ot in OrderType:
            assert ot in _ORDER_TYPE_MAP, f"{ot} not in _ORDER_TYPE_MAP"

    def test_all_product_types_mapped(self):
        for pt in ProductType:
            assert pt in _PRODUCT_TYPE_MAP, f"{pt} not in _PRODUCT_TYPE_MAP"

    def test_status_map_covers_terminal_states(self):
        assert "COMPLETE" in _STATUS_MAP
        assert "CANCELLED" in _STATUS_MAP
        assert "REJECTED" in _STATUS_MAP
        assert _STATUS_MAP["COMPLETE"] == OrderStatus.FILLED
        assert _STATUS_MAP["CANCELLED"] == OrderStatus.CANCELLED
        assert _STATUS_MAP["REJECTED"] == OrderStatus.REJECTED
