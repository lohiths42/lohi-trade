"""Trade response models."""

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.models.base import CamelModel


class TradeResponse(CamelModel):
    id: int
    trade_id: str
    symbol: str
    side: str
    strategy: str
    entry_price: float
    exit_price: Optional[float] = None
    quantity: int = Field(alias="qty")
    entry_time: datetime
    exit_time: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    stop_loss: float
    target: float
    exit_reason: Optional[str] = None
