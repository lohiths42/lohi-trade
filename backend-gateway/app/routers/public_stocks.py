"""Public (no-auth) stock universe and screener endpoints for development.

These mirror the authenticated endpoints but skip RBAC/JWT checks,
allowing the frontend to display stock data without login.

Prefix: /api/v2/public
"""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.routers.stock_universe import (
    SecurityItem,
    SearchResponse,
    PaginatedSecuritiesResponse,
    SectorListResponse,
    get_stock_universe_service,
    get_sector_service,
    _security_to_item,
    _decimal_to_str,
    GainerLoserItem,
    SectorAggregateResponse,
)
from app.routers.screener import (
    ScreenerSearchRequest,
    ScreenerSearchResponse,
    ScreenerResultItemResponse,
    TemplateListResponse,
    _request_to_filters,
    _item_to_response,
    _preset_to_response,
)
from app.services.stock_universe_service import StockUniverseService
from app.services.sector_service import SectorService
from app.services.screener_service import ScreenerEngine

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Chart response models ───────────────────────────────────────────────────


class OHLCVBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class ChartResponse(BaseModel):
    symbol: str
    period: str
    interval: str
    bars: List[OHLCVBar]
    count: int
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None


# ── Service helpers ─────────────────────────────────────────────────────────


def _get_stock_svc() -> StockUniverseService:
    try:
        return get_stock_universe_service()
    except HTTPException:
        raise HTTPException(503, "Stock service not ready")


def _get_sector_svc() -> SectorService:
    try:
        return get_sector_service()
    except HTTPException:
        raise HTTPException(503, "Sector service not ready")


def _get_screener() -> ScreenerEngine:
    from app.routers.screener import get_screener_engine
    try:
        return get_screener_engine()
    except HTTPException:
        raise HTTPException(503, "Screener service not ready")


def _fetch_chart_data(symbol: str, period: str, interval: str) -> dict:
    """Fetch OHLCV + current price.

    Priority: Nubra SDK → yfinance → direct Yahoo Finance API (curl_cffi).
    """
    import math
    import time

    # 1) Try Nubra first (if configured)
    try:
        from app.services.nubra_service import is_nubra_configured, fetch_chart_nubra
        if is_nubra_configured():
            result = fetch_chart_nubra(symbol, period, interval)
            if result:
                return result
            logger.debug("Nubra chart unavailable for %s, falling back to yfinance", symbol)
    except Exception as e:
        logger.debug("Nubra chart import/call error: %s", e)

    # 2) Try yfinance
    try:
        import yfinance as yf
        for suffix in (".NS", ".BO"):
            yf_sym = f"{symbol.upper()}{suffix}"
            try:
                ticker = yf.Ticker(yf_sym)
                hist = ticker.history(period=period, interval=interval)
                if hist is not None and not hist.empty:
                    return _parse_yfinance_hist(symbol, period, interval, hist, ticker)
            except Exception as e:
                if "RateLimit" in type(e).__name__:
                    logger.info("yfinance rate limited for %s, falling back to direct API", yf_sym)
                    break
                continue
    except ImportError:
        pass

    # 3) Fallback: direct Yahoo Finance API via curl_cffi
    return _fetch_chart_direct(symbol, period, interval)


def _fetch_chart_direct(symbol: str, period: str, interval: str) -> dict:
    """Fetch chart data directly from Yahoo Finance API using curl_cffi."""
    import math

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        raise HTTPException(503, "Chart service temporarily unavailable (rate limited)")

    for suffix in (".NS", ".BO"):
        yf_sym = f"{symbol.upper()}{suffix}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}"
        params = {"range": period, "interval": interval, "includePrePost": "false"}

        try:
            resp = cffi_requests.get(url, params=params, impersonate="chrome", timeout=15)
            if resp.status_code != 200:
                continue

            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue

            chart_data = result[0]
            timestamps = chart_data.get("timestamp", [])
            quote = chart_data.get("indicators", {}).get("quote", [{}])[0]
            opens = quote.get("open", [])
            highs = quote.get("high", [])
            lows = quote.get("low", [])
            closes = quote.get("close", [])
            volumes = quote.get("volume", [])

            if not timestamps or not closes:
                continue

            bars = []
            from datetime import datetime, timezone
            for i, ts in enumerate(timestamps):
                o = opens[i] if i < len(opens) else None
                h = highs[i] if i < len(highs) else None
                l = lows[i] if i < len(lows) else None
                c = closes[i] if i < len(closes) else None
                v = volumes[i] if i < len(volumes) else 0

                if any(x is None for x in [o, h, l, c]):
                    continue

                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if interval in ("1d", "5d", "1wk", "1mo"):
                    time_str = dt.strftime("%Y-%m-%d")
                else:
                    time_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

                bars.append({
                    "time": time_str,
                    "open": round(float(o), 2),
                    "high": round(float(h), 2),
                    "low": round(float(l), 2),
                    "close": round(float(c), 2),
                    "volume": int(v) if v else 0,
                })

            if not bars:
                continue

            # Get current price from meta
            meta = chart_data.get("meta", {})
            current_price = meta.get("regularMarketPrice")
            previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            change = None
            change_pct = None
            if current_price and previous_close and previous_close > 0:
                change = round(current_price - previous_close, 2)
                change_pct = round((change / previous_close) * 100, 2)

            return {
                "symbol": symbol.upper(),
                "period": period,
                "interval": interval,
                "bars": bars,
                "count": len(bars),
                "current_price": round(float(current_price), 2) if current_price else (bars[-1]["close"] if bars else None),
                "previous_close": round(float(previous_close), 2) if previous_close else None,
                "change": change,
                "change_percent": change_pct,
            }

        except Exception as e:
            logger.debug("Direct chart fetch %s failed: %s", yf_sym, e)
            continue

    raise HTTPException(404, f"No chart data for '{symbol}'")


def _parse_yfinance_hist(symbol: str, period: str, interval: str, hist, ticker) -> dict:
    """Parse yfinance history DataFrame into chart response dict."""
    import math

    bars = []
    for idx, row in hist.iterrows():
        o, h, l, c, v = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"), row.get("Volume", 0)
        if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in [o, h, l, c]):
            continue
        if interval in ("1d", "5d", "1wk", "1mo"):
            time_str = idx.strftime("%Y-%m-%d")
        else:
            time_str = idx.strftime("%Y-%m-%dT%H:%M:%S")
        bars.append({
            "time": time_str,
            "open": round(float(o), 2),
            "high": round(float(h), 2),
            "low": round(float(l), 2),
            "close": round(float(c), 2),
            "volume": int(v) if v and not (isinstance(v, float) and math.isnan(v)) else 0,
        })

    current_price = None
    previous_close = None
    change = None
    change_pct = None
    try:
        fi = ticker.fast_info
        current_price = float(fi.last_price) if fi.last_price else None
        previous_close = float(fi.previous_close) if fi.previous_close else None
        if current_price and previous_close and previous_close > 0:
            change = round(current_price - previous_close, 2)
            change_pct = round((change / previous_close) * 100, 2)
    except Exception:
        if bars:
            current_price = bars[-1]["close"]

    return {
        "symbol": symbol.upper(),
        "period": period,
        "interval": interval,
        "bars": bars,
        "count": len(bars),
        "current_price": current_price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_pct,
    }


# ── Stock endpoints (public) ─────────────────────────────────────────────────


@router.get("/stocks/search", response_model=SearchResponse)
async def public_search_stocks(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    svc = _get_stock_svc()
    results = await svc.search_securities(q, limit=limit)
    items = [_security_to_item(s) for s in results]
    return SearchResponse(results=items, count=len(items))


@router.get("/stocks/{symbol}/chart", response_model=ChartResponse)
async def public_stock_chart(
    symbol: str,
    period: str = Query("6mo", description="yfinance period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max"),
    interval: str = Query("1d", description="yfinance interval: 1m,5m,15m,1h,1d,1wk,1mo"),
):
    """Fetch OHLCV chart data for a stock via yfinance."""
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
    valid_intervals = {"1m", "2m", "5m", "15m", "30m", "1h", "1d", "5d", "1wk", "1mo"}

    if period not in valid_periods:
        raise HTTPException(400, f"Invalid period '{period}'. Use: {', '.join(sorted(valid_periods))}")
    if interval not in valid_intervals:
        raise HTTPException(400, f"Invalid interval '{interval}'. Use: {', '.join(sorted(valid_intervals))}")

    try:
        # Offload the blocking yfinance call via `asyncio.to_thread` —
        # the modern, non-deprecated equivalent of
        # `get_event_loop().run_in_executor(None, …)`.
        data = await asyncio.to_thread(_fetch_chart_data, symbol, period, interval)
        return data
    except HTTPException:
        raise
    except Exception as e:
        err_name = type(e).__name__
        logger.exception("Chart fetch failed for %s (period=%s, interval=%s): %s", symbol, period, interval, err_name)
        if "RateLimit" in err_name or "rate" in str(e).lower():
            raise HTTPException(429, "Yahoo Finance rate limit reached. Please try again in a minute.")
        raise HTTPException(500, f"Failed to fetch chart data: {err_name}")


@router.get("/stocks/{symbol}", response_model=SecurityItem)
async def public_get_stock(symbol: str):
    """Get a single security by symbol (no auth)."""
    svc = _get_stock_svc()
    sec = await svc.get_security_by_symbol(symbol)
    if sec is None:
        raise HTTPException(404, f"Security '{symbol}' not found")
    return _security_to_item(sec)


@router.get("/stocks", response_model=PaginatedSecuritiesResponse)
async def public_list_stocks(
    exchange: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    market_cap_category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    svc = _get_stock_svc()
    result = await svc.list_securities(
        exchange=exchange, sector=sector,
        market_cap_category=market_cap_category,
        status=status, page=page, page_size=page_size,
    )
    items = [_security_to_item(s) for s in result.items]
    return PaginatedSecuritiesResponse(
        items=items, total=result.total, page=result.page,
        page_size=result.page_size, total_pages=result.total_pages,
    )


# ── Sector endpoints (public) ───────────────────────────────────────────────


@router.get("/sectors", response_model=SectorListResponse)
async def public_list_sectors():
    svc = _get_sector_svc()
    sectors = svc.get_sectors()
    return SectorListResponse(sectors=sectors, count=len(sectors))


@router.get("/sectors/{name}", response_model=SectorAggregateResponse)
async def public_sector_aggregate(name: str):
    svc = _get_sector_svc()
    agg = await svc.get_sector_aggregate(name)
    gainers = [
        GainerLoserItem(
            security_id=g.security_id, symbol=g.symbol,
            company_name=g.company_name,
            price_change_1d=_decimal_to_str(g.price_change_1d),
            market_cap=_decimal_to_str(g.market_cap),
        ) for g in agg.top_gainers
    ]
    losers = [
        GainerLoserItem(
            security_id=g.security_id, symbol=g.symbol,
            company_name=g.company_name,
            price_change_1d=_decimal_to_str(g.price_change_1d),
            market_cap=_decimal_to_str(g.market_cap),
        ) for g in agg.top_losers
    ]
    return SectorAggregateResponse(
        sector=agg.sector, total_market_cap=str(agg.total_market_cap),
        stock_count=agg.stock_count, top_gainers=gainers, top_losers=losers,
    )


# ── Screener endpoints (public) ─────────────────────────────────────────────


@router.post("/screener/search", response_model=ScreenerSearchResponse)
async def public_screener_search(req: ScreenerSearchRequest):
    engine = _get_screener()
    filters = _request_to_filters(req)
    result = await engine.screen(
        filters=filters, sort_by=req.sort_by, order=req.order,
        page=req.page, page_size=req.page_size,
    )
    return ScreenerSearchResponse(
        items=[_item_to_response(item) for item in result.items],
        total=result.total, page=result.page,
        page_size=result.page_size, total_pages=result.total_pages,
    )


@router.get("/screener/templates", response_model=TemplateListResponse)
async def public_screener_templates():
    engine = _get_screener()
    templates = engine.get_prebuilt_templates()
    return TemplateListResponse(
        templates=[_preset_to_response(t) for t in templates],
        count=len(templates),
    )


# ── Data refresh endpoints ──────────────────────────────────────────────────


@router.get("/data/status")
async def public_data_status():
    """Get live data refresh status."""
    svc = _get_stock_svc()
    if svc.db_pool is None:
        return {"total": 0, "with_fundamentals": 0, "with_technicals": 0}

    async with svc.db_pool.acquire() as conn:
        total = (await conn.fetchrow("SELECT COUNT(*) AS c FROM securities WHERE status='ACTIVE'"))["c"]
        with_fund = (await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM security_fundamentals WHERE pe_ratio IS NOT NULL OR market_cap IS NOT NULL"
        ))["c"]
        with_tech = (await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM security_technicals WHERE rsi_14 IS NOT NULL OR price_change_1d IS NOT NULL"
        ))["c"]
        last_update = (await conn.fetchrow(
            "SELECT MAX(updated_at) AS t FROM security_technicals WHERE price_change_1d IS NOT NULL"
        ))["t"]

    return {
        "total_securities": total,
        "with_fundamentals": with_fund,
        "with_technicals": with_tech,
        "last_data_update": str(last_update) if last_update else None,
    }


@router.post("/data/refresh")
async def public_trigger_refresh():
    """Manually trigger a live data refresh cycle."""
    from app.main import app as main_app
    live_svc = getattr(main_app.state, "live_data_service", None)
    if not live_svc:
        raise HTTPException(503, "Live data service not available")

    asyncio.create_task(live_svc._refresh_live_data())
    return {"message": "Refresh triggered", "batch_size": 100}


@router.get("/data/source")
async def public_data_source():
    """Show which market data source is active for chart/quote endpoints."""
    nubra_configured = False
    nubra_connected = False
    try:
        from app.services.nubra_service import is_nubra_configured, _nubra_client
        nubra_configured = is_nubra_configured()
        nubra_connected = _nubra_client is not None
    except Exception:
        pass

    return {
        "primary": "nubra" if nubra_connected else "yfinance",
        "nubra": {
            "configured": nubra_configured,
            "connected": nubra_connected,
        },
        "fallback_chain": ["nubra", "yfinance", "yahoo_direct_api"] if nubra_configured else ["yfinance", "yahoo_direct_api"],
    }


# ── On-demand live quote endpoint ───────────────────────────────────────────


class LiveQuoteResponse(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    open_price: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None


def _fetch_live_quote(symbol: str) -> dict:
    """Fetch live quote.

    Priority: Nubra SDK → yfinance → direct Yahoo Finance API (curl_cffi).
    """
    import math

    # 1) Try Nubra first (if configured)
    try:
        from app.services.nubra_service import is_nubra_configured, fetch_quote_nubra
        if is_nubra_configured():
            result = fetch_quote_nubra(symbol)
            if result:
                return result
            logger.debug("Nubra quote unavailable for %s, falling back to yfinance", symbol)
    except Exception as e:
        logger.debug("Nubra quote import/call error: %s", e)

    # 2) Try yfinance
    try:
        import yfinance as yf
        for suffix in (".NS", ".BO"):
            yf_sym = f"{symbol.upper()}{suffix}"
            try:
                ticker = yf.Ticker(yf_sym)
                fi = ticker.fast_info
                if fi and fi.last_price:
                    current = float(fi.last_price)
                    prev_close = float(fi.previous_close) if fi.previous_close else None
                    change = round(current - prev_close, 2) if prev_close else None
                    change_pct = round((change / prev_close) * 100, 2) if change and prev_close else None

                    info = {}
                    try:
                        info = ticker.info or {}
                    except Exception:
                        pass

                    return {
                        "symbol": symbol.upper(),
                        "current_price": round(current, 2),
                        "previous_close": round(prev_close, 2) if prev_close else None,
                        "change": change,
                        "change_percent": change_pct,
                        "day_high": round(float(fi.day_high), 2) if getattr(fi, 'day_high', None) else info.get("dayHigh"),
                        "day_low": round(float(fi.day_low), 2) if getattr(fi, 'day_low', None) else info.get("dayLow"),
                        "open_price": round(float(fi.open), 2) if getattr(fi, 'open', None) else info.get("open"),
                        "volume": int(fi.last_volume) if getattr(fi, 'last_volume', None) else info.get("volume"),
                        "market_cap": float(fi.market_cap) if getattr(fi, 'market_cap', None) else info.get("marketCap"),
                        "pe_ratio": info.get("trailingPE"),
                        "high_52w": info.get("fiftyTwoWeekHigh"),
                        "low_52w": info.get("fiftyTwoWeekLow"),
                    }
            except Exception as e:
                if "RateLimit" in type(e).__name__:
                    logger.info("yfinance rate limited for quote %s, falling back to direct API", yf_sym)
                    break
                continue
    except ImportError:
        pass

    # 3) Fallback: direct Yahoo Finance API via curl_cffi
    return _fetch_quote_direct(symbol)


def _fetch_quote_direct(symbol: str) -> dict:
    """Fetch live quote directly from Yahoo Finance API using curl_cffi."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        raise HTTPException(503, "Quote service temporarily unavailable (rate limited)")

    for suffix in (".NS", ".BO"):
        yf_sym = f"{symbol.upper()}{suffix}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}"
        params = {"range": "1d", "interval": "1m", "includePrePost": "false"}

        try:
            resp = cffi_requests.get(url, params=params, impersonate="chrome", timeout=10)
            if resp.status_code != 200:
                continue

            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue

            meta = result[0].get("meta", {})
            current = meta.get("regularMarketPrice")
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")

            if not current:
                continue

            change = round(current - prev_close, 2) if prev_close else None
            change_pct = round((change / prev_close) * 100, 2) if change and prev_close else None

            return {
                "symbol": symbol.upper(),
                "current_price": round(float(current), 2),
                "previous_close": round(float(prev_close), 2) if prev_close else None,
                "change": change,
                "change_percent": change_pct,
                "day_high": meta.get("regularMarketDayHigh"),
                "day_low": meta.get("regularMarketDayLow"),
                "open_price": meta.get("regularMarketOpen"),
                "volume": meta.get("regularMarketVolume"),
                "market_cap": None,
                "pe_ratio": None,
                "high_52w": meta.get("fiftyTwoWeekHigh"),
                "low_52w": meta.get("fiftyTwoWeekLow"),
            }
        except Exception as e:
            logger.debug("Direct quote fetch %s failed: %s", yf_sym, e)
            continue

    raise HTTPException(404, f"No live data for '{symbol}'")


@router.get("/stocks/{symbol}/quote", response_model=LiveQuoteResponse)
async def public_live_quote(symbol: str):
    """Fetch on-demand live quote for a stock via yfinance. No DB storage needed."""
    try:
        # `to_thread` is the modern replacement for
        # `asyncio.get_event_loop().run_in_executor(None, …)`; safe on
        # Python 3.10+ inside a running coroutine.
        data = await asyncio.to_thread(_fetch_live_quote, symbol)
        return data
    except HTTPException:
        raise
    except Exception as e:
        err_name = type(e).__name__
        logger.exception("Live quote failed for %s: %s", symbol, err_name)
        if "RateLimit" in err_name or "rate" in str(e).lower():
            raise HTTPException(429, "Yahoo Finance rate limit reached. Please try again in a minute.")
        raise HTTPException(500, "Failed to fetch live quote")
