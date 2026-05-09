"""``research_snapshots`` — pre-computed watchlist brief cache (Req 11.5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Text

from .base import Base


class ResearchSnapshot(Base):
    """A cached :class:`ResearchBrief` keyed by ``(user_id, symbol)``."""

    __tablename__ = "research_snapshots"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False)
    brief_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    input_document_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False
    )
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
