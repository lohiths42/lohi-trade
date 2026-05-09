"""Bias and news endpoints."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.bias import BiasResponse, NewsResponse
from app.services import db_service

router = APIRouter()


@router.get("/bias", response_model=List[BiasResponse])
def list_bias():
    try:
        return db_service.get_bias()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bias/{ticker}", response_model=BiasResponse)
def get_bias_ticker(ticker: str):
    result = db_service.get_bias_for_ticker(ticker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No bias data for {ticker}")
    return result


@router.get("/news", response_model=List[NewsResponse])
def list_news(
    ticker: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        return db_service.get_news(ticker=ticker, sentiment=sentiment, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
