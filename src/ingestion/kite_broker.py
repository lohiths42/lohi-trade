"""Zerodha Kite Connect API v3 broker adapter implementation.

This module implements the BrokerInterface for Zerodha Kite Connect,
providing OAuth2 authentication, order management, WebSocket market data,
daily token refresh, and transient error retry logic.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8
"""

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

logger = get_logger("KiteBroker")

# Kite Connect API v3 status codes that are transient / retryable
_TRANSIENT_HTTP_CODES = {502, 503, 504, 429}
_MAX_RETRIES = 2

# Terminal order states in Kite
_TERMINAL_STATES = {"COMPLETE", "CANCELLED", "REJECTED"}

# Kite order‑type mapping from internal enum to Kite API string
_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL",
    OrderType.SL_M: "SL-M",
}

# Kite product‑type mapping
_PRODUCT_TYPE_MAP: dict[ProductType, str] = {
    ProductType.MIS: "MIS",
    ProductType.CNC: "CNC",
    ProductType.NRML: "NRML",
}

# Kite order‑status → internal OrderStatus mapping
_STATUS_MAP: dict[str, OrderStatus] = {
    "OPEN": OrderStatus.PLACED,
    "PENDING": OrderStatus.PENDING,
    "COMPLETE": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "TRIGGER PENDING": OrderStatus.PLACED,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
}


class KiteBroker(BrokerInterface):
    """Zerodha Kite Connect API v3 broker adapter.

    Implements OAuth2 login, order placement with Kite parameter mapping,
    order status polling, daily token refresh at 8:30 AM IST, KiteTicker
    WebSocket for real-time market data, and transient error retry (up to 2).

    Requirements: 15.1–15.8
    """

    # Kite Connect API v3 endpoints
    BASE_URL = "https://api.kite.trade"
    LOGIN_URL = "https://kite.zerodha.com/connect/login"
    WS_URL = "wss://ws.kite.trade"

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._api_secret: str | None = None
        self._access_token: str | None = None
        self._user_id: str | None = None

        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._connected: bool = False

        self._subscribed_symbols: dict[str, int] = {}  # symbol → instrument token
        self._tick_callback: Callable[[Tick], None] | None = None

        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 5

        self._token_refresh_thread: threading.Thread | None = None
        self._token_refresh_stop: threading.Event = threading.Event()

    # ── authentication ────────────────────────────────────────────

    def connect(self, credentials: BrokerCredentials) -> bool:
        """Authenticate via Kite Connect OAuth2 flow.

        ``credentials.api_key``   → Kite API key
        ``credentials.password``  → Kite API secret
        ``credentials.client_id`` → user id
        ``credentials.totp_secret`` → request_token obtained from OAuth redirect

        Returns True on success.

        Requirements: 15.1, 15.2
        """
        try:
            logger.info("Connecting to Kite Connect API v3...")

            self._api_key = credentials.api_key
            self._api_secret = credentials.password
            self._user_id = credentials.client_id
            request_token = credentials.totp_secret

            if not request_token:
                raise AuthenticationError(
                    "request_token is required (pass via credentials.totp_secret)",
                )

            # Exchange request_token for access_token
            session_data = self._create_session(request_token)
            self._access_token = session_data.get("access_token")

            if not self._access_token:
                raise AuthenticationError("Failed to obtain access token from Kite")

            self._connected = True
            logger.info(f"Connected to Kite Connect (User: {self._user_id})")

            # Start daily token refresh scheduler (8:30 AM IST)
            self._start_token_refresh_scheduler()

            return True

        except AuthenticationError:
            raise
        except requests.exceptions.RequestException as exc:
            raise ConnectionError(f"Network error during Kite login: {exc}")
        except Exception as exc:
            raise ConnectionError(f"Unexpected error during Kite login: {exc}")

    def disconnect(self) -> None:
        """Disconnect and clean up all resources."""
        logger.info("Disconnecting from Kite Connect...")

        # Stop token refresh scheduler
        self._token_refresh_stop.set()
        if self._token_refresh_thread and self._token_refresh_thread.is_alive():
            self._token_refresh_thread.join(timeout=5)

        # Close WebSocket
        if self._ws:
            self._ws.close()
            self._ws = None
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)

        self._connected = False
        self._access_token = None
        self._user_id = None
        self._subscribed_symbols.clear()
        logger.info("Disconnected from Kite Connect")

    def is_connected(self) -> bool:
        return self._connected and self._access_token is not None

    # ── session helpers ───────────────────────────────────────────

    def _create_session(self, request_token: str) -> dict:
        """Exchange request_token for an access_token (Kite Connect v3)."""
        import hashlib

        checksum = hashlib.sha256(
            f"{self._api_key}{request_token}{self._api_secret}".encode(),
        ).hexdigest()

        payload = {
            "api_key": self._api_key,
            "request_token": request_token,
            "checksum": checksum,
        }

        resp = self._kite_post("/session/token", payload, auth=False)
        return resp

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self._api_key}:{self._access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # ── HTTP helpers with retry ───────────────────────────────────

    def _kite_post(
        self, path: str, data: dict, auth: bool = True,
    ) -> dict:
        """POST to Kite API with transient-error retry (Req 15.8)."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers() if auth else {
            "X-Kite-Version": "3",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.post(url, data=data, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Transient error {resp.status_code} on POST {path}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES}",
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("status") == "error":
                    error_type = body.get("error_type", "GeneralException")
                    message = body.get("message", "Unknown error")
                    logger.error(f"Kite API error: {error_type} — {message}")
                    raise _kite_error(error_type, message)
                return body.get("data", body)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Network error on POST {path}, retry {attempt + 1}/{_MAX_RETRIES}: {exc}",
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectionError(f"Network error on POST {path}: {exc}") from exc

        raise ConnectionError(f"POST {path} failed after retries: {last_exc}")

    def _kite_get(self, path: str) -> dict:
        """GET from Kite API with transient-error retry (Req 15.8)."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers()

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Transient error {resp.status_code} on GET {path}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES}",
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("status") == "error":
                    error_type = body.get("error_type", "GeneralException")
                    message = body.get("message", "Unknown error")
                    logger.error(f"Kite API error: {error_type} — {message}")
                    raise _kite_error(error_type, message)
                return body.get("data", body)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Network error on GET {path}, retry {attempt + 1}/{_MAX_RETRIES}: {exc}",
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectionError(f"Network error on GET {path}: {exc}") from exc

        raise ConnectionError(f"GET {path} failed after retries: {last_exc}")

    def _kite_delete(self, path: str) -> dict:
        """DELETE from Kite API with transient-error retry."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers()

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.delete(url, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("status") == "error":
                    error_type = body.get("error_type", "GeneralException")
                    message = body.get("message", "Unknown error")
                    raise _kite_error(error_type, message)
                return body.get("data", body)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectionError(f"Network error on DELETE {path}: {exc}") from exc

        raise ConnectionError(f"DELETE {path} failed after retries: {last_exc}")

    # ── order management ──────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        """Place an order via Kite Connect.

        Maps internal Order to Kite params: exchange, tradingsymbol,
        transaction_type, quantity, price, trigger_price, order_type, product.

        Requirements: 15.4, 15.5
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        kite_order_type = _ORDER_TYPE_MAP.get(order.order_type, "MARKET")
        kite_product = _PRODUCT_TYPE_MAP.get(order.product_type, "MIS")

        params: dict[str, str] = {
            "exchange": "NSE",
            "tradingsymbol": order.symbol,
            "transaction_type": order.side.value,  # BUY / SELL
            "quantity": str(order.quantity),
            "order_type": kite_order_type,
            "product": kite_product,
            "validity": "DAY",
        }

        # Price fields
        if order.price is not None:
            params["price"] = str(order.price)
        else:
            params["price"] = "0"

        if order.trigger_price is not None:
            params["trigger_price"] = str(order.trigger_price)
        else:
            params["trigger_price"] = "0"

        result = self._kite_post("/orders/regular", params)
        broker_order_id = str(result.get("order_id", ""))
        logger.info(f"Order placed on Kite: {broker_order_id}")
        return broker_order_id

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel a pending order on Kite."""
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        try:
            self._kite_delete(f"/orders/regular/{broker_order_id}")
            logger.info(f"Order cancelled on Kite: {broker_order_id}")
            return True
        except OrderNotFoundError:
            raise
        except Exception as exc:
            logger.error(f"Failed to cancel order {broker_order_id}: {exc}")
            return False

    def get_order_status(self, broker_order_id: str) -> Order:
        """Get current status of an order from Kite.

        Raises OrderNotFoundError if the order does not exist.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        try:
            order_history = self._kite_get(f"/orders/{broker_order_id}")
        except Exception:
            raise OrderNotFoundError(f"Order not found: {broker_order_id}")

        # order_history is a list of status updates; take the latest
        if isinstance(order_history, list) and order_history:
            info = order_history[-1]
        elif isinstance(order_history, dict):
            info = order_history
        else:
            raise OrderNotFoundError(f"Order not found: {broker_order_id}")

        kite_status = info.get("status", "").upper()
        internal_status = _STATUS_MAP.get(kite_status, OrderStatus.PENDING)

        return Order(
            order_id="",
            symbol=info.get("tradingsymbol", ""),
            side=OrderSide.BUY if info.get("transaction_type") == "BUY" else OrderSide.SELL,
            order_type=_reverse_order_type(info.get("order_type", "MARKET")),
            quantity=int(info.get("quantity", 0)),
            product_type=_reverse_product_type(info.get("product", "MIS")),
            status=internal_status,
            price=_safe_float(info.get("price")),
            trigger_price=_safe_float(info.get("trigger_price")),
            broker_order_id=broker_order_id,
            filled_qty=int(info.get("filled_quantity", 0)),
            filled_price=_safe_float(info.get("average_price")),
            timestamp=datetime.now(),
            rejection_reason=info.get("status_message"),
        )

    def poll_order_status(
        self, broker_order_id: str, interval: float = 1.0, max_polls: int = 300,
    ) -> Order:
        """Poll order status every *interval* seconds until a terminal state.

        Terminal states: COMPLETE, CANCELLED, REJECTED.

        Requirement: 15.6
        """
        for _ in range(max_polls):
            order = self.get_order_status(broker_order_id)
            if order.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            ):
                return order
            time.sleep(interval)

        logger.warning(f"Order {broker_order_id} did not reach terminal state after {max_polls} polls")
        return self.get_order_status(broker_order_id)

    # ── positions ─────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Get all open positions from Kite."""
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        try:
            data = self._kite_get("/portfolio/positions")
            positions = []
            # Kite returns {"net": [...], "day": [...]}
            net_positions = data.get("net", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            for pos in net_positions:
                positions.append({
                    "symbol": pos.get("tradingsymbol"),
                    "quantity": int(pos.get("quantity", 0)),
                    "avg_price": float(pos.get("average_price", 0)),
                    "ltp": float(pos.get("last_price", 0)),
                    "pnl": float(pos.get("pnl", 0)),
                })
            return positions
        except Exception as exc:
            logger.error(f"Error fetching positions: {exc}")
            return []

    def get_holdings(self) -> list[dict]:
        """Get portfolio holdings from Kite for reconciliation."""
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        try:
            data = self._kite_get("/portfolio/holdings")
            holdings = []
            items = data if isinstance(data, list) else []
            for h in items:
                holdings.append({
                    "symbol": h.get("tradingsymbol"),
                    "quantity": int(h.get("quantity", 0)),
                    "avg_price": float(h.get("average_price", 0)),
                    "ltp": float(h.get("last_price", 0)),
                    "pnl": float(h.get("pnl", 0)),
                    "isin": h.get("isin", ""),
                })
            return holdings
        except Exception as exc:
            logger.error(f"Error fetching holdings: {exc}")
            return []

    # ── instrument master ─────────────────────────────────────────

    def get_instrument_master(self) -> list[dict]:
        """Download instrument master from Kite Connect.

        Returns list of dicts with symbol, token, exchange, lot_size, tick_size, etc.
        """
        logger.info("Fetching instrument master from Kite Connect...")
        try:
            url = f"{self.BASE_URL}/instruments"
            headers = self._auth_headers()
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Failed to download Kite instruments: {resp.status_code}")
                return []

            import csv
            import io

            reader = csv.DictReader(io.StringIO(resp.text))
            instruments: list[dict] = []
            for row in reader:
                try:
                    instruments.append({
                        "symbol": row.get("tradingsymbol", "").strip(),
                        "token": int(row.get("instrument_token", 0)),
                        "exchange": row.get("exchange", "NSE").strip(),
                        "lot_size": int(row.get("lot_size", 1)),
                        "tick_size": float(row.get("tick_size", 0.05)),
                        "trading_symbol": row.get("tradingsymbol", "").strip(),
                        "instrument": row.get("instrument_type", "").strip(),
                        "name": row.get("name", "").strip(),
                    })
                except (ValueError, KeyError):
                    continue

            logger.info(f"Downloaded {len(instruments)} instruments from Kite")
            return instruments
        except Exception as exc:
            logger.error(f"Error downloading Kite instrument master: {exc}", exc_info=True)
            return []

    # ── WebSocket (KiteTicker) ────────────────────────────────────

    def subscribe(self, symbols: list[str], on_tick: Callable[[Tick], None]) -> bool:
        """Subscribe to real-time market data via KiteTicker WebSocket.

        Requirement: 15.7
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Kite API")

        self._tick_callback = on_tick

        # Resolve symbol → instrument_token
        instruments = self.get_instrument_master()
        sym_map = {inst["symbol"]: inst["token"] for inst in instruments}

        tokens_to_sub: list[int] = []
        for sym in symbols:
            token = sym_map.get(sym)
            if token is None:
                logger.warning(f"Symbol {sym} not found in Kite instrument master")
                continue
            self._subscribed_symbols[sym] = token
            tokens_to_sub.append(token)

        if not tokens_to_sub:
            return False

        # Start WebSocket if not already running
        if self._ws is None:
            self._init_websocket()

        # Send subscribe message
        if self._ws:
            sub_msg = json.dumps({"a": "subscribe", "v": tokens_to_sub})
            try:
                self._ws.send(sub_msg)
            except Exception as exc:
                logger.error(f"Error sending subscribe message: {exc}")
                return False

        logger.info(f"Subscribed to {len(tokens_to_sub)} symbols on KiteTicker")
        return True

    def unsubscribe(self, symbols: list[str]) -> bool:
        """Unsubscribe from KiteTicker for given symbols."""
        if not self._ws:
            return False

        tokens_to_unsub: list[int] = []
        for sym in symbols:
            token = self._subscribed_symbols.pop(sym, None)
            if token is not None:
                tokens_to_unsub.append(token)

        if tokens_to_unsub:
            unsub_msg = json.dumps({"a": "unsubscribe", "v": tokens_to_unsub})
            try:
                self._ws.send(unsub_msg)
            except Exception as exc:
                logger.error(f"Error sending unsubscribe message: {exc}")
                return False

        return True

    def _init_websocket(self) -> None:
        """Initialize KiteTicker WebSocket connection."""
        ws_url = (
            f"{self.WS_URL}?api_key={self._api_key}&access_token={self._access_token}"
        )

        def on_open(ws):
            logger.info("KiteTicker WebSocket opened")

        def on_message(ws, message):
            try:
                if isinstance(message, bytes):
                    self._handle_binary_tick(message)
                else:
                    data = json.loads(message)
                    self._handle_json_message(data)
            except Exception as exc:
                logger.error(f"Error processing KiteTicker message: {exc}")

        def on_error(ws, error):
            logger.error(f"KiteTicker WebSocket error: {error}")

        def on_close(ws, status_code, msg):
            logger.warning(f"KiteTicker WebSocket closed: {status_code} — {msg}")
            self._handle_ws_disconnect()

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()
        time.sleep(2)

    def _handle_binary_tick(self, data: bytes) -> None:
        """Parse binary tick packets from KiteTicker (simplified)."""
        if not self._tick_callback or len(data) < 8:
            return

        # KiteTicker binary format: first 4 bytes = instrument_token (big-endian)
        # Simplified: in production, full binary protocol parsing is needed.
        try:
            import struct

            offset = 0
            while offset + 8 <= len(data):
                token = struct.unpack(">I", data[offset : offset + 4])[0]
                # Next 4 bytes: LTP as int (price * 100)
                ltp_raw = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
                ltp = ltp_raw / 100.0

                symbol = self._token_to_symbol(token)
                if symbol:
                    tick = Tick(
                        symbol=symbol,
                        token=token,
                        ltp=ltp,
                        volume=0,
                        timestamp=datetime.now(),
                        exchange="NSE",
                    )
                    self._tick_callback(tick)

                # Move to next packet (simplified: 8 bytes per tick)
                offset += 8
        except Exception as exc:
            logger.error(f"Error parsing binary tick: {exc}")

    def _handle_json_message(self, data: dict) -> None:
        """Handle JSON messages from KiteTicker (e.g. order updates)."""
        logger.debug(f"KiteTicker JSON message: {data}")

    def _token_to_symbol(self, token: int) -> str | None:
        for sym, tok in self._subscribed_symbols.items():
            if tok == token:
                return sym
        return None

    def _handle_ws_disconnect(self) -> None:
        """Reconnect KiteTicker with exponential backoff."""
        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            backoff = min(2 ** self._reconnect_attempts, 30)
            logger.info(
                f"KiteTicker reconnect in {backoff}s (attempt {self._reconnect_attempts})",
            )
            time.sleep(backoff)
            try:
                self._init_websocket()
                if self._subscribed_symbols and self._tick_callback:
                    self.subscribe(list(self._subscribed_symbols.keys()), self._tick_callback)
                self._reconnect_attempts = 0
            except Exception as exc:
                logger.error(f"KiteTicker reconnection failed: {exc}")
        else:
            logger.error("Max KiteTicker reconnection attempts reached")
            self._connected = False

    # ── daily token refresh ───────────────────────────────────────

    def _start_token_refresh_scheduler(self) -> None:
        """Start a background thread that refreshes the Kite access token
        daily at 8:30 AM IST.

        Requirement: 15.3
        """
        self._token_refresh_stop.clear()

        def _scheduler():
            while not self._token_refresh_stop.is_set():
                now = datetime.now()
                # IST = UTC+5:30 — we use local time and assume server is IST
                target = now.replace(hour=8, minute=30, second=0, microsecond=0)
                if now >= target:
                    # Already past 8:30 today, schedule for tomorrow
                    from datetime import timedelta

                    target += timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                logger.info(f"Next Kite token refresh in {wait_seconds:.0f}s")

                # Wait, but check stop event every 60s
                while wait_seconds > 0 and not self._token_refresh_stop.is_set():
                    sleep_time = min(wait_seconds, 60)
                    self._token_refresh_stop.wait(timeout=sleep_time)
                    wait_seconds -= sleep_time

                if self._token_refresh_stop.is_set():
                    break

                self._refresh_token_daily()

        self._token_refresh_thread = threading.Thread(target=_scheduler, daemon=True)
        self._token_refresh_thread.start()

    def _refresh_token_daily(self) -> None:
        """Attempt to invalidate the old session and log a reminder.

        Kite tokens cannot be refreshed programmatically — the user must
        re-authenticate via the OAuth2 redirect flow each day. This method
        invalidates the current session and marks the broker as disconnected
        so the system can prompt re-authentication.

        Requirement: 15.3
        """
        logger.info("Daily Kite token refresh triggered (8:30 AM IST)")
        try:
            # Invalidate current session
            self._kite_delete("/session/token")
        except Exception as exc:
            logger.warning(f"Error invalidating Kite session: {exc}")

        self._access_token = None
        self._connected = False
        logger.warning(
            "Kite session invalidated. Re-authentication required via OAuth2 flow.",
        )


# ── module-level helpers ──────────────────────────────────────────


def _kite_error(error_type: str, message: str) -> Exception:
    """Map Kite error_type to the appropriate BrokerError subclass."""
    if error_type in ("TokenException", "UserException"):
        return AuthenticationError(message)
    if error_type == "OrderException":
        return OrderRejectionError(message)
    if error_type == "InputException":
        return OrderRejectionError(message)
    return ConnectionError(message)


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _reverse_order_type(kite_type: str) -> OrderType:
    _map = {v: k for k, v in _ORDER_TYPE_MAP.items()}
    return _map.get(kite_type, OrderType.MARKET)


def _reverse_product_type(kite_product: str) -> ProductType:
    _map = {v: k for k, v in _PRODUCT_TYPE_MAP.items()}
    return _map.get(kite_product, ProductType.MIS)
