"""Property-based tests for rate limiting enforcement.

**Validates: Requirements 30.1, 30.2**

Property 5: Rate limit enforcement — after N requests in a window,
    subsequent requests return 429. Also verifies that after the window
    expires, requests are allowed again.

Uses Hypothesis with a FakeRedis in-memory implementation for deterministic,
fast property testing without a real Redis instance.
"""

import pytest
from app.middleware.rate_limiter import (
    READ_LIMIT,
    WINDOW_SECONDS,
    WRITE_LIMIT,
    check_rate_limit,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ── Fake async Redis (in-memory sorted-set implementation) ───────────────────


class FakeRedis:
    """Minimal in-memory async Redis mock supporting sorted sets and pipelines."""

    def __init__(self):
        self._data: dict[str, dict[str, float]] = {}
        self._ttls: dict[str, float] = {}

    def _get_zset(self, key: str) -> dict[str, float]:
        return self._data.setdefault(key, {})

    async def zadd(self, key, mapping):
        zset = self._get_zset(key)
        zset.update(mapping)

    async def zremrangebyscore(self, key, min_score, max_score):
        zset = self._get_zset(key)
        if min_score == "-inf":
            min_score = float("-inf")
        if max_score == "inf":
            max_score = float("inf")
        to_remove = [m for m, s in zset.items() if s <= float(max_score)]
        for m in to_remove:
            del zset[m]
        return len(to_remove)

    async def zcard(self, key):
        return len(self._get_zset(key))

    async def zrange(self, key, start, stop, withscores=False):
        zset = self._get_zset(key)
        items = sorted(zset.items(), key=lambda x: x[1])
        sliced = items[start : stop + 1] if stop >= 0 else items[start:]
        if withscores:
            return sliced
        return [m for m, _ in sliced]

    async def zrem(self, key, *members):
        zset = self._get_zset(key)
        removed = 0
        for m in members:
            if m in zset:
                del zset[m]
                removed += 1
        return removed

    async def expire(self, key, seconds):
        self._ttls[key] = seconds
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    """Collects commands and executes them in order."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._commands: list = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._commands.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zadd(self, key, mapping):
        self._commands.append(("zadd", key, mapping))
        return self

    def zcard(self, key):
        self._commands.append(("zcard", key))
        return self

    def zrange(self, key, start, stop, withscores=False):
        self._commands.append(("zrange", key, start, stop, withscores))
        return self

    def expire(self, key, seconds):
        self._commands.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for cmd in self._commands:
            name = cmd[0]
            if name == "zremrangebyscore":
                r = await self._redis.zremrangebyscore(cmd[1], cmd[2], cmd[3])
            elif name == "zadd":
                r = await self._redis.zadd(cmd[1], cmd[2])
            elif name == "zcard":
                r = await self._redis.zcard(cmd[1])
            elif name == "zrange":
                r = await self._redis.zrange(cmd[1], cmd[2], cmd[3], withscores=cmd[4])
            elif name == "expire":
                r = await self._redis.expire(cmd[1], cmd[2])
            else:
                r = None
            results.append(r)
        return results


# ── Strategies ───────────────────────────────────────────────────────────────

# Endpoint type: read or write
endpoint_types = st.sampled_from(["read", "write"])

# User IDs: simple alphanumeric strings
user_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=20,
)

# Number of requests within the limit (1..limit)
read_request_counts = st.integers(min_value=1, max_value=READ_LIMIT)
write_request_counts = st.integers(min_value=1, max_value=WRITE_LIMIT)

# Number of requests exceeding the limit (limit+1..limit+50)
excess_read_counts = st.integers(min_value=READ_LIMIT + 1, max_value=READ_LIMIT + 50)
excess_write_counts = st.integers(min_value=WRITE_LIMIT + 1, max_value=WRITE_LIMIT + 50)


# ── Property 5: Rate limit enforcement ───────────────────────────────────────


class TestRateLimitEnforcementProperty:
    """**Validates: Requirements 30.1, 30.2**

    Property 5: Rate limit enforcement — for any number of requests N,
    if N <= limit then all are allowed. If N > limit within the same window,
    the (limit+1)th request is rejected. After the window expires, requests
    are allowed again.
    """

    @given(n=read_request_counts, user_id=user_ids)
    @settings(max_examples=25)
    @pytest.mark.asyncio
    async def test_read_requests_within_limit_all_allowed(self, n: int, user_id: str):
        """For any N <= READ_LIMIT requests within a window, all must be allowed."""
        redis = FakeRedis()
        base_time = 1_000_000.0

        for i in range(n):
            allowed, retry_after = await check_rate_limit(
                redis, user_id, "read", now=base_time + i * 0.001
            )
            assert allowed is True, f"Request {i + 1}/{n} should be allowed (limit={READ_LIMIT})"
            assert retry_after == 0

    @given(n=write_request_counts, user_id=user_ids)
    @settings(max_examples=25)
    @pytest.mark.asyncio
    async def test_write_requests_within_limit_all_allowed(self, n: int, user_id: str):
        """For any N <= WRITE_LIMIT requests within a window, all must be allowed."""
        redis = FakeRedis()
        base_time = 1_000_000.0

        for i in range(n):
            allowed, retry_after = await check_rate_limit(
                redis, user_id, "write", now=base_time + i * 0.001
            )
            assert allowed is True, f"Request {i + 1}/{n} should be allowed (limit={WRITE_LIMIT})"
            assert retry_after == 0

    @given(user_id=user_ids, endpoint_type=endpoint_types)
    @settings(max_examples=25)
    @pytest.mark.asyncio
    async def test_request_after_limit_is_rejected(self, user_id: str, endpoint_type: str):
        """After exactly `limit` requests, the next request must be rejected
        with allowed=False and retry_after > 0."""
        redis = FakeRedis()
        limit = READ_LIMIT if endpoint_type == "read" else WRITE_LIMIT
        base_time = 1_000_000.0

        # Fill up to the limit
        for i in range(limit):
            await check_rate_limit(redis, user_id, endpoint_type, now=base_time + i * 0.001)

        # The (limit+1)th request must be rejected
        allowed, retry_after = await check_rate_limit(
            redis, user_id, endpoint_type, now=base_time + limit * 0.001
        )
        assert allowed is False, (
            f"Request {limit + 1} should be rejected for {endpoint_type} " f"(limit={limit})"
        )
        assert retry_after > 0, "Retry-After must be positive when rate limited"
        assert isinstance(retry_after, int), "Retry-After must be an integer"

    @given(
        excess=st.integers(min_value=1, max_value=20),
        user_id=user_ids,
        endpoint_type=endpoint_types,
    )
    @settings(max_examples=25)
    @pytest.mark.asyncio
    async def test_all_excess_requests_rejected(
        self, excess: int, user_id: str, endpoint_type: str
    ):
        """All requests beyond the limit within the same window must be rejected."""
        redis = FakeRedis()
        limit = READ_LIMIT if endpoint_type == "read" else WRITE_LIMIT
        base_time = 1_000_000.0

        # Fill up to the limit
        for i in range(limit):
            await check_rate_limit(redis, user_id, endpoint_type, now=base_time + i * 0.001)

        # Every excess request must be rejected
        for j in range(excess):
            allowed, retry_after = await check_rate_limit(
                redis,
                user_id,
                endpoint_type,
                now=base_time + (limit + j) * 0.001,
            )
            assert allowed is False, f"Excess request {j + 1} should be rejected"
            assert retry_after > 0

    @given(user_id=user_ids, endpoint_type=endpoint_types)
    @settings(max_examples=25)
    @pytest.mark.asyncio
    async def test_window_expiry_allows_new_requests(self, user_id: str, endpoint_type: str):
        """After the sliding window expires, requests must be allowed again."""
        redis = FakeRedis()
        limit = READ_LIMIT if endpoint_type == "read" else WRITE_LIMIT
        base_time = 1_000_000.0

        # Fill up to the limit
        for i in range(limit):
            await check_rate_limit(redis, user_id, endpoint_type, now=base_time + i * 0.001)

        # Confirm we're rate limited
        allowed, _ = await check_rate_limit(
            redis, user_id, endpoint_type, now=base_time + limit * 0.001
        )
        assert allowed is False

        # Jump past the window
        future_time = base_time + WINDOW_SECONDS + 2
        allowed, retry_after = await check_rate_limit(
            redis, user_id, endpoint_type, now=future_time
        )
        assert allowed is True, "Request after window expiry should be allowed"
        assert retry_after == 0

    @given(
        user_id=user_ids,
        endpoint_type=endpoint_types,
        new_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=15)
    @pytest.mark.asyncio
    async def test_full_capacity_restored_after_window(
        self, user_id: str, endpoint_type: str, new_count: int
    ):
        """After the window expires, the full limit capacity is restored —
        we can make up to `limit` new requests again."""
        redis = FakeRedis()
        limit = READ_LIMIT if endpoint_type == "read" else WRITE_LIMIT
        assume(new_count <= limit)
        base_time = 1_000_000.0

        # Fill up to the limit
        for i in range(limit):
            await check_rate_limit(redis, user_id, endpoint_type, now=base_time + i * 0.001)

        # Jump past the window
        future_time = base_time + WINDOW_SECONDS + 2

        # All new_count requests should be allowed
        for i in range(new_count):
            allowed, retry_after = await check_rate_limit(
                redis, user_id, endpoint_type, now=future_time + i * 0.001
            )
            assert allowed is True, f"Post-window request {i + 1}/{new_count} should be allowed"
            assert retry_after == 0
