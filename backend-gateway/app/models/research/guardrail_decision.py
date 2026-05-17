"""``research_guardrail_decisions`` — input/output guardrail log (Req 16.11)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .run import ResearchRun


class ResearchGuardrailDecision(Base):
    """One allow/modify/refuse decision from the Guardrail_Layer."""

    __tablename__ = "research_guardrail_decisions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # run_id is nullable: input-phase refusals can fire before a run row
    # has been created (design §3.5 / Req 16.11).
    run_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    # input | output
    phase: Mapped[str] = mapped_column(String(8), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # allow | modify | refuse
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Optional["ResearchRun"]] = relationship(back_populates="guardrail_decisions")
