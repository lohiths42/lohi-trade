"""Screener API router — stock screener endpoints and stock detail.

Endpoints:
  POST /screener/search — apply screener filters, return paginated results
  GET  /screener/presets — get user's saved presets
  POST /screener/presets — save a new preset
  DELETE /screener/presets/{id} — delete a preset
  GET  /screener/templates — get pre-built templates
  GET  /screener/export — export filtered results as CSV
  GET  /stocks/{symbol}/detail — full fundamental + technical data for a stock

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 10.4, 10.6, 10.7, 11.4
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id
from app.services.screener_service import (
    Range,
    ScreenerEngine,
    ScreenerFilters,
    ScreenerPreset,
    ScreenerResultItem,
    dict_to_filters,
    filters_to_dict,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────


class RangeModel(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class ScreenerSearchRequest(BaseModel):
    """Request body for POST /screener/search."""

    # Fundamental
    pe_ratio: Optional[RangeModel] = None
    pb_ratio: Optional[RangeModel] = None
    market_cap: Optional[RangeModel] = None
    dividend_yield: Optional[RangeModel] = None
    eps: Optional[RangeModel] = None
    roe: Optional[RangeModel] = None
    debt_to_equity: Optional[RangeModel] = None
    revenue_growth_1y: Optional[RangeModel] = None
    revenue_growth_3y: Optional[RangeModel] = None
    profit_growth_1y: Optional[RangeModel] = None
    profit_growth_3y: Optional[RangeModel] = None
    # Technical
    rsi_14: Optional[RangeModel] = None
    near_52w_high: Optional[bool] = None
    near_52w_low: Optional[bool] = None
    ma_crossover_50_200: Optional[str] = None
    avg_volume: Optional[RangeModel] = None
    price_change_1d: Optional[RangeModel] = None
    price_change_1w: Optional[RangeModel] = None
    price_change_1m: Optional[RangeModel] = None
    price_change_3m: Optional[RangeModel] = None
    price_change_6m: Optional[RangeModel] = None
    price_change_1y: Optional[RangeModel] = None
    price_change_3y: Optional[RangeModel] = None
    price_change_5y: Optional[RangeModel] = None
    # Returns
    return_1y: Optional[RangeModel] = None
    cagr_3y: Optional[RangeModel] = None
    cagr_5y: Optional[RangeModel] = None
    # Meta
    exchange: Optional[str] = None
    sector: Optional[str] = None
    market_cap_category: Optional[str] = None
    # Pagination / sorting
    sort_by: str = "market_cap"
    order: str = "desc"
    page: int = 1
    page_size: int = 50


class SavePresetRequest(BaseModel):
    """Request body for POST /screener/presets."""

    name: str = Field(..., description="Preset name")
    filters: dict = Field(..., description="Filter configuration dict")


class ScreenerResultItemResponse(BaseModel):
    security_id: int
    symbol: str = ""
    company_name: str = ""
    exchange: str = ""
    sector: Optional[str] = None
    market_cap_category: Optional[str] = None
    pe_ratio: Optional[str] = None
    pb_ratio: Optional[str] = None
    market_cap: Optional[str] = None
    dividend_yield: Optional[str] = None
    eps: Optional[str] = None
    roe: Optional[str] = None
    debt_to_equity: Optional[str] = None
    revenue_growth_1y: Optional[str] = None
    revenue_growth_3y: Optional[str] = None
    profit_growth_1y: Optional[str] = None
    profit_growth_3y: Optional[str] = None
    return_1y: Optional[str] = None
    cagr_3y: Optional[str] = None
    cagr_5y: Optional[str] = None
    high_52w: Optional[str] = None
    low_52w: Optional[str] = None
    rsi_14: Optional[str] = None
    sma_50: Optional[str] = None
    sma_200: Optional[str] = None
    avg_volume_20d: Optional[int] = None
    price_change_1d: Optional[str] = None
    price_change_1w: Optional[str] = None
    price_change_1m: Optional[str] = None
    price_change_3m: Optional[str] = None
    price_change_6m: Optional[str] = None
    price_change_1y: Optional[str] = None
    price_change_3y: Optional[str] = None
    price_change_5y: Optional[str] = None


class ScreenerSearchResponse(BaseModel):
    items: list[ScreenerResultItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PresetResponse(BaseModel):
    id: Optional[str] = None
    name: str
    filters: dict
    is_prebuilt: bool = False
    created_at: Optional[str] = None


class PresetListResponse(BaseModel):
    presets: list[PresetResponse]
    count: int


class TemplateListResponse(BaseModel):
    templates: list[PresetResponse]
    count: int


class MessageResponse(BaseModel):
    message: str


class StockDetailResponse(BaseModel):
    """Full fundamental + technical data for a stock."""

    security_id: int
    symbol: str
    company_name: str
    exchange: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap_category: Optional[str] = None
    listing_date: Optional[str] = None
    face_value: Optional[str] = None
    status: str = "ACTIVE"
    # Fundamentals
    pe_ratio: Optional[str] = None
    pb_ratio: Optional[str] = None
    market_cap: Optional[str] = None
    dividend_yield: Optional[str] = None
    eps: Optional[str] = None
    roe: Optional[str] = None
    debt_to_equity: Optional[str] = None
    revenue_growth_1y: Optional[str] = None
    revenue_growth_3y: Optional[str] = None
    profit_growth_1y: Optional[str] = None
    profit_growth_3y: Optional[str] = None
    return_1y: Optional[str] = None
    cagr_3y: Optional[str] = None
    cagr_5y: Optional[str] = None
    high_52w: Optional[str] = None
    low_52w: Optional[str] = None
    # Technicals
    rsi_14: Optional[str] = None
    sma_50: Optional[str] = None
    sma_200: Optional[str] = None
    avg_volume_20d: Optional[int] = None
    price_change_1d: Optional[str] = None
    price_change_1w: Optional[str] = None
    price_change_1m: Optional[str] = None
    price_change_3m: Optional[str] = None
    price_change_6m: Optional[str] = None
    price_change_1y: Optional[str] = None
    price_change_3y: Optional[str] = None
    price_change_5y: Optional[str] = None


# ── Service dependency ───────────────────────────────────────────────────────

_screener_engine: Optional[ScreenerEngine] = None
_db_pool = None


def set_screener_service(engine: ScreenerEngine, db_pool=None) -> None:
    """Called at app startup to inject the ScreenerEngine instance."""
    global _screener_engine, _db_pool
    _screener_engine = engine
    _db_pool = db_pool


def get_screener_engine() -> ScreenerEngine:
    if _screener_engine is None:
        raise HTTPException(status_code=503, detail="Screener service not initialized")
    return _screener_engine


def get_db_pool():
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    return _db_pool


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_str(val) -> Optional[str]:
    """Convert a Decimal or numeric value to string, or None."""
    if val is None:
        return None
    return str(val)


def _request_to_filters(req: ScreenerSearchRequest) -> ScreenerFilters:
    """Convert a ScreenerSearchRequest to ScreenerFilters."""
    filters = ScreenerFilters()
    range_fields = [
        "pe_ratio",
        "pb_ratio",
        "market_cap",
        "dividend_yield",
        "eps",
        "roe",
        "debt_to_equity",
        "revenue_growth_1y",
        "revenue_growth_3y",
        "profit_growth_1y",
        "profit_growth_3y",
        "rsi_14",
        "avg_volume",
        "price_change_1d",
        "price_change_1w",
        "price_change_1m",
        "price_change_3m",
        "price_change_6m",
        "price_change_1y",
        "price_change_3y",
        "price_change_5y",
        "return_1y",
        "cagr_3y",
        "cagr_5y",
    ]
    for fld in range_fields:
        val = getattr(req, fld, None)
        if val is not None:
            setattr(filters, fld, Range(min=val.min, max=val.max))

    filters.near_52w_high = req.near_52w_high
    filters.near_52w_low = req.near_52w_low
    filters.ma_crossover_50_200 = req.ma_crossover_50_200
    filters.exchange = req.exchange
    filters.sector = req.sector
    filters.market_cap_category = req.market_cap_category
    return filters


def _item_to_response(item: ScreenerResultItem) -> ScreenerResultItemResponse:
    """Convert a ScreenerResultItem to a response model."""
    return ScreenerResultItemResponse(
        security_id=item.security_id,
        symbol=item.symbol,
        company_name=item.company_name,
        exchange=item.exchange,
        sector=item.sector,
        market_cap_category=item.market_cap_category,
        pe_ratio=_to_str(item.pe_ratio),
        pb_ratio=_to_str(item.pb_ratio),
        market_cap=_to_str(item.market_cap),
        dividend_yield=_to_str(item.dividend_yield),
        eps=_to_str(item.eps),
        roe=_to_str(item.roe),
        debt_to_equity=_to_str(item.debt_to_equity),
        revenue_growth_1y=_to_str(item.revenue_growth_1y),
        revenue_growth_3y=_to_str(item.revenue_growth_3y),
        profit_growth_1y=_to_str(item.profit_growth_1y),
        profit_growth_3y=_to_str(item.profit_growth_3y),
        return_1y=_to_str(item.return_1y),
        cagr_3y=_to_str(item.cagr_3y),
        cagr_5y=_to_str(item.cagr_5y),
        high_52w=_to_str(item.high_52w),
        low_52w=_to_str(item.low_52w),
        rsi_14=_to_str(item.rsi_14),
        sma_50=_to_str(item.sma_50),
        sma_200=_to_str(item.sma_200),
        avg_volume_20d=item.avg_volume_20d,
        price_change_1d=_to_str(item.price_change_1d),
        price_change_1w=_to_str(item.price_change_1w),
        price_change_1m=_to_str(item.price_change_1m),
        price_change_3m=_to_str(item.price_change_3m),
        price_change_6m=_to_str(item.price_change_6m),
        price_change_1y=_to_str(item.price_change_1y),
        price_change_3y=_to_str(item.price_change_3y),
        price_change_5y=_to_str(item.price_change_5y),
    )


def _preset_to_response(preset: ScreenerPreset) -> PresetResponse:
    """Convert a ScreenerPreset to a response model."""
    return PresetResponse(
        id=preset.id,
        name=preset.name,
        filters=filters_to_dict(preset.filters) if preset.filters else {},
        is_prebuilt=preset.is_prebuilt,
        created_at=preset.created_at.isoformat() if preset.created_at else None,
    )


# ── Screener Endpoints ──────────────────────────────────────────────────────


@router.post("/screener/search", response_model=ScreenerSearchResponse)
async def screener_search(
    req: ScreenerSearchRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Apply screener filters and return paginated results.

    Requirements: 10.4, 10.5
    """
    try:
        filters = _request_to_filters(req)
        result = await engine.screen(
            filters=filters,
            sort_by=req.sort_by,
            order=req.order,
            page=req.page,
            page_size=req.page_size,
        )
        return ScreenerSearchResponse(
            items=[_item_to_response(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            total_pages=result.total_pages,
        )
    except Exception:
        logger.exception("Screener search failed")
        raise HTTPException(status_code=500, detail="Screener search failed")


@router.get("/screener/presets", response_model=PresetListResponse)
async def get_presets(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Get user's saved screener presets.

    Requirements: 10.6
    """
    try:
        presets = await engine.get_user_presets(user_id)
        return PresetListResponse(
            presets=[_preset_to_response(p) for p in presets],
            count=len(presets),
        )
    except Exception:
        logger.exception("Get presets failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve presets")


@router.post("/screener/presets", response_model=PresetResponse, status_code=201)
async def save_preset(
    req: SavePresetRequest,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Save a new screener preset. Max 10 per user.

    Requirements: 10.6
    """
    try:
        filters = dict_to_filters(req.filters)
        preset = await engine.save_preset(user_id, req.name, filters)
        if preset is None:
            raise HTTPException(
                status_code=400,
                detail="Cannot save preset. Maximum 10 presets reached or invalid data.",
            )
        logger.info("SCREENER_EVENT save_preset user=%s name=%s", user_id, req.name)
        return _preset_to_response(preset)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Save preset failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to save preset")


@router.delete("/screener/presets/{preset_id}", response_model=MessageResponse)
async def delete_preset(
    preset_id: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Delete a saved screener preset.

    Requirements: 10.6
    """
    try:
        deleted = await engine.delete_preset(user_id, preset_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Preset not found")
        logger.info("SCREENER_EVENT delete_preset user=%s id=%s", user_id, preset_id)
        return MessageResponse(message="Preset deleted successfully")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Delete preset failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="Failed to delete preset")


@router.get("/screener/templates", response_model=TemplateListResponse)
async def get_templates(
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Get pre-built screener templates.

    Requirements: 10.7
    """
    templates = engine.get_prebuilt_templates()
    return TemplateListResponse(
        templates=[_preset_to_response(t) for t in templates],
        count=len(templates),
    )


@router.get("/screener/export")
async def export_csv(
    sort_by: str = Query("market_cap", description="Column to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    # Filter params as query params for GET
    pe_ratio_min: Optional[float] = Query(None),
    pe_ratio_max: Optional[float] = Query(None),
    pb_ratio_min: Optional[float] = Query(None),
    pb_ratio_max: Optional[float] = Query(None),
    market_cap_min: Optional[float] = Query(None),
    market_cap_max: Optional[float] = Query(None),
    dividend_yield_min: Optional[float] = Query(None),
    dividend_yield_max: Optional[float] = Query(None),
    sector: Optional[str] = Query(None),
    exchange: Optional[str] = Query(None),
    market_cap_category: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    engine: ScreenerEngine = Depends(get_screener_engine),
):
    """Export filtered screener results as CSV.

    Requirements: 11.5
    """
    try:
        filters = ScreenerFilters(
            pe_ratio=(
                Range(min=pe_ratio_min, max=pe_ratio_max)
                if pe_ratio_min is not None or pe_ratio_max is not None
                else None
            ),
            pb_ratio=(
                Range(min=pb_ratio_min, max=pb_ratio_max)
                if pb_ratio_min is not None or pb_ratio_max is not None
                else None
            ),
            market_cap=(
                Range(min=market_cap_min, max=market_cap_max)
                if market_cap_min is not None or market_cap_max is not None
                else None
            ),
            dividend_yield=(
                Range(min=dividend_yield_min, max=dividend_yield_max)
                if dividend_yield_min is not None or dividend_yield_max is not None
                else None
            ),
            sector=sector,
            exchange=exchange,
            market_cap_category=market_cap_category,
        )
        csv_bytes = await engine.export_csv(filters, sort_by=sort_by, order=order)
        return StreamingResponse(
            iter([csv_bytes]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=screener_results.csv"},
        )
    except Exception:
        logger.exception("CSV export failed")
        raise HTTPException(status_code=500, detail="CSV export failed")


# ── Stock Detail Endpoint ────────────────────────────────────────────────────


@router.get("/stocks/{symbol}/detail", response_model=StockDetailResponse)
async def get_stock_detail(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    db_pool=Depends(get_db_pool),
):
    """Get full fundamental + technical data for a stock.

    Queries securities, security_fundamentals, and security_technicals tables.

    Requirements: 11.4
    """
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    s.id, s.symbol, s.company_name, s.exchange, s.sector,
                    s.industry, s.market_cap_category, s.listing_date,
                    s.face_value, s.status,
                    sf.pe_ratio, sf.pb_ratio, sf.market_cap, sf.dividend_yield,
                    sf.eps, sf.roe, sf.debt_to_equity,
                    sf.revenue_growth_1y, sf.revenue_growth_3y,
                    sf.profit_growth_1y, sf.profit_growth_3y,
                    sf.return_1y, sf.cagr_3y, sf.cagr_5y,
                    sf.high_52w, sf.low_52w,
                    st.rsi_14, st.sma_50, st.sma_200, st.avg_volume_20d,
                    st.price_change_1d, st.price_change_1w, st.price_change_1m,
                    st.price_change_3m, st.price_change_6m, st.price_change_1y,
                    st.price_change_3y, st.price_change_5y
                FROM securities s
                LEFT JOIN security_fundamentals sf ON sf.security_id = s.id
                LEFT JOIN security_technicals st ON st.security_id = s.id
                WHERE UPPER(s.symbol) = UPPER($1)
                """,
                symbol,
            )

        if row is None:
            raise HTTPException(status_code=404, detail=f"Stock '{symbol}' not found")

        return StockDetailResponse(
            security_id=row["id"],
            symbol=row["symbol"],
            company_name=row["company_name"],
            exchange=row["exchange"],
            sector=row.get("sector"),
            industry=row.get("industry"),
            market_cap_category=row.get("market_cap_category"),
            listing_date=row["listing_date"].isoformat() if row.get("listing_date") else None,
            face_value=_to_str(row.get("face_value")),
            status=row["status"],
            pe_ratio=_to_str(row.get("pe_ratio")),
            pb_ratio=_to_str(row.get("pb_ratio")),
            market_cap=_to_str(row.get("market_cap")),
            dividend_yield=_to_str(row.get("dividend_yield")),
            eps=_to_str(row.get("eps")),
            roe=_to_str(row.get("roe")),
            debt_to_equity=_to_str(row.get("debt_to_equity")),
            revenue_growth_1y=_to_str(row.get("revenue_growth_1y")),
            revenue_growth_3y=_to_str(row.get("revenue_growth_3y")),
            profit_growth_1y=_to_str(row.get("profit_growth_1y")),
            profit_growth_3y=_to_str(row.get("profit_growth_3y")),
            return_1y=_to_str(row.get("return_1y")),
            cagr_3y=_to_str(row.get("cagr_3y")),
            cagr_5y=_to_str(row.get("cagr_5y")),
            high_52w=_to_str(row.get("high_52w")),
            low_52w=_to_str(row.get("low_52w")),
            rsi_14=_to_str(row.get("rsi_14")),
            sma_50=_to_str(row.get("sma_50")),
            sma_200=_to_str(row.get("sma_200")),
            avg_volume_20d=row.get("avg_volume_20d"),
            price_change_1d=_to_str(row.get("price_change_1d")),
            price_change_1w=_to_str(row.get("price_change_1w")),
            price_change_1m=_to_str(row.get("price_change_1m")),
            price_change_3m=_to_str(row.get("price_change_3m")),
            price_change_6m=_to_str(row.get("price_change_6m")),
            price_change_1y=_to_str(row.get("price_change_1y")),
            price_change_3y=_to_str(row.get("price_change_3y")),
            price_change_5y=_to_str(row.get("price_change_5y")),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Stock detail failed for symbol=%s", symbol)
        raise HTTPException(status_code=500, detail="Failed to retrieve stock detail")
