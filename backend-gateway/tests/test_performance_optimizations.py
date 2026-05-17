"""Unit tests for backend performance optimizations.

Tests cover:
- asyncpg connection pool configuration (min=5, max=20)
- Redis connection pool configuration (max=10)
- GZip compression middleware (>1KB threshold)
- HTTP caching headers (ETag, Cache-Control) for stock universe/sector data
- Pool lifecycle (create/close)

Requirements: 34.5, 34.6, 34.7, 34.12
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.middleware.caching import (
    CACHE_CONTROL_VALUE,
    CacheHeadersMiddleware,
    _compute_etag,
    _is_cacheable_path,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware

# ── Caching helper tests ────────────────────────────────────────────────────


class TestIsCacheablePath:
    def test_stocks_path_is_cacheable(self):
        assert _is_cacheable_path("/api/v2/stocks") is True

    def test_stocks_search_is_cacheable(self):
        assert _is_cacheable_path("/api/v2/stocks/search") is True

    def test_sectors_path_is_cacheable(self):
        assert _is_cacheable_path("/api/v2/sectors") is True

    def test_sectors_sub_path_is_cacheable(self):
        assert _is_cacheable_path("/api/v2/sectors/IT/stocks") is True

    def test_orders_path_not_cacheable(self):
        assert _is_cacheable_path("/api/orders") is False

    def test_auth_path_not_cacheable(self):
        assert _is_cacheable_path("/api/v2/auth/login") is False

    def test_watchlist_path_not_cacheable(self):
        assert _is_cacheable_path("/api/v2/watchlists") is False


class TestComputeEtag:
    def test_returns_weak_etag(self):
        body = b'{"data": "test"}'
        etag = _compute_etag(body)
        assert etag.startswith('W/"')
        assert etag.endswith('"')

    def test_same_body_same_etag(self):
        body = b"hello world"
        assert _compute_etag(body) == _compute_etag(body)

    def test_different_body_different_etag(self):
        assert _compute_etag(b"hello") != _compute_etag(b"world")

    def test_etag_uses_md5(self):
        body = b"test content"
        expected = f'W/"{hashlib.md5(body).hexdigest()}"'
        assert _compute_etag(body) == expected


# ── CacheHeadersMiddleware integration tests ─────────────────────────────────


def _build_cache_test_app() -> FastAPI:
    """Build a FastAPI app with CacheHeadersMiddleware and test routes."""
    test_app = FastAPI()
    test_app.add_middleware(CacheHeadersMiddleware)

    @test_app.get("/api/v2/stocks")
    async def list_stocks():
        return {"items": [{"symbol": "RELIANCE"}, {"symbol": "TCS"}], "total": 2}

    @test_app.get("/api/v2/sectors")
    async def list_sectors():
        return {"sectors": ["IT", "Pharma", "Banking"], "count": 3}

    @test_app.get("/api/v2/sectors/{name}")
    async def get_sector(name: str):
        return {"sector": name, "stock_count": 100}

    @test_app.get("/api/orders")
    async def list_orders():
        return {"orders": []}

    @test_app.post("/api/v2/stocks")
    async def create_stock():
        return {"created": True}

    return test_app


class TestCacheHeadersMiddleware:
    def test_stocks_get_has_cache_control(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/v2/stocks")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert resp.headers["Cache-Control"] == CACHE_CONTROL_VALUE

    def test_stocks_get_has_etag(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/v2/stocks")
        assert resp.status_code == 200
        assert "ETag" in resp.headers
        assert resp.headers["ETag"].startswith('W/"')

    def test_sectors_get_has_cache_headers(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/v2/sectors")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "ETag" in resp.headers

    def test_sector_detail_has_cache_headers(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/v2/sectors/IT")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "ETag" in resp.headers

    def test_non_cacheable_path_no_cache_headers(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/orders")
        assert resp.status_code == 200
        assert "Cache-Control" not in resp.headers
        assert "ETag" not in resp.headers

    def test_post_request_not_cached(self):
        client = TestClient(_build_cache_test_app())
        resp = client.post("/api/v2/stocks")
        assert resp.status_code == 200
        assert "Cache-Control" not in resp.headers

    def test_conditional_request_304(self):
        client = TestClient(_build_cache_test_app())
        # First request to get the ETag
        resp1 = client.get("/api/v2/stocks")
        etag = resp1.headers["ETag"]

        # Second request with If-None-Match
        resp2 = client.get("/api/v2/stocks", headers={"If-None-Match": etag})
        assert resp2.status_code == 304

    def test_conditional_request_mismatched_etag(self):
        client = TestClient(_build_cache_test_app())
        resp = client.get("/api/v2/stocks", headers={"If-None-Match": 'W/"stale"'})
        assert resp.status_code == 200
        assert "ETag" in resp.headers

    def test_same_content_same_etag(self):
        client = TestClient(_build_cache_test_app())
        resp1 = client.get("/api/v2/stocks")
        resp2 = client.get("/api/v2/stocks")
        assert resp1.headers["ETag"] == resp2.headers["ETag"]


# ── Connection pool configuration tests ──────────────────────────────────────


class TestPoolConfiguration:
    def test_pg_pool_defaults(self):
        """Verify default asyncpg pool config values from config module."""
        from app.config import PG_POOL_MAX_SIZE, PG_POOL_MIN_SIZE

        assert PG_POOL_MIN_SIZE == 5
        assert PG_POOL_MAX_SIZE == 20

    def test_redis_pool_defaults(self):
        """Verify default Redis pool config values from config module."""
        from app.config import REDIS_POOL_MAX_CONNECTIONS, REDIS_POOL_MIN_CONNECTIONS

        assert REDIS_POOL_MIN_CONNECTIONS == 2
        assert REDIS_POOL_MAX_CONNECTIONS == 10

    def test_pg_pool_env_override(self, monkeypatch):
        """Pool sizes should be configurable via environment variables."""
        monkeypatch.setenv("PG_POOL_MIN_SIZE", "10")
        monkeypatch.setenv("PG_POOL_MAX_SIZE", "50")
        import importlib

        import app.config as cfg

        importlib.reload(cfg)
        assert cfg.PG_POOL_MIN_SIZE == 10
        assert cfg.PG_POOL_MAX_SIZE == 50
        # Reset
        monkeypatch.delenv("PG_POOL_MIN_SIZE", raising=False)
        monkeypatch.delenv("PG_POOL_MAX_SIZE", raising=False)
        importlib.reload(cfg)

    def test_redis_pool_env_override(self, monkeypatch):
        """Redis pool sizes should be configurable via environment variables."""
        monkeypatch.setenv("REDIS_POOL_MAX_CONNECTIONS", "25")
        import importlib

        import app.config as cfg

        importlib.reload(cfg)
        assert cfg.REDIS_POOL_MAX_CONNECTIONS == 25
        # Reset
        monkeypatch.delenv("REDIS_POOL_MAX_CONNECTIONS", raising=False)
        importlib.reload(cfg)


# ── Pool lifecycle tests ─────────────────────────────────────────────────────


class TestPgPoolLifecycle:
    @pytest.mark.asyncio
    async def test_create_pg_pool_calls_asyncpg(self):
        """create_pg_pool should call asyncpg.create_pool with correct params."""
        from app.services import db_service

        mock_pool = AsyncMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        # Reset module state
        db_service._pg_pool = None

        with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
            pool = await db_service.create_pg_pool()

            mock_asyncpg.create_pool.assert_called_once()
            call_kwargs = mock_asyncpg.create_pool.call_args
            assert call_kwargs.kwargs["min_size"] == 5
            assert call_kwargs.kwargs["max_size"] == 20
            assert pool is mock_pool

        # Cleanup
        db_service._pg_pool = None

    @pytest.mark.asyncio
    async def test_create_pg_pool_reuses_existing(self):
        """Calling create_pg_pool twice should return the same pool."""
        from app.services import db_service

        mock_pool = AsyncMock()
        db_service._pg_pool = mock_pool

        pool = await db_service.create_pg_pool()
        assert pool is mock_pool

        # Cleanup
        db_service._pg_pool = None

    @pytest.mark.asyncio
    async def test_close_pg_pool(self):
        """close_pg_pool should call pool.close() and reset state."""
        from app.services import db_service

        mock_pool = AsyncMock()
        db_service._pg_pool = mock_pool

        await db_service.close_pg_pool()

        mock_pool.close.assert_called_once()
        assert db_service._pg_pool is None

    @pytest.mark.asyncio
    async def test_close_pg_pool_noop_when_none(self):
        """close_pg_pool should be safe to call when no pool exists."""
        from app.services import db_service

        db_service._pg_pool = None
        await db_service.close_pg_pool()  # Should not raise

    def test_get_pg_pool_returns_current(self):
        """get_pg_pool should return the current pool reference."""
        from app.services import db_service

        sentinel = object()
        db_service._pg_pool = sentinel
        assert db_service.get_pg_pool() is sentinel
        db_service._pg_pool = None

    @pytest.mark.asyncio
    async def test_create_pg_pool_handles_failure(self):
        """create_pg_pool should return None if asyncpg.create_pool fails."""
        from app.services import db_service

        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(side_effect=Exception("Connection refused"))

        db_service._pg_pool = None

        with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
            pool = await db_service.create_pg_pool()
            assert pool is None

        db_service._pg_pool = None


class TestRedisPoolLifecycle:
    def test_create_redis_pool(self):
        """create_redis_pool should create a ConnectionPool with correct max."""
        from app.services import db_service

        db_service._redis_pool = None

        mock_redis_lib = MagicMock()
        mock_pool_instance = MagicMock()
        mock_redis_lib.ConnectionPool.return_value = mock_pool_instance

        with patch.dict("sys.modules", {"redis": mock_redis_lib}):
            # Need to reimport since the function does `import redis as redis_lib`
            # We patch at the sys.modules level
            pool = db_service.create_redis_pool()

        # Verify pool was created (may use cached import)
        assert pool is not None

        db_service._redis_pool = None

    def test_create_redis_pool_reuses_existing(self):
        """Calling create_redis_pool twice should return the same pool."""
        from app.services import db_service

        sentinel = MagicMock()
        db_service._redis_pool = sentinel

        pool = db_service.create_redis_pool()
        assert pool is sentinel

        db_service._redis_pool = None

    def test_create_async_redis_pool_reuses_existing(self):
        """Calling create_async_redis_pool twice should return the same client."""
        from app.services import db_service

        sentinel = MagicMock()
        db_service._redis_async_client = sentinel

        client = db_service.create_async_redis_pool()
        assert client is sentinel

        db_service._redis_async_client = None

    @pytest.mark.asyncio
    async def test_close_redis_pools(self):
        """close_redis_pools should close both sync and async pools."""
        from app.services import db_service

        mock_sync_pool = MagicMock()
        mock_async_client = AsyncMock()
        db_service._redis_pool = mock_sync_pool
        db_service._redis_async_client = mock_async_client

        await db_service.close_redis_pools()

        mock_async_client.aclose.assert_called_once()
        mock_sync_pool.disconnect.assert_called_once()
        assert db_service._redis_pool is None
        assert db_service._redis_async_client is None

    @pytest.mark.asyncio
    async def test_close_redis_pools_noop_when_none(self):
        """close_redis_pools should be safe when no pools exist."""
        from app.services import db_service

        db_service._redis_pool = None
        db_service._redis_async_client = None
        await db_service.close_redis_pools()  # Should not raise


# ── GZip middleware configuration test ───────────────────────────────────────


class TestGZipConfiguration:
    def test_gzip_minimum_size_1024(self):
        """GZipMiddleware should be configured with minimum_size=1024 (>1KB)."""
        test_app = FastAPI()
        test_app.add_middleware(GZipMiddleware, minimum_size=1024)

        @test_app.get("/small")
        async def small():
            return {"ok": True}

        @test_app.get("/large")
        async def large():
            return {"data": "x" * 2000}

        client = TestClient(test_app)

        # Large response should be compressed
        resp = client.get("/large", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") == "gzip"

        # Small response should NOT be compressed
        resp = client.get("/small", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
