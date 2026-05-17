"""Redis Stream consumer that forwards events to Socket.IO."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import redis

from app.config import REDIS_DB, REDIS_HOST, REDIS_PORT

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Get or create Redis connection."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


def redis_ping() -> bool:
    """Check if Redis is reachable."""
    try:
        return get_redis().ping()
    except Exception:
        return False


def publish_command(command: str, data: Dict[str, Any]) -> Optional[str]:
    """Publish a command to stream:commands for backend consumption."""
    try:
        r = get_redis()
        fields = {"command": command}
        for k, v in data.items():
            fields[k] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        return r.xadd("stream:commands", fields, maxlen=1000)
    except Exception as e:
        logger.error(f"Failed to publish command: {e}")
        return None


def get_kill_switch_status() -> bool:
    """Read kill switch status from Redis."""
    try:
        val = get_redis().get("kill_switch:active")
        return val == "true" or val == "1"
    except Exception:
        return False


async def consume_streams(sio):
    """Background task: consume Redis Streams and emit Socket.IO events."""
    group = "frontend_gateway"
    consumer = "gw-1"
    streams_to_consume = ["stream:signals", "stream:ticks"]

    # Wait for Redis to become available before setting up consumer groups
    while True:
        try:
            r = get_redis()
            for stream in streams_to_consume:
                try:
                    r.xgroup_create(stream, group, id="$", mkstream=True)
                except redis.exceptions.ResponseError as e:
                    if "BUSYGROUP" not in str(e):
                        logger.error(f"Failed to create group for {stream}: {e}")
            logger.info("Redis consumer started")
            break
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning("Redis not available, will retry in background...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Redis setup error: {e}, retrying in 5s...")
            await asyncio.sleep(5)

    # Main consume loop
    while True:
        try:
            result = await asyncio.to_thread(
                r.xreadgroup,
                group,
                consumer,
                {s: ">" for s in streams_to_consume},
                50,  # count
                1000,  # block ms
            )
            if result:
                for stream_name, messages in result:
                    for msg_id, fields in messages:
                        event = _map_stream_to_event(stream_name, fields)
                        if event:
                            await sio.emit(event["type"], event["data"])
                        r.xack(stream_name, group, msg_id)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning("Redis connection lost, retrying in 2s...")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Consumer error: {e}")
            await asyncio.sleep(1)


def _map_stream_to_event(stream: str, fields: Dict) -> Optional[Dict]:
    """Map a Redis stream message to a Socket.IO event."""
    if stream == "stream:signals":
        return {"type": "signal_generated", "data": _deserialize(fields)}
    if stream == "stream:ticks" or stream.startswith("stream:ticks:"):
        return {"type": "price_tick", "data": _deserialize(fields)}
    if stream.startswith("stream:bias:"):
        return {"type": "bias_update", "data": _deserialize(fields)}
    return None


def _deserialize(fields: Dict) -> Dict:
    """Try to JSON-parse field values."""
    result = {}
    for k, v in fields.items():
        try:
            result[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            result[k] = v
    return result
