"""Watchlist management service.

Provides CRUD operations for custom watchlists, enforces per-user limits,
validates securities before adding, enriches watchlists with live price data
from Redis, and serves pre-built index watchlists.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_WATCHLISTS_PER_USER = 20
MAX_SECURITIES_PER_WATCHLIST = 100

PREBUILT_WATCHLISTS = [
    {"name": "Nifty 50", "symbols": []},
    {"name": "Nifty Bank", "symbols": []},
    {"name": "Nifty IT", "symbols": []},
    {"name": "Nifty Pharma", "symbols": []},
    {"name": "Nifty Next 50", "symbols": []},
]


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class Watchlist:
    """A user's watchlist."""

    id: Optional[str] = None
    user_id: Optional[str] = None
    name: str = ""
    is_prebuilt: bool = False
    sort_order: int = 0
    created_at: Optional[datetime] = None


@dataclass
class WatchlistItem:
    """A single security in a watchlist."""

    id: Optional[str] = None
    watchlist_id: Optional[str] = None
    security_id: Optional[int] = None
    symbol: str = ""
    company_name: str = ""
    sort_order: int = 0
    added_at: Optional[datetime] = None


@dataclass
class SecurityPrice:
    """Live price data for a security."""

    symbol: str = ""
    company_name: str = ""
    ltp: float = 0.0
    change_percent: float = 0.0
    volume: int = 0
    sort_order: int = 0


@dataclass
class WatchlistWithPrices:
    """Watchlist enriched with live price data."""

    id: Optional[str] = None
    name: str = ""
    is_prebuilt: bool = False
    securities: list[SecurityPrice] = field(default_factory=list)


# ── Rejection reasons ────────────────────────────────────────────────────────


class WatchlistError(Exception):
    """Raised when a watchlist operation fails."""

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        self.message = message or reason
        super().__init__(self.message)


REASON_MAX_WATCHLISTS = "max_watchlists_reached"
REASON_MAX_SECURITIES = "max_securities_reached"
REASON_SECURITY_NOT_FOUND = "security_not_found"
REASON_SECURITY_NOT_ACTIVE = "security_not_active"
REASON_WATCHLIST_NOT_FOUND = "watchlist_not_found"
REASON_DUPLICATE_SECURITY = "duplicate_security"
REASON_SECURITY_NOT_IN_WATCHLIST = "security_not_in_watchlist"
REASON_EMPTY_NAME = "empty_name"


# ── Service ──────────────────────────────────────────────────────────────────


class WatchlistService:
    """Custom watchlist management. Max 20 lists, 100 securities each.

    Uses asyncpg db_pool for PostgreSQL access and an optional Redis client
    for live price enrichment.
    """

    def __init__(self, db_pool=None, redis_client=None):
        self.db_pool = db_pool
        self.redis_client = redis_client

    # ── Create ───────────────────────────────────────────────────────────

    async def create_watchlist(self, user_id: str, name: str) -> Watchlist:
        """Create a new watchlist for the user.

        Raises WatchlistError if the user already has 20 watchlists or name is empty.
        """
        if not name or not name.strip():
            raise WatchlistError(REASON_EMPTY_NAME, "Watchlist name cannot be empty")

        name = name.strip()

        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        count = await self._get_watchlist_count(user_id)
        if count >= MAX_WATCHLISTS_PER_USER:
            raise WatchlistError(
                REASON_MAX_WATCHLISTS,
                f"Maximum {MAX_WATCHLISTS_PER_USER} watchlists allowed per user",
            )

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO watchlists (user_id, name, is_prebuilt, sort_order)
                    VALUES ($1, $2, FALSE, $3)
                    RETURNING id, user_id, name, is_prebuilt, sort_order, created_at
                    """,
                    user_id,
                    name,
                    count,
                )
                return self._row_to_watchlist(row)
        except Exception:
            logger.exception("create_watchlist failed for user %s", user_id)
            raise

    # ── Rename ───────────────────────────────────────────────────────────

    async def rename_watchlist(
        self, user_id: str, watchlist_id: str, new_name: str
    ) -> Watchlist:
        """Rename an existing watchlist.

        Raises WatchlistError if watchlist not found or name is empty.
        """
        if not new_name or not new_name.strip():
            raise WatchlistError(REASON_EMPTY_NAME, "Watchlist name cannot be empty")

        new_name = new_name.strip()

        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    UPDATE watchlists SET name = $1
                    WHERE id = $2 AND user_id = $3 AND is_prebuilt = FALSE
                    RETURNING id, user_id, name, is_prebuilt, sort_order, created_at
                    """,
                    new_name,
                    watchlist_id,
                    user_id,
                )
                if row is None:
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )
                return self._row_to_watchlist(row)
        except WatchlistError:
            raise
        except Exception:
            logger.exception("rename_watchlist failed for %s", watchlist_id)
            raise

    # ── Delete ───────────────────────────────────────────────────────────

    async def delete_watchlist(self, user_id: str, watchlist_id: str) -> bool:
        """Delete a watchlist and all its items (CASCADE).

        Returns True if deleted, raises WatchlistError if not found.
        Pre-built watchlists cannot be deleted.
        """
        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM watchlists
                    WHERE id = $1 AND user_id = $2 AND is_prebuilt = FALSE
                    """,
                    watchlist_id,
                    user_id,
                )
                if result == "DELETE 0":
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )
                return True
        except WatchlistError:
            raise
        except Exception:
            logger.exception("delete_watchlist failed for %s", watchlist_id)
            raise

    # ── Add security ─────────────────────────────────────────────────────

    async def add_security(
        self, user_id: str, watchlist_id: str, symbol: str
    ) -> WatchlistItem:
        """Add a security to a watchlist.

        Validates:
        - Watchlist belongs to user
        - Security exists and is ACTIVE
        - Watchlist has fewer than 100 securities
        - Security is not already in the watchlist
        """
        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        symbol = symbol.strip().upper()

        try:
            async with self.db_pool.acquire() as conn:
                # Verify watchlist ownership
                wl = await conn.fetchrow(
                    "SELECT id FROM watchlists WHERE id = $1 AND (user_id = $2 OR is_prebuilt = TRUE)",
                    watchlist_id,
                    user_id,
                )
                if wl is None:
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )

                # Validate security exists and is active
                sec = await conn.fetchrow(
                    "SELECT id, symbol, status FROM securities WHERE symbol = $1",
                    symbol,
                )
                if sec is None:
                    raise WatchlistError(
                        REASON_SECURITY_NOT_FOUND,
                        f"Security '{symbol}' not found",
                    )
                if sec["status"] != "ACTIVE":
                    raise WatchlistError(
                        REASON_SECURITY_NOT_ACTIVE,
                        f"Security '{symbol}' is not actively traded",
                    )

                # Check item count
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM watchlist_items WHERE watchlist_id = $1",
                    watchlist_id,
                )
                item_count = count_row["cnt"] if count_row else 0
                if item_count >= MAX_SECURITIES_PER_WATCHLIST:
                    raise WatchlistError(
                        REASON_MAX_SECURITIES,
                        f"Maximum {MAX_SECURITIES_PER_WATCHLIST} securities per watchlist",
                    )

                # Check for duplicate
                existing = await conn.fetchrow(
                    "SELECT id FROM watchlist_items WHERE watchlist_id = $1 AND security_id = $2",
                    watchlist_id,
                    sec["id"],
                )
                if existing is not None:
                    raise WatchlistError(
                        REASON_DUPLICATE_SECURITY,
                        f"Security '{symbol}' is already in this watchlist",
                    )

                # Insert
                row = await conn.fetchrow(
                    """
                    INSERT INTO watchlist_items (watchlist_id, security_id, sort_order)
                    VALUES ($1, $2, $3)
                    RETURNING id, watchlist_id, security_id, sort_order, added_at
                    """,
                    watchlist_id,
                    sec["id"],
                    item_count,
                )
                return WatchlistItem(
                    id=str(row["id"]),
                    watchlist_id=str(row["watchlist_id"]),
                    security_id=row["security_id"],
                    symbol=symbol,
                    company_name="",
                    sort_order=row["sort_order"],
                    added_at=row["added_at"],
                )
        except WatchlistError:
            raise
        except Exception:
            logger.exception("add_security failed for watchlist %s", watchlist_id)
            raise

    # ── Remove security ──────────────────────────────────────────────────

    async def remove_security(
        self, user_id: str, watchlist_id: str, symbol: str
    ) -> bool:
        """Remove a security from a watchlist.

        Returns True if removed, raises WatchlistError if not found.
        """
        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        symbol = symbol.strip().upper()

        try:
            async with self.db_pool.acquire() as conn:
                # Verify watchlist ownership
                wl = await conn.fetchrow(
                    "SELECT id FROM watchlists WHERE id = $1 AND (user_id = $2 OR is_prebuilt = TRUE)",
                    watchlist_id,
                    user_id,
                )
                if wl is None:
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )

                # Find security id
                sec = await conn.fetchrow(
                    "SELECT id FROM securities WHERE symbol = $1",
                    symbol,
                )
                if sec is None:
                    raise WatchlistError(
                        REASON_SECURITY_NOT_FOUND,
                        f"Security '{symbol}' not found",
                    )

                result = await conn.execute(
                    "DELETE FROM watchlist_items WHERE watchlist_id = $1 AND security_id = $2",
                    watchlist_id,
                    sec["id"],
                )
                if result == "DELETE 0":
                    raise WatchlistError(
                        REASON_SECURITY_NOT_IN_WATCHLIST,
                        f"Security '{symbol}' is not in this watchlist",
                    )
                return True
        except WatchlistError:
            raise
        except Exception:
            logger.exception("remove_security failed for watchlist %s", watchlist_id)
            raise

    # ── Reorder securities ───────────────────────────────────────────────

    async def reorder_securities(
        self, user_id: str, watchlist_id: str, security_ids: list[int]
    ) -> bool:
        """Reorder securities in a watchlist by updating sort_order.

        security_ids is the desired order of security IDs.
        Returns True on success.
        """
        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        try:
            async with self.db_pool.acquire() as conn:
                # Verify watchlist ownership
                wl = await conn.fetchrow(
                    "SELECT id FROM watchlists WHERE id = $1 AND (user_id = $2 OR is_prebuilt = TRUE)",
                    watchlist_id,
                    user_id,
                )
                if wl is None:
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )

                for idx, sec_id in enumerate(security_ids):
                    await conn.execute(
                        """
                        UPDATE watchlist_items SET sort_order = $1
                        WHERE watchlist_id = $2 AND security_id = $3
                        """,
                        idx,
                        watchlist_id,
                        sec_id,
                    )
                return True
        except WatchlistError:
            raise
        except Exception:
            logger.exception("reorder_securities failed for watchlist %s", watchlist_id)
            raise

    # ── Get user watchlists ──────────────────────────────────────────────

    async def get_user_watchlists(self, user_id: str) -> list[Watchlist]:
        """Return all watchlists for a user, ordered by sort_order."""
        if self.db_pool is None:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, name, is_prebuilt, sort_order, created_at
                    FROM watchlists
                    WHERE user_id = $1
                    ORDER BY sort_order
                    """,
                    user_id,
                )
                return [self._row_to_watchlist(row) for row in rows]
        except Exception:
            logger.exception("get_user_watchlists failed for user %s", user_id)
            return []

    # ── Get watchlist with prices ────────────────────────────────────────

    async def get_watchlist_with_prices(
        self, user_id: str, watchlist_id: str
    ) -> WatchlistWithPrices:
        """Return a watchlist with live LTP, change%, volume for all securities.

        Fetches price data from Redis hash keys: price:{symbol}.
        Target <500ms response time.
        """
        if self.db_pool is None:
            raise WatchlistError("no_db", "Database not available")

        try:
            async with self.db_pool.acquire() as conn:
                # Verify watchlist ownership
                wl = await conn.fetchrow(
                    """
                    SELECT id, name, is_prebuilt
                    FROM watchlists
                    WHERE id = $1 AND (user_id = $2 OR is_prebuilt = TRUE)
                    """,
                    watchlist_id,
                    user_id,
                )
                if wl is None:
                    raise WatchlistError(
                        REASON_WATCHLIST_NOT_FOUND, "Watchlist not found"
                    )

                # Fetch items with security details
                rows = await conn.fetch(
                    """
                    SELECT wi.sort_order, s.symbol, s.company_name
                    FROM watchlist_items wi
                    JOIN securities s ON s.id = wi.security_id
                    WHERE wi.watchlist_id = $1
                    ORDER BY wi.sort_order
                    """,
                    watchlist_id,
                )

                securities: list[SecurityPrice] = []
                for row in rows:
                    symbol = row["symbol"]
                    price_data = self._get_price_from_redis(symbol)
                    securities.append(
                        SecurityPrice(
                            symbol=symbol,
                            company_name=row["company_name"],
                            ltp=price_data.get("ltp", 0.0),
                            change_percent=price_data.get("change_percent", 0.0),
                            volume=price_data.get("volume", 0),
                            sort_order=row["sort_order"],
                        )
                    )

                return WatchlistWithPrices(
                    id=str(wl["id"]),
                    name=wl["name"],
                    is_prebuilt=wl["is_prebuilt"],
                    securities=securities,
                )
        except WatchlistError:
            raise
        except Exception:
            logger.exception(
                "get_watchlist_with_prices failed for watchlist %s", watchlist_id
            )
            raise

    # ── Pre-built watchlists ─────────────────────────────────────────────

    async def get_prebuilt_watchlists(self) -> list[Watchlist]:
        """Return pre-built watchlists: Nifty 50, Nifty Bank, Nifty IT, Nifty Pharma, Nifty Next 50."""
        if self.db_pool is None:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, name, is_prebuilt, sort_order, created_at
                    FROM watchlists
                    WHERE is_prebuilt = TRUE
                    ORDER BY sort_order
                    """,
                )
                return [self._row_to_watchlist(row) for row in rows]
        except Exception:
            logger.exception("get_prebuilt_watchlists failed")
            return []

    async def ensure_prebuilt_watchlists(self) -> int:
        """Create pre-built watchlists if they don't exist. Returns count created."""
        if self.db_pool is None:
            return 0

        created = 0
        try:
            async with self.db_pool.acquire() as conn:
                for idx, wl_def in enumerate(PREBUILT_WATCHLISTS):
                    existing = await conn.fetchrow(
                        "SELECT id FROM watchlists WHERE name = $1 AND is_prebuilt = TRUE",
                        wl_def["name"],
                    )
                    if existing is None:
                        await conn.execute(
                            """
                            INSERT INTO watchlists (user_id, name, is_prebuilt, sort_order)
                            VALUES (NULL, $1, TRUE, $2)
                            """,
                            wl_def["name"],
                            idx,
                        )
                        created += 1
            logger.info("Ensured pre-built watchlists: %d created", created)
            return created
        except Exception:
            logger.exception("ensure_prebuilt_watchlists failed")
            return 0

    # ── Redis price helper ───────────────────────────────────────────────

    def _get_price_from_redis(self, symbol: str) -> dict[str, Any]:
        """Read live price data from Redis for a symbol.

        Reads from Redis key `price:{symbol}`. Supports both hash and
        simple string formats for backward compatibility.
        Returns dict with ltp, change_percent, volume.
        """
        if self.redis_client is None:
            return {"ltp": 0.0, "change_percent": 0.0, "volume": 0}

        try:
            key = f"price:{symbol}"
            # Try hash format first (design spec)
            data = self.redis_client.hgetall(key)
            if data:
                ltp = float(data.get("ltp", data.get(b"ltp", 0)))
                prev_close = float(data.get("close", data.get(b"close", 0)))
                volume = int(float(data.get("volume", data.get(b"volume", 0))))
                change_pct = 0.0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                return {
                    "ltp": ltp,
                    "change_percent": change_pct,
                    "volume": volume,
                }

            # Fallback: simple string key (existing pattern)
            simple = self.redis_client.get(key)
            if simple is not None:
                ltp = float(simple)
                return {"ltp": ltp, "change_percent": 0.0, "volume": 0}

        except Exception:
            logger.debug("Failed to read price for %s from Redis", symbol)

        return {"ltp": 0.0, "change_percent": 0.0, "volume": 0}

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _get_watchlist_count(self, user_id: str) -> int:
        """Return the number of non-prebuilt watchlists for the user."""
        if self.db_pool is None:
            return 0
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM watchlists WHERE user_id = $1 AND is_prebuilt = FALSE",
                    user_id,
                )
                return row["cnt"] if row else 0
        except Exception:
            logger.exception("_get_watchlist_count failed for user %s", user_id)
            return 0

    @staticmethod
    def _row_to_watchlist(row) -> Watchlist:
        """Convert an asyncpg Record to a Watchlist dataclass."""
        return Watchlist(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row["user_id"] else None,
            name=row["name"],
            is_prebuilt=row["is_prebuilt"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
        )
