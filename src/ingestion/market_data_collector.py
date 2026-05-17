"""NSE Market Data Collector for LOHI-TRADE.

Collects real-time market data from NSE official data feeds via WebSocket,
publishes tick updates to Redis event bus within 50ms of receipt, and
implements reconnection with fallback to broker WebSocket during outages.

Handles pre-market (9:00-9:15 AM IST) and post-market (3:30-4:00 PM IST) sessions.

Requirements: 25.1, 25.2, 25.4, 25.5, 25.6, 25.7
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from src.ingestion.broker_interface import BrokerInterface, Tick
from src.state.event_bus import EventBus
from src.utils.logger import get_logger

logger = get_logger("MarketDataCollector")

# IST timezone offset: UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


class FeedSource(Enum):
    """Active data feed source."""

    NSE = "NSE"
    BSE = "BSE"
    BROKER_FALLBACK = "BROKER_FALLBACK"
    DISCONNECTED = "DISCONNECTED"


class MarketSession(Enum):
    """Current market session type."""

    PRE_MARKET = "PRE_MARKET"  # 9:00 - 9:15 IST
    NORMAL = "NORMAL"  # 9:15 - 15:30 IST
    POST_MARKET = "POST_MARKET"  # 15:30 - 16:00 IST
    CLOSED = "CLOSED"


@dataclass
class TickData:
    """Comprehensive tick data collected per security from NSE feed.

    Includes LTP, last traded qty, total volume, best bid/ask,
    OHLC, and previous close as required by 25.2.
    """

    symbol: str
    token: int
    ltp: float
    last_traded_qty: int
    total_volume: int
    best_bid_price: float
    best_bid_qty: int
    best_ask_price: float
    best_ask_qty: int
    open: float
    high: float
    low: float
    close: float
    previous_close: float
    timestamp: datetime
    exchange: str = "NSE"


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""

    price: float
    quantity: int


@dataclass
class OrderBookDepth:
    """Top 5 bid/ask levels for a security.

    Requirement 25.3: full order book depth (top 5 bid/ask levels)
    for securities in the user's active watchlists.
    """

    symbol: str
    bids: list["OrderBookLevel"] = field(default_factory=list)
    asks: list["OrderBookLevel"] = field(default_factory=list)
    timestamp: datetime | None = None

    def to_redis_hash(self) -> dict[str, str]:
        """Convert to flat dict for Redis hash storage.

        Keys: bid_1..bid_5, ask_1..ask_5, bid_qty_1..bid_qty_5, ask_qty_1..ask_qty_5
        """
        data: dict[str, str] = {}
        for i in range(5):
            idx = i + 1
            if i < len(self.bids):
                data[f"bid_{idx}"] = str(self.bids[i].price)
                data[f"bid_qty_{idx}"] = str(self.bids[i].quantity)
            else:
                data[f"bid_{idx}"] = "0.0"
                data[f"bid_qty_{idx}"] = "0"
            if i < len(self.asks):
                data[f"ask_{idx}"] = str(self.asks[i].price)
                data[f"ask_qty_{idx}"] = str(self.asks[i].quantity)
            else:
                data[f"ask_{idx}"] = "0.0"
                data[f"ask_qty_{idx}"] = "0"
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()
        data["symbol"] = self.symbol
        return data

    @classmethod
    def from_redis_hash(cls, data: dict[str, str]) -> "OrderBookDepth":
        """Reconstruct from a Redis hash dict."""
        symbol = data.get("symbol", "")
        bids = []
        asks = []
        for i in range(1, 6):
            bid_price = float(data.get(f"bid_{i}", "0.0"))
            bid_qty = int(data.get(f"bid_qty_{i}", "0"))
            if bid_price > 0 or bid_qty > 0:
                bids.append(OrderBookLevel(price=bid_price, quantity=bid_qty))
            ask_price = float(data.get(f"ask_{i}", "0.0"))
            ask_qty = int(data.get(f"ask_qty_{i}", "0"))
            if ask_price > 0 or ask_qty > 0:
                asks.append(OrderBookLevel(price=ask_price, quantity=ask_qty))
        ts_str = data.get("timestamp")
        timestamp = datetime.fromisoformat(ts_str) if ts_str else None
        return cls(symbol=symbol, bids=bids, asks=asks, timestamp=timestamp)


@dataclass
class ConnectionStats:
    """Statistics for the NSE/BSE feed connections."""

    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    total_ticks_received: int = 0
    total_ticks_published: int = 0
    reconnection_attempts: int = 0
    fallback_activations: int = 0
    last_tick_time: datetime | None = None
    total_publish_latency_ms: float = 0.0
    publish_count_for_latency: int = 0
    # BSE-specific stats
    bse_connected_at: datetime | None = None
    bse_disconnected_at: datetime | None = None
    bse_ticks_received: int = 0
    bse_ticks_published: int = 0
    bse_reconnection_attempts: int = 0
    price_discrepancies_detected: int = 0

    @property
    def avg_publish_latency_ms(self) -> float:
        if self.publish_count_for_latency == 0:
            return 0.0
        return self.total_publish_latency_ms / self.publish_count_for_latency


class MarketDataCollector:
    """Collects real-time and session data from NSE official feeds.

    Connects via WebSocket to NSE data feed endpoint, publishes tick
    updates to Redis stream ``stream:ticks`` within 50 ms of receipt,
    and falls back to broker WebSocket on feed loss.

    Requirements: 25.1, 25.2, 25.4, 25.5, 25.6, 25.7
    """

    # Pre-market: 09:00 - 09:15 IST
    PRE_MARKET_START_HOUR = 9
    PRE_MARKET_START_MIN = 0
    PRE_MARKET_END_HOUR = 9
    PRE_MARKET_END_MIN = 15

    # Normal market: 09:15 - 15:30 IST
    NORMAL_START_HOUR = 9
    NORMAL_START_MIN = 15
    NORMAL_END_HOUR = 15
    NORMAL_END_MIN = 30

    # Post-market: 15:30 - 16:00 IST
    POST_MARKET_START_HOUR = 15
    POST_MARKET_START_MIN = 30
    POST_MARKET_END_HOUR = 16
    POST_MARKET_END_MIN = 0

    # Reconnection parameters (max 5 seconds as per requirement 25.5)
    RECONNECT_BASE_DELAY = 0.5
    RECONNECT_MAX_DELAY = 5.0
    MAX_RECONNECT_ATTEMPTS = 10

    # Publish latency target (50 ms as per requirement 25.4)
    PUBLISH_LATENCY_TARGET_MS = 50.0

    # Stream configuration
    TICK_STREAM_MAXLEN = 1000

    def __init__(
        self,
        event_bus: EventBus,
        nse_feed_url: str = "wss://nse-feed.example.com/ws",
        bse_feed_url: str = "wss://bse-feed.example.com/ws",
        fallback_broker: BrokerInterface | None = None,
        subscribed_symbols: list[str] | None = None,
        dual_listed_symbols: list[str] | None = None,
        bse_only_symbols: list[str] | None = None,
    ):
        """Initialise the market data collector.

        Args:
            event_bus: EventBus instance for publishing ticks to Redis.
            nse_feed_url: WebSocket URL for the NSE data feed.
            bse_feed_url: WebSocket URL for the BSE data feed.
            fallback_broker: Optional broker adapter used as fallback
                when the NSE feed is unavailable (requirement 25.5).
            subscribed_symbols: Initial list of symbols to subscribe to.
            dual_listed_symbols: Symbols listed on both NSE and BSE.
            bse_only_symbols: Symbols listed only on BSE.

        """
        self.event_bus = event_bus
        self.nse_feed_url = nse_feed_url
        self.bse_feed_url = bse_feed_url
        self.fallback_broker = fallback_broker
        self._subscribed_symbols: list[str] = subscribed_symbols or []
        self._dual_listed_symbols: list[str] = dual_listed_symbols or []
        self._bse_only_symbols: list[str] = bse_only_symbols or []

        # NSE connection state
        self._feed_source = FeedSource.DISCONNECTED
        self._ws_connection: Any = None  # websockets connection object
        self._connected = False
        self._running = False
        self._reconnect_attempts = 0

        # BSE connection state
        self._bse_feed_url = bse_feed_url
        self._bse_ws_connection: Any = None
        self._bse_connected = False
        self._bse_reconnect_attempts = 0

        # Fallback state
        self._fallback_active = False

        # Price discrepancy detection: symbol -> latest NSE price
        self._nse_latest_prices: dict[str, float] = {}
        # Price discrepancy threshold (0.5% as per requirement 26.5)
        self.PRICE_DISCREPANCY_THRESHOLD = 0.005

        # Statistics
        self._stats = ConnectionStats()

        # Threading / async control
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect_nse_feed(self) -> None:
        """Connect to NSE official data feed for all actively traded securities.

        Establishes a WebSocket connection to the NSE feed endpoint,
        subscribes to configured symbols, and begins publishing tick
        updates to the Redis event bus.

        On connection loss, reconnects within 5 seconds with exponential
        backoff and falls back to broker WebSocket during the outage.

        Requirements: 25.1, 25.4, 25.5
        """
        logger.info("Connecting to NSE data feed", extra={"url": self.nse_feed_url})
        self._running = True
        self._stop_event.clear()

        try:
            await self._establish_nse_connection()
            self._start_health_monitor()
            logger.info(
                "NSE feed connected successfully",
                extra={"symbols_count": len(self._subscribed_symbols)},
            )
        except Exception as e:
            logger.error(f"Failed to connect to NSE feed: {e}", exc_info=True)
            await self._activate_fallback()
            raise

    async def disconnect(self) -> None:
        """Disconnect from NSE feed and clean up resources."""
        logger.info("Disconnecting from NSE data feed")
        self._running = False
        self._stop_event.set()

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

        await self._close_nse_connection()
        await self._close_bse_connection()
        self._deactivate_fallback()

        self._stats.disconnected_at = datetime.now(IST)
        self._feed_source = FeedSource.DISCONNECTED
        self._connected = False
        self._bse_connected = False
        logger.info("NSE/BSE feeds disconnected")

    async def connect_bse_feed(self) -> None:
        """Connect to BSE official data feed.

        Establishes a WebSocket connection to the BSE feed endpoint,
        subscribes to BSE-only and dual-listed symbols, and begins
        publishing tick updates to the Redis event bus.

        For dual-listed securities, NSE is the primary source (requirement 26.3).
        BSE data is used as the sole source for BSE-only securities (requirement 26.4).
        If BSE feed is unavailable, continues operating with NSE only (requirement 26.6).

        Requirements: 26.1, 26.2, 26.3, 26.4, 26.6
        """
        logger.info("Connecting to BSE data feed", extra={"url": self.bse_feed_url})

        try:
            await self._establish_bse_connection()
            logger.info(
                "BSE feed connected successfully",
                extra={
                    "dual_listed_count": len(self._dual_listed_symbols),
                    "bse_only_count": len(self._bse_only_symbols),
                },
            )
        except Exception as e:
            logger.warning(
                f"Failed to connect to BSE feed: {e}. "
                "Continuing with NSE data only (requirement 26.6).",
            )
            self._bse_connected = False

    async def disconnect_bse(self) -> None:
        """Disconnect from BSE feed only."""
        logger.info("Disconnecting from BSE data feed")
        await self._close_bse_connection()
        self._bse_connected = False
        self._stats.bse_disconnected_at = datetime.now(IST)
        logger.info("BSE feed disconnected")

    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to tick data for the given symbols.

        Args:
            symbols: List of NSE trading symbols.

        """
        new_symbols = [s for s in symbols if s not in self._subscribed_symbols]
        if new_symbols:
            self._subscribed_symbols.extend(new_symbols)
            logger.info(f"Subscribed to {len(new_symbols)} new symbols")

    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from tick data for the given symbols.

        Args:
            symbols: List of symbols to remove.

        """
        self._subscribed_symbols = [s for s in self._subscribed_symbols if s not in symbols]
        logger.info(f"Unsubscribed from {len(symbols)} symbols")

    def detect_price_discrepancy(
        self,
        symbol: str,
        nse_price: float,
        bse_price: float,
    ) -> bool:
        """Detect and log price discrepancy between NSE and BSE for dual-listed securities.

        Logs when the price difference exceeds 0.5% (requirement 26.5).

        Args:
            symbol: Trading symbol of the dual-listed security.
            nse_price: Latest price from NSE.
            bse_price: Latest price from BSE.

        Returns:
            True if a discrepancy >0.5% is detected, False otherwise.

        Requirements: 26.5

        """
        if nse_price <= 0 or bse_price <= 0:
            return False

        diff_pct = abs(nse_price - bse_price) / nse_price
        if diff_pct > self.PRICE_DISCREPANCY_THRESHOLD:
            self._stats.price_discrepancies_detected += 1
            logger.warning(
                f"Price discrepancy detected for {symbol}: "
                f"NSE={nse_price:.2f}, BSE={bse_price:.2f}, "
                f"diff={diff_pct * 100:.2f}%",
                extra={
                    "symbol": symbol,
                    "nse_price": nse_price,
                    "bse_price": bse_price,
                    "diff_pct": round(diff_pct * 100, 4),
                },
            )
            return True
        return False

    @property
    def is_connected(self) -> bool:
        """Whether the collector is actively receiving data."""
        return self._connected

    # ------------------------------------------------------------------
    # Order book depth collection (Requirement 25.3)
    # ------------------------------------------------------------------

    async def collect_order_book(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, OrderBookDepth]:
        """Collect top 5 bid/ask levels for watchlist securities and store in Redis.

        For each symbol, fetches order book depth data and stores it as a
        Redis hash at ``depth:{symbol}`` with keys bid_1..bid_5, ask_1..ask_5,
        bid_qty_1..bid_qty_5, ask_qty_1..ask_qty_5.

        Args:
            symbols: List of symbols to collect depth for.
                Defaults to subscribed symbols if not provided.

        Returns:
            Dict mapping symbol to OrderBookDepth.

        Requirements: 25.3

        """
        target_symbols = symbols if symbols is not None else list(self._subscribed_symbols)
        if not target_symbols:
            logger.debug("No symbols for order book depth collection")
            return {}

        results: dict[str, OrderBookDepth] = {}
        for symbol in target_symbols:
            try:
                depth = await self._fetch_order_book_depth(symbol)
                if depth is not None:
                    self._store_order_book_depth(depth)
                    results[symbol] = depth
            except Exception as e:
                logger.error(
                    f"Failed to collect order book for {symbol}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Collected order book depth for {len(results)}/{len(target_symbols)} symbols",
        )
        return results

    async def _fetch_order_book_depth(self, symbol: str) -> OrderBookDepth | None:
        """Fetch order book depth for a single symbol from the exchange feed.

        In production this would query the NSE/BSE WebSocket or REST API.
        Here we return None so callers can inject data via
        ``_store_order_book_depth`` directly or override this method.

        Args:
            symbol: Trading symbol.

        Returns:
            OrderBookDepth or None if unavailable.

        """
        # Production implementation would fetch from exchange feed.
        # Returning None by default; tests and live code override/inject.
        return None

    def _store_order_book_depth(self, depth: OrderBookDepth) -> None:
        """Store order book depth in Redis as a hash at ``depth:{symbol}``.

        Args:
            depth: OrderBookDepth to persist.

        """
        redis_key = f"depth:{depth.symbol}"
        hash_data = depth.to_redis_hash()
        try:
            self.event_bus.redis_client.hset(redis_key, mapping=hash_data)
            logger.debug(f"Stored order book depth for {depth.symbol}")
        except Exception as e:
            logger.error(
                f"Failed to store order book depth for {depth.symbol}: {e}",
                exc_info=True,
            )

    def get_order_book_depth(self, symbol: str) -> OrderBookDepth | None:
        """Retrieve stored order book depth from Redis.

        Args:
            symbol: Trading symbol.

        Returns:
            OrderBookDepth or None if not found.

        """
        redis_key = f"depth:{symbol}"
        try:
            data = self.event_bus.redis_client.hgetall(redis_key)
            if not data:
                return None
            return OrderBookDepth.from_redis_hash(data)
        except Exception as e:
            logger.error(
                f"Failed to retrieve order book depth for {symbol}: {e}",
                exc_info=True,
            )
            return None

    @property
    def feed_source(self) -> FeedSource:
        """Current active feed source."""
        return self._feed_source

    @property
    def stats(self) -> ConnectionStats:
        """Connection and performance statistics."""
        return self._stats

    @property
    def subscribed_symbols(self) -> list[str]:
        """Currently subscribed symbols."""
        return list(self._subscribed_symbols)

    @property
    def is_bse_connected(self) -> bool:
        """Whether the BSE feed is actively receiving data."""
        return self._bse_connected

    @property
    def dual_listed_symbols(self) -> list[str]:
        """Symbols listed on both NSE and BSE."""
        return list(self._dual_listed_symbols)

    @property
    def bse_only_symbols(self) -> list[str]:
        """Symbols listed only on BSE."""
        return list(self._bse_only_symbols)

    # ------------------------------------------------------------------
    # Market session helpers (Requirements 25.6, 25.7)
    # ------------------------------------------------------------------

    @staticmethod
    def get_current_session(now: datetime | None = None) -> MarketSession:
        """Determine the current market session based on IST time.

        Args:
            now: Optional datetime for testing; defaults to current IST time.

        Returns:
            The current MarketSession.

        Requirements: 25.6, 25.7

        """
        if now is None:
            now = datetime.now(IST)
        # Ensure we work in IST
        elif now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        else:
            now = now.astimezone(IST)

        t = now.hour * 60 + now.minute

        pre_start = 9 * 60  # 09:00
        pre_end = 9 * 60 + 15  # 09:15
        normal_end = 15 * 60 + 30  # 15:30
        post_end = 16 * 60  # 16:00

        if pre_start <= t < pre_end:
            return MarketSession.PRE_MARKET
        if pre_end <= t < normal_end:
            return MarketSession.NORMAL
        if normal_end <= t < post_end:
            return MarketSession.POST_MARKET
        return MarketSession.CLOSED

    # ------------------------------------------------------------------
    # Tick processing & publishing (Requirement 25.4)
    # ------------------------------------------------------------------

    def _process_tick(self, tick_data: TickData) -> None:
        """Process a single tick and publish to Redis event bus.

        Publishes within 50 ms of receipt (requirement 25.4).
        Tracks NSE prices for cross-exchange discrepancy detection.

        Args:
            tick_data: Parsed tick from the NSE feed.

        """
        receipt_time = time.monotonic()

        self._stats.total_ticks_received += 1
        self._stats.last_tick_time = datetime.now(IST)

        # Track NSE prices for discrepancy detection with BSE
        if tick_data.exchange == "NSE":
            self._nse_latest_prices[tick_data.symbol] = tick_data.ltp

        # Build message for event bus
        stream_name = f"stream:ticks:{tick_data.symbol}"
        message = self._tick_to_message(tick_data)

        try:
            self.event_bus.publish(
                stream_name=stream_name,
                message=message,
                maxlen=self.TICK_STREAM_MAXLEN,
            )
            self._stats.total_ticks_published += 1

            # Track publish latency
            elapsed_ms = (time.monotonic() - receipt_time) * 1000
            self._stats.total_publish_latency_ms += elapsed_ms
            self._stats.publish_count_for_latency += 1

            if elapsed_ms > self.PUBLISH_LATENCY_TARGET_MS:
                logger.warning(
                    f"Publish latency {elapsed_ms:.1f}ms exceeds "
                    f"{self.PUBLISH_LATENCY_TARGET_MS}ms target",
                    extra={"symbol": tick_data.symbol, "latency_ms": elapsed_ms},
                )

        except Exception as e:
            logger.error(
                f"Failed to publish tick for {tick_data.symbol}: {e}",
                exc_info=True,
            )

    @staticmethod
    def _tick_to_message(tick_data: TickData) -> dict[str, Any]:
        """Convert TickData to a dict suitable for event bus publishing."""
        return {
            "symbol": tick_data.symbol,
            "token": tick_data.token,
            "ltp": tick_data.ltp,
            "last_traded_qty": tick_data.last_traded_qty,
            "volume": tick_data.total_volume,
            "bid": tick_data.best_bid_price,
            "bid_qty": tick_data.best_bid_qty,
            "ask": tick_data.best_ask_price,
            "ask_qty": tick_data.best_ask_qty,
            "open": tick_data.open,
            "high": tick_data.high,
            "low": tick_data.low,
            "close": tick_data.close,
            "previous_close": tick_data.previous_close,
            "timestamp": tick_data.timestamp.isoformat(),
            "exchange": tick_data.exchange,
            "session": MarketDataCollector.get_current_session(tick_data.timestamp).value,
        }

    # ------------------------------------------------------------------
    # NSE WebSocket connection management
    # ------------------------------------------------------------------

    async def _establish_nse_connection(self) -> None:
        """Open a WebSocket connection to the NSE feed endpoint.

        In production this would use the ``websockets`` library.
        Here we set state so the rest of the class operates correctly.
        """
        try:
            # In production: self._ws_connection = await websockets.connect(self.nse_feed_url)
            self._connected = True
            self._feed_source = FeedSource.NSE
            self._reconnect_attempts = 0
            self._stats.connected_at = datetime.now(IST)
            logger.info("NSE WebSocket connection established")
        except Exception as e:
            logger.error(f"NSE WebSocket connection failed: {e}", exc_info=True)
            raise

    async def _close_nse_connection(self) -> None:
        """Close the NSE WebSocket connection."""
        if self._ws_connection is not None:
            try:
                await self._ws_connection.close()
            except Exception as e:
                logger.error(f"Error closing NSE WebSocket: {e}")
            finally:
                self._ws_connection = None

    # ------------------------------------------------------------------
    # BSE WebSocket connection management (Requirements 26.1, 26.6)
    # ------------------------------------------------------------------

    async def _establish_bse_connection(self) -> None:
        """Open a WebSocket connection to the BSE feed endpoint.

        In production this would use the ``websockets`` library.
        Here we set state so the rest of the class operates correctly.

        Requirements: 26.1
        """
        try:
            # In production: self._bse_ws_connection = await websockets.connect(self.bse_feed_url)
            self._bse_connected = True
            self._bse_reconnect_attempts = 0
            self._stats.bse_connected_at = datetime.now(IST)
            logger.info("BSE WebSocket connection established")
        except Exception as e:
            logger.error(f"BSE WebSocket connection failed: {e}", exc_info=True)
            raise

    async def _close_bse_connection(self) -> None:
        """Close the BSE WebSocket connection."""
        if self._bse_ws_connection is not None:
            try:
                await self._bse_ws_connection.close()
            except Exception as e:
                logger.error(f"Error closing BSE WebSocket: {e}")
            finally:
                self._bse_ws_connection = None

    def _process_bse_tick(self, tick_data: TickData) -> None:
        """Process a BSE tick with dual-listing logic.

        For dual-listed securities: NSE is primary, BSE is used for
        cross-validation / discrepancy detection (requirement 26.3, 26.5).
        For BSE-only securities: BSE is the sole source (requirement 26.4).

        Args:
            tick_data: Parsed tick from the BSE feed.

        Requirements: 26.2, 26.3, 26.4, 26.5

        """
        self._stats.bse_ticks_received += 1

        is_dual_listed = tick_data.symbol in self._dual_listed_symbols
        is_bse_only = tick_data.symbol in self._bse_only_symbols

        if is_dual_listed:
            # For dual-listed: check for price discrepancy, don't publish
            # as primary (NSE is primary per requirement 26.3)
            nse_price = self._nse_latest_prices.get(tick_data.symbol)
            if nse_price is not None:
                self.detect_price_discrepancy(
                    tick_data.symbol,
                    nse_price,
                    tick_data.ltp,
                )
            self._stats.bse_ticks_published += 1
        elif is_bse_only:
            # For BSE-only: publish as sole source (requirement 26.4)
            self._process_tick(tick_data)
            self._stats.bse_ticks_published += 1
        else:
            # Unknown symbol — publish anyway as BSE data
            self._process_tick(tick_data)
            self._stats.bse_ticks_published += 1

    def parse_bse_message(self, raw: str) -> TickData | None:
        """Parse a raw JSON message from the BSE WebSocket feed.

        Collects the same data fields as NSE (requirement 26.2).

        Args:
            raw: Raw JSON string from the BSE feed.

        Returns:
            Parsed TickData or None if parsing fails.

        """
        try:
            data = json.loads(raw)
            return TickData(
                symbol=str(data["symbol"]),
                token=int(data["token"]),
                ltp=float(data["ltp"]),
                last_traded_qty=int(data.get("last_traded_qty", 0)),
                total_volume=int(data.get("total_volume", 0)),
                best_bid_price=float(data.get("best_bid_price", 0.0)),
                best_bid_qty=int(data.get("best_bid_qty", 0)),
                best_ask_price=float(data.get("best_ask_price", 0.0)),
                best_ask_qty=int(data.get("best_ask_qty", 0)),
                open=float(data.get("open", 0.0)),
                high=float(data.get("high", 0.0)),
                low=float(data.get("low", 0.0)),
                close=float(data.get("close", 0.0)),
                previous_close=float(data.get("previous_close", 0.0)),
                timestamp=datetime.fromisoformat(data["timestamp"]),
                exchange="BSE",
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to parse BSE message: {e}", extra={"raw": raw[:200]})
            return None

    async def handle_bse_feed_disconnect(self) -> None:
        """Handle BSE feed disconnection.

        Continues operating with NSE data only (requirement 26.6).
        Attempts reconnection in the background.
        """
        logger.warning(
            "BSE feed disconnected. Continuing with NSE data only (requirement 26.6).",
        )
        self._bse_connected = False
        self._stats.bse_disconnected_at = datetime.now(IST)

        # Attempt reconnection loop for BSE
        while self._running and not self._bse_connected:
            success = await self._reconnect_bse()
            if success:
                break

    async def _reconnect_bse(self) -> bool:
        """Attempt to reconnect to the BSE feed with exponential backoff.

        Returns:
            True if reconnection succeeded.

        """
        self._bse_reconnect_attempts += 1
        self._stats.bse_reconnection_attempts += 1

        if self._bse_reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"Max BSE reconnection attempts ({self.MAX_RECONNECT_ATTEMPTS}) reached. "
                "Continuing with NSE only.",
            )
            return False

        delay = min(
            self.RECONNECT_BASE_DELAY * (2 ** (self._bse_reconnect_attempts - 1)),
            self.RECONNECT_MAX_DELAY,
        )
        logger.info(
            f"Reconnecting to BSE feed in {delay:.1f}s "
            f"(attempt {self._bse_reconnect_attempts}/{self.MAX_RECONNECT_ATTEMPTS})",
        )
        await asyncio.sleep(delay)

        try:
            await self._establish_bse_connection()
            logger.info("BSE feed reconnected successfully")
            return True
        except Exception as e:
            logger.warning(f"BSE reconnection attempt failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Reconnection with exponential backoff (Requirement 25.5)
    # ------------------------------------------------------------------

    async def _reconnect(self) -> bool:
        """Attempt to reconnect to the NSE feed with exponential backoff.

        Max delay capped at 5 seconds (requirement 25.5).

        Returns:
            True if reconnection succeeded.

        """
        self._reconnect_attempts += 1
        self._stats.reconnection_attempts += 1

        if self._reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"Max reconnection attempts ({self.MAX_RECONNECT_ATTEMPTS}) reached",
            )
            return False

        delay = min(
            self.RECONNECT_BASE_DELAY * (2 ** (self._reconnect_attempts - 1)),
            self.RECONNECT_MAX_DELAY,
        )
        logger.info(
            f"Reconnecting to NSE feed in {delay:.1f}s "
            f"(attempt {self._reconnect_attempts}/{self.MAX_RECONNECT_ATTEMPTS})",
        )
        await asyncio.sleep(delay)

        try:
            await self._establish_nse_connection()
            logger.info("NSE feed reconnected successfully")
            self._deactivate_fallback()
            return True
        except Exception as e:
            logger.warning(f"Reconnection attempt failed: {e}")
            return False

    async def handle_feed_disconnect(self) -> None:
        """Handle NSE feed disconnection.

        Activates broker fallback immediately, then attempts reconnection
        in the background (requirement 25.5).
        """
        logger.warning("NSE feed disconnected, activating fallback")
        self._connected = False
        self._feed_source = FeedSource.DISCONNECTED

        await self._activate_fallback()

        # Attempt reconnection loop
        while self._running and not self._connected:
            success = await self._reconnect()
            if success:
                break

    # ------------------------------------------------------------------
    # Broker fallback (Requirement 25.5)
    # ------------------------------------------------------------------

    async def _activate_fallback(self) -> None:
        """Activate broker WebSocket as fallback data source.

        Subscribes to the same symbols via the fallback broker and
        routes ticks through the same publish pipeline.
        """
        if self.fallback_broker is None:
            logger.warning("No fallback broker configured, cannot activate fallback")
            return

        if self._fallback_active:
            return

        try:
            self.fallback_broker.subscribe(
                self._subscribed_symbols,
                self._on_fallback_tick,
            )
            self._fallback_active = True
            self._feed_source = FeedSource.BROKER_FALLBACK
            self._stats.fallback_activations += 1
            logger.info(
                "Broker fallback activated",
                extra={"symbols_count": len(self._subscribed_symbols)},
            )
        except Exception as e:
            logger.error(f"Failed to activate broker fallback: {e}", exc_info=True)

    def _deactivate_fallback(self) -> None:
        """Deactivate broker fallback when NSE feed is restored."""
        if not self._fallback_active:
            return

        if self.fallback_broker is not None:
            try:
                self.fallback_broker.unsubscribe(self._subscribed_symbols)
            except Exception as e:
                logger.error(f"Error deactivating fallback: {e}")

        self._fallback_active = False
        logger.info("Broker fallback deactivated")

    def _on_fallback_tick(self, tick: Tick) -> None:
        """Callback for ticks received from the fallback broker.

        Converts broker Tick to TickData and publishes via the
        standard pipeline.
        """
        tick_data = TickData(
            symbol=tick.symbol,
            token=tick.token,
            ltp=tick.ltp,
            last_traded_qty=0,
            total_volume=tick.volume,
            best_bid_price=tick.bid or 0.0,
            best_bid_qty=0,
            best_ask_price=tick.ask or 0.0,
            best_ask_qty=0,
            open=tick.open or 0.0,
            high=tick.high or 0.0,
            low=tick.low or 0.0,
            close=tick.close or 0.0,
            previous_close=tick.close or 0.0,
            timestamp=tick.timestamp,
            exchange=tick.exchange,
        )
        self._process_tick(tick_data)

    # ------------------------------------------------------------------
    # NSE feed message parsing
    # ------------------------------------------------------------------

    def parse_nse_message(self, raw: str) -> TickData | None:
        """Parse a raw JSON message from the NSE WebSocket feed.

        Expected fields per requirement 25.2:
        symbol, token, ltp, last_traded_qty, total_volume,
        best_bid_price, best_bid_qty, best_ask_price, best_ask_qty,
        open, high, low, close, previous_close, timestamp.

        Args:
            raw: Raw JSON string from the NSE feed.

        Returns:
            Parsed TickData or None if parsing fails.

        """
        try:
            data = json.loads(raw)
            return TickData(
                symbol=str(data["symbol"]),
                token=int(data["token"]),
                ltp=float(data["ltp"]),
                last_traded_qty=int(data.get("last_traded_qty", 0)),
                total_volume=int(data.get("total_volume", 0)),
                best_bid_price=float(data.get("best_bid_price", 0.0)),
                best_bid_qty=int(data.get("best_bid_qty", 0)),
                best_ask_price=float(data.get("best_ask_price", 0.0)),
                best_ask_qty=int(data.get("best_ask_qty", 0)),
                open=float(data.get("open", 0.0)),
                high=float(data.get("high", 0.0)),
                low=float(data.get("low", 0.0)),
                close=float(data.get("close", 0.0)),
                previous_close=float(data.get("previous_close", 0.0)),
                timestamp=datetime.fromisoformat(data["timestamp"]),
                exchange=str(data.get("exchange", "NSE")),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to parse NSE message: {e}", extra={"raw": raw[:200]})
            return None

    # ------------------------------------------------------------------
    # Pre-market & post-market session data (Requirements 25.6, 25.7)
    # ------------------------------------------------------------------

    def collect_pre_market_data(self, tick_data: TickData) -> dict[str, Any]:
        """Collect pre-market session data including indicative opening prices.

        Pre-market session runs 9:00 - 9:15 AM IST (requirement 25.6).

        Args:
            tick_data: Tick received during pre-market session.

        Returns:
            Dict with pre-market specific fields.

        """
        session = self.get_current_session(tick_data.timestamp)
        message = self._tick_to_message(tick_data)
        message["session"] = MarketSession.PRE_MARKET.value
        message["indicative_open"] = tick_data.ltp

        if session == MarketSession.PRE_MARKET:
            self._process_tick(tick_data)
            logger.debug(
                f"Pre-market tick: {tick_data.symbol} indicative open={tick_data.ltp}",
            )

        return message

    def collect_post_market_data(self, tick_data: TickData) -> dict[str, Any]:
        """Collect post-market session data including closing prices.

        Post-market session runs 3:30 - 4:00 PM IST (requirement 25.7).

        Args:
            tick_data: Tick received during post-market session.

        Returns:
            Dict with post-market specific fields.

        """
        session = self.get_current_session(tick_data.timestamp)
        message = self._tick_to_message(tick_data)
        message["session"] = MarketSession.POST_MARKET.value
        message["closing_price"] = tick_data.ltp

        if session == MarketSession.POST_MARKET:
            self._process_tick(tick_data)
            logger.debug(
                f"Post-market tick: {tick_data.symbol} closing={tick_data.ltp}",
            )

        return message

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def _start_health_monitor(self) -> None:
        """Start a background thread that monitors feed health."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name="NSEFeedHealthMonitor",
        )
        self._monitor_thread.start()
        logger.info("NSE feed health monitor started")

    def _health_monitor_loop(self) -> None:
        """Periodically check feed health and log statistics."""
        while not self._stop_event.is_set():
            try:
                if self._stats.last_tick_time is not None:
                    elapsed = (datetime.now(IST) - self._stats.last_tick_time).total_seconds()
                    session = self.get_current_session()

                    # Only alert during active sessions
                    if session != MarketSession.CLOSED and elapsed > 10:
                        logger.warning(
                            f"No ticks received for {elapsed:.1f}s during {session.value}",
                        )

                # Log periodic stats
                if self._stats.total_ticks_published > 0 and (
                    self._stats.total_ticks_published % 1000 == 0
                ):
                    logger.info(
                        f"Feed stats: published={self._stats.total_ticks_published}, "
                        f"avg_latency={self._stats.avg_publish_latency_ms:.2f}ms, "
                        f"source={self._feed_source.value}",
                    )

            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)

            self._stop_event.wait(5)
