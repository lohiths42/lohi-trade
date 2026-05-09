"""
Angel One broker adapter implementation.

This module implements the BrokerInterface for Angel One (Angel Broking) API,
providing WebSocket connectivity for live ticks and REST API for order management.
"""

import json
import time
import threading
from datetime import datetime
from typing import Callable, List, Optional, Dict
import requests
import websocket

from src.ingestion.broker_interface import (
    BrokerInterface,
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
from src.utils.logger import get_logger


logger = get_logger("AngelOneBroker")


class AngelOneBroker(BrokerInterface):
    """
    Angel One broker adapter.
    
    Implements WebSocket connection for live ticks and REST API for order placement.
    """
    
    # API endpoints
    BASE_URL = "https://apiconnect.angelbroking.com"
    WS_URL = "wss://smartapisocket.angelone.in/smart-stream"
    
    def __init__(self):
        """Initialize Angel One broker adapter."""
        self._jwt_token: Optional[str] = None
        self._api_key: Optional[str] = None
        self._client_id: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._connected = False
        self._subscribed_symbols: Dict[str, str] = {}  # symbol -> token mapping
        self._tick_callback: Optional[Callable[[Tick], None]] = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
    
    def connect(self, credentials: BrokerCredentials) -> bool:
        """
        Connect to Angel One API and authenticate.
        
        Args:
            credentials: Angel One authentication credentials
            
        Returns:
            True if connection successful
            
        Raises:
            ConnectionError: If connection fails
            AuthenticationError: If authentication fails
        """
        try:
            logger.info("Connecting to Angel One API...")
            
            self._api_key = credentials.api_key
            self._client_id = credentials.client_id
            
            # Login request
            login_data = {
                "clientcode": credentials.client_id,
                "password": credentials.password,
                "totp": credentials.totp_secret or "",
            }
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": credentials.api_key,
            }
            
            response = requests.post(
                f"{self.BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
                json=login_data,
                headers=headers,
                timeout=10,
            )
            
            if response.status_code != 200:
                raise ConnectionError(f"Login request failed: {response.status_code}")
            
            result = response.json()
            
            if not result.get("status"):
                error_msg = result.get("message", "Unknown error")
                raise AuthenticationError(f"Login failed: {error_msg}")
            
            data = result.get("data", {})
            self._jwt_token = data.get("jwtToken")
            self._feed_token = data.get("feedToken")
            
            if not self._jwt_token or not self._feed_token:
                raise AuthenticationError("Failed to obtain authentication tokens")
            
            self._connected = True
            
            logger.info(f"Successfully connected to Angel One API (Client: {self._client_id})")
            
            # Initialize WebSocket connection
            self._init_websocket()
            
            return True
            
        except AuthenticationError:
            # Re-raise authentication errors as-is
            raise
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during login: {str(e)}")
        except Exception as e:
            raise ConnectionError(f"Unexpected error during login: {str(e)}")
    
    def disconnect(self) -> None:
        """Disconnect from Angel One API and clean up resources."""
        logger.info("Disconnecting from Angel One API...")
        
        # Logout
        if self._jwt_token:
            try:
                headers = {
                    "Authorization": f"Bearer {self._jwt_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-UserType": "USER",
                    "X-SourceID": "WEB",
                    "X-ClientLocalIP": "127.0.0.1",
                    "X-ClientPublicIP": "127.0.0.1",
                    "X-MACAddress": "00:00:00:00:00:00",
                    "X-PrivateKey": self._api_key,
                }
                
                requests.post(
                    f"{self.BASE_URL}/rest/secure/angelbroking/user/v1/logout",
                    json={"clientcode": self._client_id},
                    headers=headers,
                    timeout=5,
                )
            except Exception as e:
                logger.warning(f"Error during logout: {e}")
        
        # Close WebSocket
        if self._ws:
            self._ws.close()
            self._ws = None
        
        # Wait for WebSocket thread to finish
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
        
        self._connected = False
        self._jwt_token = None
        self._feed_token = None
        self._subscribed_symbols.clear()
        
        logger.info("Disconnected from Angel One API")
    
    def is_connected(self) -> bool:
        """Check if broker connection is active."""
        return self._connected and self._jwt_token is not None
    
    def _init_websocket(self) -> None:
        """Initialize WebSocket connection for live ticks."""
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        def on_open(ws):
            logger.info("WebSocket connection opened")
            # Send authentication message
            auth_msg = {
                "action": 1,
                "params": {
                    "mode": 1,
                    "tokenList": [],
                }
            }
            ws.send(json.dumps(auth_msg))
        
        def on_message(ws, message):
            try:
                # Angel One sends binary data, need to decode
                if isinstance(message, bytes):
                    # Binary tick data format - simplified parsing
                    # In production, this would need proper binary protocol parsing
                    pass
                else:
                    data = json.loads(message)
                    self._handle_ws_message(data)
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
        
        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
            self._handle_ws_disconnect()
        
        # WebSocket URL includes feed token
        ws_url = f"{self.WS_URL}?feedToken={self._feed_token}"
        
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        
        # Start WebSocket in separate thread
        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()
        
        # Wait for connection to establish
        time.sleep(2)
    
    def _handle_ws_message(self, data: dict) -> None:
        """
        Handle incoming WebSocket messages.
        
        Args:
            data: Parsed JSON message from WebSocket
        """
        # Angel One WebSocket message handling
        # This is simplified - actual implementation would need to handle
        # the specific message format from Angel One
        
        if "tick" in data and self._tick_callback:
            tick = self._parse_tick(data["tick"])
            if tick:
                self._tick_callback(tick)
    
    def _parse_tick(self, data: dict) -> Optional[Tick]:
        """
        Parse tick data from WebSocket message.
        
        Args:
            data: WebSocket message data
            
        Returns:
            Tick object or None if parsing fails
        """
        try:
            # Find symbol from token
            token = str(data.get("token", ""))
            symbol = None
            for sym, tok in self._subscribed_symbols.items():
                if tok == token:
                    symbol = sym
                    break
            
            if not symbol:
                return None
            
            return Tick(
                symbol=symbol,
                token=int(token),
                ltp=float(data.get("ltp", 0)),
                volume=int(data.get("volume", 0)),
                timestamp=datetime.now(),
                exchange=data.get("exchange", "NSE"),
                bid=float(data.get("best_bid_price", 0)) if data.get("best_bid_price") else None,
                ask=float(data.get("best_ask_price", 0)) if data.get("best_ask_price") else None,
                open=float(data.get("open", 0)) if data.get("open") else None,
                high=float(data.get("high", 0)) if data.get("high") else None,
                low=float(data.get("low", 0)) if data.get("low") else None,
                close=float(data.get("close", 0)) if data.get("close") else None,
            )
        except Exception as e:
            logger.error(f"Error parsing tick data: {e}")
            return None
    
    def _handle_ws_disconnect(self) -> None:
        """Handle WebSocket disconnection and attempt reconnection."""
        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            backoff = min(2 ** self._reconnect_attempts, 30)  # Exponential backoff, max 30s
            logger.info(f"Attempting WebSocket reconnection in {backoff}s (attempt {self._reconnect_attempts})")
            time.sleep(backoff)
            
            try:
                self._init_websocket()
                # Resubscribe to symbols
                if self._subscribed_symbols and self._tick_callback:
                    symbols = list(self._subscribed_symbols.keys())
                    self.subscribe(symbols, self._tick_callback)
                self._reconnect_attempts = 0
            except Exception as e:
                logger.error(f"WebSocket reconnection failed: {e}")
        else:
            logger.error("Max WebSocket reconnection attempts reached")
            self._connected = False
    
    def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> bool:
        """
        Subscribe to real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to subscribe to
            on_tick: Callback function to handle incoming ticks
            
        Returns:
            True if subscription successful
            
        Raises:
            ConnectionError: If not connected to broker
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        if not self._ws:
            raise ConnectionError("WebSocket not initialized")
        
        self._tick_callback = on_tick
        
        # Get instrument master to map symbols to tokens
        instruments = self.get_instrument_master()
        symbol_token_map = {inst["symbol"]: inst["token"] for inst in instruments}
        
        # Prepare token list for subscription
        token_list = []
        for symbol in symbols:
            token = symbol_token_map.get(symbol)
            if not token:
                logger.warning(f"Symbol {symbol} not found in instrument master")
                continue
            
            self._subscribed_symbols[symbol] = token
            token_list.append({
                "exchangeType": 1,  # NSE
                "tokens": [token]
            })
            logger.info(f"Subscribed to {symbol} (token: {token})")
        
        # Send subscription message
        if token_list:
            sub_msg = {
                "action": 1,
                "params": {
                    "mode": 1,  # LTP mode
                    "tokenList": token_list
                }
            }
            self._ws.send(json.dumps(sub_msg))
        
        return True
    
    def unsubscribe(self, symbols: List[str]) -> bool:
        """
        Unsubscribe from real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to unsubscribe from
            
        Returns:
            True if unsubscription successful
        """
        if not self._ws:
            return False
        
        token_list = []
        for symbol in symbols:
            token = self._subscribed_symbols.get(symbol)
            if token:
                token_list.append({
                    "exchangeType": 1,  # NSE
                    "tokens": [token]
                })
                del self._subscribed_symbols[symbol]
                logger.info(f"Unsubscribed from {symbol}")
        
        # Send unsubscription message
        if token_list:
            unsub_msg = {
                "action": 0,  # Unsubscribe
                "params": {
                    "mode": 1,
                    "tokenList": token_list
                }
            }
            self._ws.send(json.dumps(unsub_msg))
        
        return True
    
    def place_order(self, order: Order) -> str:
        """
        Place an order with Angel One broker.
        
        Args:
            order: Order object with all required details
            
        Returns:
            Broker order ID if successful
            
        Raises:
            OrderRejectionError: If broker rejects the order
            ConnectionError: If not connected to broker
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        try:
            # Prepare order data
            order_data = {
                "variety": "NORMAL",
                "tradingsymbol": order.symbol,
                "symboltoken": "",  # Would need to look up from instrument master
                "transactiontype": order.side.value,
                "exchange": "NSE",
                "ordertype": order.order_type.value,
                "producttype": order.product_type.value,
                "duration": "DAY",
                "price": str(order.price) if order.price else "0",
                "triggerprice": str(order.trigger_price) if order.trigger_price else "0",
                "quantity": str(order.quantity),
            }
            
            headers = {
                "Authorization": f"Bearer {self._jwt_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": self._api_key,
            }
            
            response = requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                json=order_data,
                headers=headers,
                timeout=10,
            )
            
            if response.status_code != 200:
                raise OrderRejectionError(f"Order placement failed: {response.status_code}")
            
            result = response.json()
            
            if not result.get("status"):
                error_msg = result.get("message", "Unknown error")
                raise OrderRejectionError(f"Order rejected: {error_msg}")
            
            broker_order_id = result.get("data", {}).get("orderid")
            logger.info(f"Order placed successfully: {broker_order_id}")
            
            return broker_order_id
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during order placement: {str(e)}")
    
    def cancel_order(self, broker_order_id: str) -> bool:
        """
        Cancel a pending order.
        
        Args:
            broker_order_id: Broker's order ID to cancel
            
        Returns:
            True if cancellation successful
            
        Raises:
            OrderNotFoundError: If order ID not found
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        try:
            cancel_data = {
                "variety": "NORMAL",
                "orderid": broker_order_id,
            }
            
            headers = {
                "Authorization": f"Bearer {self._jwt_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": self._api_key,
            }
            
            response = requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/cancelOrder",
                json=cancel_data,
                headers=headers,
                timeout=10,
            )
            
            if response.status_code != 200:
                return False
            
            result = response.json()
            
            if not result.get("status"):
                error_msg = result.get("message", "Unknown error")
                if "not found" in error_msg.lower():
                    raise OrderNotFoundError(f"Order not found: {broker_order_id}")
                return False
            
            logger.info(f"Order cancelled successfully: {broker_order_id}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during order cancellation: {e}")
            return False
    
    def get_order_status(self, broker_order_id: str) -> Order:
        """
        Get current status of an order.
        
        Args:
            broker_order_id: Broker's order ID to query
            
        Returns:
            Order object with updated status
            
        Raises:
            OrderNotFoundError: If order ID not found
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        try:
            headers = {
                "Authorization": f"Bearer {self._jwt_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": self._api_key,
            }
            
            response = requests.get(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/getOrderBook",
                headers=headers,
                timeout=10,
            )
            
            if response.status_code != 200:
                raise OrderNotFoundError(f"Order not found: {broker_order_id}")
            
            result = response.json()
            
            if not result.get("status"):
                raise OrderNotFoundError(f"Order not found: {broker_order_id}")
            
            # Find the specific order
            orders = result.get("data", [])
            order_info = None
            for order in orders:
                if order.get("orderid") == broker_order_id:
                    order_info = order
                    break
            
            if not order_info:
                raise OrderNotFoundError(f"Order not found: {broker_order_id}")
            
            # Parse order status
            status_map = {
                "pending": OrderStatus.PENDING,
                "open": OrderStatus.PLACED,
                "complete": OrderStatus.FILLED,
                "rejected": OrderStatus.REJECTED,
                "cancelled": OrderStatus.CANCELLED,
            }
            
            status = status_map.get(
                order_info.get("status", "").lower(),
                OrderStatus.PENDING
            )
            
            return Order(
                order_id="",  # Internal ID not available from broker
                symbol=order_info.get("tradingsymbol", ""),
                side=OrderSide.BUY if order_info.get("transactiontype") == "BUY" else OrderSide.SELL,
                order_type=OrderType.MARKET,  # Simplified
                quantity=int(order_info.get("quantity", 0)),
                product_type=ProductType.MIS,  # Simplified
                status=status,
                broker_order_id=broker_order_id,
                filled_qty=int(order_info.get("filledshares", 0)),
                filled_price=float(order_info.get("averageprice", 0)) if order_info.get("averageprice") else None,
                timestamp=datetime.now(),
                rejection_reason=order_info.get("text"),
            )
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during order status query: {str(e)}")
    
    def get_positions(self) -> List[dict]:
        """
        Get all open positions.
        
        Returns:
            List of position dictionaries
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")
        
        try:
            headers = {
                "Authorization": f"Bearer {self._jwt_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress": "00:00:00:00:00:00",
                "X-PrivateKey": self._api_key,
            }
            
            response = requests.get(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/getPosition",
                headers=headers,
                timeout=10,
            )
            
            if response.status_code != 200:
                return []
            
            result = response.json()
            
            if not result.get("status"):
                return []
            
            # Parse positions
            positions = []
            for pos in result.get("data", []):
                positions.append({
                    "symbol": pos.get("tradingsymbol"),
                    "quantity": int(pos.get("netqty", 0)),
                    "avg_price": float(pos.get("netavgprice", 0)),
                    "ltp": float(pos.get("ltp", 0)),
                    "pnl": float(pos.get("pnl", 0)),
                })
            
            return positions
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during positions query: {e}")
            return []
    
    def get_instrument_master(self) -> List[dict]:
        """
        Download instrument master with symbol tokens and trading details.
        
        Returns:
            List of instrument dictionaries with symbol, token, exchange, lot_size, tick_size, trading_symbol
            
        Requirements: 23.1, 23.2
        """
        logger.info("Fetching instrument master from Angel One...")
        
        try:
            # Angel One provides instrument master as downloadable file
            # Download master contract file
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to download instrument master: {response.status_code}")
                return []
            
            # Parse JSON response
            data = response.json()
            
            instruments = []
            for item in data:
                try:
                    # Parse instrument data
                    # Angel One format includes: token, symbol, name, expiry, strike, lotsize, instrumenttype, exch_seg, tick_size
                    instruments.append({
                        "symbol": item.get("symbol", "").strip(),
                        "token": item.get("token", "").strip(),
                        "exchange": item.get("exch_seg", "NSE").strip(),
                        "lot_size": int(item.get("lotsize", 1)),
                        "tick_size": float(item.get("tick_size", 0.05)),
                        "trading_symbol": item.get("symbol", "").strip(),
                        "instrument": item.get("instrumenttype", "").strip(),
                        "name": item.get("name", "").strip(),
                    })
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping invalid instrument: {e}")
                    continue
            
            logger.info(f"Downloaded {len(instruments)} instruments from Angel One")
            return instruments
            
        except Exception as e:
            logger.error(f"Error downloading instrument master: {e}", exc_info=True)
            return []
