"""Stock Universe Service — manages NSE/BSE securities catalog.

Provides full-text search, paginated listing with filters, daily catalog
refresh, and handling of new listings/delistings.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

NSE_LISTINGS_URL = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
BSE_LISTINGS_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
API_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0

VALID_EXCHANGES = {"NSE", "BSE", "BOTH"}
VALID_MARKET_CAP_CATEGORIES = {"large-cap", "mid-cap", "small-cap"}
VALID_STATUSES = {"ACTIVE", "INACTIVE", "SUSPENDED"}

SECTORS = [
    "Pharma",
    "IT/Technology",
    "AI/Deep Tech",
    "Metals & Mining",
    "Banking & Finance",
    "FMCG",
    "Energy",
    "Automobile",
    "Telecom",
    "Real Estate",
    "Infrastructure",
    "Chemicals",
    "Media & Entertainment",
    "Insurance",
    "Miscellaneous",
]


# ── Data classes ─────────────────────────────────────────────────────────────


class SecurityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


@dataclass
class Security:
    """Represents a single listed security."""

    id: Optional[int] = None
    symbol: str = ""
    isin: str = ""
    company_name: str = ""
    exchange: str = ""
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap_category: Optional[str] = None
    listing_date: Optional[date] = None
    face_value: Optional[Decimal] = None
    status: str = "ACTIVE"
    updated_at: Optional[datetime] = None


@dataclass
class PaginatedResult:
    """Paginated query result."""

    items: list[Security] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 0


# ── Service ──────────────────────────────────────────────────────────────────


class StockUniverseService:
    """Manages 5000+ NSE/BSE securities catalog.

    Uses asyncpg db_pool for PostgreSQL access. The securities table has a
    GIN index on to_tsvector('english', symbol || ' ' || company_name || ' ' || isin)
    for fast full-text search.
    """

    def __init__(
        self,
        db_pool=None,
        nse_url: str = "",
        bse_url: str = "",
    ):
        self.db_pool = db_pool
        self.nse_url = nse_url or NSE_LISTINGS_URL
        self.bse_url = bse_url or BSE_LISTINGS_URL

    # ── Search ───────────────────────────────────────────────────────────

    async def search_securities(self, query: str, limit: int = 20) -> list[Security]:
        """Full-text search by symbol, name, or ISIN using PostgreSQL GIN index.

        Target <200ms response time. Uses ts_rank for relevance ordering.
        Falls back to ILIKE prefix match when tsquery yields no results.
        """
        if not query or not query.strip():
            return []

        if self.db_pool is None:
            logger.debug("No db_pool configured — returning empty search results")
            return []

        limit = max(1, min(limit, 100))
        sanitized = query.strip()

        try:
            async with self.db_pool.acquire() as conn:
                # Build tsquery from the user input — prefix matching with :*
                ts_query = " & ".join(f"{word}:*" for word in sanitized.split() if word)

                rows = await conn.fetch(
                    """
                    SELECT id, symbol, isin, company_name, exchange, sector,
                           industry, market_cap_category, listing_date,
                           face_value, status, updated_at
                    FROM securities
                    WHERE to_tsvector('english', symbol || ' ' || company_name || ' ' || isin)
                          @@ to_tsquery('english', $1)
                      AND status = 'ACTIVE'
                    ORDER BY ts_rank(
                        to_tsvector('english', symbol || ' ' || company_name || ' ' || isin),
                        to_tsquery('english', $1)
                    ) DESC
                    LIMIT $2
                    """,
                    ts_query,
                    limit,
                )

                # Fallback to ILIKE if tsquery returns nothing
                if not rows:
                    like_pattern = f"%{sanitized}%"
                    rows = await conn.fetch(
                        """
                        SELECT id, symbol, isin, company_name, exchange, sector,
                               industry, market_cap_category, listing_date,
                               face_value, status, updated_at
                        FROM securities
                        WHERE status = 'ACTIVE'
                          AND (symbol ILIKE $1
                               OR company_name ILIKE $1
                               OR isin ILIKE $1)
                        ORDER BY symbol
                        LIMIT $2
                        """,
                        like_pattern,
                        limit,
                    )

                return [self._row_to_security(row) for row in rows]

        except Exception:
            logger.exception("search_securities failed for query=%s", sanitized)
            return []

    # ── Paginated listing ────────────────────────────────────────────────

    async def list_securities(
        self,
        exchange: Optional[str] = None,
        sector: Optional[str] = None,
        market_cap_category: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResult:
        """Paginated listing with filters (exchange, sector, market_cap_category, status).

        Returns a PaginatedResult with items, total count, and pagination metadata.
        """
        if self.db_pool is None:
            logger.debug("No db_pool configured — returning empty listing")
            return PaginatedResult()

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        where_clauses: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if exchange:
            if exchange.upper() in ("NSE", "BSE"):
                # When filtering by NSE or BSE, also include dual-listed (BOTH)
                where_clauses.append(f"(exchange = ${param_idx} OR exchange = 'BOTH')")
            else:
                where_clauses.append(f"exchange = ${param_idx}")
            params.append(exchange)
            param_idx += 1

        if sector:
            where_clauses.append(f"sector = ${param_idx}")
            params.append(sector)
            param_idx += 1

        if market_cap_category:
            where_clauses.append(f"market_cap_category = ${param_idx}")
            params.append(market_cap_category)
            param_idx += 1

        if status:
            where_clauses.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        try:
            async with self.db_pool.acquire() as conn:
                # Count total
                count_row = await conn.fetchrow(
                    f"SELECT COUNT(*) AS cnt FROM securities WHERE {where_sql}",
                    *params,
                )
                total = count_row["cnt"] if count_row else 0

                # Fetch page
                rows = await conn.fetch(
                    f"""
                    SELECT id, symbol, isin, company_name, exchange, sector,
                           industry, market_cap_category, listing_date,
                           face_value, status, updated_at
                    FROM securities
                    WHERE {where_sql}
                    ORDER BY symbol
                    LIMIT ${param_idx} OFFSET ${param_idx + 1}
                    """,
                    *params,
                    page_size,
                    offset,
                )

                total_pages = max(1, (total + page_size - 1) // page_size)

                return PaginatedResult(
                    items=[self._row_to_security(row) for row in rows],
                    total=total,
                    page=page,
                    page_size=page_size,
                    total_pages=total_pages,
                )

        except Exception:
            logger.exception("list_securities failed")
            return PaginatedResult()

    # ── Get single security ──────────────────────────────────────────────

    async def get_security_by_symbol(self, symbol: str) -> Optional[Security]:
        """Fetch a single security by its symbol."""
        if not symbol or self.db_pool is None:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, symbol, isin, company_name, exchange, sector,
                           industry, market_cap_category, listing_date,
                           face_value, status, updated_at
                    FROM securities
                    WHERE symbol = $1
                    LIMIT 1
                    """,
                    symbol.strip().upper(),
                )
                return self._row_to_security(row) if row else None
        except Exception:
            logger.exception("get_security_by_symbol failed for %s", symbol)
            return None

    # ── Catalog refresh ──────────────────────────────────────────────────

    async def refresh_catalog(self) -> int:
        """Daily refresh from NSE/BSE data sources at 7:00 AM IST.

        Fetches current listings, upserts into the securities table,
        marks delisted securities as INACTIVE. Returns count of
        updated/inserted securities.
        """
        if self.db_pool is None:
            logger.warning("No db_pool configured — cannot refresh catalog")
            return 0

        nse_securities = await self._fetch_nse_listings()
        bse_securities = await self._fetch_bse_listings()

        # Merge: NSE takes priority for dual-listed
        merged: dict[str, dict] = {}
        for sec in bse_securities:
            merged[sec["isin"]] = sec
        for sec in nse_securities:
            if sec["isin"] in merged:
                # Dual-listed — mark as BOTH
                existing = merged[sec["isin"]]
                existing["exchange"] = "BOTH"
                # Prefer NSE symbol/name
                existing["symbol"] = sec["symbol"]
                existing["company_name"] = sec.get("company_name", existing.get("company_name", ""))
            else:
                merged[sec["isin"]] = sec

        updated_count = 0
        now = datetime.now(timezone.utc)

        try:
            async with self.db_pool.acquire() as conn:
                for isin, sec_data in merged.items():
                    await conn.execute(
                        """
                        INSERT INTO securities
                            (symbol, isin, company_name, exchange, sector,
                             industry, market_cap_category, listing_date,
                             face_value, status, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'ACTIVE', $10)
                        ON CONFLICT (isin) DO UPDATE SET
                            symbol = EXCLUDED.symbol,
                            company_name = EXCLUDED.company_name,
                            exchange = EXCLUDED.exchange,
                            sector = COALESCE(EXCLUDED.sector, securities.sector),
                            industry = COALESCE(EXCLUDED.industry, securities.industry),
                            market_cap_category = COALESCE(EXCLUDED.market_cap_category, securities.market_cap_category),
                            listing_date = COALESCE(EXCLUDED.listing_date, securities.listing_date),
                            face_value = COALESCE(EXCLUDED.face_value, securities.face_value),
                            status = 'ACTIVE',
                            updated_at = EXCLUDED.updated_at
                        """,
                        sec_data.get("symbol", ""),
                        isin,
                        sec_data.get("company_name", ""),
                        sec_data.get("exchange", "NSE"),
                        sec_data.get("sector"),
                        sec_data.get("industry"),
                        sec_data.get("market_cap_category"),
                        sec_data.get("listing_date"),
                        sec_data.get("face_value"),
                        now,
                    )
                    updated_count += 1

                # Mark securities not in the fetched set as INACTIVE (delisted)
                if merged:
                    fetched_isins = list(merged.keys())
                    await conn.execute(
                        """
                        UPDATE securities
                        SET status = 'INACTIVE', updated_at = $1
                        WHERE isin != ALL($2::varchar[])
                          AND status = 'ACTIVE'
                        """,
                        now,
                        fetched_isins,
                    )

                logger.info("Catalog refresh complete: %d securities upserted", updated_count)
                return updated_count

        except Exception:
            logger.exception("refresh_catalog failed")
            return 0

    # ── Delisting handler ────────────────────────────────────────────────

    async def delist_security(self, isin: str) -> bool:
        """Mark a security as INACTIVE (delisted). Prevents new orders."""
        if not isin or self.db_pool is None:
            return False

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE securities
                    SET status = 'INACTIVE', updated_at = $1
                    WHERE isin = $2 AND status = 'ACTIVE'
                    """,
                    datetime.now(timezone.utc),
                    isin,
                )
                return result == "UPDATE 1"
        except Exception:
            logger.exception("delist_security failed for isin=%s", isin)
            return False

    # ── New listing handler ──────────────────────────────────────────────

    async def add_new_listing(self, security_data: dict) -> Optional[Security]:
        """Add a newly listed security within 24 hours of listing."""
        if self.db_pool is None:
            return None

        isin = security_data.get("isin", "").strip()
        symbol = security_data.get("symbol", "").strip()
        company_name = security_data.get("company_name", "").strip()

        if not isin or not symbol or not company_name:
            logger.warning("add_new_listing: missing required fields")
            return None

        now = datetime.now(timezone.utc)

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO securities
                        (symbol, isin, company_name, exchange, sector,
                         industry, market_cap_category, listing_date,
                         face_value, status, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'ACTIVE', $10)
                    ON CONFLICT (isin) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        company_name = EXCLUDED.company_name,
                        status = 'ACTIVE',
                        updated_at = EXCLUDED.updated_at
                    RETURNING id, symbol, isin, company_name, exchange, sector,
                              industry, market_cap_category, listing_date,
                              face_value, status, updated_at
                    """,
                    symbol,
                    isin,
                    company_name,
                    security_data.get("exchange", "NSE"),
                    security_data.get("sector"),
                    security_data.get("industry"),
                    security_data.get("market_cap_category"),
                    security_data.get("listing_date"),
                    security_data.get("face_value"),
                    now,
                )
                return self._row_to_security(row) if row else None
        except Exception:
            logger.exception("add_new_listing failed for isin=%s", isin)
            return None

    # ── Check if security is tradeable ───────────────────────────────────

    async def is_tradeable(self, symbol: str) -> bool:
        """Check if a security is ACTIVE and can accept new orders."""
        sec = await self.get_security_by_symbol(symbol)
        return sec is not None and sec.status == SecurityStatus.ACTIVE.value

    # ── NSE/BSE data fetching ────────────────────────────────────────────

    async def _fetch_nse_listings(self) -> list[dict]:
        """Fetch current NSE listings with retry."""
        return await self._fetch_exchange_data(self.nse_url, "NSE")

    async def _fetch_bse_listings(self) -> list[dict]:
        """Fetch current BSE listings with retry."""
        return await self._fetch_exchange_data(self.bse_url, "BSE")

    async def _fetch_exchange_data(self, url: str, exchange: str) -> list[dict]:
        """Fetch listing data from an exchange API with retries.

        Returns a list of dicts with keys: symbol, isin, company_name, exchange,
        sector, industry, market_cap_category, listing_date, face_value.
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                    response = await client.get(
                        url,
                        headers={
                            "User-Agent": "LOHI-TRADE/1.0",
                            "Accept": "application/json",
                        },
                    )
                    if response.status_code == 200:
                        return self._parse_exchange_response(response.json(), exchange)
                    else:
                        logger.warning(
                            "%s API returned status %d on attempt %d",
                            exchange,
                            response.status_code,
                            attempt + 1,
                        )
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.HTTPError,
            ) as exc:
                last_exception = exc
                logger.warning(
                    "%s API attempt %d/%d failed: %s",
                    exchange,
                    attempt + 1,
                    MAX_RETRIES,
                    str(exc),
                )

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                await asyncio.sleep(backoff)

        logger.error(
            "%s API unreachable after %d attempts. Last error: %s",
            exchange,
            MAX_RETRIES,
            str(last_exception),
        )
        return []

    @staticmethod
    def _parse_exchange_response(data: Any, exchange: str) -> list[dict]:
        """Parse exchange API JSON into a list of security dicts.

        Handles both NSE and BSE response formats. Returns a normalized list.
        """
        securities: list[dict] = []

        if not isinstance(data, (list, dict)):
            return securities

        # NSE format: {"data": [{"symbol": ..., "isin": ..., ...}]}
        items = data if isinstance(data, list) else data.get("data", [])

        for item in items:
            if not isinstance(item, dict):
                continue

            isin = item.get("isin", "") or item.get("ISIN", "") or item.get("isin_code", "")
            symbol = item.get("symbol", "") or item.get("Symbol", "") or item.get("scrip_code", "")
            company_name = (
                item.get("company_name", "")
                or item.get("companyName", "")
                or item.get("Issuer Name", "")
                or item.get("meta", {}).get("companyName", "")
                if isinstance(item.get("meta"), dict)
                else item.get("company_name", "")
            )

            if not isin or not symbol:
                continue

            sec: dict = {
                "symbol": str(symbol).strip().upper(),
                "isin": str(isin).strip().upper(),
                "company_name": str(company_name).strip(),
                "exchange": exchange,
                "sector": item.get("sector") or item.get("Sector"),
                "industry": item.get("industry") or item.get("Industry"),
                "market_cap_category": item.get("market_cap_category"),
                "listing_date": _parse_date(item.get("listing_date") or item.get("listingDate")),
                "face_value": _parse_decimal(item.get("face_value") or item.get("faceValue")),
            }
            securities.append(sec)

        return securities

    # ── Row mapping ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_security(row) -> Security:
        """Convert an asyncpg Record to a Security dataclass."""
        return Security(
            id=row["id"],
            symbol=row["symbol"],
            isin=row["isin"],
            company_name=row["company_name"],
            exchange=row["exchange"],
            sector=row.get("sector"),
            industry=row.get("industry"),
            market_cap_category=row.get("market_cap_category"),
            listing_date=row.get("listing_date"),
            face_value=row.get("face_value"),
            status=row["status"],
            updated_at=row.get("updated_at"),
        )


# ── Utility helpers ──────────────────────────────────────────────────────────


def _parse_date(value) -> Optional[date]:
    """Parse a date string or return None."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _parse_decimal(value) -> Optional[Decimal]:
    """Parse a numeric value to Decimal or return None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
