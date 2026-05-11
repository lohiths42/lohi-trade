"""Unit tests for the Redis-based sliding window rate limiter.

Tests cover:
- Endpoint classification (read vs write methods)
- Rate limit enforcement for read and write endpoints
- HTTP 429 response with Retry-After header when limit exceeded
- Sliding window behaviour (old entries expire)
- Unauthenticated requests bypass rate limiting
- Redis key naming convention
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.rate_limiter import (
    READ_LIMIT,
    WRITE_LIMIT,
    WINDOW_SECONDS,
    check_rate_limit,
    classify_method,
    RateLimitMiddleware,
)


# ── classify_method tests ───────────────────────────────────────────────────


class TestClassifyMethod:
    def test_get_is_read(self):
        assert classify_method("GET") == "read"

    def test_head_is_read(self):
        assert classify_method("HEAD") == "read"

    def test_options_is_read(self):
        assert classify_method("OPTIONS") == "read"

    def test_post_is_write(self):
        assert classify_method("POST") == "write"

    def test_put_is_write(self):
        assert classify_method("PUT") == "write"

    def test_patch_is_write(self):
        assert classify_method("PATCH") == "write"

    def test_delete_is_write(self):
        assert classify_method("DELETE") == "write"

    def test_case_insensitive(self):
        assert classify_method("get") == "read"
        assert classify_method("post") == "write"


# ── Fake async Redis for unit tests ─────────────────────────────────────────


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


# ── check_rate_limit tests ──────────────────────────────────────────────────


class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_first_request_allowed(self):
        redis = FakeRedis()
        allowed, retry_after = await check_rate_limit(redis, "user1", "read")
        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_read_limit_allows_100_requests(self):
        redis = FakeRedis()
        now = time.time()
        for i in range(READ_LIMIT):
            allowed, _ = await check_rate_limit(redis, "user1", "read", now=now + i * 0.01)
            assert allowed is True, f"Request {i+1} should be allowed"

    @pytest.mark.asyncio
    async def test_read_limit_rejects_101st_request(self):
        redis = FakeRedis()
        now = time.time()
        for i in range(READ_LIMIT):
            await check_rate_limit(redis, "user1", "read", now=now + i * 0.01)

        allowed, retry_after = await check_rate_limit(
            redis, "user1", "read", now=now + READ_LIMIT * 0.01
        )
        assert allowed is False
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_write_limit_allows_30_requests(self):
        redis = FakeRedis()
        now = time.time()
        for i in range(WRITE_LIMIT):
            allowed, _ = await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)
            assert allowed is True, f"Request {i+1} should be allowed"

    @pytest.mark.asyncio
    async def test_write_limit_rejects_31st_request(self):
        redis = FakeRedis()
        now = time.time()
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)

        allowed, retry_after = await check_rate_limit(
            redis, "user1", "write", now=now + WRITE_LIMIT * 0.01
        )
        assert allowed is False
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_sliding_window_allows_after_expiry(self):
        redis = FakeRedis()
        now = time.time()
        # Fill up the write limit
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)

        # 61 seconds later, window has slid past all old entries
        future = now + WINDOW_SECONDS + 1
        allowed, retry_after = await check_rate_limit(
            redis, "user1", "write", now=future
        )
        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_different_users_have_separate_limits(self):
        redis = FakeRedis()
        now = time.time()
        # Fill user1's write limit
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)

        # user2 should still be allowed
        allowed, _ = await check_rate_limit(redis, "user2", "write", now=now)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_read_and_write_have_separate_counters(self):
        redis = FakeRedis()
        now = time.time()
        # Fill write limit
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)

        # Read should still be allowed
        allowed, _ = await check_rate_limit(redis, "user1", "read", now=now)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_redis_key_format(self):
        redis = FakeRedis()
        await check_rate_limit(redis, "abc-123", "read")
        assert "rate:abc-123:read" in redis._data

    @pytest.mark.asyncio
    async def test_retry_after_is_positive_integer(self):
        redis = FakeRedis()
        now = time.time()
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now)

        _, retry_after = await check_rate_limit(redis, "user1", "write", now=now)
        assert isinstance(retry_after, int)
        assert retry_after >= 1

    @pytest.mark.asyncio
    async def test_rejected_request_not_counted(self):
        """When a request is rejected, it should not consume a slot."""
        redis = FakeRedis()
        now = time.time()
        for i in range(WRITE_LIMIT):
            await check_rate_limit(redis, "user1", "write", now=now + i * 0.01)

        # This should be rejected
        allowed, _ = await check_rate_limit(redis, "user1", "write", now=now + 0.5)
        assert allowed is False

        # After window expires, we should be able to make WRITE_LIMIT requests again
        future = now + WINDOW_SECONDS + 2
        for i in range(WRITE_LIMIT):
            allowed, _ = await check_rate_limit(redis, "user1", "write", now=future + i * 0.01)
            assert allowed is True


# ── RateLimitMiddleware integration tests ───────────────────────────────────


class TestRateLimitMiddleware:
    def test_middleware_with_fastapi(self):
        """Integration test using FastAPI TestClient."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.base import BaseHTTPMiddleware

        fake_redis = FakeRedis()
        app = FastAPI()

        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "test-user"
                return await call_next(request)

        app.add_middleware(RateLimitMiddleware, redis_client=fake_redis)
        app.add_middleware(FakeAuthMiddleware)

        @app.get("/data")
        async def get_data():
            return {"ok": True}

        @app.post("/action")
        async def post_action():
            return {"ok": True}

        client = TestClient(app)

        # First request should succeed
        resp = client.get("/data")
        assert resp.status_code == 200

    def test_middleware_returns_429_on_write_limit(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.base import BaseHTTPMiddleware

        fake_redis = FakeRedis()
        app = FastAPI()

        # Auth middleware that sets user_id — added via add_middleware so
        # ordering is predictable (Starlette runs add_middleware in reverse
        # order, so the *last* added runs first/outermost).
        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "test-user"
                return await call_next(request)

        # Rate limiter added first → runs second (inner)
        app.add_middleware(RateLimitMiddleware, redis_client=fake_redis)
        # Auth added second → runs first (outer), sets user_id before rate limiter
        app.add_middleware(FakeAuthMiddleware)

        @app.post("/action")
        async def post_action():
            return {"ok": True}

        client = TestClient(app)

        # Exhaust write limit
        for _ in range(WRITE_LIMIT):
            resp = client.post("/action")
            assert resp.status_code == 200

        # Next request should be 429
        resp = client.post("/action")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1
        assert "rate limit" in resp.json()["detail"].lower()

    def test_middleware_skips_unauthenticated_requests(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        fake_redis = FakeRedis()
        app = FastAPI()

        # No auth middleware — user_id not set
        app.add_middleware(RateLimitMiddleware, redis_client=fake_redis)

        @app.get("/public")
        async def public():
            return {"ok": True}

        client = TestClient(app)

        # Should always succeed (no rate limiting for unauthenticated)
        for _ in range(READ_LIMIT + 10):
            resp = client.get("/public")
            assert resp.status_code == 200

    def test_middleware_skips_when_no_redis(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.middleware("http")
        async def fake_auth(request, call_next):
            request.state.user_id = "test-user"
            return await call_next(request)

        app.add_middleware(RateLimitMiddleware, redis_client=None)

        @app.get("/data")
        async def get_data():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/data")
        assert resp.status_code == 200
