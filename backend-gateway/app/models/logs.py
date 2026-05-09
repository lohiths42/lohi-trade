"""Log response models."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.models.base import CamelModel


class LogResponse(CamelModel):
    id: int
    event_type: str
    component: str
    message: str
    metadata: Optional[str] = None
    created_at: datetime
