"""Log response models."""

from datetime import datetime
from typing import Optional

from app.models.base import CamelModel


class LogResponse(CamelModel):
    id: int
    event_type: str
    component: str
    message: str
    metadata: Optional[str] = None
    created_at: datetime
