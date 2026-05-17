"""Tests for the Groww trading API broker adapter.

Covers: OAuth2 token exchange, order placement parameter mapping,
order status polling, holdings retrieval, retry logic,
and all BrokerInterface methods.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7
"""

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
from src.ingestion.groww_broker import (
    _MAX_RETRIES,
    _ORDER_TYPE_MAP,
    _PRODUCT_TYPE_MAP,
    _STATUS_MAP,
    GrowwBroker,
    _groww_error,
    _reverse_order_type,
    _reverse_product_type,
    _safe_float,
)

# ── fixtures ──────────────────────────────────────────────────────


def _make_credentials(**overrides) -> BrokerCredentials:
    defaults = dict(
        api_key="groww_client_id",
        client_id="GU1234",
        password="groww_client_secret",
        totp_secret="test_auth_code",
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


def _connected_broker() -> GrowwBroker:
    """Return a GrowwBroker that is already 'connected' (tokens set)."""
    broker = GrowwBroker()
    broker._client_id = "groww_client_id"
    broker._client_secret = "groww_client_secret"
    broker._access_token = "access_tok"
    broker._user_id = "GU1234"
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

    def test_reverse_order_type_unknown(self):
        assert _reverse_order_type("UNKNOWN") == OrderType.MARKET

    def test_reverse_product_type_known(self):
        assert _reverse_product_type("INTRADAY") == ProductType.MIS
        assert _reverse_product_type("DELIVERY") == ProductType.CNC

    def test_reverse_product_type_unknown(self):
        assert _reverse_product_type("XYZ") == ProductType.CNC

    def test_groww_error_auth(self):
        err = _groww_error("AUTH_FAILED", "bad creds")
        assert isinstance(err, AuthenticationError)

    def test_groww_error_token_expired(self):
        err = _groww_error("TOKEN_EXPIRED", "expired")
        assert isinstance(err, AuthenticationError)

    def test_groww_error_order_rejected(self):
        err = _groww_error("ORDER_REJECTED", "rejected")
        assert isinstance(err, OrderRejectionError)

    def test_groww_error_insufficient_funds(self):
        err = _groww_error("INSUFFICIENT_FUNDS", "no money")
        assert isinstance(err, OrderRejectionError)

    def test_groww_error_order_not_found(self):
        err = _groww_error("ORDER_NOT_FOUND", "missing")
        assert isinstance(err, OrderNotFoundError)

    def test_groww_error_general(self):
        err = _groww_error("UNKNOWN", "oops")
        assert isinstance(err, ConnectionError)


# ── connect / disconnect ──────────────────────────────────────────


class TestConnect:
    @patch("src.ingestion.groww_broker.requests.post")
    def test_connect_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"access_token": "groww_tok_123"},
                }
            ),
        )
        broker = GrowwBroker()
        result = broker.connect(_make_credentials())
        assert result is True
        assert broker.is_connected()
        assert broker._access_token == "groww_tok_123"

    @patch("src.ingestion.groww_broker.requests.post")
    def test_connect_missing_auth_code(self, mock_post):
        broker = GrowwBroker()
        creds = _make_credentials(totp_secret=None)
        with pytest.raises(AuthenticationError, match="authorization_code"):
            broker.connect(creds)

    @patch("src.ingestion.groww_broker.requests.post")
    def test_connect_api_error(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": False,
                    "error_code": "AUTH_FAILED",
                    "message": "Invalid auth code",
                }
            ),
        )
        broker = GrowwBroker()
        with pytest.raises(AuthenticationError):
            broker.connect(_make_credentials())

    @patch("src.ingestion.groww_broker.requests.post")
    def test_connect_network_error(self, mock_post):
        import requests as req

        mock_post.side_effect = req.exceptions.ConnectionError("timeout")
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.connect(_make_credentials())

    def test_disconnect(self):
        broker = _connected_broker()
        broker.disconnect()
        assert not broker.is_connected()
        assert broker._access_token is None

    def test_is_connected_false_by_default(self):
        broker = GrowwBroker()
        assert not broker.is_connected()


# ── place_order ───────────────────────────────────────────────────


class TestPlaceOrder:
    @patch("src.ingestion.groww_broker.requests.post")
    def test_place_limit_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"order_id": "GRW-001"},
                }
            ),
        )
        broker = _connected_broker()
        order = _make_order()
        oid = broker.place_order(order)
        assert oid == "GRW-001"

        call_data = mock_post.call_args
        posted = call_data.kwargs.get("json") or call_data[1].get("json")
        assert posted["symbol"] == "RELIANCE"
        assert posted["transaction_type"] == "BUY"
        assert posted["order_type"] == "LIMIT"
        assert posted["product"] == "DELIVERY"
        assert posted["quantity"] == 10
        assert posted["price"] == 2500.0

    @patch("src.ingestion.groww_broker.requests.post")
    def test_place_market_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"order_id": "GRW-002"},
                }
            ),
        )
        broker = _connected_broker()
        order = _make_order(order_type=OrderType.MARKET, price=None)
        oid = broker.place_order(order)
        assert oid == "GRW-002"

        posted = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert posted["order_type"] == "MARKET"
        assert posted["price"] == 0

    @patch("src.ingestion.groww_broker.requests.post")
    def test_place_sl_order(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"order_id": "GRW-003"},
                }
            ),
        )
        broker = _connected_broker()
        order = _make_order(
            order_type=OrderType.SL,
            price=2480.0,
            trigger_price=2490.0,
        )
        oid = broker.place_order(order)
        assert oid == "GRW-003"

        posted = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert posted["order_type"] == "SL"
        assert posted["trigger_price"] == 2490.0

    def test_place_order_not_connected(self):
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.place_order(_make_order())

    @patch("src.ingestion.groww_broker.requests.post")
    def test_place_order_rejected(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": False,
                    "error_code": "ORDER_REJECTED",
                    "message": "Insufficient funds",
                }
            ),
        )
        broker = _connected_broker()
        with pytest.raises(OrderRejectionError, match="Insufficient funds"):
            broker.place_order(_make_order())


# ── get_order_status ──────────────────────────────────────────────


class TestGetOrderStatus:
    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_order_status_executed(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "symbol": "RELIANCE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "DELIVERY",
                        "quantity": 10,
                        "filled_quantity": 10,
                        "average_price": 2500.5,
                        "price": 2500.0,
                        "trigger_price": 0,
                        "status": "EXECUTED",
                        "rejection_reason": None,
                    },
                }
            ),
        )
        broker = _connected_broker()
        order = broker.get_order_status("GRW-001")
        assert order.status == OrderStatus.FILLED
        assert order.filled_qty == 10
        assert order.filled_price == 2500.5
        assert order.symbol == "RELIANCE"

    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_order_status_rejected(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "symbol": "INFY",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "INTRADAY",
                        "quantity": 5,
                        "filled_quantity": 0,
                        "average_price": 0,
                        "price": 0,
                        "trigger_price": 0,
                        "status": "REJECTED",
                        "rejection_reason": "Insufficient margin",
                    },
                }
            ),
        )
        broker = _connected_broker()
        order = broker.get_order_status("GRW-002")
        assert order.status == OrderStatus.REJECTED
        assert order.rejection_reason == "Insufficient margin"
        assert order.side == OrderSide.SELL

    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_order_status_not_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": False,
                    "error_code": "ORDER_NOT_FOUND",
                    "message": "No order found",
                }
            ),
        )
        broker = _connected_broker()
        with pytest.raises(OrderNotFoundError):
            broker.get_order_status("bad-id")

    def test_get_order_status_not_connected(self):
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.get_order_status("GRW-001")


# ── poll_order_status ─────────────────────────────────────────────


class TestPollOrderStatus:
    @patch("src.ingestion.groww_broker.time.sleep")
    @patch.object(GrowwBroker, "get_order_status")
    def test_poll_reaches_terminal(self, mock_status, mock_sleep):
        pending = Order(
            order_id="",
            symbol="X",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        filled = Order(
            order_id="",
            symbol="X",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            product_type=ProductType.MIS,
            status=OrderStatus.FILLED,
        )
        mock_status.side_effect = [pending, pending, filled]

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0)
        assert result.status == OrderStatus.FILLED
        assert mock_status.call_count == 3

    @patch("src.ingestion.groww_broker.time.sleep")
    @patch.object(GrowwBroker, "get_order_status")
    def test_poll_cancelled(self, mock_status, mock_sleep):
        cancelled = Order(
            order_id="",
            symbol="X",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            product_type=ProductType.MIS,
            status=OrderStatus.CANCELLED,
        )
        mock_status.return_value = cancelled

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0)
        assert result.status == OrderStatus.CANCELLED

    @patch("src.ingestion.groww_broker.time.sleep")
    @patch.object(GrowwBroker, "get_order_status")
    def test_poll_max_polls_exceeded(self, mock_status, mock_sleep):
        pending = Order(
            order_id="",
            symbol="X",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        mock_status.return_value = pending

        broker = _connected_broker()
        result = broker.poll_order_status("oid", interval=0, max_polls=3)
        assert result.status == OrderStatus.PENDING
        # 3 polls + 1 final call
        assert mock_status.call_count == 4


# ── cancel_order ──────────────────────────────────────────────────


class TestCancelOrder:
    @patch("src.ingestion.groww_broker.requests.delete")
    def test_cancel_success(self, mock_delete):
        mock_delete.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"order_id": "GRW-001"},
                }
            ),
        )
        broker = _connected_broker()
        assert broker.cancel_order("GRW-001") is True

    @patch("src.ingestion.groww_broker.requests.delete")
    def test_cancel_failure(self, mock_delete):
        mock_delete.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": False,
                    "error_code": "UNKNOWN",
                    "message": "Something went wrong",
                }
            ),
        )
        broker = _connected_broker()
        assert broker.cancel_order("GRW-001") is False

    def test_cancel_not_connected(self):
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.cancel_order("GRW-001")


# ── get_positions ─────────────────────────────────────────────────


class TestGetPositions:
    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_positions_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "positions": [
                            {
                                "symbol": "RELIANCE",
                                "quantity": 10,
                                "average_price": 2500.0,
                                "ltp": 2520.0,
                                "pnl": 200.0,
                            },
                        ],
                    },
                }
            ),
        )
        broker = _connected_broker()
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE"
        assert positions[0]["quantity"] == 10

    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_positions_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"positions": []},
                }
            ),
        )
        broker = _connected_broker()
        assert broker.get_positions() == []

    def test_get_positions_not_connected(self):
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.get_positions()


# ── get_holdings (Req 16.7) ───────────────────────────────────────


class TestGetHoldings:
    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_holdings_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "holdings": [
                            {
                                "symbol": "TCS",
                                "quantity": 5,
                                "average_price": 3400.0,
                                "ltp": 3450.0,
                                "pnl": 250.0,
                                "isin": "INE467B01029",
                            },
                        ],
                    },
                }
            ),
        )
        broker = _connected_broker()
        holdings = broker.get_holdings()
        assert len(holdings) == 1
        assert holdings[0]["symbol"] == "TCS"
        assert holdings[0]["isin"] == "INE467B01029"
        assert holdings[0]["quantity"] == 5

    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_holdings_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {"holdings": []},
                }
            ),
        )
        broker = _connected_broker()
        assert broker.get_holdings() == []

    def test_get_holdings_not_connected(self):
        broker = GrowwBroker()
        with pytest.raises(ConnectionError):
            broker.get_holdings()


# ── retry logic (Req 16.6) ───────────────────────────────────────


class TestRetryLogic:
    @patch("src.ingestion.groww_broker.time.sleep")
    @patch("src.ingestion.groww_broker.requests.post")
    def test_post_retries_on_503(self, mock_post, mock_sleep):
        fail_resp = MagicMock(
            status_code=503,
            json=MagicMock(return_value={"success": False, "message": "unavailable"}),
        )
        ok_resp = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"order_id": "ok"}}),
        )
        mock_post.side_effect = [fail_resp, ok_resp]

        broker = _connected_broker()
        result = broker._groww_post("/orders", {"test": "1"})
        assert result["order_id"] == "ok"
        assert mock_post.call_count == 2

    @patch("src.ingestion.groww_broker.time.sleep")
    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_retries_on_network_error(self, mock_get, mock_sleep):
        import requests as req

        mock_get.side_effect = [
            req.exceptions.ConnectionError("timeout"),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"data": {"ok": True}}),
            ),
        ]
        broker = _connected_broker()
        result = broker._groww_get("/test")
        assert result["ok"] is True
        assert mock_get.call_count == 2

    @patch("src.ingestion.groww_broker.time.sleep")
    @patch("src.ingestion.groww_broker.requests.post")
    def test_post_exhausts_retries(self, mock_post, mock_sleep):
        import requests as req

        mock_post.side_effect = req.exceptions.ConnectionError("down")

        broker = _connected_broker()
        with pytest.raises(ConnectionError):
            broker._groww_post("/fail", {})
        assert mock_post.call_count == _MAX_RETRIES + 1

    @patch("src.ingestion.groww_broker.time.sleep")
    @patch("src.ingestion.groww_broker.requests.post")
    def test_post_retries_on_429(self, mock_post, mock_sleep):
        rate_limited = MagicMock(
            status_code=429,
            json=MagicMock(return_value={"success": False, "message": "rate limited"}),
        )
        ok_resp = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"result": "ok"}}),
        )
        mock_post.side_effect = [rate_limited, ok_resp]

        broker = _connected_broker()
        result = broker._groww_post("/orders", {})
        assert result["result"] == "ok"
        assert mock_post.call_count == 2


# ── subscribe / unsubscribe stubs ─────────────────────────────────


class TestWebSocketStubs:
    def test_subscribe_returns_false(self):
        broker = _connected_broker()
        assert broker.subscribe(["RELIANCE"], lambda t: None) is False

    def test_unsubscribe_returns_false(self):
        broker = _connected_broker()
        assert broker.unsubscribe(["RELIANCE"]) is False


# ── instrument master ─────────────────────────────────────────────


class TestInstrumentMaster:
    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_instrument_master_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "instruments": [
                            {
                                "symbol": "RELIANCE",
                                "token": 738561,
                                "exchange": "NSE",
                                "lot_size": 1,
                                "tick_size": 0.05,
                                "trading_symbol": "RELIANCE",
                                "instrument_type": "EQ",
                                "name": "Reliance Industries",
                                "isin": "INE002A01018",
                            },
                        ],
                    },
                }
            ),
        )
        broker = _connected_broker()
        instruments = broker.get_instrument_master()
        assert len(instruments) == 1
        assert instruments[0]["symbol"] == "RELIANCE"
        assert instruments[0]["token"] == 738561
        assert instruments[0]["isin"] == "INE002A01018"

    @patch("src.ingestion.groww_broker.requests.get")
    def test_get_instrument_master_failure(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": False,
                    "error_code": "UNKNOWN",
                    "error": "Server error",
                }
            ),
        )
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
        assert "EXECUTED" in _STATUS_MAP
        assert "CANCELLED" in _STATUS_MAP
        assert "REJECTED" in _STATUS_MAP
        assert _STATUS_MAP["EXECUTED"] == OrderStatus.FILLED
        assert _STATUS_MAP["CANCELLED"] == OrderStatus.CANCELLED
        assert _STATUS_MAP["REJECTED"] == OrderStatus.REJECTED
