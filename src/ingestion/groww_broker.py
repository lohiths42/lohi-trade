"""
Groww trading API broker adapter implementation.

This module implements the BrokerInterface for Groww,
providing OAuth2 authentication, order management, portfolio holdings
retrieval, and transient error retry logic.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7
"""

import time
import threading
from datetime import datetime
from typing import Callable, List, Optional, Dict

import requests

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


logger = get_logger("GrowwBroker")

# Transient HTTP status codes eligible for retry
_TRANSIENT_HTTP_CODES = {502, 503, 504, 429}
_MAX_RETRIES = 2

# Groww order-type mapping from internal enum to Groww API string
_ORDER_TYPE_MAP: Dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL",
    OrderType.SL_M: "SL",  # Groww maps SL-M to SL
}

# Groww product-type mapping
_PRODUCT_TYPE_MAP: Dict[ProductType, str] = {
    ProductType.MIS: "INTRADAY",
    ProductType.CNC: "DELIVERY",
    ProductType.NRML: "DELIVERY",
}

# Groww order-status → internal OrderStatus mapping
_STATUS_MAP: Dict[str, OrderStatus] = {
    "OPEN": OrderStatus.PLACED,
    "PENDING": OrderStatus.PENDING,
    "EXECUTED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "PARTIALLY_EXECUTED": OrderStatus.PARTIALLY_FILLED,
    "TRIGGER_PENDING": OrderStatus.PLACED,
}

# Terminal states in Groww
_TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
}


class GrowwBroker(BrokerInterface):
    """
    Groww trading API broker adapter.

    Implements OAuth2 login, order placement with Groww parameter mapping,
    order status tracking until terminal state, portfolio holdings retrieval,
    and transient error retry (up to 2).

    Requirements: 16.1–16.7
    """

    BASE_URL = "https://api.groww.in/v1"
    AUTH_URL = "https://api.groww.in/v1/oauth/token"

    def __init__(self) -> None:
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._access_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._connected: bool = False

    # ── authentication ────────────────────────────────────────────

    def connect(self, credentials: BrokerCredentials) -> bool:
        """
        Authenticate via Groww OAuth2 flow.

        ``credentials.api_key``     → Groww client ID
        ``credentials.password``    → Groww client secret
        ``credentials.client_id``   → Groww user ID
        ``credentials.totp_secret`` → authorization code from OAuth redirect

        Returns True on success.

        Requirements: 16.1, 16.2
        """
        try:
            logger.info("Connecting to Groww trading API...")

            self._client_id = credentials.api_key
            self._client_secret = credentials.password
            self._user_id = credentials.client_id
            auth_code = credentials.totp_secret

            if not auth_code:
                raise AuthenticationError(
                    "authorization_code is required (pass via credentials.totp_secret)"
                )

            token_data = self._exchange_token(auth_code)
            self._access_token = token_data.get("access_token")

            if not self._access_token:
                raise AuthenticationError("Failed to obtain access token from Groww")

            self._connected = True
            logger.info(f"Connected to Groww (User: {self._user_id})")
            return True

        except AuthenticationError:
            raise
        except requests.exceptions.RequestException as exc:
            raise ConnectionError(f"Network error during Groww login: {exc}")
        except Exception as exc:
            raise ConnectionError(f"Unexpected error during Groww login: {exc}")

    def disconnect(self) -> None:
        """Disconnect and clean up resources."""
        logger.info("Disconnecting from Groww...")
        self._connected = False
        self._access_token = None
        self._user_id = None
        logger.info("Disconnected from Groww")

    def is_connected(self) -> bool:
        return self._connected and self._access_token is not None

    # ── session helpers ───────────────────────────────────────────

    def _exchange_token(self, auth_code: str) -> dict:
        """Exchange authorization code for an access token (Groww OAuth2)."""
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        resp = self._groww_post("/oauth/token", payload, auth=False)
        return resp

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    # ── HTTP helpers with retry ───────────────────────────────────

    def _groww_post(self, path: str, data: dict, auth: bool = True) -> dict:
        """POST to Groww API with transient-error retry (Req 16.6)."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers() if auth else {"Content-Type": "application/json"}

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=data, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Transient error {resp.status_code} on POST {path}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES}"
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("success") is False or body.get("error"):
                    error_code = body.get("error_code", "UNKNOWN")
                    message = body.get("message") or body.get("error", "Unknown error")
                    logger.error(f"Groww API error: {error_code} — {message}")
                    raise _groww_error(error_code, message)
                return body.get("data", body)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Network error on POST {path}, retry {attempt + 1}/{_MAX_RETRIES}: {exc}"
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectionError(f"Network error on POST {path}: {exc}") from exc

        raise ConnectionError(f"POST {path} failed after retries: {last_exc}")

    def _groww_get(self, path: str) -> dict:
        """GET from Groww API with transient-error retry (Req 16.6)."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers()

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Transient error {resp.status_code} on GET {path}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES}"
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("success") is False or body.get("error"):
                    error_code = body.get("error_code", "UNKNOWN")
                    message = body.get("message") or body.get("error", "Unknown error")
                    logger.error(f"Groww API error: {error_code} — {message}")
                    raise _groww_error(error_code, message)
                return body.get("data", body)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Network error on GET {path}, retry {attempt + 1}/{_MAX_RETRIES}: {exc}"
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectionError(f"Network error on GET {path}: {exc}") from exc

        raise ConnectionError(f"GET {path} failed after retries: {last_exc}")

    def _groww_delete(self, path: str) -> dict:
        """DELETE from Groww API with transient-error retry."""
        url = f"{self.BASE_URL}{path}"
        headers = self._auth_headers()

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.delete(url, headers=headers, timeout=10)
                if resp.status_code in _TRANSIENT_HTTP_CODES and attempt < _MAX_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                body = resp.json()
                if body.get("success") is False or body.get("error"):
                    error_code = body.get("error_code", "UNKNOWN")
                    message = body.get("message") or body.get("error", "Unknown error")
                    raise _groww_error(error_code, message)
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
        """
        Place an order via Groww trading API.

        Maps internal Order to Groww params: symbol, exchange,
        transaction_type, quantity, price, trigger_price, order_type, product.

        Requirements: 16.3, 16.4
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Groww API")

        groww_order_type = _ORDER_TYPE_MAP.get(order.order_type, "MARKET")
        groww_product = _PRODUCT_TYPE_MAP.get(order.product_type, "DELIVERY")

        params: Dict = {
            "symbol": order.symbol,
            "exchange": "NSE",
            "transaction_type": order.side.value,  # BUY / SELL
            "quantity": order.quantity,
            "order_type": groww_order_type,
            "product": groww_product,
            "validity": "DAY",
        }

        if order.price is not None:
            params["price"] = order.price
        else:
            params["price"] = 0

        if order.trigger_price is not None:
            params["trigger_price"] = order.trigger_price
        else:
            params["trigger_price"] = 0

        result = self._groww_post("/orders", params)
        broker_order_id = str(result.get("order_id", ""))
        logger.info(f"Order placed on Groww: {broker_order_id}")
        return broker_order_id

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel a pending order on Groww."""
        if not self.is_connected():
            raise ConnectionError("Not connected to Groww API")

        try:
            self._groww_delete(f"/orders/{broker_order_id}")
            logger.info(f"Order cancelled on Groww: {broker_order_id}")
            return True
        except OrderNotFoundError:
            raise
        except Exception as exc:
            logger.error(f"Failed to cancel order {broker_order_id}: {exc}")
            return False

    def get_order_status(self, broker_order_id: str) -> Order:
        """
        Get current status of an order from Groww.

        Raises OrderNotFoundError if the order does not exist.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Groww API")

        try:
            info = self._groww_get(f"/orders/{broker_order_id}")
        except Exception:
            raise OrderNotFoundError(f"Order not found: {broker_order_id}")

        groww_status = info.get("status", "").upper()
        internal_status = _STATUS_MAP.get(groww_status, OrderStatus.PENDING)

        return Order(
            order_id="",
            symbol=info.get("symbol", ""),
            side=OrderSide.BUY if info.get("transaction_type") == "BUY" else OrderSide.SELL,
            order_type=_reverse_order_type(info.get("order_type", "MARKET")),
            quantity=int(info.get("quantity", 0)),
            product_type=_reverse_product_type(info.get("product", "DELIVERY")),
            status=internal_status,
            price=_safe_float(info.get("price")),
            trigger_price=_safe_float(info.get("trigger_price")),
            broker_order_id=broker_order_id,
            filled_qty=int(info.get("filled_quantity", 0)),
            filled_price=_safe_float(info.get("average_price")),
            timestamp=datetime.now(),
            rejection_reason=info.get("rejection_reason"),
        )

    def poll_order_status(
        self, broker_order_id: str, interval: float = 1.0, max_polls: int = 300
    ) -> Order:
        """
        Poll order status every *interval* seconds until a terminal state.

        Terminal states: EXECUTED, CANCELLED, REJECTED.

        Requirement: 16.5
        """
        for _ in range(max_polls):
            order = self.get_order_status(broker_order_id)
            if order.status in _TERMINAL_STATUSES:
                return order
            time.sleep(interval)

        logger.warning(
            f"Order {broker_order_id} did not reach terminal state after {max_polls} polls"
        )
        return self.get_order_status(broker_order_id)

    # ── positions ─────────────────────────────────────────────────

    def get_positions(self) -> List[dict]:
        """Get all open positions from Groww."""
        if not self.is_connected():
            raise ConnectionError("Not connected to Groww API")

        try:
            data = self._groww_get("/portfolio/positions")
            positions = []
            items = data if isinstance(data, list) else data.get("positions", []) if isinstance(data, dict) else []
            for pos in items:
                positions.append({
                    "symbol": pos.get("symbol"),
                    "quantity": int(pos.get("quantity", 0)),
                    "avg_price": float(pos.get("average_price", 0)),
                    "ltp": float(pos.get("ltp", 0)),
                    "pnl": float(pos.get("pnl", 0)),
                })
            return positions
        except Exception as exc:
            logger.error(f"Error fetching positions: {exc}")
            return []

    def get_holdings(self) -> List[dict]:
        """
        Get portfolio holdings from Groww for reconciliation.

        Requirement: 16.7
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to Groww API")

        try:
            data = self._groww_get("/portfolio/holdings")
            holdings = []
            items = data if isinstance(data, list) else data.get("holdings", []) if isinstance(data, dict) else []
            for h in items:
                holdings.append({
                    "symbol": h.get("symbol"),
                    "quantity": int(h.get("quantity", 0)),
                    "avg_price": float(h.get("average_price", 0)),
                    "ltp": float(h.get("ltp", 0)),
                    "pnl": float(h.get("pnl", 0)),
                    "isin": h.get("isin", ""),
                })
            return holdings
        except Exception as exc:
            logger.error(f"Error fetching holdings: {exc}")
            return []

    # ── instrument master ─────────────────────────────────────────

    def get_instrument_master(self) -> List[dict]:
        """
        Download instrument master from Groww.

        Returns list of dicts with symbol, token, exchange, lot_size, tick_size.
        """
        logger.info("Fetching instrument master from Groww...")
        try:
            data = self._groww_get("/instruments")
            instruments: List[dict] = []
            items = data if isinstance(data, list) else data.get("instruments", []) if isinstance(data, dict) else []
            for row in items:
                try:
                    instruments.append({
                        "symbol": row.get("symbol", "").strip(),
                        "token": int(row.get("token", 0)),
                        "exchange": row.get("exchange", "NSE").strip(),
                        "lot_size": int(row.get("lot_size", 1)),
                        "tick_size": float(row.get("tick_size", 0.05)),
                        "trading_symbol": row.get("trading_symbol", row.get("symbol", "")).strip(),
                        "instrument": row.get("instrument_type", "").strip(),
                        "name": row.get("name", "").strip(),
                        "isin": row.get("isin", "").strip(),
                    })
                except (ValueError, KeyError):
                    continue
            logger.info(f"Downloaded {len(instruments)} instruments from Groww")
            return instruments
        except Exception as exc:
            logger.error(f"Error downloading Groww instrument master: {exc}", exc_info=True)
            return []

    # ── WebSocket (not supported by Groww — stub) ─────────────────

    def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> bool:
        """
        Groww does not provide a WebSocket market data feed.
        Returns False — use NSE/BSE feed or another broker for live ticks.
        """
        logger.warning("Groww does not support WebSocket market data subscriptions")
        return False

    def unsubscribe(self, symbols: List[str]) -> bool:
        """No-op for Groww (no WebSocket support)."""
        return False


# ── module-level helpers ──────────────────────────────────────────


def _groww_error(error_code: str, message: str) -> Exception:
    """Map Groww error_code to the appropriate BrokerError subclass."""
    if error_code in ("AUTH_FAILED", "TOKEN_EXPIRED", "UNAUTHORIZED"):
        return AuthenticationError(message)
    if error_code in ("ORDER_REJECTED", "INVALID_ORDER", "INSUFFICIENT_FUNDS"):
        return OrderRejectionError(message)
    if error_code in ("ORDER_NOT_FOUND",):
        return OrderNotFoundError(message)
    return ConnectionError(message)


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _reverse_order_type(groww_type: str) -> OrderType:
    # Explicit mapping since SL and SL_M both map to "SL" in Groww
    _map: Dict[str, OrderType] = {
        "MARKET": OrderType.MARKET,
        "LIMIT": OrderType.LIMIT,
        "SL": OrderType.SL,
    }
    return _map.get(groww_type, OrderType.MARKET)


def _reverse_product_type(groww_product: str) -> ProductType:
    # Explicit mapping since CNC and NRML both map to "DELIVERY" in Groww
    _map: Dict[str, ProductType] = {
        "INTRADAY": ProductType.MIS,
        "DELIVERY": ProductType.CNC,
    }
    return _map.get(groww_product, ProductType.CNC)
