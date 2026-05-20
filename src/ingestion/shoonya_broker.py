"""Shoonya (Finvasia) broker adapter implementation.

This module implements the BrokerInterface for Shoonya broker API,
providing WebSocket connectivity for live ticks and REST API for order management.
"""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import datetime

import requests
import websocket

from src.ingestion.broker_interface import (
    AuthenticationError,
    BrokerCredentials,
    BrokerInterface,
    ConnectionError,
    Order,
    OrderNotFoundError,
    OrderRejectionError,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    Tick,
)
from src.utils.logger import get_logger

logger = get_logger("ShoonyaBroker")


class ShoonyaBroker(BrokerInterface):
    """Shoonya (Finvasia) broker adapter.

    Implements WebSocket connection for live ticks and REST API for order placement.
    """

    # API endpoints
    BASE_URL = "https://api.shoonya.com/NorenWClientTP"
    WS_URL = "wss://api.shoonya.com/NorenWSTP/"

    def __init__(self):
        """Initialize Shoonya broker adapter."""
        self._session_token: str | None = None
        self._user_id: str | None = None
        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._connected = False
        self._subscribed_symbols: dict[str, int] = {}  # symbol -> token mapping
        self._tick_callback: Callable[[Tick], None] | None = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    def connect(self, credentials: BrokerCredentials) -> bool:
        """Connect to Shoonya API and authenticate.

        Args:
            credentials: Shoonya authentication credentials

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
            AuthenticationError: If authentication fails

        """
        try:
            logger.info("Connecting to Shoonya API...")

            # Generate password hash
            pwd_hash = hashlib.sha256(credentials.password.encode()).hexdigest()

            # Login request
            login_data = {
                "source": "API",
                "apkversion": "1.0.0",
                "uid": credentials.client_id,
                "pwd": pwd_hash,
                "factor2": credentials.totp_secret or "",
                "vc": credentials.vendor_code or credentials.client_id,
                "appkey": hashlib.sha256(
                    f"{credentials.client_id}|{credentials.api_key}".encode(),
                ).hexdigest(),
                "imei": credentials.imei or "abc1234",
            }

            response = requests.post(
                f"{self.BASE_URL}/QuickAuth",
                data=f"jData={json.dumps(login_data)}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code != 200:
                raise ConnectionError(f"Login request failed: {response.status_code}")

            result = response.json()

            if result.get("stat") != "Ok":
                error_msg = result.get("emsg", "Unknown error")
                raise AuthenticationError(f"Login failed: {error_msg}")

            self._session_token = result.get("susertoken")
            self._user_id = credentials.client_id
            self._connected = True

            logger.info(f"Successfully connected to Shoonya API (User: {self._user_id})")

            # Initialize WebSocket connection
            self._init_websocket()

            return True

        except AuthenticationError:
            # Re-raise authentication errors as-is
            raise
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during login: {e!s}")
        except Exception as e:
            raise ConnectionError(f"Unexpected error during login: {e!s}")

    def disconnect(self) -> None:
        """Disconnect from Shoonya API and clean up resources."""
        logger.info("Disconnecting from Shoonya API...")

        # Close WebSocket
        if self._ws:
            self._ws.close()
            self._ws = None

        # Wait for WebSocket thread to finish
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)

        self._connected = False
        self._session_token = None
        self._user_id = None
        self._subscribed_symbols.clear()

        logger.info("Disconnected from Shoonya API")

    def is_connected(self) -> bool:
        """Check if broker connection is active."""
        return self._connected and self._session_token is not None

    def _init_websocket(self) -> None:
        """Initialize WebSocket connection for live ticks."""
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")

        def on_open(ws):
            logger.info("WebSocket connection opened")
            # Send connection message
            connect_msg = {
                "t": "c",
                "uid": self._user_id,
                "actid": self._user_id,
                "susertoken": self._session_token,
                "source": "API",
            }
            ws.send(json.dumps(connect_msg))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                self._handle_ws_message(data)
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
            self._handle_ws_disconnect()

        self._ws = websocket.WebSocketApp(
            self.WS_URL,
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
        """Handle incoming WebSocket messages.

        Args:
            data: Parsed JSON message from WebSocket

        """
        msg_type = data.get("t")

        if msg_type == "ck":
            # Connection acknowledgment
            logger.info("WebSocket connection acknowledged")

        elif msg_type == "tk" or msg_type == "tf":
            # Tick data (tk = touchline, tf = full)
            if self._tick_callback:
                tick = self._parse_tick(data)
                if tick:
                    self._tick_callback(tick)

        elif msg_type == "dk":
            # Depth data (not used currently)
            pass

        else:
            logger.debug(f"Unhandled WebSocket message type: {msg_type}")

    def _parse_tick(self, data: dict) -> Tick | None:
        """Parse tick data from WebSocket message.

        Args:
            data: WebSocket message data

        Returns:
            Tick object or None if parsing fails

        """
        try:
            # Find symbol from token
            token = int(data.get("tk", 0))
            symbol = None
            for sym, tok in self._subscribed_symbols.items():
                if tok == token:
                    symbol = sym
                    break

            if not symbol:
                return None

            return Tick(
                symbol=symbol,
                token=token,
                ltp=float(data.get("lp", 0)),
                volume=int(data.get("v", 0)),
                timestamp=datetime.now(),
                exchange=data.get("e", "NSE"),
                bid=float(data.get("bp1", 0)) if data.get("bp1") else None,
                ask=float(data.get("sp1", 0)) if data.get("sp1") else None,
                open=float(data.get("o", 0)) if data.get("o") else None,
                high=float(data.get("h", 0)) if data.get("h") else None,
                low=float(data.get("l", 0)) if data.get("l") else None,
                close=float(data.get("c", 0)) if data.get("c") else None,
            )
        except Exception as e:
            logger.error(f"Error parsing tick data: {e}")
            return None

    def _handle_ws_disconnect(self) -> None:
        """Handle WebSocket disconnection and attempt reconnection."""
        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            backoff = min(2**self._reconnect_attempts, 30)  # Exponential backoff, max 30s
            logger.info(
                f"Attempting WebSocket reconnection in {backoff}s (attempt {self._reconnect_attempts})"
            )
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

    def subscribe(self, symbols: list[str], on_tick: Callable[[Tick], None]) -> bool:
        """Subscribe to real-time tick data for given symbols.

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

        # Subscribe to each symbol
        for symbol in symbols:
            token = symbol_token_map.get(symbol)
            if not token:
                logger.warning(f"Symbol {symbol} not found in instrument master")
                continue

            self._subscribed_symbols[symbol] = token

            # Send subscription message
            sub_msg = {
                "t": "t",  # Subscribe to touchline
                "k": f"NSE|{token}",
            }
            self._ws.send(json.dumps(sub_msg))
            logger.info(f"Subscribed to {symbol} (token: {token})")

        return True

    def unsubscribe(self, symbols: list[str]) -> bool:
        """Unsubscribe from real-time tick data for given symbols.

        Args:
            symbols: List of trading symbols to unsubscribe from

        Returns:
            True if unsubscription successful

        """
        if not self._ws:
            return False

        for symbol in symbols:
            token = self._subscribed_symbols.get(symbol)
            if token:
                # Send unsubscription message
                unsub_msg = {
                    "t": "u",  # Unsubscribe
                    "k": f"NSE|{token}",
                }
                self._ws.send(json.dumps(unsub_msg))
                del self._subscribed_symbols[symbol]
                logger.info(f"Unsubscribed from {symbol}")

        return True

    def place_order(self, order: Order) -> str:
        """Place an order with Shoonya broker.

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
                "uid": self._user_id,
                "actid": self._user_id,
                "exch": "NSE",
                "tsym": order.symbol,
                "qty": str(order.quantity),
                "prc": str(order.price) if order.price else "0",
                "trgprc": str(order.trigger_price) if order.trigger_price else "0",
                "prd": order.product_type.value,
                "trantype": order.side.value,
                "prctyp": order.order_type.value,
                "ret": "DAY",
            }

            response = requests.post(
                f"{self.BASE_URL}/PlaceOrder",
                data=f"jData={json.dumps(order_data)}&jKey={self._session_token}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code != 200:
                raise OrderRejectionError(f"Order placement failed: {response.status_code}")

            result = response.json()

            if result.get("stat") != "Ok":
                error_msg = result.get("emsg", "Unknown error")
                raise OrderRejectionError(f"Order rejected: {error_msg}")

            broker_order_id = result.get("norenordno")
            logger.info(f"Order placed successfully: {broker_order_id}")

            return broker_order_id

        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during order placement: {e!s}")

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel a pending order.

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
                "uid": self._user_id,
                "norenordno": broker_order_id,
            }

            response = requests.post(
                f"{self.BASE_URL}/CancelOrder",
                data=f"jData={json.dumps(cancel_data)}&jKey={self._session_token}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code != 200:
                return False

            result = response.json()

            if result.get("stat") != "Ok":
                error_msg = result.get("emsg", "Unknown error")
                if "not found" in error_msg.lower():
                    raise OrderNotFoundError(f"Order not found: {broker_order_id}")
                return False

            logger.info(f"Order cancelled successfully: {broker_order_id}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during order cancellation: {e}")
            return False

    def get_order_status(self, broker_order_id: str) -> Order:
        """Get current status of an order.

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
            order_data = {
                "uid": self._user_id,
                "norenordno": broker_order_id,
            }

            response = requests.post(
                f"{self.BASE_URL}/SingleOrdHist",
                data=f"jData={json.dumps(order_data)}&jKey={self._session_token}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code != 200:
                raise OrderNotFoundError(f"Order not found: {broker_order_id}")

            result = response.json()

            if result.get("stat") != "Ok":
                raise OrderNotFoundError(f"Order not found: {broker_order_id}")

            # Parse order status
            order_info = result
            status_map = {
                "PENDING": OrderStatus.PENDING,
                "OPEN": OrderStatus.PLACED,
                "COMPLETE": OrderStatus.FILLED,
                "REJECTED": OrderStatus.REJECTED,
                "CANCELED": OrderStatus.CANCELLED,
            }

            status = status_map.get(order_info.get("status", "PENDING"), OrderStatus.PENDING)

            return Order(
                order_id="",  # Internal ID not available from broker
                symbol=order_info.get("tsym", ""),
                side=OrderSide.BUY if order_info.get("trantype") == "B" else OrderSide.SELL,
                order_type=OrderType.MARKET,  # Simplified
                quantity=int(order_info.get("qty", 0)),
                product_type=ProductType.MIS,  # Simplified
                status=status,
                broker_order_id=broker_order_id,
                filled_qty=int(order_info.get("fillshares", 0)),
                filled_price=(
                    float(order_info.get("avgprc", 0)) if order_info.get("avgprc") else None
                ),
                timestamp=datetime.now(),
                rejection_reason=order_info.get("rejreason"),
            )

        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Network error during order status query: {e!s}")

    def get_positions(self) -> list[dict]:
        """Get all open positions.

        Returns:
            List of position dictionaries

        """
        if not self.is_connected():
            raise ConnectionError("Not connected to broker API")

        try:
            pos_data = {
                "uid": self._user_id,
                "actid": self._user_id,
            }

            response = requests.post(
                f"{self.BASE_URL}/PositionBook",
                data=f"jData={json.dumps(pos_data)}&jKey={self._session_token}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code != 200:
                return []

            result = response.json()

            # Handle both dict and list responses
            if isinstance(result, dict):
                if result.get("stat") != "Ok":
                    return []
                # If it's a dict with stat=Ok, the positions might be in the response itself
                # or we need to iterate over the dict
                positions_data = result if "tsym" in result else []
            else:
                # It's already a list
                positions_data = result

            # Parse positions
            positions = []
            if isinstance(positions_data, list):
                for pos in positions_data:
                    positions.append(
                        {
                            "symbol": pos.get("tsym"),
                            "quantity": int(pos.get("netqty", 0)),
                            "avg_price": float(pos.get("netavgprc", 0)),
                            "ltp": float(pos.get("lp", 0)),
                            "pnl": float(pos.get("rpnl", 0)),
                        }
                    )

            return positions

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during positions query: {e}")
            return []

    def get_instrument_master(self) -> list[dict]:
        """Download instrument master with symbol tokens and trading details.

        Returns:
            List of instrument dictionaries with symbol, token, exchange, lot_size, tick_size, trading_symbol

        Requirements: 23.1, 23.2

        """
        logger.info("Fetching instrument master from Shoonya...")

        try:
            # Shoonya provides instrument master as downloadable CSV files
            # Download NSE instruments
            url = "https://api.shoonya.com/NSE_symbols.txt.zip"

            import csv
            import io
            import zipfile

            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to download instrument master: {response.status_code}")
                return []

            # Extract CSV from zip
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                # Get the first file in the zip
                filename = z.namelist()[0]
                with z.open(filename) as f:
                    # Read CSV
                    content = f.read().decode("utf-8")
                    reader = csv.DictReader(io.StringIO(content))

                    instruments = []
                    for row in reader:
                        # Parse instrument data
                        # Shoonya CSV format: Exchange, Token, LotSize, Symbol, TradingSymbol, Expiry, Instrument, OptionType, StrikePrice, TickSize
                        try:
                            instruments.append(
                                {
                                    "symbol": row.get("Symbol", "").strip(),
                                    "token": int(row.get("Token", 0)),
                                    "exchange": row.get("Exchange", "NSE").strip(),
                                    "lot_size": int(row.get("LotSize", 1)),
                                    "tick_size": float(row.get("TickSize", 0.05)),
                                    "trading_symbol": row.get("TradingSymbol", "").strip(),
                                    "instrument": row.get("Instrument", "").strip(),
                                }
                            )
                        except (ValueError, KeyError) as e:
                            logger.debug(f"Skipping invalid instrument row: {e}")
                            continue

                    logger.info(f"Downloaded {len(instruments)} instruments from Shoonya")
                    return instruments

        except Exception as e:
            logger.error(f"Error downloading instrument master: {e}", exc_info=True)
            # Return empty list on error
            return []
