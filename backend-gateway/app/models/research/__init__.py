"""SQLAlchemy 2.0 ORM models for the Lohi-Research schema (design §4.1).

This package is a **typed schema reference** for the 12 tables created by
``backend-gateway/alembic/versions/002_research_tables.py``. It is the
autogenerate target for any future Alembic revisions that modify this
subsystem's schema.

Coexistence with ``app/models/*.py``
------------------------------------
The sibling modules under ``backend-gateway/app/models/`` (``analytics.py``,
``orders.py``, ``positions.py``, ``trades.py`` …) are **Pydantic response
models**, not SQLAlchemy ORM classes. They shape JSON payloads returned by
the FastAPI layer and are unrelated to the ORM layer defined here.

The LOHI-TRADE runtime query path remains **raw asyncpg** everywhere — the
research service acquires pooled connections, sets ``app.user_id`` for RLS,
and issues parameterised SQL directly. These ORM classes are not wired into
that path and are not intended to supplant it. They exist to:

1. Give type checkers a single source of truth for column shapes when
   writing or reviewing asyncpg queries against the research schema.
2. Serve as the authoritative model metadata for Alembic autogeneration on
   subsequent schema changes.

``embedding`` column handling
-----------------------------
The ``embedding`` column on :class:`ResearchChunk` and
:class:`ResearchSemanticMemory` is **intentionally omitted** from the ORM
layer. It is conditionally created by the Alembic migration based on whether
the pgvector extension is present (see the migration's module docstring); at
the Python level it is accessed exclusively through the
:class:`PgVectorVectorStore` adapter (Task 2.16), which owns the
conditional-column story. Keeping it out of the ORM avoids either a hard
``pgvector`` Python dependency at the model layer or an
``Optional[list[float]]`` sentinel that would leak infrastructure concerns.

Package layout
--------------
Each table gets its own module so cross-module ``relationship`` hints stay
readable and ``TYPE_CHECKING`` guards prevent circular imports. Concrete
classes are re-exported here for flat access:

    from app.models.research import ResearchDocument, ResearchChunk
"""

from __future__ import annotations

from .audit_log import ResearchAuditLog
from .base import Base
from .brief_section import ResearchBriefSection
from .chunk import ResearchChunk
from .document import ResearchDocument
from .episodic_memory import ResearchEpisodicMemory
from .guardrail_decision import ResearchGuardrailDecision
from .judge_report import ResearchJudgeReport
from .llm_usage import LLMUsage
from .provenance import ResearchProvenance
from .run import ResearchRun
from .semantic_memory import ResearchSemanticMemory
from .snapshot import ResearchSnapshot

__all__ = [
    "Base",
    "LLMUsage",
    "ResearchAuditLog",
    "ResearchBriefSection",
    "ResearchChunk",
    "ResearchDocument",
    "ResearchEpisodicMemory",
    "ResearchGuardrailDecision",
    "ResearchJudgeReport",
    "ResearchProvenance",
    "ResearchRun",
    "ResearchSemanticMemory",
    "ResearchSnapshot",
]
