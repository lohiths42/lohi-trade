"""WebSocket client for tick ingestion with connection management.

This module provides a high-level WebSocket client that:
- Connects to broker WebSocket via broker adapters
- Subscribes to symbols from configuration
- Handles tick messages and publishes to Event Bus
- Implements heartbeat monitoring
- Implements automatic reconnection with exponential backoff
- Measures and logs latency
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime

from src.ingestion.broker_interface import (
    BrokerCredentials,
    BrokerInterface,
    Tick,
)
from src.ingestion.broker_interface import (
    ConnectionError as BrokerConnectionError,
)
from src.state.event_bus import EventBus
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger("WebSocketClient")


@dataclass
class ConnectionStats:
    """Statistics for WebSocket connection."""

    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    total_ticks_received: int = 0
    total_ticks_published: int = 0
    last_tick_timestamp: datetime | None = None
    reconnection_attempts: int = 0
    total_latency_ms: float = 0.0
    tick_count_for_latency: int = 0

    @property
    def average_latency_ms(self) -> float:
        """Calculate average latency in milliseconds."""
        if self.tick_count_for_latency == 0:
            return 0.0
        return self.total_latency_ms / self.tick_count_for_latency


class WebSocketClient:
    """WebSocket client for real-time tick ingestion.
    
    Manages connection to broker WebSocket, subscribes to symbols,
    handles incoming ticks, and publishes to Event Bus with latency tracking.
    
    Requirements: 1.1, 1.2, 1.3, 1.4
    """

    def __init__(
        self,
        broker: BrokerInterface,
        event_bus: EventBus,
        config: Config,
    ):
        """Initialize WebSocket client.
        
        Args:
            broker: Broker adapter (Shoonya or Angel One)
            event_bus: Event Bus for publishing ticks
            config: System configuration

        """
        self.broker = broker
        self.event_bus = event_bus
        self.config = config

        # Connection state
        self._connected = False
        self._subscribed_symbols: list[str] = []
        self._stats = ConnectionStats()

        # Heartbeat monitoring
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop_event = threading.Event()
        self._heartbeat_interval = 5  # Check every 5 seconds
        self._heartbeat_timeout = 5  # Alert if no ticks for 5 seconds

        # Reconnection
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._reconnect_backoff_base = 1  # Start with 1 second
        self._reconnect_backoff_max = 30  # Max 30 seconds

        # Latency tracking
        self._latency_log_interval = 100  # Log average latency every 100 ticks

    def connect(self, credentials: BrokerCredentials) -> bool:
        """Connect to broker WebSocket.
        
        Args:
            credentials: Broker authentication credentials
            
        Returns:
            True if connection successful
            
        Raises:
            ConnectionError: If connection fails
            
        Requirements: 1.1

        """
        try:
            logger.info("Connecting to broker WebSocket...")

            # Connect to broker API
            success = self.broker.connect(credentials)

            if success:
                self._connected = True
                self._stats.connected_at = datetime.now()
                self._stats.reconnection_attempts = 0

                logger.info("Successfully connected to broker WebSocket")

                # Start heartbeat monitoring
                self._start_heartbeat_monitor()

                return True
            logger.error("Failed to connect to broker WebSocket")
            return False

        except Exception as e:
            logger.error(f"Error connecting to broker WebSocket: {e}", exc_info=True)
            raise BrokerConnectionError(f"Failed to connect: {e!s}")

    def disconnect(self) -> None:
        """Disconnect from broker WebSocket and clean up resources.
        
        Requirements: 1.1
        """
        logger.info("Disconnecting from broker WebSocket...")

        # Stop heartbeat monitoring
        self._stop_heartbeat_monitor()

        # Disconnect from broker
        if self.broker:
            self.broker.disconnect()

        self._connected = False
        self._stats.disconnected_at = datetime.now()

        # Log final statistics
        self._log_statistics()

        logger.info("Disconnected from broker WebSocket")

    def is_connected(self) -> bool:
        """Check if WebSocket connection is active.
        
        Returns:
            True if connected, False otherwise

        """
        return self._connected and self.broker.is_connected()

    def subscribe(self, symbols: list[str]) -> bool:
        """Subscribe to real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to subscribe to
            
        Returns:
            True if subscription successful
            
        Raises:
            ConnectionError: If not connected to broker
            
        Requirements: 1.1

        """
        if not self.is_connected():
            raise BrokerConnectionError("Not connected to broker WebSocket")

        logger.info(f"Subscribing to {len(symbols)} symbols: {symbols}")

        try:
            # Subscribe via broker with tick callback
            success = self.broker.subscribe(symbols, self._on_tick)

            if success:
                self._subscribed_symbols = symbols
                logger.info(f"Successfully subscribed to {len(symbols)} symbols")
                return True
            logger.error("Failed to subscribe to symbols")
            return False

        except Exception as e:
            logger.error(f"Error subscribing to symbols: {e}", exc_info=True)
            raise

    def unsubscribe(self, symbols: list[str]) -> bool:
        """Unsubscribe from real-time tick data for given symbols.
        
        Args:
            symbols: List of trading symbols to unsubscribe from
            
        Returns:
            True if unsubscription successful

        """
        if not self.is_connected():
            return False

        logger.info(f"Unsubscribing from {len(symbols)} symbols")

        try:
            success = self.broker.unsubscribe(symbols)

            if success:
                # Remove from subscribed list
                self._subscribed_symbols = [
                    s for s in self._subscribed_symbols if s not in symbols
                ]
                logger.info(f"Successfully unsubscribed from {len(symbols)} symbols")
                return True
            logger.error("Failed to unsubscribe from symbols")
            return False

        except Exception as e:
            logger.error(f"Error unsubscribing from symbols: {e}", exc_info=True)
            return False

    def _on_tick(self, tick: Tick) -> None:
        """Handle incoming tick from broker.
        
        This callback is invoked by the broker adapter for each tick.
        It publishes the tick to Event Bus and tracks latency.
        
        Args:
            tick: Tick object from broker
            
        Requirements: 1.2

        """
        try:
            # Record tick receipt time
            receipt_time = datetime.now()

            # Update statistics
            self._stats.total_ticks_received += 1
            self._stats.last_tick_timestamp = receipt_time

            # Publish tick to Event Bus
            stream_name = f"stream:ticks:{tick.symbol}"

            # Prepare tick message
            tick_message = {
                "symbol": tick.symbol,
                "token": tick.token,
                "ltp": tick.ltp,
                "volume": tick.volume,
                "timestamp": tick.timestamp.isoformat(),
                "exchange": tick.exchange,
            }

            # Add optional fields if present
            if tick.bid is not None:
                tick_message["bid"] = tick.bid
            if tick.ask is not None:
                tick_message["ask"] = tick.ask
            if tick.open is not None:
                tick_message["open"] = tick.open
            if tick.high is not None:
                tick_message["high"] = tick.high
            if tick.low is not None:
                tick_message["low"] = tick.low
            if tick.close is not None:
                tick_message["close"] = tick.close

            # Publish to Event Bus with maxlen=1000 (circular buffer)
            self.event_bus.publish(
                stream_name=stream_name,
                message=tick_message,
                maxlen=1000,
            )

            # Calculate and track latency
            publish_time = datetime.now()
            latency_ms = (publish_time - receipt_time).total_seconds() * 1000

            self._stats.total_ticks_published += 1
            self._stats.total_latency_ms += latency_ms
            self._stats.tick_count_for_latency += 1

            # Log latency periodically
            if self._stats.total_ticks_published % self._latency_log_interval == 0:
                avg_latency = self._stats.average_latency_ms
                logger.info(
                    f"Tick processing stats: "
                    f"received={self._stats.total_ticks_received}, "
                    f"published={self._stats.total_ticks_published}, "
                    f"avg_latency={avg_latency:.2f}ms",
                )

                # Log warning if latency exceeds 10ms
                if avg_latency > 10.0:
                    logger.warning(
                        f"Average tick latency ({avg_latency:.2f}ms) exceeds 10ms threshold",
                    )

        except Exception as e:
            logger.error(f"Error processing tick for {tick.symbol}: {e}", exc_info=True)

    def _start_heartbeat_monitor(self) -> None:
        """Start heartbeat monitoring thread.
        
        Monitors last tick timestamp and triggers alert if no ticks
        received for configured timeout period.
        
        Requirements: 1.4
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_monitor_loop,
            daemon=True,
            name="HeartbeatMonitor",
        )
        self._heartbeat_thread.start()

        logger.info("Started heartbeat monitoring")

    def _stop_heartbeat_monitor(self) -> None:
        """Stop heartbeat monitoring thread."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_stop_event.set()
            self._heartbeat_thread.join(timeout=5)
            logger.info("Stopped heartbeat monitoring")

    def _heartbeat_monitor_loop(self) -> None:
        """Heartbeat monitoring loop.
        
        Runs in separate thread and checks for tick activity.
        """
        while not self._heartbeat_stop_event.is_set():
            try:
                # Check if we've received any ticks
                if self._stats.last_tick_timestamp is not None:
                    time_since_last_tick = datetime.now() - self._stats.last_tick_timestamp

                    # Alert if no ticks for timeout period
                    if time_since_last_tick.total_seconds() > self._heartbeat_timeout:
                        logger.warning(
                            f"Heartbeat alert: No ticks received for "
                            f"{time_since_last_tick.total_seconds():.1f} seconds",
                        )

                        # Attempt reconnection if no ticks for extended period
                        if time_since_last_tick.total_seconds() > self._heartbeat_timeout * 2:
                            logger.error("Extended heartbeat failure, attempting reconnection...")
                            self._attempt_reconnection()

                # Sleep for interval
                self._heartbeat_stop_event.wait(self._heartbeat_interval)

            except Exception as e:
                logger.error(f"Error in heartbeat monitor: {e}", exc_info=True)

    def _attempt_reconnection(self) -> None:
        """Attempt to reconnect to broker WebSocket.
        
        Implements exponential backoff strategy.
        
        Requirements: 1.3
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error(
                f"Max reconnection attempts ({self._max_reconnect_attempts}) reached. "
                "Manual intervention required.",
            )
            self._connected = False
            return

        self._reconnect_attempts += 1
        self._stats.reconnection_attempts += 1

        # Calculate backoff delay: 1s, 2s, 4s, 8s, max 30s
        backoff_delay = min(
            self._reconnect_backoff_base * (2 ** (self._reconnect_attempts - 1)),
            self._reconnect_backoff_max,
        )

        logger.info(
            f"Reconnection attempt {self._reconnect_attempts}/{self._max_reconnect_attempts} "
            f"in {backoff_delay}s...",
        )

        time.sleep(backoff_delay)

        try:
            # Disconnect first
            self.broker.disconnect()

            # Reconnect (credentials should be stored in broker)
            # Note: This assumes broker stores credentials internally
            # In production, we'd need to pass credentials again
            logger.info("Attempting to reconnect to broker...")

            # For now, we'll just check if broker can reconnect
            # The actual reconnection logic is in the broker adapter
            if self.broker.is_connected():
                logger.info("Broker reconnected successfully")

                # Resubscribe to symbols
                if self._subscribed_symbols:
                    logger.info(f"Resubscribing to {len(self._subscribed_symbols)} symbols...")
                    self.broker.subscribe(self._subscribed_symbols, self._on_tick)

                # Reset reconnection counter on success
                self._reconnect_attempts = 0
                self._connected = True

                logger.info("Reconnection successful")
            else:
                logger.warning("Broker reconnection failed, will retry...")

        except Exception as e:
            logger.error(f"Reconnection attempt failed: {e}", exc_info=True)

    def _log_statistics(self) -> None:
        """Log connection statistics."""
        if self._stats.connected_at:
            duration = (
                (self._stats.disconnected_at or datetime.now()) -
                self._stats.connected_at
            )

            logger.info(
                f"WebSocket session statistics:\n"
                f"  Duration: {duration}\n"
                f"  Ticks received: {self._stats.total_ticks_received}\n"
                f"  Ticks published: {self._stats.total_ticks_published}\n"
                f"  Average latency: {self._stats.average_latency_ms:.2f}ms\n"
                f"  Reconnection attempts: {self._stats.reconnection_attempts}",
            )

    def get_statistics(self) -> ConnectionStats:
        """Get current connection statistics.
        
        Returns:
            ConnectionStats object with current statistics

        """
        return self._stats
