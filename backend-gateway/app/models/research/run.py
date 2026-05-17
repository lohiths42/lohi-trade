"""``research_runs`` — one agent execution (Req 1.*, 13.3)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Float, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .brief_section import ResearchBriefSection
    from .episodic_memory import ResearchEpisodicMemory
    from .guardrail_decision import ResearchGuardrailDecision
    from .judge_report import ResearchJudgeReport
    from .llm_usage import LLMUsage
    from .provenance import ResearchProvenance


class ResearchRun(Base):
    """A single Orchestrator execution for one user prompt."""

    __tablename__ = "research_runs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | running | done | error | partial
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # normal | low
    quality: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    judge_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    budget_exhausted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    brief_sections: Mapped[list["ResearchBriefSection"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    provenance: Mapped[list["ResearchProvenance"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    guardrail_decisions: Mapped[list["ResearchGuardrailDecision"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    judge_reports: Mapped[list["ResearchJudgeReport"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    episodic_summaries: Mapped[list["ResearchEpisodicMemory"]] = relationship(back_populates="run")
    llm_usage: Mapped[list["LLMUsage"]] = relationship(back_populates="run")
