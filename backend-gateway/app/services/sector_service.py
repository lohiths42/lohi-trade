"""Sector Service — sector classification, sub-industry mapping, and aggregation.

Classifies all securities into 15 pre-defined sectors with sub-industry
breakdowns. Provides sector-level aggregates (market cap, stock count,
top gainers/losers) and supports filtering within sectors.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

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

# Sub-industry classification within each sector (Requirement 8.2)
SUB_INDUSTRIES: dict[str, list[str]] = {
    "Pharma": [
        "Pharmaceuticals",
        "Biotechnology",
        "Healthcare Services",
        "Medical Devices",
        "Drug Discovery",
    ],
    "IT/Technology": [
        "IT Services",
        "Software Products",
        "Cloud Computing",
        "Cybersecurity",
        "IT Consulting",
    ],
    "AI/Deep Tech": [
        "Artificial Intelligence",
        "Machine Learning",
        "Robotics",
        "Semiconductors",
        "Quantum Computing",
    ],
    "Metals & Mining": [
        "Steel",
        "Aluminium",
        "Copper",
        "Gold & Precious Metals",
        "Mining",
    ],
    "Banking & Finance": [
        "Private Banks",
        "PSU Banks",
        "NBFCs",
        "Microfinance",
        "Wealth Management",
    ],
    "FMCG": [
        "Food & Beverages",
        "Personal Care",
        "Household Products",
        "Tobacco",
        "Packaged Foods",
    ],
    "Energy": [
        "Oil & Gas",
        "Renewable Energy",
        "Power Generation",
        "Power Distribution",
        "Coal",
    ],
    "Automobile": [
        "Passenger Vehicles",
        "Commercial Vehicles",
        "Two Wheelers",
        "Auto Components",
        "Electric Vehicles",
    ],
    "Telecom": [
        "Telecom Services",
        "Telecom Equipment",
        "Internet Services",
        "Tower Companies",
        "Fiber Optics",
    ],
    "Real Estate": [
        "Residential",
        "Commercial",
        "REITs",
        "Property Management",
        "Construction Materials",
    ],
    "Infrastructure": [
        "Roads & Highways",
        "Railways",
        "Ports & Shipping",
        "Airports",
        "Urban Infrastructure",
    ],
    "Chemicals": [
        "Specialty Chemicals",
        "Agrochemicals",
        "Petrochemicals",
        "Industrial Chemicals",
        "Paints & Coatings",
    ],
    "Media & Entertainment": [
        "Broadcasting",
        "Digital Media",
        "Film Production",
        "Gaming",
        "Advertising",
    ],
    "Insurance": [
        "Life Insurance",
        "General Insurance",
        "Health Insurance",
        "Reinsurance",
        "Insurance Broking",
    ],
    "Miscellaneous": [
        "Conglomerates",
        "Trading Companies",
        "Textiles",
        "Paper & Packaging",
        "Other",
    ],
}


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class SecurityGainerLoser:
    """A security entry for top gainers/losers lists."""

    security_id: int
    symbol: str
    company_name: str
    price_change_1d: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None


@dataclass
class SectorAggregate:
    """Aggregated data for a single sector."""

    sector: str
    total_market_cap: Decimal = Decimal("0")
    stock_count: int = 0
    top_gainers: list[SecurityGainerLoser] = field(default_factory=list)
    top_losers: list[SecurityGainerLoser] = field(default_factory=list)


@dataclass
class SectorFilterParams:
    """Filter parameters for querying within a sector."""

    market_cap_min: Optional[Decimal] = None
    market_cap_max: Optional[Decimal] = None
    pe_ratio_min: Optional[Decimal] = None
    pe_ratio_max: Optional[Decimal] = None
    dividend_yield_min: Optional[Decimal] = None
    dividend_yield_max: Optional[Decimal] = None


@dataclass
class SectorSecurity:
    """A security with fundamental data, returned from sector queries."""

    security_id: int
    symbol: str
    company_name: str
    industry: Optional[str] = None
    market_cap: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    price_change_1d: Optional[Decimal] = None


@dataclass
class ClassificationUpdate:
    """Result of a quarterly classification update."""

    updated_count: int = 0
    timestamp: Optional[datetime] = None


# ── Service ──────────────────────────────────────────────────────────────────


class SectorService:
    """Sector classification, aggregation, and filtering.

    Uses asyncpg db_pool for PostgreSQL access. Relies on the `securities`,
    `security_fundamentals`, and `security_technicals` tables.
    """

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    # ── Classification ───────────────────────────────────────────────────

    @staticmethod
    def get_sectors() -> list[str]:
        """Return the list of all 15 pre-defined sectors."""
        return list(SECTORS)

    @staticmethod
    def get_sub_industries(sector: str) -> list[str]:
        """Return sub-industries for a given sector.

        Returns empty list if sector is not recognized.
        """
        return list(SUB_INDUSTRIES.get(sector, []))

    @staticmethod
    def classify_sector(sector: Optional[str]) -> str:
        """Validate and return a sector name, defaulting to Miscellaneous."""
        if sector and sector in SECTORS:
            return sector
        return "Miscellaneous"

    @staticmethod
    def classify_sub_industry(sector: str, industry: Optional[str]) -> str:
        """Validate a sub-industry within a sector.

        Returns 'Other' (or the last sub-industry) if not recognized.
        """
        subs = SUB_INDUSTRIES.get(sector, [])
        if not subs:
            return "Other"
        if industry and industry in subs:
            return industry
        return subs[-1]  # Default to last entry (typically 'Other' or catch-all)

    # ── Aggregation (Requirement 8.4) ────────────────────────────────────

    async def get_sector_aggregate(self, sector: str) -> SectorAggregate:
        """Get sector-level aggregate: total market cap, stock count,
        top 5 gainers and top 5 losers for the current trading day.

        Returns an empty aggregate if sector is invalid or db_pool is None.
        """
        if sector not in SECTORS:
            return SectorAggregate(sector=sector)

        if self.db_pool is None:
            logger.debug("No db_pool configured — returning empty aggregate")
            return SectorAggregate(sector=sector)

        try:
            async with self.db_pool.acquire() as conn:
                # Total market cap and stock count
                agg_row = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(SUM(sf.market_cap), 0) AS total_market_cap,
                        COUNT(s.id) AS stock_count
                    FROM securities s
                    LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                    WHERE s.sector = $1 AND s.status = 'ACTIVE'
                    """,
                    sector,
                )

                total_market_cap = (
                    Decimal(str(agg_row["total_market_cap"])) if agg_row else Decimal("0")
                )
                stock_count = agg_row["stock_count"] if agg_row else 0

                # Top 5 gainers (highest price_change_1d)
                gainer_rows = await conn.fetch(
                    """
                    SELECT s.id, s.symbol, s.company_name,
                           st.price_change_1d, sf.market_cap
                    FROM securities s
                    LEFT JOIN security_technicals st ON st.security_id = s.id
                    LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                    WHERE s.sector = $1 AND s.status = 'ACTIVE'
                      AND st.price_change_1d IS NOT NULL
                    ORDER BY st.price_change_1d DESC
                    LIMIT 5
                    """,
                    sector,
                )

                # Top 5 losers (lowest price_change_1d)
                loser_rows = await conn.fetch(
                    """
                    SELECT s.id, s.symbol, s.company_name,
                           st.price_change_1d, sf.market_cap
                    FROM securities s
                    LEFT JOIN security_technicals st ON st.security_id = s.id
                    LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                    WHERE s.sector = $1 AND s.status = 'ACTIVE'
                      AND st.price_change_1d IS NOT NULL
                    ORDER BY st.price_change_1d ASC
                    LIMIT 5
                    """,
                    sector,
                )

                return SectorAggregate(
                    sector=sector,
                    total_market_cap=total_market_cap,
                    stock_count=stock_count,
                    top_gainers=[self._row_to_gainer_loser(r) for r in gainer_rows],
                    top_losers=[self._row_to_gainer_loser(r) for r in loser_rows],
                )

        except Exception:
            logger.exception("get_sector_aggregate failed for sector=%s", sector)
            return SectorAggregate(sector=sector)

    # ── Filtering within sector (Requirement 8.5) ────────────────────────

    async def filter_sector_securities(
        self,
        sector: str,
        filters: Optional[SectorFilterParams] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SectorSecurity], int]:
        """Filter securities within a sector by market cap, PE ratio,
        and dividend yield ranges. Returns (items, total_count).

        Results sorted by market cap descending (Requirement 8.3).
        """
        if sector not in SECTORS:
            return [], 0

        if self.db_pool is None:
            logger.debug("No db_pool configured — returning empty filter results")
            return [], 0

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        where_clauses = ["s.sector = $1", "s.status = 'ACTIVE'"]
        params: list[Any] = [sector]
        param_idx = 2

        if filters:
            if filters.market_cap_min is not None:
                where_clauses.append(f"sf.market_cap >= ${param_idx}")
                params.append(filters.market_cap_min)
                param_idx += 1
            if filters.market_cap_max is not None:
                where_clauses.append(f"sf.market_cap <= ${param_idx}")
                params.append(filters.market_cap_max)
                param_idx += 1
            if filters.pe_ratio_min is not None:
                where_clauses.append(f"sf.pe_ratio >= ${param_idx}")
                params.append(filters.pe_ratio_min)
                param_idx += 1
            if filters.pe_ratio_max is not None:
                where_clauses.append(f"sf.pe_ratio <= ${param_idx}")
                params.append(filters.pe_ratio_max)
                param_idx += 1
            if filters.dividend_yield_min is not None:
                where_clauses.append(f"sf.dividend_yield >= ${param_idx}")
                params.append(filters.dividend_yield_min)
                param_idx += 1
            if filters.dividend_yield_max is not None:
                where_clauses.append(f"sf.dividend_yield <= ${param_idx}")
                params.append(filters.dividend_yield_max)
                param_idx += 1

        where_sql = " AND ".join(where_clauses)

        try:
            async with self.db_pool.acquire() as conn:
                count_row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM securities s
                    LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                    WHERE {where_sql}
                    """,
                    *params,
                )
                total = count_row["cnt"] if count_row else 0

                rows = await conn.fetch(
                    f"""
                    SELECT s.id, s.symbol, s.company_name, s.industry,
                           sf.market_cap, sf.pe_ratio, sf.dividend_yield,
                           st.price_change_1d
                    FROM securities s
                    LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                    LEFT JOIN security_technicals st ON st.security_id = s.id
                    WHERE {where_sql}
                    ORDER BY sf.market_cap DESC NULLS LAST
                    LIMIT ${param_idx} OFFSET ${param_idx + 1}
                    """,
                    *params,
                    page_size,
                    offset,
                )

                items = [self._row_to_sector_security(r) for r in rows]
                return items, total

        except Exception:
            logger.exception("filter_sector_securities failed for sector=%s", sector)
            return [], 0

    # ── Quarterly classification update (Requirement 8.6) ────────────────

    async def update_classifications(
        self,
        classifications: list[dict],
    ) -> ClassificationUpdate:
        """Update sector and industry classifications for securities.

        Each dict in `classifications` should have keys:
        - security_id (int)
        - sector (str)
        - industry (str, optional)

        Invalid sectors are mapped to 'Miscellaneous'.
        """
        if self.db_pool is None:
            logger.warning("No db_pool configured — cannot update classifications")
            return ClassificationUpdate()

        if not classifications:
            return ClassificationUpdate(updated_count=0, timestamp=datetime.now(timezone.utc))

        now = datetime.now(timezone.utc)
        updated = 0

        try:
            async with self.db_pool.acquire() as conn:
                for entry in classifications:
                    sec_id = entry.get("security_id")
                    if sec_id is None:
                        continue

                    sector = self.classify_sector(entry.get("sector"))
                    industry = entry.get("industry")

                    result = await conn.execute(
                        """
                        UPDATE securities
                        SET sector = $1, industry = $2, updated_at = $3
                        WHERE id = $4
                        """,
                        sector,
                        industry,
                        now,
                        sec_id,
                    )
                    if result and "UPDATE 1" in result:
                        updated += 1

            return ClassificationUpdate(updated_count=updated, timestamp=now)

        except Exception:
            logger.exception("update_classifications failed")
            return ClassificationUpdate(updated_count=0, timestamp=now)

    # ── Row mapping helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_gainer_loser(row) -> SecurityGainerLoser:
        """Convert an asyncpg Record to a SecurityGainerLoser."""
        return SecurityGainerLoser(
            security_id=row["id"],
            symbol=row["symbol"],
            company_name=row["company_name"],
            price_change_1d=row.get("price_change_1d"),
            market_cap=row.get("market_cap"),
        )

    @staticmethod
    def _row_to_sector_security(row) -> SectorSecurity:
        """Convert an asyncpg Record to a SectorSecurity."""
        return SectorSecurity(
            security_id=row["id"],
            symbol=row["symbol"],
            company_name=row["company_name"],
            industry=row.get("industry"),
            market_cap=row.get("market_cap"),
            pe_ratio=row.get("pe_ratio"),
            dividend_yield=row.get("dividend_yield"),
            price_change_1d=row.get("price_change_1d"),
        )
