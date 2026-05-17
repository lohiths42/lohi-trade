"""``research_judge_reports`` — groundedness + safe-to-display (Req 16.17)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .run import ResearchRun


class ResearchJudgeReport(Base):
    """Judge_LLM verdict for a :class:`ResearchRun`."""

    __tablename__ = "research_judge_reports"

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
    groundedness_score_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    unsupported_claims_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    safe_to_display: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["ResearchRun"] = relationship(back_populates="judge_reports")
