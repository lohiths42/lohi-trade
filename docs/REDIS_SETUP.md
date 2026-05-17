# Redis and Event Bus Setup

This document explains how to set up and use Redis and the Event Bus infrastructure for LOHI-TRADE.

## Overview

The LOHI-TRADE system uses Redis Streams as the Event Bus for inter-component communication. All components communicate asynchronously through Redis Streams, enabling loose coupling and independent scaling.

## Architecture

- **Redis Client**: Low-level wrapper around redis-py with automatic reconnection
- **Event Bus**: High-level abstraction for publishing, consuming, and acknowledging messages
- **Redis Streams**: Persistent message queues with consumer groups

## Starting Redis

### Using Docker Compose (Recommended)

```bash
# Start Redis container
docker-compose up -d redis

# Check Redis status
docker-compose ps

# View Redis logs
docker-compose logs -f redis

# Stop Redis
docker-compose down
```

### Using Local Redis Installation

If you have Redis installed locally:

```bash
# Start Redis with AOF persistence
redis-server --appendonly yes --appendfsync everysec
```

## Configuration

Redis configuration is in `config/settings.yaml`:

```yaml
redis:
  host: "localhost"
  port: 6379
  db: 0
```

## Usage Examples

### Basic Redis Client

```python
from src.state.redis_client import RedisClient

# Create and connect
client = RedisClient(host="localhost", port=6379, db=0)
client.connect()

# Health check
if client.ping():
    print("Redis is connected!")

# Publish to stream
message_id = client.xadd(
    stream_name="stream:ticks:RELIANCE",
    fields={"symbol": "RELIANCE", "ltp": "2500.0", "volume": "1000"},
    maxlen=1000
)

# Disconnect
client.disconnect()
```

### Event Bus

```python
from src.state.redis_client import RedisClient
from src.state.event_bus import EventBus

# Initialize
redis_client = RedisClient()
redis_client.connect()
event_bus = EventBus(redis_client)

# Publish message
message_id = event_bus.publish(
    "stream:ticks:RELIANCE",
    {
        "symbol": "RELIANCE",
        "ltp": 2500.0,
        "volume": 1000,
        "timestamp": "2024-01-15T10:30:00"
    },
    maxlen=1000
)

# Create consumer group
event_bus.create_consumer_group(
    "stream:ticks:RELIANCE",
    "candle_builder_group",
    start_id="$"  # Read only new messages
)

# Consume messages
messages = event_bus.consume(
    "stream:ticks:RELIANCE",
    "candle_builder_group",
    "candle_builder_1",
    count=10,
    block=1000  # Block for 1 second
)

for message in messages:
    print(f"Message ID: {message['message_id']}")
    print(f"Data: {message['data']}")

    # Process message...

    # Acknowledge message
    event_bus.acknowledge(
        "stream:ticks:RELIANCE",
        "candle_builder_group",
        message["message_id"]
    )
```

### Consume and Process Pattern

```python
def process_tick(message):
    """Process a tick message."""
    data = message["data"]
    print(f"Processing tick: {data['symbol']} @ {data['ltp']}")
    # Build candle, calculate indicators, etc.

# Consume and process with automatic acknowledgment
count = event_bus.consume_and_process(
    "stream:ticks:RELIANCE",
    "candle_builder_group",
    "candle_builder_1",
    process_tick,
    count=100,
    block=5000,
    auto_ack=True
)

print(f"Processed {count} messages")
```

## Stream Naming Convention

All streams follow this naming pattern:

- `stream:ticks:{symbol}` - Real-time tick data
- `stream:candles:{symbol}:{timeframe}` - OHLCV candles (1m, 5m, 15m)
- `stream:indicators:{symbol}` - Technical indicators
- `stream:signals` - Trading signals from strategies
- `stream:news` - News articles
- `stream:entities` - Resolved entities (company → ticker)
- `stream:sentiment` - Sentiment analysis results
- `stream:bias:{symbol}` - Aggregated sentiment bias
- `stream:rejections` - Rejected orders from RMS

## Consumer Groups

Consumer groups enable multiple consumers to process messages in parallel:

- Each consumer group maintains its own position in the stream
- Messages are distributed among consumers in the group
- Messages must be acknowledged after processing
- Unacknowledged messages remain in the Pending Entries List (PEL)

### Creating Consumer Groups

```python
# Read from beginning (for historical processing)
event_bus.create_consumer_group("stream:ticks:RELIANCE", "backfill_group", start_id="0")

# Read only new messages (for live processing)
event_bus.create_consumer_group("stream:ticks:RELIANCE", "live_group", start_id="$")
```

## Message Serialization

The Event Bus automatically handles serialization:

- **Strings**: Stored as-is
- **Numbers**: Converted to strings
- **Dicts/Lists**: Serialized to JSON
- **None**: Converted to empty string

On consumption, JSON fields are automatically deserialized back to Python objects.

## Error Handling

### Automatic Reconnection

The Redis client automatically reconnects on connection loss:

```python
client = RedisClient(
    max_retries=5,
    retry_delay=1.0  # Exponential backoff starting at 1 second
)
client.connect()  # Will retry up to 5 times
```

### Processing Errors

When using `consume_and_process`, errors in the processor don't stop other messages:

```python
def processor(message):
    try:
        # Process message
        process_data(message["data"])
    except Exception as e:
        logger.error(f"Processing error: {e}")
        # Error is logged, other messages continue processing

event_bus.consume_and_process(
    stream_name,
    group_name,
    consumer_name,
    processor,
    auto_ack=True  # Only successful messages are acknowledged
)
```

## Performance Considerations

### Stream Maxlen

Use `maxlen` to limit stream size (circular buffer):

```python
# Keep only last 1000 messages
event_bus.publish("stream:ticks:RELIANCE", message, maxlen=1000)
```

### Batch Processing

Process messages in batches for better throughput:

```python
messages = event_bus.consume(
    stream_name,
    group_name,
    consumer_name,
    count=100,  # Process 100 messages at once
    block=1000
)
```

### Connection Pooling

The Redis client uses connection pooling (max 50 connections) for efficient resource usage.

## Monitoring

### Stream Information

```python
info = event_bus.get_stream_info("stream:ticks:RELIANCE")
print(f"Stream length: {info['length']}")
print(f"Consumer groups: {info['groups']}")
```

### Health Check

```python
if redis_client.ping():
    print("Redis is healthy")
else:
    print("Redis connection lost")
```

## Testing

### Unit Tests

Run unit tests (use mocks, no Redis required):

```bash
pytest tests/test_redis_client.py tests/test_event_bus.py -v
```

### Integration Tests

Run integration tests (requires running Redis):

```bash
# Start Redis first
docker-compose up -d redis

# Run integration tests
pytest tests/test_integration_redis.py -v -m integration

# Stop Redis
docker-compose down
```

### Property-Based Tests

Run property-based tests to verify correctness properties:

```bash
pytest tests/test_redis_client.py::TestRedisClientPropertyBased -v
```

## Troubleshooting

### Connection Refused

```
redis.exceptions.ConnectionError: Error connecting to localhost:6379
```

**Solution**: Start Redis using Docker Compose or local installation.

### Consumer Group Already Exists

```
redis.exceptions.ResponseError: BUSYGROUP Consumer Group name already exists
```

**Solution**: This is handled automatically by the Event Bus. The existing group will be reused.

### Memory Issues

If Redis runs out of memory:

1. Increase Docker memory limit in `docker-compose.yml`
2. Use smaller `maxlen` values for streams
3. Increase message processing rate to prevent backlog

### Persistence Issues

If data is lost after restart:

1. Verify AOF is enabled: `redis-cli CONFIG GET appendonly`
2. Check AOF file exists: `ls -la data/redis/appendonly.aof`
3. Review Redis logs: `docker-compose logs redis`

## Best Practices

1. **Always acknowledge messages** after successful processing
2. **Use consumer groups** for parallel processing
3. **Set appropriate maxlen** to prevent unbounded memory growth
4. **Handle errors gracefully** in processor functions
5. **Monitor stream lengths** to detect processing bottlenecks
6. **Use structured logging** for debugging
7. **Test with property-based tests** to verify correctness

## Next Steps

After setting up Redis and Event Bus:

1. Implement WebSocket client for tick ingestion (Task 7)
2. Implement candle builder (Task 12)
3. Implement indicator engine (Task 13)
4. Implement strategy engine (Task 14)

All components will communicate through the Event Bus using Redis Streams.
