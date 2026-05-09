"""Trades endpoints."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.trades import TradeResponse
from app.services import db_service

router = APIRouter()


@router.get("/trades", response_model=List[TradeResponse])
def list_trades(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    try:
        return db_service.get_trades(start_date=start_date, end_date=end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
