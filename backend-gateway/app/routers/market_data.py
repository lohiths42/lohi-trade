"""Market Data API router — real-time prices, order book depth, corporate actions, historical data.

Endpoints:
  GET /market/price/{symbol}           — latest price data for a symbol
  GET /market/depth/{symbol}           — order book depth (top 5 bid/ask)
  GET /market/corporate-actions        — corporate action history with optional filters
  GET /market/historical/{symbol}      — historical OHLCV data by date range and timeframe

All endpoints require authenticated user with TRADER or ADMIN role.
Prefix: /api/v2

Requirements: 25.2, 25.3, 27.4, 28.4
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.middleware.rbac import require_role
from app.routers.auth_v2 import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────


class PriceResponse(BaseModel):
    """Real-time price data for a security (Req 25.2)."""

    symbol: str
    ltp: float
    last_traded_qty: int = 0
    volume: int = 0
    best_bid_price: float = 0.0
    best_bid_qty: int = 0
    best_ask_price: float = 0.0
    best_ask_qty: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    previous_close: float = 0.0
    timestamp: Optional[str] = None
    exchange: str = "NSE"


class OrderBookLevelResponse(BaseModel):
    price: float
    quantity: int


class DepthResponse(BaseModel):
    """Order book depth — top 5 bid/ask levels (Req 25.3)."""

    symbol: str
    bids: List[OrderBookLevelResponse] = []
    asks: List[OrderBookLevelResponse] = []
    timestamp: Optional[str] = None


class CorporateActionResponse(BaseModel):
    """A single corporate action record (Req 27.4)."""

    symbol: str
    action_type: str
    ex_date: Optional[str] = None
    record_date: Optional[str] = None
    details: Dict[str, Any] = {}
    source: str = "NSE"
    fetched_at: Optional[str] = None


class CorporateActionsListResponse(BaseModel):
    actions: List[CorporateActionResponse]
    count: int


class OHLCVResponse(BaseModel):
    """A single OHLCV bar."""

    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoricalDataResponse(BaseModel):
    """Historical OHLCV data response (Req 28.4)."""

    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    bars: List[OHLCVResponse]
    count: int


class MessageResponse(BaseModel):
    message: str


# ── Service dependencies ─────────────────────────────────────────────────────

_market_data_collector = None
_corporate_actions_collector = None
_historical_data_service = None


def set_market_data_services(
    market_data_collector=None,
    corporate_actions_collector=None,
    historical_data_service=None,
) -> None:
    """Called at app startup to inject service instances."""
    global _market_data_collector, _corporate_actions_collector, _historical_data_service
    if market_data_collector is not None:
        _market_data_collector = market_data_collector
    if corporate_actions_collector is not None:
        _corporate_actions_collector = corporate_actions_collector
    if historical_data_service is not None:
        _historical_data_service = historical_data_service


def get_market_data_collector():
    if _market_data_collector is None:
        raise HTTPException(status_code=503, detail="Market data service not initialized")
    return _market_data_collector


def get_corporate_actions_collector():
    if _corporate_actions_collector is None:
        raise HTTPException(status_code=503, detail="Corporate actions service not initialized")
    return _corporate_actions_collector


def get_historical_data_service():
    if _historical_data_service is None:
        raise HTTPException(status_code=503, detail="Historical data service not initialized")
    return _historical_data_service


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/market/price/{symbol}", response_model=PriceResponse)
async def get_price(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    collector=Depends(get_market_data_collector),
):
    """Get latest price data for a symbol.

    Returns LTP, volume, bid/ask, OHLC, and previous close from the
    real-time market data collector's Redis cache.

    Requirements: 25.2
    """
    try:
        # Try to get price from Redis event bus cache
        data = collector.event_bus.redis_client.hgetall(f"price:{symbol.upper()}")

        if not data:
            raise HTTPException(
                status_code=404,
                detail=f"No price data available for '{symbol}'",
            )

        return PriceResponse(
            symbol=symbol.upper(),
            ltp=float(data.get("ltp", 0)),
            last_traded_qty=int(data.get("last_traded_qty", 0)),
            volume=int(data.get("volume", 0)),
            best_bid_price=float(data.get("bid", 0)),
            best_bid_qty=int(data.get("bid_qty", 0)),
            best_ask_price=float(data.get("ask", 0)),
            best_ask_qty=int(data.get("ask_qty", 0)),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            previous_close=float(data.get("previous_close", 0)),
            timestamp=data.get("timestamp"),
            exchange=data.get("exchange", "NSE"),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get price for symbol=%s", symbol)
        raise HTTPException(status_code=500, detail="Failed to retrieve price data")


@router.get("/market/depth/{symbol}", response_model=DepthResponse)
async def get_depth(
    symbol: str,
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    collector=Depends(get_market_data_collector),
):
    """Get order book depth (top 5 bid/ask levels) for a symbol.

    Requirements: 25.3
    """
    try:
        depth = collector.get_order_book_depth(symbol.upper())
        if depth is None:
            raise HTTPException(
                status_code=404,
                detail=f"No order book depth available for '{symbol}'",
            )

        return DepthResponse(
            symbol=depth.symbol,
            bids=[
                OrderBookLevelResponse(price=level.price, quantity=level.quantity)
                for level in depth.bids
            ],
            asks=[
                OrderBookLevelResponse(price=level.price, quantity=level.quantity)
                for level in depth.asks
            ],
            timestamp=depth.timestamp.isoformat() if depth.timestamp else None,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get depth for symbol=%s", symbol)
        raise HTTPException(status_code=500, detail="Failed to retrieve order book depth")


@router.get("/market/corporate-actions", response_model=CorporateActionsListResponse)
async def get_corporate_actions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    action_type: Optional[str] = Query(
        None, description="Filter by action type (DIVIDEND, SPLIT, BONUS, RIGHTS, BUYBACK)"
    ),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    collector=Depends(get_corporate_actions_collector),
):
    """Get corporate action history with optional filters.

    Requirements: 27.4
    """
    try:
        from src.ingestion.corporate_actions_collector import CorporateActionType

        ca_type = None
        if action_type:
            try:
                ca_type = CorporateActionType(action_type.upper())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid action_type '{action_type}'. Must be one of: DIVIDEND, SPLIT, BONUS, RIGHTS, BUYBACK",
                )

        actions = collector.get_action_history(
            symbol=symbol.upper() if symbol else None,
            action_type=ca_type,
        )

        items = [
            CorporateActionResponse(
                symbol=a.symbol,
                action_type=a.action_type.value,
                ex_date=a.ex_date.isoformat() if a.ex_date else None,
                record_date=a.record_date.isoformat() if a.record_date else None,
                details=a.details,
                source=a.source,
                fetched_at=a.fetched_at.isoformat() if a.fetched_at else None,
            )
            for a in actions
        ]

        return CorporateActionsListResponse(actions=items, count=len(items))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get corporate actions")
        raise HTTPException(status_code=500, detail="Failed to retrieve corporate actions")


@router.get("/market/historical/{symbol}", response_model=HistoricalDataResponse)
async def get_historical(
    symbol: str,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    timeframe: str = Query("daily", description="Timeframe: daily, weekly, or monthly"),
    user_id: str = Depends(get_current_user_id),
    _rbac: dict = Depends(require_role("TRADER", "ADMIN")),
    service=Depends(get_historical_data_service),
):
    """Query historical OHLCV data by symbol, date range, and timeframe.

    Requirements: 28.4
    """
    try:
        from src.ingestion.historical_data_service import Timeframe

        # Parse dates
        try:
            sd = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format: '{start_date}'. Use YYYY-MM-DD.",
            )
        try:
            ed = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid end_date format: '{end_date}'. Use YYYY-MM-DD."
            )

        if sd > ed:
            raise HTTPException(
                status_code=400, detail="start_date must be before or equal to end_date"
            )

        # Parse timeframe
        try:
            tf = Timeframe(timeframe.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timeframe '{timeframe}'. Must be one of: daily, weekly, monthly",
            )

        bars = service.query(
            symbol=symbol.upper(),
            start_date=sd,
            end_date=ed,
            timeframe=tf,
        )

        return HistoricalDataResponse(
            symbol=symbol.upper(),
            timeframe=tf.value,
            start_date=sd.isoformat(),
            end_date=ed.isoformat(),
            bars=[
                OHLCVResponse(
                    symbol=b.symbol,
                    date=b.date.isoformat(),
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
                for b in bars
            ],
            count=len(bars),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get historical data for symbol=%s", symbol)
        raise HTTPException(status_code=500, detail="Failed to retrieve historical data")
