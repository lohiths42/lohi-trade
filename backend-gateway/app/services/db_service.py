"""Database service for querying existing SQLite tables and managing asyncpg pool.

Provides:
- SQLite helpers for legacy tables (trades, orders, bias_log, etc.)
- asyncpg connection pool lifecycle for PostgreSQL (Requirement 34.6)
- Redis connection pool lifecycle (Requirement 34.6)

Requirements: 34.5, 34.6
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional
from datetime import date, datetime

from app.config import (
    DB_PATH,
    DATABASE_URL,
    PG_POOL_MIN_SIZE,
    PG_POOL_MAX_SIZE,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_POOL_MIN_CONNECTIONS,
    REDIS_POOL_MAX_CONNECTIONS,
)

logger = logging.getLogger(__name__)

# ── asyncpg connection pool (PostgreSQL) ─────────────────────────────────────

_pg_pool = None


async def create_pg_pool():
    """Create an asyncpg connection pool with configured min/max sizes.

    Pool settings (Requirement 34.6):
    - min_size: 5 connections per worker (keeps warm connections ready)
    - max_size: 20 connections per worker (caps resource usage)

    Returns the pool instance, also stored in module-level ``_pg_pool``.
    """
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool

    try:
        import asyncpg

        _pg_pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=PG_POOL_MIN_SIZE,
            max_size=PG_POOL_MAX_SIZE,
            command_timeout=30,
        )
        logger.info(
            "asyncpg pool created: min_size=%d, max_size=%d",
            PG_POOL_MIN_SIZE,
            PG_POOL_MAX_SIZE,
        )
        return _pg_pool
    except Exception as e:
        logger.warning("Failed to create asyncpg pool (PostgreSQL may not be available): %s", e)
        return None


async def close_pg_pool():
    """Gracefully close the asyncpg connection pool."""
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("asyncpg pool closed")


def get_pg_pool():
    """Return the current asyncpg pool (may be None if not initialized)."""
    return _pg_pool


# ── Redis connection pool ────────────────────────────────────────────────────

_redis_pool = None
_redis_async_client = None


def create_redis_pool():
    """Create a Redis connection pool with configured min/max sizes.

    Pool settings (Requirement 34.6):
    - min 2 idle connections kept warm
    - max 10 connections per worker

    Returns a ``redis.ConnectionPool`` instance.
    """
    global _redis_pool
    if _redis_pool is not None:
        return _redis_pool

    try:
        import redis as redis_lib

        _redis_pool = redis_lib.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            max_connections=REDIS_POOL_MAX_CONNECTIONS,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        logger.info(
            "Redis connection pool created: max_connections=%d",
            REDIS_POOL_MAX_CONNECTIONS,
        )
        return _redis_pool
    except Exception as e:
        logger.warning("Failed to create Redis connection pool: %s", e)
        return None


def create_async_redis_pool():
    """Create an async Redis connection pool for use with redis.asyncio.

    Pool settings (Requirement 34.6):
    - max_connections: 10 per worker

    Returns a ``redis.asyncio.ConnectionPool`` instance.
    """
    global _redis_async_client
    if _redis_async_client is not None:
        return _redis_async_client

    try:
        import redis.asyncio as aioredis

        pool = aioredis.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            max_connections=REDIS_POOL_MAX_CONNECTIONS,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        _redis_async_client = aioredis.Redis(connection_pool=pool)
        logger.info(
            "Async Redis pool created: max_connections=%d",
            REDIS_POOL_MAX_CONNECTIONS,
        )
        return _redis_async_client
    except Exception as e:
        logger.warning("Failed to create async Redis pool: %s", e)
        return None


async def close_redis_pools():
    """Close Redis connection pools."""
    global _redis_pool, _redis_async_client
    if _redis_async_client is not None:
        await _redis_async_client.aclose()
        _redis_async_client = None
    if _redis_pool is not None:
        _redis_pool.disconnect()
        _redis_pool = None
    logger.info("Redis pools closed")


def get_redis_pool():
    """Return the current sync Redis connection pool."""
    return _redis_pool


def get_async_redis_client():
    """Return the current async Redis client."""
    return _redis_async_client


# ── SQLite helpers (legacy) ──────────────────────────────────────────────────


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def get_positions() -> List[Dict[str, Any]]:
    """Get open positions (trades with no exit_time)."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time DESC"
        )
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def get_orders(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Get orders with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM orders WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def get_trades(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get completed trades with optional date range."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM trades WHERE exit_time IS NOT NULL"
        params: List[Any] = []

        if start_date:
            query += " AND entry_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND entry_time <= ?"
            params.append(end_date)

        query += " ORDER BY exit_time DESC"
        cursor = conn.execute(query, params)
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def get_bias() -> List[Dict[str, Any]]:
    """Get latest bias per ticker."""
    conn = _get_connection()
    try:
        cursor = conn.execute("""
            SELECT b.* FROM bias_log b
            INNER JOIN (
                SELECT ticker, MAX(created_at) as max_time
                FROM bias_log GROUP BY ticker
            ) latest ON b.ticker = latest.ticker AND b.created_at = latest.max_time
            ORDER BY b.ticker
        """)
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def get_bias_for_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """Get latest bias for a specific ticker."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM bias_log WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
            [ticker],
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_news(
    ticker: Optional[str] = None,
    sentiment: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Get news articles from sentiment_log."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM sentiment_log WHERE 1=1"
        params: List[Any] = []

        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if sentiment:
            query += " AND sentiment = ?"
            params.append(sentiment)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def get_logs(
    level: Optional[str] = None,
    component: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Get audit log entries with optional filters."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: List[Any] = []

        if level:
            query += " AND event_type = ?"
            params.append(level)
        if component:
            query += " AND component = ?"
            params.append(component)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


# ─── Trade Notes ─────────────────────────────────────────────────────────────


def ensure_trade_notes_table() -> None:
    """Create trade_notes table if it doesn't exist."""
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                note_text TEXT NOT NULL CHECK(length(note_text) <= 2000),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_notes_trade_id ON trade_notes(trade_id)"
        )
        conn.commit()
    finally:
        conn.close()


def get_trade_notes(trade_id: str) -> List[Dict[str, Any]]:
    """Get all notes for a trade."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM trade_notes WHERE trade_id = ? ORDER BY created_at DESC",
            [trade_id],
        )
        return _rows_to_dicts(cursor.fetchall())
    finally:
        conn.close()


def create_trade_note(trade_id: str, note_text: str) -> Dict[str, Any]:
    """Create a new trade note."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO trade_notes (trade_id, note_text) VALUES (?, ?)",
            [trade_id, note_text[:2000]],
        )
        conn.commit()
        note_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM trade_notes WHERE id = ?", [note_id]).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_trade_note(trade_id: str, note_id: int, note_text: str) -> Optional[Dict[str, Any]]:
    """Update an existing trade note."""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE trade_notes SET note_text = ?, updated_at = datetime('now') WHERE id = ? AND trade_id = ?",
            [note_text[:2000], note_id, trade_id],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM trade_notes WHERE id = ? AND trade_id = ?", [note_id, trade_id]).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_trade_note(trade_id: str, note_id: int) -> bool:
    """Delete a trade note. Returns True if deleted."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM trade_notes WHERE id = ? AND trade_id = ?",
            [note_id, trade_id],
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
