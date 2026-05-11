"""``research_brief_sections`` — per-section markdown + citations (Req 1.5)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .run import ResearchRun


class ResearchBriefSection(Base):
    """One named section of a :class:`ResearchBrief` produced for a run."""

    __tablename__ = "research_brief_sections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_name: Mapped[str] = mapped_column(String(64), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["ResearchRun"] = relationship(back_populates="brief_sections")
