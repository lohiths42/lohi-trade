"""``research_semantic_memory`` — user preferences and facts (Req 4.3, 4.5, 4.6).

The pgvector ``embedding`` column is intentionally omitted from this ORM
model for the same reason it is omitted from :class:`ResearchChunk` — it is
a runtime-conditional column that lives behind the pgvector adapter. See the
:mod:`backend-gateway.app.models.research` package docstring for the full
explanation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ResearchSemanticMemory(Base):
    """A preference, watchlist fact, or session summary for one user."""

    __tablename__ = "research_semantic_memory"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # preference | watchlist_fact | session_summary
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
