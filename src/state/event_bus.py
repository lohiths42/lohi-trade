"""Event Bus abstraction for Redis Streams."""

import json
import logging
from collections.abc import Callable
from typing import Any

from src.state.redis_client import RedisClient

logger = logging.getLogger(__name__)


class EventBus:
    """Event Bus abstraction for Redis Streams.

    Provides high-level methods for:
    - Publishing messages to streams
    - Creating and managing consumer groups
    - Consuming messages from streams
    - Acknowledging processed messages
    """

    def __init__(self, redis_client: RedisClient):
        """Initialize Event Bus with Redis client.

        Args:
            redis_client: Connected Redis client instance

        """
        self.redis_client = redis_client
        self._consumer_groups: dict[str, set] = {}  # Track created consumer groups

    def publish(
        self,
        stream_name: str,
        message: dict[str, Any],
        maxlen: int | None = None,
    ) -> str:
        """Publish message to a stream.

        Args:
            stream_name: Name of the stream (e.g., "stream:ticks:RELIANCE")
            message: Dictionary of field-value pairs to publish
            maxlen: Maximum stream length (circular buffer), None for unlimited

        Returns:
            Message ID

        Raises:
            Exception: If publish fails

        Example:
            >>> event_bus.publish(
            ...     "stream:ticks:RELIANCE",
            ...     {"symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000}
            ... )
            '1234567890-0'

        """
        try:
            # Serialize complex values to JSON strings
            serialized_message = {}
            for key, value in message.items():
                if isinstance(value, (dict, list)):
                    serialized_message[key] = json.dumps(value)
                elif value is None:
                    serialized_message[key] = ""
                else:
                    serialized_message[key] = str(value)

            message_id = self.redis_client.xadd(
                stream_name=stream_name,
                fields=serialized_message,
                maxlen=maxlen,
                approximate=True,
            )

            logger.debug(f"Published message to {stream_name}: {message_id}")
            return message_id

        except Exception as e:
            logger.error(f"Failed to publish message to {stream_name}: {e}")
            raise

    def create_consumer_group(
        self,
        stream_name: str,
        group_name: str,
        start_id: str = "$",
    ) -> bool:
        """Create consumer group for a stream.

        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            start_id: Starting message ID:
                - '0' = read from beginning
                - '$' = read only new messages (default)
                - specific ID = read from that message

        Returns:
            True if group created or already exists

        Raises:
            Exception: If creation fails (except BUSYGROUP)

        Example:
            >>> event_bus.create_consumer_group(
            ...     "stream:ticks:RELIANCE",
            ...     "candle_builder_group",
            ...     start_id="$"
            ... )
            True

        """
        try:
            result = self.redis_client.xgroup_create(
                stream_name=stream_name,
                group_name=group_name,
                id=start_id,
                mkstream=True,
            )

            # Track created consumer groups
            if stream_name not in self._consumer_groups:
                self._consumer_groups[stream_name] = set()
            self._consumer_groups[stream_name].add(group_name)

            return result

        except Exception as e:
            logger.error(f"Failed to create consumer group {group_name} for {stream_name}: {e}")
            raise

    def consume(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int | None = None,
        block: int | None = None,
    ) -> list[dict[str, Any]]:
        """Consume messages from a stream as part of a consumer group.

        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            consumer_name: Name of this consumer (unique within group)
            count: Maximum number of messages to read
            block: Block for specified milliseconds (None = non-blocking)

        Returns:
            List of messages, each containing:
                - message_id: Redis message ID
                - stream: Stream name
                - data: Dictionary of message fields

        Raises:
            Exception: If consume fails

        Example:
            >>> messages = event_bus.consume(
            ...     "stream:ticks:RELIANCE",
            ...     "candle_builder_group",
            ...     "candle_builder_1",
            ...     count=10,
            ...     block=1000
            ... )
            >>> for msg in messages:
            ...     print(msg['message_id'], msg['data'])

        """
        try:
            # Read from consumer group
            result = self.redis_client.xreadgroup(
                group_name=group_name,
                consumer_name=consumer_name,
                streams={stream_name: ">"},  # '>' means only new messages
                count=count,
                block=block,
            )

            # Parse result into structured format
            messages = []
            if result:
                for stream_data in result:
                    stream = stream_data[0]
                    message_list = stream_data[1]

                    for message_id, fields in message_list:
                        # Deserialize JSON fields
                        deserialized_fields = {}
                        for key, value in fields.items():
                            try:
                                # Try to parse as JSON
                                deserialized_fields[key] = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                # Keep as string if not JSON
                                deserialized_fields[key] = value

                        messages.append(
                            {
                                "message_id": message_id,
                                "stream": stream,
                                "data": deserialized_fields,
                            }
                        )

            logger.debug(
                f"Consumed {len(messages)} messages from {stream_name} "
                f"(group={group_name}, consumer={consumer_name})",
            )
            return messages

        except Exception as e:
            logger.error(
                f"Failed to consume from {stream_name} "
                f"(group={group_name}, consumer={consumer_name}): {e}",
            )
            raise

    def acknowledge(
        self,
        stream_name: str,
        group_name: str,
        *message_ids: str,
    ) -> int:
        """Acknowledge messages in a consumer group.

        Messages must be acknowledged after processing to remove them
        from the pending entries list (PEL).

        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            message_ids: One or more message IDs to acknowledge

        Returns:
            Number of messages acknowledged

        Raises:
            Exception: If acknowledgment fails

        Example:
            >>> event_bus.acknowledge(
            ...     "stream:ticks:RELIANCE",
            ...     "candle_builder_group",
            ...     "1234567890-0",
            ...     "1234567891-0"
            ... )
            2

        """
        try:
            count = self.redis_client.xack(stream_name, group_name, *message_ids)
            logger.debug(
                f"Acknowledged {count} messages in {stream_name} (group={group_name})",
            )
            return count

        except Exception as e:
            logger.error(
                f"Failed to acknowledge messages in {stream_name} (group={group_name}): {e}",
            )
            raise

    def consume_and_process(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        processor: Callable[[dict[str, Any]], None],
        count: int | None = None,
        block: int | None = None,
        auto_ack: bool = True,
    ) -> int:
        """Consume messages and process them with a callback function.

        This is a convenience method that combines consume, process, and acknowledge.

        Args:
            stream_name: Name of the stream
            group_name: Name of the consumer group
            consumer_name: Name of this consumer
            processor: Callback function to process each message
            count: Maximum number of messages to read
            block: Block for specified milliseconds (None = non-blocking)
            auto_ack: Automatically acknowledge messages after successful processing

        Returns:
            Number of messages processed

        Raises:
            Exception: If consume or process fails

        Example:
            >>> def process_tick(message):
            ...     print(f"Processing tick: {message['data']}")
            ...
            >>> event_bus.consume_and_process(
            ...     "stream:ticks:RELIANCE",
            ...     "candle_builder_group",
            ...     "candle_builder_1",
            ...     process_tick,
            ...     count=10
            ... )
            10

        """
        try:
            # Consume messages
            messages = self.consume(
                stream_name=stream_name,
                group_name=group_name,
                consumer_name=consumer_name,
                count=count,
                block=block,
            )

            # Process each message
            processed_count = 0
            message_ids_to_ack = []

            for message in messages:
                try:
                    # Call processor callback
                    processor(message)
                    processed_count += 1

                    if auto_ack:
                        message_ids_to_ack.append(message["message_id"])

                except Exception as e:
                    logger.error(
                        f"Error processing message {message['message_id']} "
                        f"from {stream_name}: {e}",
                    )
                    # Continue processing other messages

            # Acknowledge processed messages
            if auto_ack and message_ids_to_ack:
                self.acknowledge(stream_name, group_name, *message_ids_to_ack)

            return processed_count

        except Exception as e:
            logger.error(f"Failed to consume and process from {stream_name}: {e}")
            raise

    def read_latest(
        self,
        stream_name: str,
        count: int = 1,
    ) -> list[dict[str, Any]]:
        """Read latest messages from a stream without consumer group.

        This is useful for reading current state without joining a consumer group.

        Args:
            stream_name: Name of the stream
            count: Number of latest messages to read

        Returns:
            List of messages (newest first)

        Example:
            >>> latest = event_bus.read_latest("stream:bias:RELIANCE", count=1)
            >>> if latest:
            ...     print(f"Current bias: {latest[0]['data']}")

        """
        try:
            # Read from end of stream
            result = self.redis_client.xread(
                streams={stream_name: "$"},
                count=count,
                block=0,  # Non-blocking
            )

            # Parse result
            messages = []
            if result:
                for stream_data in result:
                    stream = stream_data[0]
                    message_list = stream_data[1]

                    for message_id, fields in message_list:
                        # Deserialize JSON fields
                        deserialized_fields = {}
                        for key, value in fields.items():
                            try:
                                deserialized_fields[key] = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                deserialized_fields[key] = value

                        messages.append(
                            {
                                "message_id": message_id,
                                "stream": stream,
                                "data": deserialized_fields,
                            }
                        )

            return messages

        except Exception as e:
            logger.error(f"Failed to read latest from {stream_name}: {e}")
            raise

    def get_stream_info(self, stream_name: str) -> dict[str, Any]:
        """Get information about a stream.

        Args:
            stream_name: Name of the stream

        Returns:
            Dictionary with stream information (length, first/last entry, etc.)

        """
        try:
            info = self.redis_client._client.xinfo_stream(stream_name)
            return info
        except Exception as e:
            logger.error(f"Failed to get info for stream {stream_name}: {e}")
            raise

    def get_consumer_groups(self, stream_name: str) -> list[str]:
        """Get list of consumer groups for a stream.

        Args:
            stream_name: Name of the stream

        Returns:
            List of consumer group names

        """
        return list(self._consumer_groups.get(stream_name, set()))
