"""``research_chunks`` — chunked text for retrieval (Req 3.6, 3.7).

The ``embedding`` column is intentionally **not** declared on this ORM model.
It is pgvector-conditional at the schema level (see the module docstring of
``alembic/versions/002_research_tables.py``): depending on whether the
``vector`` extension is installed at migration time the physical column is
either ``vector(384)`` or absent. Vectors are read/written exclusively
through the :class:`PgVectorVectorStore` adapter (Task 2.16), which owns the
conditional-column story end to end. Adding ``embedding`` to this typed ORM
layer would either hard-require a pgvector Python dependency here or force
every caller to handle ``Optional[list[float]]`` sentinel semantics; both
options leak infrastructure concerns into the model layer.

The ``user_id`` and ``symbol`` columns are denormalised from
:class:`ResearchDocument` to let the pgvector adapter filter by tenant/symbol
without an extra join — see the Alembic migration docstring for the full
rationale.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .document import ResearchDocument


class ResearchChunk(Base):
    """A chunk of canonical text from a :class:`ResearchDocument`."""

    __tablename__ = "research_chunks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("research_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised from research_documents for pgvector adapter filtering.
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["ResearchDocument"] = relationship(back_populates="chunks")
