"""``research_episodic_memory`` — past-run summaries (Req 4.4)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .run import ResearchRun


class ResearchEpisodicMemory(Base):
    """A short summary of a prior :class:`ResearchRun`, keyed by user+symbol."""

    __tablename__ = "research_episodic_memory"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("research_runs.id"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["ResearchRun"] = relationship(back_populates="episodic_summaries")
