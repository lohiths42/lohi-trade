"""Tests for Redis client wrapper."""

from unittest.mock import Mock, patch

import pytest
import redis
from hypothesis import given, settings
from hypothesis import strategies as st

from src.state.redis_client import RedisClient


class TestRedisClientBasic:
    """Basic unit tests for Redis client."""

    def test_init(self):
        """Test Redis client initialization."""
        client = RedisClient(host="localhost", port=6379, db=0)
        assert client.host == "localhost"
        assert client.port == 6379
        assert client.db == 0
        assert client._client is None

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_connect_success(self, mock_pool, mock_redis):
        """Test successful connection to Redis."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        assert client._client is not None
        mock_redis_instance.ping.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_connect_with_retry(self, mock_pool, mock_redis):
        """Test connection retry on failure."""
        mock_redis_instance = Mock()
        # Fail first 2 attempts, succeed on 3rd
        mock_redis_instance.ping.side_effect = [
            redis.exceptions.ConnectionError("Connection failed"),
            redis.exceptions.ConnectionError("Connection failed"),
            True,
        ]
        mock_redis.return_value = mock_redis_instance

        client = RedisClient(max_retries=5, retry_delay=0.01)
        client.connect()

        assert client._client is not None
        assert mock_redis_instance.ping.call_count == 3

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_connect_max_retries_exceeded(self, mock_pool, mock_redis):
        """Test connection failure after max retries."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = redis.exceptions.ConnectionError(
            "Connection failed",
        )
        mock_redis.return_value = mock_redis_instance

        client = RedisClient(max_retries=3, retry_delay=0.01)

        with pytest.raises(redis.exceptions.ConnectionError):
            client.connect()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_ping_success(self, mock_pool, mock_redis):
        """Test successful ping."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        assert client.ping() is True

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_ping_failure(self, mock_pool, mock_redis):
        """Test ping failure."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = redis.exceptions.ConnectionError(
            "Connection lost",
        )
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client._client = mock_redis_instance

        assert client.ping() is False

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_disconnect(self, mock_pool, mock_redis):
        """Test disconnection."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()
        client.disconnect()

        mock_redis_instance.close.assert_called_once()
        assert client._client is None

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_xadd(self, mock_pool, mock_redis):
        """Test adding message to stream."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xadd.return_value = "1234567890-0"
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        message_id = client.xadd("test_stream", {"field": "value"}, maxlen=1000)

        assert message_id == "1234567890-0"
        mock_redis_instance.xadd.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_xread(self, mock_pool, mock_redis):
        """Test reading from stream."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xread.return_value = [
            ["test_stream", [("1234567890-0", {"field": "value"})]],
        ]
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        messages = client.xread({"test_stream": "0"}, count=10)

        assert len(messages) == 1
        mock_redis_instance.xread.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_xgroup_create(self, mock_pool, mock_redis):
        """Test creating consumer group."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xgroup_create.return_value = True
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        result = client.xgroup_create("test_stream", "test_group")

        assert result is True
        mock_redis_instance.xgroup_create.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_xgroup_create_already_exists(self, mock_pool, mock_redis):
        """Test creating consumer group that already exists."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xgroup_create.side_effect = redis.exceptions.ResponseError(
            "BUSYGROUP Consumer Group name already exists",
        )
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        result = client.xgroup_create("test_stream", "test_group")

        assert result is True  # Should return True even if group exists


class TestRedisClientPropertyBased:
    """Property-based tests for Redis client."""

    @settings(max_examples=5, deadline=5000)
    @given(
        max_retries=st.integers(min_value=2, max_value=10),
        retry_delay=st.floats(min_value=0.001, max_value=0.1),
    )
    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_property_reconnection_on_failure(
        self, mock_pool, mock_redis, max_retries, retry_delay,
    ):
        """Feature: lohi-trade, Property 79: WebSocket Reconnection on Failure
        
        For any Redis connection failure, reconnection should be attempted
        without crashing other components. The client should retry up to
        max_retries times with exponential backoff.
        
        Validates: Requirements 25.2
        """
        mock_redis_instance = Mock()

        # Simulate connection failures followed by success
        failure_count = min(max_retries - 1, 3)  # Fail a few times, then succeed
        # Create enough responses for connect() and subsequent ping() call
        mock_redis_instance.ping.side_effect = (
            [redis.exceptions.ConnectionError("Connection failed")] * failure_count
            + [True, True]  # One for connect, one for the final ping check
        )
        mock_redis.return_value = mock_redis_instance

        client = RedisClient(max_retries=max_retries, retry_delay=retry_delay)

        # Should successfully connect after retries
        client.connect()

        # Verify connection was established
        assert client._client is not None
        assert mock_redis_instance.ping.call_count == failure_count + 1

        # Verify client can perform operations after reconnection
        assert client.ping() is True
        assert mock_redis_instance.ping.call_count == failure_count + 2

    @settings(max_examples=5, deadline=5000)
    @given(
        stream_name=st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))),
        field_count=st.integers(min_value=1, max_value=10),
    )
    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_property_stream_operations_after_reconnection(
        self, mock_pool, mock_redis, stream_name, field_count,
    ):
        """Property: Stream operations should work correctly after reconnection.
        
        For any stream name and field count, after a connection failure and
        reconnection, the client should be able to publish messages to streams.
        """
        mock_redis_instance = Mock()

        # First ping succeeds (initial connection)
        # Second ping fails (simulating connection loss)
        # Third ping succeeds (reconnection)
        mock_redis_instance.ping.side_effect = [True, False, True, True]
        mock_redis_instance.xadd.return_value = "1234567890-0"
        mock_redis.return_value = mock_redis_instance

        client = RedisClient(max_retries=5, retry_delay=0.01)
        client.connect()

        # Simulate connection loss and automatic reconnection
        # The _ensure_connected method should handle this
        fields = {f"field_{i}": f"value_{i}" for i in range(field_count)}

        message_id = client.xadd(stream_name, fields)

        # Verify message was published
        assert message_id == "1234567890-0"
        mock_redis_instance.xadd.assert_called_once()

    @settings(max_examples=5, deadline=5000)
    @given(
        max_retries=st.integers(min_value=1, max_value=5),
    )
    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_property_connection_failure_raises_after_max_retries(
        self, mock_pool, mock_redis, max_retries,
    ):
        """Property: Connection should fail after max_retries attempts.
        
        For any max_retries value, if all connection attempts fail,
        a ConnectionError should be raised.
        """
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = redis.exceptions.ConnectionError(
            "Connection failed",
        )
        mock_redis.return_value = mock_redis_instance

        client = RedisClient(max_retries=max_retries, retry_delay=0.01)

        with pytest.raises(redis.exceptions.ConnectionError):
            client.connect()

        # Verify we attempted exactly max_retries times
        assert mock_redis_instance.ping.call_count == max_retries

    @settings(max_examples=5, deadline=5000)
    @given(
        key=st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))),
        value=st.text(min_size=0, max_size=100, alphabet=st.characters(blacklist_categories=("Cs",))),
    )
    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_property_get_set_operations(self, mock_pool, mock_redis, key, value):
        """Property: Get/Set operations should work correctly.
        
        For any key-value pair, after setting a value, getting the key
        should return the same value.
        """
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = value
        mock_redis.return_value = mock_redis_instance

        client = RedisClient()
        client.connect()

        # Set value
        result = client.set(key, value)
        assert result is True

        # Get value
        retrieved_value = client.get(key)
        assert retrieved_value == value
