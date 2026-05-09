"""Integration tests for Redis and Event Bus (requires running Redis)."""

import pytest

from src.state.event_bus import EventBus
from src.state.redis_client import RedisClient


@pytest.mark.integration
class TestRedisIntegration:
    """Integration tests that require a running Redis instance."""

    @pytest.fixture
    def redis_client(self):
        """Create and connect Redis client."""
        client = RedisClient(host="localhost", port=6379, db=0)
        try:
            client.connect()
            yield client
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
        finally:
            if client._client:
                client.disconnect()

    @pytest.fixture
    def event_bus(self, redis_client):
        """Create Event Bus with connected Redis client."""
        return EventBus(redis_client)

    def test_redis_connection(self, redis_client):
        """Test Redis connection."""
        assert redis_client.ping() is True

    def test_publish_and_consume(self, event_bus):
        """Test publishing and consuming messages."""
        stream_name = "test:stream:integration"
        group_name = "test_group"
        consumer_name = "test_consumer"

        # Create consumer group
        event_bus.create_consumer_group(stream_name, group_name, start_id="0")

        # Publish messages
        message_id1 = event_bus.publish(
            stream_name,
            {"symbol": "TEST", "price": 100.0, "volume": 1000},
            maxlen=1000,
        )
        message_id2 = event_bus.publish(
            stream_name,
            {"symbol": "TEST", "price": 101.0, "volume": 1500},
            maxlen=1000,
        )

        assert message_id1 is not None
        assert message_id2 is not None

        # Consume messages
        messages = event_bus.consume(
            stream_name,
            group_name,
            consumer_name,
            count=10,
            block=1000,
        )

        assert len(messages) == 2
        assert messages[0]["data"]["symbol"] == "TEST"
        assert float(messages[0]["data"]["price"]) == 100.0
        assert messages[1]["data"]["symbol"] == "TEST"
        assert float(messages[1]["data"]["price"]) == 101.0

        # Acknowledge messages
        ack_count = event_bus.acknowledge(
            stream_name,
            group_name,
            messages[0]["message_id"],
            messages[1]["message_id"],
        )

        assert ack_count == 2

    def test_consume_and_process(self, event_bus):
        """Test consume and process with callback."""
        stream_name = "test:stream:process"
        group_name = "test_group"
        consumer_name = "test_consumer"

        # Create consumer group
        event_bus.create_consumer_group(stream_name, group_name, start_id="0")

        # Publish messages
        event_bus.publish(stream_name, {"value": "message1"})
        event_bus.publish(stream_name, {"value": "message2"})
        event_bus.publish(stream_name, {"value": "message3"})

        # Process messages
        processed = []

        def processor(message):
            processed.append(message["data"]["value"])

        count = event_bus.consume_and_process(
            stream_name,
            group_name,
            consumer_name,
            processor,
            count=10,
            auto_ack=True,
        )

        assert count == 3
        assert processed == ["message1", "message2", "message3"]

    def test_complex_message_serialization(self, event_bus):
        """Test publishing and consuming complex messages."""
        stream_name = "test:stream:complex"
        group_name = "test_group"
        consumer_name = "test_consumer"

        # Create consumer group
        event_bus.create_consumer_group(stream_name, group_name, start_id="0")

        # Publish complex message
        complex_message = {
            "string": "value",
            "number": 123,
            "float": 123.45,
            "dict": {"nested": "value", "count": 42},
            "list": [1, 2, 3, 4, 5],
            "bool": True,
        }

        message_id = event_bus.publish(stream_name, complex_message)
        assert message_id is not None

        # Consume and verify
        messages = event_bus.consume(
            stream_name,
            group_name,
            consumer_name,
            count=1,
        )

        assert len(messages) == 1
        data = messages[0]["data"]

        assert data["string"] == "value"
        assert int(data["number"]) == 123
        assert float(data["float"]) == 123.45
        assert data["dict"] == {"nested": "value", "count": 42}
        assert data["list"] == [1, 2, 3, 4, 5]
        assert data["bool"] == "True"
