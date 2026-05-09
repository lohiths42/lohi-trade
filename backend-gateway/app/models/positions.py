"""Position response models."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.models.base import CamelModel


class PositionResponse(CamelModel):
    id: int
    trade_id: str
    symbol: str
    side: str
    strategy: str
    quantity: int = Field(alias="qty")
    entry_price: float
    current_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    stop_loss: float
    target: float
    entry_time: datetime


class ClosePositionRequest(BaseModel):
    reason: str = "manual_close"
