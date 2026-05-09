"""Redis client wrapper with automatic reconnection and health checks."""

import logging
import time
from typing import Any, Dict, Optional

import redis
from redis.exceptions import ConnectionError, RedisError, TimeoutError


logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redis client wrapper with connection management and automatic reconnection.
    
    Provides methods for:
    - Connection management with automatic reconnection
    - Stream publishing and consuming
    - Health checks (ping)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        max_retries: int = 5,
        retry_delay: float = 1.0,
        socket_timeout: float = 5.0,
        socket_connect_timeout: float = 5.0,
    ):
        """
        Initialize Redis client with connection parameters.
        
        Args:
            host: Redis server host
            port: Redis server port
            db: Redis database number
            max_retries: Maximum number of connection retry attempts
            retry_delay: Initial delay between retries (exponential backoff)
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Socket connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.db = db
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        
        self._client: Optional[redis.Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
        
    def connect(self) -> None:
        """
        Establish connection to Redis server with automatic retry.
        
        Raises:
            ConnectionError: If connection fails after all retry attempts
        """
        retry_count = 0
        current_delay = self.retry_delay
        
        while retry_count < self.max_retries:
            try:
                # Create connection pool
                self._connection_pool = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout,
                    decode_responses=True,
                    max_connections=50,
                )
                
                # Create Redis client
                self._client = redis.Redis(connection_pool=self._connection_pool)
                
                # Test connection
                self._client.ping()
                
                logger.info(
                    f"Successfully connected to Redis at {self.host}:{self.port} (db={self.db})"
                )
                return
                
            except (ConnectionError, TimeoutError) as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    logger.error(
                        f"Failed to connect to Redis after {self.max_retries} attempts: {e}"
                    )
                    raise ConnectionError(
                        f"Could not connect to Redis at {self.host}:{self.port}"
                    ) from e
                
                logger.warning(
                    f"Redis connection attempt {retry_count}/{self.max_retries} failed. "
                    f"Retrying in {current_delay}s..."
                )
                time.sleep(current_delay)
                current_delay *= 2  # Exponential backoff
                
    def disconnect(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self._client:
            try:
                self._client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
            finally:
                self._client = None
                
        if self._connection_pool:
            try:
                self._connection_pool.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting connection pool: {e}")
            finally:
                self._connection_pool = None
                
    def ping(self) -> bool:
        """
        Health check - ping Redis server.
        
        Returns:
            True if Redis is reachable, False otherwise
        """
        if not self._client:
            return False
            
        try:
            return self._client.ping()
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.warning(f"Redis ping failed: {e}")
            return False
            
    def _ensure_connected(self) -> None:
        """
        Ensure Redis connection is active, reconnect if necessary.
        
        Raises:
            ConnectionError: If reconnection fails
        """
        if not self._client or not self.ping():
            logger.warning("Redis connection lost, attempting to reconnect...")
            self.connect()
            
    def xadd(
        self,
        stream_name: str,
        fields: Dict[str, Any],
        maxlen: Optional[int] = None,
        approximate: bool = True,
    ) -> str:
        """
        Add message to Redis Stream.
        
        Args:
            stream_name: Name of the stream
            fields: Dictionary of field-value pairs to add
            maxlen: Maximum stream length (circular buffer)
            approximate: Use approximate trimming (~) for better performance
            
        Returns:
            Message ID
            
        Raises:
            RedisError: If operation fails
        """
        self._ensure_connected()
        
        try:
            message_id = self._client.xadd(
                name=stream_name,
                fields=fields,
                maxlen=maxlen,
                approximate=approximate,
            )
            return message_id
        except RedisError as e:
            logger.error(f"Failed to add message to stream {stream_name}: {e}")
            raise
            
    def xread(
        self,
        streams: Dict[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> list:
        """
        Read messages from Redis Streams.
        
        Args:
            streams: Dictionary mapping stream names to message IDs (use '>' for new messages)
            count: Maximum number of messages to read
            block: Block for specified milliseconds (None = non-blocking)
            
        Returns:
            List of messages from streams
            
        Raises:
            RedisError: If operation fails
        """
        self._ensure_connected()
        
        try:
            return self._client.xread(streams=streams, count=count, block=block)
        except RedisError as e:
            logger.error(f"Failed to read from streams: {e}")
            raise
            
    def xgroup_create(
        self,
        stream_name: str,
        group_name: str,
        id: str = "0",
        mkstream: bool = True,
    ) -> bool:
        """
        Create consumer group for a stream.
        
        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            id: Starting message ID ('0' = from beginning, '$' = from end)
            mkstream: Create stream if it doesn't exist
            
        Returns:
            True if group created successfully
            
        Raises:
            RedisError: If operation fails (except BUSYGROUP error)
        """
        self._ensure_connected()
        
        try:
            self._client.xgroup_create(
                name=stream_name,
                groupname=group_name,
                id=id,
                mkstream=mkstream,
            )
            logger.info(f"Created consumer group '{group_name}' for stream '{stream_name}'")
            return True
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, this is fine
                logger.debug(f"Consumer group '{group_name}' already exists for '{stream_name}'")
                return True
            logger.error(f"Failed to create consumer group: {e}")
            raise
        except RedisError as e:
            logger.error(f"Failed to create consumer group: {e}")
            raise
            
    def xreadgroup(
        self,
        group_name: str,
        consumer_name: str,
        streams: Dict[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> list:
        """
        Read messages from streams as part of a consumer group.
        
        Args:
            group_name: Name of the consumer group
            consumer_name: Name of this consumer
            streams: Dictionary mapping stream names to message IDs (use '>' for new messages)
            count: Maximum number of messages to read
            block: Block for specified milliseconds (None = non-blocking)
            
        Returns:
            List of messages from streams
            
        Raises:
            RedisError: If operation fails
        """
        self._ensure_connected()
        
        try:
            return self._client.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams=streams,
                count=count,
                block=block,
            )
        except RedisError as e:
            logger.error(f"Failed to read from consumer group: {e}")
            raise
            
    def xack(self, stream_name: str, group_name: str, *message_ids: str) -> int:
        """
        Acknowledge messages in a consumer group.
        
        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            message_ids: Message IDs to acknowledge
            
        Returns:
            Number of messages acknowledged
            
        Raises:
            RedisError: If operation fails
        """
        self._ensure_connected()
        
        try:
            return self._client.xack(stream_name, group_name, *message_ids)
        except RedisError as e:
            logger.error(f"Failed to acknowledge messages: {e}")
            raise
            
    def get(self, key: str) -> Optional[str]:
        """
        Get value for a key.
        
        Args:
            key: Redis key
            
        Returns:
            Value or None if key doesn't exist
        """
        self._ensure_connected()
        
        try:
            return self._client.get(key)
        except RedisError as e:
            logger.error(f"Failed to get key {key}: {e}")
            raise
            
    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """
        Set key to value with optional expiration.
        
        Args:
            key: Redis key
            value: Value to set
            ex: Expiration in seconds
            px: Expiration in milliseconds
            nx: Only set if key doesn't exist
            xx: Only set if key exists
            
        Returns:
            True if set successfully
        """
        self._ensure_connected()
        
        try:
            return self._client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
        except RedisError as e:
            logger.error(f"Failed to set key {key}: {e}")
            raise
            
    def delete(self, *keys: str) -> int:
        """
        Delete one or more keys.
        
        Args:
            keys: Keys to delete
            
        Returns:
            Number of keys deleted
        """
        self._ensure_connected()
        
        try:
            return self._client.delete(*keys)
        except RedisError as e:
            logger.error(f"Failed to delete keys: {e}")
            raise
            
    def sadd(self, key: str, *values: Any) -> int:
        """
        Add members to a set.
        
        Args:
            key: Set key
            values: Values to add
            
        Returns:
            Number of elements added
        """
        self._ensure_connected()
        
        try:
            return self._client.sadd(key, *values)
        except RedisError as e:
            logger.error(f"Failed to add to set {key}: {e}")
            raise
            
    def sismember(self, key: str, value: Any) -> bool:
        """
        Check if value is member of set.
        
        Args:
            key: Set key
            value: Value to check
            
        Returns:
            True if value is in set
        """
        self._ensure_connected()
        
        try:
            return self._client.sismember(key, value)
        except RedisError as e:
            logger.error(f"Failed to check set membership: {e}")
            raise
            
    def expire(self, key: str, seconds: int) -> bool:
        """
        Set expiration on a key.
        
        Args:
            key: Redis key
            seconds: Expiration time in seconds
            
        Returns:
            True if expiration was set
        """
        self._ensure_connected()
        
        try:
            return self._client.expire(key, seconds)
        except RedisError as e:
            logger.error(f"Failed to set expiration on key {key}: {e}")
            raise

    def hset(self, key: str, mapping: Dict[str, Any]) -> int:
        """
        Set multiple fields in a hash.

        Args:
            key: Hash key
            mapping: Dictionary of field-value pairs

        Returns:
            Number of fields added (not updated)
        """
        self._ensure_connected()

        try:
            return self._client.hset(key, mapping=mapping)
        except RedisError as e:
            logger.error(f"Failed to hset key {key}: {e}")
            raise

    def hgetall(self, key: str) -> Dict[str, str]:
        """
        Get all fields and values of a hash.

        Args:
            key: Hash key

        Returns:
            Dictionary of field-value pairs (empty dict if key doesn't exist)
        """
        self._ensure_connected()

        try:
            return self._client.hgetall(key)
        except RedisError as e:
            logger.error(f"Failed to hgetall key {key}: {e}")
            raise
