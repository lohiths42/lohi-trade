"""
Unit tests for broker interface and adapters.

Tests cover:
- Broker interface data classes
- Shoonya broker adapter
- Angel One broker adapter
- Mock WebSocket and REST API responses
- Login flow
- Order placement
- WebSocket reconnection
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime

from src.ingestion.broker_interface import (
    BrokerCredentials,
    Tick,
    Order,
    OrderStatus,
    OrderSide,
    OrderType,
    ProductType,
    ConnectionError,
    AuthenticationError,
    OrderRejectionError,
    OrderNotFoundError,
)
from src.ingestion.shoonya_broker import ShoonyaBroker
from src.ingestion.angelone_broker import AngelOneBroker


class TestBrokerDataClasses:
    """Test broker interface data classes."""
    
    def test_tick_creation(self):
        """Test Tick data class creation."""
        tick = Tick(
            symbol="RELIANCE",
            token=2885,
            ltp=2500.50,
            volume=1000000,
            timestamp=datetime.now(),
            exchange="NSE",
            bid=2500.00,
            ask=2501.00,
        )
        
        assert tick.symbol == "RELIANCE"
        assert tick.token == 2885
        assert tick.ltp == 2500.50
        assert tick.volume == 1000000
        assert tick.exchange == "NSE"
        assert tick.bid == 2500.00
        assert tick.ask == 2501.00
    
    def test_order_creation(self):
        """Test Order data class creation."""
        order = Order(
            order_id="test-order-123",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        assert order.order_id == "test-order-123"
        assert order.symbol == "TCS"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 10
        assert order.product_type == ProductType.MIS
        assert order.status == OrderStatus.PENDING
    
    def test_broker_credentials_creation(self):
        """Test BrokerCredentials data class creation."""
        creds = BrokerCredentials(
            api_key="test_api_key",
            client_id="test_client",
            password="test_password",
            totp_secret="test_totp",
        )
        
        assert creds.api_key == "test_api_key"
        assert creds.client_id == "test_client"
        assert creds.password == "test_password"
        assert creds.totp_secret == "test_totp"


class TestShoonyaBroker:
    """Test Shoonya broker adapter."""
    
    @pytest.fixture
    def broker(self):
        """Create a Shoonya broker instance."""
        return ShoonyaBroker()
    
    @pytest.fixture
    def credentials(self):
        """Create test credentials."""
        return BrokerCredentials(
            api_key="test_api_key",
            client_id="test_client",
            password="test_password",
        )
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    @patch('src.ingestion.shoonya_broker.ShoonyaBroker._init_websocket')
    def test_connect_success(self, mock_init_ws, mock_post, broker, credentials):
        """Test successful connection to Shoonya API."""
        # Mock successful login response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Ok",
            "susertoken": "test_session_token",
        }
        mock_post.return_value = mock_response
        
        result = broker.connect(credentials)
        
        assert result is True
        assert broker.is_connected() is True
        assert broker._session_token == "test_session_token"
        assert broker._user_id == "test_client"
        mock_init_ws.assert_called_once()
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_connect_authentication_failure(self, mock_post, broker, credentials):
        """Test authentication failure during connection."""
        # Mock failed login response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Not_Ok",
            "emsg": "Invalid credentials",
        }
        mock_post.return_value = mock_response
        
        with pytest.raises(AuthenticationError) as exc_info:
            broker.connect(credentials)
        
        assert "Invalid credentials" in str(exc_info.value)
        assert broker.is_connected() is False
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_connect_network_error(self, mock_post, broker, credentials):
        """Test network error during connection."""
        # Mock network error
        mock_post.side_effect = Exception("Network timeout")
        
        with pytest.raises(ConnectionError) as exc_info:
            broker.connect(credentials)
        
        assert "Network timeout" in str(exc_info.value)
        assert broker.is_connected() is False
    
    def test_disconnect(self, broker):
        """Test disconnection from Shoonya API."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        mock_ws = Mock()
        broker._ws = mock_ws
        
        broker.disconnect()
        
        assert broker.is_connected() is False
        assert broker._session_token is None
        assert broker._user_id is None
        mock_ws.close.assert_called_once()
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_place_order_success(self, mock_post, broker):
        """Test successful order placement."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock successful order response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Ok",
            "norenordno": "broker_order_123",
        }
        mock_post.return_value = mock_response
        
        order = Order(
            order_id="test-order-123",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        broker_order_id = broker.place_order(order)
        
        assert broker_order_id == "broker_order_123"
        mock_post.assert_called_once()
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_place_order_rejection(self, mock_post, broker):
        """Test order rejection by broker."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock order rejection response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Not_Ok",
            "emsg": "Insufficient margin",
        }
        mock_post.return_value = mock_response
        
        order = Order(
            order_id="test-order-123",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        with pytest.raises(OrderRejectionError) as exc_info:
            broker.place_order(order)
        
        assert "Insufficient margin" in str(exc_info.value)
    
    def test_place_order_not_connected(self, broker):
        """Test order placement when not connected."""
        order = Order(
            order_id="test-order-123",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        with pytest.raises(ConnectionError):
            broker.place_order(order)
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_cancel_order_success(self, mock_post, broker):
        """Test successful order cancellation."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock successful cancellation response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Ok",
        }
        mock_post.return_value = mock_response
        
        result = broker.cancel_order("broker_order_123")
        
        assert result is True
        mock_post.assert_called_once()
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_cancel_order_not_found(self, mock_post, broker):
        """Test cancellation of non-existent order."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock order not found response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Not_Ok",
            "emsg": "Order not found",
        }
        mock_post.return_value = mock_response
        
        with pytest.raises(OrderNotFoundError):
            broker.cancel_order("nonexistent_order")
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_get_order_status_success(self, mock_post, broker):
        """Test successful order status query."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock order status response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Ok",
            "status": "COMPLETE",
            "tsym": "RELIANCE",
            "trantype": "B",
            "qty": "10",
            "fillshares": "10",
            "avgprc": "2500.50",
        }
        mock_post.return_value = mock_response
        
        order = broker.get_order_status("broker_order_123")
        
        assert order.status == OrderStatus.FILLED
        assert order.symbol == "RELIANCE"
        assert order.side == OrderSide.BUY
        assert order.quantity == 10
        assert order.filled_qty == 10
        assert order.filled_price == 2500.50
    
    @patch('src.ingestion.shoonya_broker.requests.post')
    def test_get_positions(self, mock_post, broker):
        """Test getting open positions."""
        # Set up connected state
        broker._connected = True
        broker._session_token = "test_token"
        broker._user_id = "test_user"
        
        # Mock positions response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stat": "Ok",
        }
        # Mock response is a list
        mock_post.return_value = mock_response
        mock_response.json.return_value = [
            {
                "tsym": "RELIANCE",
                "netqty": "10",
                "netavgprc": "2500.00",
                "lp": "2550.00",
                "rpnl": "500.00",
            }
        ]
        
        positions = broker.get_positions()
        
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE"
        assert positions[0]["quantity"] == 10
        assert positions[0]["avg_price"] == 2500.00
    
    def test_parse_tick(self, broker):
        """Test parsing tick data from WebSocket message."""
        # Set up subscribed symbols
        broker._subscribed_symbols = {"RELIANCE": 2885}
        
        tick_data = {
            "t": "tk",
            "tk": "2885",
            "lp": "2500.50",
            "v": "1000000",
            "e": "NSE",
            "bp1": "2500.00",
            "sp1": "2501.00",
            "o": "2480.00",
            "h": "2520.00",
            "l": "2475.00",
            "c": "2490.00",
        }
        
        tick = broker._parse_tick(tick_data)
        
        assert tick is not None
        assert tick.symbol == "RELIANCE"
        assert tick.token == 2885
        assert tick.ltp == 2500.50
        assert tick.volume == 1000000
        assert tick.exchange == "NSE"
        assert tick.bid == 2500.00
        assert tick.ask == 2501.00


class TestAngelOneBroker:
    """Test Angel One broker adapter."""
    
    @pytest.fixture
    def broker(self):
        """Create an Angel One broker instance."""
        return AngelOneBroker()
    
    @pytest.fixture
    def credentials(self):
        """Create test credentials."""
        return BrokerCredentials(
            api_key="test_api_key",
            client_id="test_client",
            password="test_password",
            totp_secret="123456",
        )
    
    @patch('src.ingestion.angelone_broker.requests.post')
    @patch('src.ingestion.angelone_broker.AngelOneBroker._init_websocket')
    def test_connect_success(self, mock_init_ws, mock_post, broker, credentials):
        """Test successful connection to Angel One API."""
        # Mock successful login response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "data": {
                "jwtToken": "test_jwt_token",
                "feedToken": "test_feed_token",
            }
        }
        mock_post.return_value = mock_response
        
        result = broker.connect(credentials)
        
        assert result is True
        assert broker.is_connected() is True
        assert broker._jwt_token == "test_jwt_token"
        assert broker._feed_token == "test_feed_token"
        mock_init_ws.assert_called_once()
    
    @patch('src.ingestion.angelone_broker.requests.post')
    def test_connect_authentication_failure(self, mock_post, broker, credentials):
        """Test authentication failure during connection."""
        # Mock failed login response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": False,
            "message": "Invalid credentials",
        }
        mock_post.return_value = mock_response
        
        with pytest.raises(AuthenticationError) as exc_info:
            broker.connect(credentials)
        
        assert "Invalid credentials" in str(exc_info.value)
        assert broker.is_connected() is False
    
    @patch('src.ingestion.angelone_broker.requests.post')
    def test_disconnect(self, mock_post, broker):
        """Test disconnection from Angel One API."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        mock_ws = Mock()
        broker._ws = mock_ws
        
        # Mock logout response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        broker.disconnect()
        
        assert broker.is_connected() is False
        assert broker._jwt_token is None
        mock_ws.close.assert_called_once()
    
    @patch('src.ingestion.angelone_broker.requests.post')
    def test_place_order_success(self, mock_post, broker):
        """Test successful order placement."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        
        # Mock successful order response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "data": {
                "orderid": "angel_order_123",
            }
        }
        mock_post.return_value = mock_response
        
        order = Order(
            order_id="test-order-123",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=5,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        broker_order_id = broker.place_order(order)
        
        assert broker_order_id == "angel_order_123"
        mock_post.assert_called_once()
    
    @patch('src.ingestion.angelone_broker.requests.post')
    def test_place_order_rejection(self, mock_post, broker):
        """Test order rejection by broker."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        
        # Mock order rejection response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": False,
            "message": "Insufficient funds",
        }
        mock_post.return_value = mock_response
        
        order = Order(
            order_id="test-order-123",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=5,
            product_type=ProductType.MIS,
            status=OrderStatus.PENDING,
        )
        
        with pytest.raises(OrderRejectionError) as exc_info:
            broker.place_order(order)
        
        assert "Insufficient funds" in str(exc_info.value)
    
    @patch('src.ingestion.angelone_broker.requests.post')
    def test_cancel_order_success(self, mock_post, broker):
        """Test successful order cancellation."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        
        # Mock successful cancellation response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
        }
        mock_post.return_value = mock_response
        
        result = broker.cancel_order("angel_order_123")
        
        assert result is True
        mock_post.assert_called_once()
    
    @patch('src.ingestion.angelone_broker.requests.get')
    def test_get_order_status_success(self, mock_get, broker):
        """Test successful order status query."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        
        # Mock order status response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "data": [
                {
                    "orderid": "angel_order_123",
                    "status": "complete",
                    "tradingsymbol": "TCS",
                    "transactiontype": "BUY",
                    "quantity": "5",
                    "filledshares": "5",
                    "averageprice": "3500.75",
                }
            ]
        }
        mock_get.return_value = mock_response
        
        order = broker.get_order_status("angel_order_123")
        
        assert order.status == OrderStatus.FILLED
        assert order.symbol == "TCS"
        assert order.side == OrderSide.BUY
        assert order.quantity == 5
        assert order.filled_qty == 5
        assert order.filled_price == 3500.75
    
    @patch('src.ingestion.angelone_broker.requests.get')
    def test_get_positions(self, mock_get, broker):
        """Test getting open positions."""
        # Set up connected state
        broker._connected = True
        broker._jwt_token = "test_token"
        broker._api_key = "test_key"
        broker._client_id = "test_client"
        
        # Mock positions response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "data": [
                {
                    "tradingsymbol": "TCS",
                    "netqty": "5",
                    "netavgprice": "3500.00",
                    "ltp": "3550.00",
                    "pnl": "250.00",
                }
            ]
        }
        mock_get.return_value = mock_response
        
        positions = broker.get_positions()
        
        assert len(positions) == 1
        assert positions[0]["symbol"] == "TCS"
        assert positions[0]["quantity"] == 5
        assert positions[0]["avg_price"] == 3500.00
    
    def test_parse_tick(self, broker):
        """Test parsing tick data from WebSocket message."""
        # Set up subscribed symbols
        broker._subscribed_symbols = {"TCS": "11536"}
        
        tick_data = {
            "token": "11536",
            "ltp": "3500.50",
            "volume": "500000",
            "exchange": "NSE",
            "best_bid_price": "3500.00",
            "best_ask_price": "3501.00",
            "open": "3480.00",
            "high": "3520.00",
            "low": "3475.00",
            "close": "3490.00",
        }
        
        tick = broker._parse_tick(tick_data)
        
        assert tick is not None
        assert tick.symbol == "TCS"
        assert tick.token == 11536
        assert tick.ltp == 3500.50
        assert tick.volume == 500000
        assert tick.exchange == "NSE"
        assert tick.bid == 3500.00
        assert tick.ask == 3501.00


class TestBrokerReconnection:
    """Test WebSocket reconnection logic."""
    
    @pytest.fixture
    def shoonya_broker(self):
        """Create a Shoonya broker instance."""
        return ShoonyaBroker()
    
    def test_reconnection_backoff(self, shoonya_broker):
        """Test exponential backoff during reconnection."""
        # Set up broker state
        shoonya_broker._connected = True
        shoonya_broker._reconnect_attempts = 0
        
        # Test backoff calculation
        with patch('src.ingestion.shoonya_broker.time.sleep') as mock_sleep:
            with patch.object(shoonya_broker, '_init_websocket', side_effect=Exception("Connection failed")):
                shoonya_broker._handle_ws_disconnect()
                
                # First attempt: 2^1 = 2 seconds
                assert shoonya_broker._reconnect_attempts == 1
                mock_sleep.assert_called_with(2)
    
    def test_max_reconnection_attempts(self, shoonya_broker):
        """Test that reconnection stops after max attempts."""
        # Set up broker state
        shoonya_broker._connected = True
        shoonya_broker._reconnect_attempts = 5  # Max attempts
        
        with patch('src.ingestion.shoonya_broker.time.sleep'):
            shoonya_broker._handle_ws_disconnect()
            
            # Should not attempt reconnection
            assert shoonya_broker._connected is False
