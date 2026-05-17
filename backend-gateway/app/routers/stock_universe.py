"""Stock universe and sector classification API router.

Endpoints for searching securities, listing stocks, viewing sectors,
sector aggregates, and filtering stocks within sectors.

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 7.6, 7.7, 8.3, 8.4, 8.5
"""

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id
from app.services.sector_service import SectorService
from app.services.stock_universe_service import StockUniverseService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────


class SecurityItem(BaseModel):
    id: Optional[int] = None
    symbol: str
    isin: str = ""
    company_name: str = ""
    exchange: str = ""
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap_category: Optional[str] = None
    listing_date: Optional[str] = None
    face_value: Optional[str] = None
    status: str = "ACTIVE"
    instrument_type: str = "Stock"  # "Stock" or "Mutual Fund"


class SearchResponse(BaseModel):
    results: list[SecurityItem]
    count: int


class PaginatedSecuritiesResponse(BaseModel):
    items: list[SecurityItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class SectorListResponse(BaseModel):
    sectors: list[str]
    count: int


class GainerLoserItem(BaseModel):
    security_id: int
    symbol: str
    company_name: str
    price_change_1d: Optional[str] = None
    market_cap: Optional[str] = None


class SectorAggregateResponse(BaseModel):
    sector: str
    total_market_cap: str
    stock_count: int
    top_gainers: list[GainerLoserItem]
    top_losers: list[GainerLoserItem]


class SectorSecurityItem(BaseModel):
    security_id: int
    symbol: str
    company_name: str
    industry: Optional[str] = None
    market_cap: Optional[str] = None
    pe_ratio: Optional[str] = None
    dividend_yield: Optional[str] = None
    price_change_1d: Optional[str] = None


class SectorSecuritiesResponse(BaseModel):
    items: list[SectorSecurityItem]
    total: int
    page: int
    page_size: int


class SubIndustriesResponse(BaseModel):
    sector: str
    sub_industries: list[str]
    count: int


# ── Service dependencies ─────────────────────────────────────────────────────

_stock_universe_service: Optional[StockUniverseService] = None
_sector_service: Optional[SectorService] = None


def set_stock_universe_services(
    stock_svc: StockUniverseService,
    sector_svc: SectorService,
) -> None:
    """Called at app startup to inject service instances."""
    global _stock_universe_service, _sector_service
    _stock_universe_service = stock_svc
    _sector_service = sector_svc


def get_stock_universe_service() -> StockUniverseService:
    if _stock_universe_service is None:
        raise HTTPException(status_code=503, detail="Stock universe service not initialized")
    return _stock_universe_service


def get_sector_service() -> SectorService:
    if _sector_service is None:
        raise HTTPException(status_code=503, detail="Sector service not initialized")
    return _sector_service


# ── Helper ───────────────────────────────────────────────────────────────────


def _decimal_to_str(val) -> Optional[str]:
    """Convert a Decimal or numeric value to string, or None."""
    if val is None:
        return None
    return str(val)


def _classify_instrument_type(isin: str) -> str:
    """Derive instrument type from ISIN prefix.

    INE = Equity (Stock), INF = Mutual Fund, IN0/IN9 = Government Securities.
    """
    if not isin:
        return "Stock"
    prefix = isin[:3].upper()
    if prefix == "INF":
        return "Mutual Fund"
    return "Stock"


def _security_to_item(sec) -> SecurityItem:
    """Convert a Security dataclass to a SecurityItem response model."""
    return SecurityItem(
        id=sec.id,
        symbol=sec.symbol,
        isin=sec.isin,
        company_name=sec.company_name,
        exchange=sec.exchange,
        sector=sec.sector,
        industry=sec.industry,
        market_cap_category=sec.market_cap_category,
        listing_date=sec.listing_date.isoformat() if sec.listing_date else None,
        face_value=_decimal_to_str(sec.face_value),
        status=sec.status,
        instrument_type=_classify_instrument_type(sec.isin),
    )


# ── Stock Endpoints ──────────────────────────────────────────────────────────


@router.get("/stocks/search", response_model=SearchResponse)
async def search_stocks(
    q: str = Query(..., description="Search query (symbol, company name, or ISIN)"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: StockUniverseService = Depends(get_stock_universe_service),
):
    """Search securities by symbol, company name, or ISIN.

    Target <200ms response time using PostgreSQL GIN full-text index.

    Requirements: 7.6
    """
    try:
        results = await svc.search_securities(q, limit=limit)
        items = [_security_to_item(s) for s in results]
        return SearchResponse(results=items, count=len(items))
    except Exception:
        logger.exception("Stock search failed for query=%s", q)
        raise HTTPException(status_code=500, detail="Stock search failed")


@router.get("/stocks", response_model=PaginatedSecuritiesResponse)
async def list_stocks(
    exchange: Optional[str] = Query(None, description="Filter by exchange: NSE, BSE, BOTH"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    market_cap_category: Optional[str] = Query(
        None, description="Filter by market cap: large-cap, mid-cap, small-cap"
    ),
    status: Optional[str] = Query(
        None, description="Filter by status: ACTIVE, INACTIVE, SUSPENDED"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: StockUniverseService = Depends(get_stock_universe_service),
):
    """Paginated listing of securities with optional filters.

    Requirements: 7.7
    """
    try:
        result = await svc.list_securities(
            exchange=exchange,
            sector=sector,
            market_cap_category=market_cap_category,
            status=status,
            page=page,
            page_size=page_size,
        )
        items = [_security_to_item(s) for s in result.items]
        return PaginatedSecuritiesResponse(
            items=items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            total_pages=result.total_pages,
        )
    except Exception:
        logger.exception("Stock listing failed")
        raise HTTPException(status_code=500, detail="Stock listing failed")


@router.get("/stocks/{symbol}", response_model=SecurityItem)
async def get_stock_by_symbol(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: StockUniverseService = Depends(get_stock_universe_service),
):
    """Get a single security by its symbol.

    Requirements: 7.6
    """
    try:
        sec = await svc.get_security_by_symbol(symbol)
        if sec is None:
            raise HTTPException(status_code=404, detail=f"Security '{symbol}' not found")
        return _security_to_item(sec)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Get stock failed for symbol=%s", symbol)
        raise HTTPException(status_code=500, detail="Failed to retrieve security")


# ── Sector Endpoints ─────────────────────────────────────────────────────────


@router.get("/sectors", response_model=SectorListResponse)
async def list_sectors(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: SectorService = Depends(get_sector_service),
):
    """List all pre-defined sectors.

    Requirements: 8.3
    """
    sectors = svc.get_sectors()
    return SectorListResponse(sectors=sectors, count=len(sectors))


@router.get("/sectors/{name}", response_model=SectorAggregateResponse)
async def get_sector_aggregate(
    name: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: SectorService = Depends(get_sector_service),
):
    """Get sector-level aggregate data: total market cap, stock count,
    top 5 gainers and top 5 losers.

    Requirements: 8.4
    """
    try:
        agg = await svc.get_sector_aggregate(name)
        gainers = [
            GainerLoserItem(
                security_id=g.security_id,
                symbol=g.symbol,
                company_name=g.company_name,
                price_change_1d=_decimal_to_str(g.price_change_1d),
                market_cap=_decimal_to_str(g.market_cap),
            )
            for g in agg.top_gainers
        ]
        losers = [
            GainerLoserItem(
                security_id=g.security_id,
                symbol=g.symbol,
                company_name=g.company_name,
                price_change_1d=_decimal_to_str(g.price_change_1d),
                market_cap=_decimal_to_str(g.market_cap),
            )
            for g in agg.top_losers
        ]
        return SectorAggregateResponse(
            sector=agg.sector,
            total_market_cap=str(agg.total_market_cap),
            stock_count=agg.stock_count,
            top_gainers=gainers,
            top_losers=losers,
        )
    except Exception:
        logger.exception("Get sector aggregate failed for sector=%s", name)
        raise HTTPException(status_code=500, detail="Failed to retrieve sector aggregate")


@router.get("/sectors/{name}/sub-industries", response_model=SubIndustriesResponse)
async def get_sector_sub_industries(
    name: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: SectorService = Depends(get_sector_service),
):
    """Get sub-industries for a given sector.

    Requirements: 8.3
    """
    subs = svc.get_sub_industries(name)
    return SubIndustriesResponse(sector=name, sub_industries=subs, count=len(subs))


@router.get("/sectors/{name}/stocks", response_model=SectorSecuritiesResponse)
async def get_sector_stocks(
    name: str,
    market_cap_min: Optional[float] = Query(None, description="Min market cap filter"),
    market_cap_max: Optional[float] = Query(None, description="Max market cap filter"),
    pe_ratio_min: Optional[float] = Query(None, description="Min PE ratio filter"),
    pe_ratio_max: Optional[float] = Query(None, description="Max PE ratio filter"),
    dividend_yield_min: Optional[float] = Query(None, description="Min dividend yield filter"),
    dividend_yield_max: Optional[float] = Query(None, description="Max dividend yield filter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    svc: SectorService = Depends(get_sector_service),
):
    """Filter and list stocks within a sector, sorted by market cap descending.

    Supports filtering by market cap range, PE ratio range, and dividend yield range.

    Requirements: 8.3, 8.5
    """
    from app.services.sector_service import SectorFilterParams

    try:
        filters = SectorFilterParams(
            market_cap_min=Decimal(str(market_cap_min)) if market_cap_min is not None else None,
            market_cap_max=Decimal(str(market_cap_max)) if market_cap_max is not None else None,
            pe_ratio_min=Decimal(str(pe_ratio_min)) if pe_ratio_min is not None else None,
            pe_ratio_max=Decimal(str(pe_ratio_max)) if pe_ratio_max is not None else None,
            dividend_yield_min=(
                Decimal(str(dividend_yield_min)) if dividend_yield_min is not None else None
            ),
            dividend_yield_max=(
                Decimal(str(dividend_yield_max)) if dividend_yield_max is not None else None
            ),
        )

        items, total = await svc.filter_sector_securities(
            sector=name,
            filters=filters,
            page=page,
            page_size=page_size,
        )

        result_items = [
            SectorSecurityItem(
                security_id=s.security_id,
                symbol=s.symbol,
                company_name=s.company_name,
                industry=s.industry,
                market_cap=_decimal_to_str(s.market_cap),
                pe_ratio=_decimal_to_str(s.pe_ratio),
                dividend_yield=_decimal_to_str(s.dividend_yield),
                price_change_1d=_decimal_to_str(s.price_change_1d),
            )
            for s in items
        ]

        return SectorSecuritiesResponse(
            items=result_items,
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception:
        logger.exception("Get sector stocks failed for sector=%s", name)
        raise HTTPException(status_code=500, detail="Failed to retrieve sector stocks")
