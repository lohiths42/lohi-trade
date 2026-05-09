"""Order response models."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.models.base import CamelModel


class OrderResponse(CamelModel):
    id: int
    order_id: str = Field(alias="orderId")
    trade_id: Optional[str] = None
    symbol: str
    side: str
    order_type: str
    quantity: int = Field(alias="qty")
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    status: str
    broker_order_id: Optional[str] = None
    filled_qty: int = 0
    filled_price: Optional[float] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
