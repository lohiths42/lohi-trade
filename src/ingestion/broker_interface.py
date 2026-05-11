"""Broker API abstraction layer for LOHI-TRADE.

This module defines the abstract interface for broker adapters and common data classes
for ticks, orders, and order status. Concrete broker implementations (Shoonya, Angel One)
must implement this interface.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderType(Enum):
    """Order type enumeration."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"  # Stop Loss
    SL_M = "SL-M"  # Stop Loss Market


class OrderSide(Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "PENDING"
    PLACED = "PLACED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"


class ProductType(Enum):
    """Product type enumeration."""

    MIS = "MIS"  # Margin Intraday Square-off
    CNC = "CNC"  # Cash and Carry
    NRML = "NRML"  # Normal


@dataclass
class Tick:
    """Represents a single price update from the exchange.
    
    Attributes:
        symbol: Trading symbol (e.g., "RELIANCE")
        token: Exchange token for the instrument
        ltp: Last traded price
        volume: Cumulative volume for the day
        timestamp: Time when tick was received
        exchange: Exchange name (e.g., "NSE", "BSE")
        bid: Best bid price (optional)
        ask: Best ask price (optional)
        open: Day's opening price (optional)
        high: Day's high price (optional)
        low: Day's low price (optional)
        close: Previous day's closing price (optional)

    """

    symbol: str
    token: int
    ltp: float
    volume: int
    timestamp: datetime
    exchange: str
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None


@dataclass
class Order:
    """Represents a trading order.
    
    Attributes:
        order_id: Internal UUID for the order
        symbol: Trading symbol
        side: BUY or SELL
        order_type: MARKET, LIMIT, SL, or SL-M
        quantity: Number of shares
        price: Limit price (for LIMIT orders)
        trigger_price: Trigger price (for SL orders)
        product_type: MIS, CNC, or NRML
        status: Current order status
        broker_order_id: Order ID from broker (after placement)
        filled_qty: Number of shares filled
        filled_price: Average fill price
        timestamp: Order creation timestamp
        rejection_reason: Reason for rejection (if rejected)

    """

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    product_type: ProductType
    status: OrderStatus
    price: float | None = None
    trigger_price: float | None = None
    broker_order_id: str | None = None
    filled_qty: int = 0
    filled_price: float | None = None
    timestamp: datetime | None = None
    rejection_reason: str | None = None


@dataclass
class BrokerCredentials:
    """Broker authentication credentials.
    
    Attributes:
        api_key: API key for broker
        client_id: Client ID or user ID
        password: Password or API secret
        totp_secret: TOTP secret for 2FA (optional)

    """

    api_key: str
    client_id: str
    password: str
    totp_secret: str | None = None


class BrokerInterface(ABC):
    """Abstract base class for broker adapters.
    
    All broker implementations (Shoonya, Angel One) must implement this interface
    to ensure consistent behavior across different brokers.
    """

    @abstractmethod
    def connect(self, credentials: BrokerCredentials) -> bool:
        """Establish connection to broker API and authenticate.
        
        Args:
            credentials: Broker authentication credentials
            
        Returns:
            True if connection successful, False otherwise
            
        Raises:
            ConnectionError: If connection fails
            AuthenticationError: If authentication fails

        """

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from broker API and clean up resources.
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if broker connection is active.
        
        Returns:
            True if connected, False otherwise

        """

    @abstractmethod
    def subscribe(self, symbols: list[str], on_tick: Callable[[Tick], None]) -> bool:
        """Subscribe to real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to subscribe to
            on_tick: Callback function to handle incoming ticks
            
        Returns:
            True if subscription successful, False otherwise
            
        Raises:
            ConnectionError: If not connected to broker

        """

    @abstractmethod
    def unsubscribe(self, symbols: list[str]) -> bool:
        """Unsubscribe from real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to unsubscribe from
            
        Returns:
            True if unsubscription successful, False otherwise

        """

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """Place an order with the broker.
        
        Args:
            order: Order object with all required details
            
        Returns:
            Broker order ID if successful
            
        Raises:
            OrderRejectionError: If broker rejects the order
            ConnectionError: If not connected to broker

        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel a pending order.
        
        Args:
            broker_order_id: Broker's order ID to cancel
            
        Returns:
            True if cancellation successful, False otherwise
            
        Raises:
            OrderNotFoundError: If order ID not found

        """

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> Order:
        """Get current status of an order.
        
        Args:
            broker_order_id: Broker's order ID to query
            
        Returns:
            Order object with updated status
            
        Raises:
            OrderNotFoundError: If order ID not found

        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Get all open positions.
        
        Returns:
            List of position dictionaries with symbol, quantity, avg_price, etc.

        """

    @abstractmethod
    def get_instrument_master(self) -> list[dict]:
        """Download instrument master with symbol tokens and trading details.
        
        Returns:
            List of instrument dictionaries with symbol, token, lot_size, tick_size, etc.

        """


class BrokerError(Exception):
    """Base exception for broker-related errors."""



class ConnectionError(BrokerError):
    """Raised when broker connection fails."""



class AuthenticationError(BrokerError):
    """Raised when broker authentication fails."""



class OrderRejectionError(BrokerError):
    """Raised when broker rejects an order."""



class OrderNotFoundError(BrokerError):
    """Raised when order ID is not found."""

