"""Analytics endpoints — equity curve, daily P&L, strategy performance."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.analytics import EquityCurvePoint, DailyPnL, StrategyMetrics
from app.services import analytics_service

router = APIRouter()


@router.get("/analytics/equity-curve", response_model=List[EquityCurvePoint])
def equity_curve(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    try:
        return analytics_service.get_equity_curve(start_date, end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/daily-pnl", response_model=List[DailyPnL])
def daily_pnl(days: int = Query(30, ge=1, le=365)):
    try:
        return analytics_service.get_daily_pnl(days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/strategy-performance", response_model=List[StrategyMetrics])
def strategy_performance():
    try:
        return analytics_service.get_strategy_performance()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
