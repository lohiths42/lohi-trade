"""Tests for Event Bus abstraction."""

import json
from unittest.mock import Mock, patch

import pytest

from src.state.event_bus import EventBus
from src.state.redis_client import RedisClient


class TestEventBus:
    """Unit tests for Event Bus."""

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_publish_simple_message(self, mock_pool, mock_redis):
        """Test publishing a simple message."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xadd.return_value = "1234567890-0"
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        message_id = event_bus.publish(
            "stream:test",
            {"field1": "value1", "field2": "value2"},
            maxlen=1000,
        )

        assert message_id == "1234567890-0"
        mock_redis_instance.xadd.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_publish_complex_message(self, mock_pool, mock_redis):
        """Test publishing a message with complex types."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xadd.return_value = "1234567890-0"
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        message_id = event_bus.publish(
            "stream:test",
            {
                "string": "value",
                "number": 123,
                "float": 123.45,
                "dict": {"nested": "value"},
                "list": [1, 2, 3],
                "none": None,
            },
        )

        assert message_id == "1234567890-0"
        
        # Verify serialization
        call_args = mock_redis_instance.xadd.call_args
        fields = call_args[1]["fields"]
        
        assert fields["string"] == "value"
        assert fields["number"] == "123"
        assert fields["float"] == "123.45"
        assert json.loads(fields["dict"]) == {"nested": "value"}
        assert json.loads(fields["list"]) == [1, 2, 3]
        assert fields["none"] == ""

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_create_consumer_group(self, mock_pool, mock_redis):
        """Test creating a consumer group."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xgroup_create.return_value = True
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        result = event_bus.create_consumer_group(
            "stream:test",
            "test_group",
            start_id="$",
        )

        assert result is True
        mock_redis_instance.xgroup_create.assert_called_once()
        assert "test_group" in event_bus.get_consumer_groups("stream:test")

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_consume_messages(self, mock_pool, mock_redis):
        """Test consuming messages from a stream."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xreadgroup.return_value = [
            [
                "stream:test",
                [
                    ("1234567890-0", {"field1": "value1", "field2": "value2"}),
                    ("1234567891-0", {"field1": "value3", "field2": "value4"}),
                ],
            ]
        ]
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        messages = event_bus.consume(
            "stream:test",
            "test_group",
            "consumer1",
            count=10,
        )

        assert len(messages) == 2
        assert messages[0]["message_id"] == "1234567890-0"
        assert messages[0]["data"]["field1"] == "value1"
        assert messages[1]["message_id"] == "1234567891-0"
        assert messages[1]["data"]["field1"] == "value3"

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_consume_with_json_deserialization(self, mock_pool, mock_redis):
        """Test consuming messages with JSON deserialization."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xreadgroup.return_value = [
            [
                "stream:test",
                [
                    (
                        "1234567890-0",
                        {
                            "string": "value",
                            "dict": json.dumps({"nested": "value"}),
                            "list": json.dumps([1, 2, 3]),
                        },
                    ),
                ],
            ]
        ]
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        messages = event_bus.consume(
            "stream:test",
            "test_group",
            "consumer1",
        )

        assert len(messages) == 1
        data = messages[0]["data"]
        assert data["string"] == "value"
        assert data["dict"] == {"nested": "value"}
        assert data["list"] == [1, 2, 3]

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_acknowledge_messages(self, mock_pool, mock_redis):
        """Test acknowledging messages."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xack.return_value = 2
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        count = event_bus.acknowledge(
            "stream:test",
            "test_group",
            "1234567890-0",
            "1234567891-0",
        )

        assert count == 2
        mock_redis_instance.xack.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_consume_and_process(self, mock_pool, mock_redis):
        """Test consume and process with callback."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xreadgroup.return_value = [
            [
                "stream:test",
                [
                    ("1234567890-0", {"field": "value1"}),
                    ("1234567891-0", {"field": "value2"}),
                ],
            ]
        ]
        mock_redis_instance.xack.return_value = 2
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        processed_messages = []

        def processor(message):
            processed_messages.append(message["data"]["field"])

        count = event_bus.consume_and_process(
            "stream:test",
            "test_group",
            "consumer1",
            processor,
            count=10,
            auto_ack=True,
        )

        assert count == 2
        assert processed_messages == ["value1", "value2"]
        mock_redis_instance.xack.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_consume_and_process_with_error(self, mock_pool, mock_redis):
        """Test consume and process with processor error."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xreadgroup.return_value = [
            [
                "stream:test",
                [
                    ("1234567890-0", {"field": "value1"}),
                    ("1234567891-0", {"field": "value2"}),
                ],
            ]
        ]
        mock_redis_instance.xack.return_value = 1
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        processed_count = 0

        def processor(message):
            nonlocal processed_count
            if message["data"]["field"] == "value1":
                raise ValueError("Processing error")
            processed_count += 1

        count = event_bus.consume_and_process(
            "stream:test",
            "test_group",
            "consumer1",
            processor,
            auto_ack=True,
        )

        # Only one message processed successfully
        assert count == 1
        assert processed_count == 1
        # Only one message acknowledged
        mock_redis_instance.xack.assert_called_once()

    @patch("src.state.redis_client.redis.Redis")
    @patch("src.state.redis_client.redis.ConnectionPool")
    def test_read_latest(self, mock_pool, mock_redis):
        """Test reading latest messages without consumer group."""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.xread.return_value = [
            [
                "stream:test",
                [
                    ("1234567890-0", {"field": "latest_value"}),
                ],
            ]
        ]
        mock_redis.return_value = mock_redis_instance

        redis_client = RedisClient()
        redis_client.connect()
        event_bus = EventBus(redis_client)

        messages = event_bus.read_latest("stream:test", count=1)

        assert len(messages) == 1
        assert messages[0]["data"]["field"] == "latest_value"
        mock_redis_instance.xread.assert_called_once()
