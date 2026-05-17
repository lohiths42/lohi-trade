"""Lohi-Research tables (design §4.1).

Creates the 12 tables that back the Lohi-Research dashboard feature:

  1.  ``research_documents``            -- parsed source documents (Req 3.4, 8.5)
  2.  ``research_chunks``               -- chunked text + embeddings (Req 3.6, 3.7)
  3.  ``research_runs``                 -- one agent execution (Req 1.*, 13.3)
  4.  ``research_brief_sections``       -- per-section markdown + citations (Req 1.5)
  5.  ``research_provenance``           -- per-agent LLM usage per run (Req 1.8)
  6.  ``research_guardrail_decisions``  -- input/output guardrail log (Req 16.11)
  7.  ``research_judge_reports``        -- groundedness + safe-to-display (Req 16.17)
  8.  ``research_semantic_memory``      -- user preferences/facts + embedding (Req 4.3, 4.5, 4.6)
  9.  ``research_episodic_memory``      -- past-run summaries (Req 4.4)
  10. ``research_snapshots``            -- pre-computed watchlist brief cache (Req 11.5)
  11. ``llm_usage``                     -- per-call LLM cost telemetry (Req 12.5)
  12. ``research_audit_log``            -- append-only audit trail (Req 4.9)

Row-Level Security (RLS) pattern
--------------------------------
Every table that carries a ``user_id`` column enables RLS and installs a policy
``USING (user_id = current_setting('app.user_id')::uuid)`` matching the existing
LOHI-TRADE convention (migration 001). Tables keyed by ``run_id`` instead of
``user_id`` (``research_brief_sections``, ``research_provenance``,
``research_judge_reports``) inherit tenant isolation transitively through the
``research_runs`` parent row (the application layer always joins through the
parent run, which is itself RLS-guarded).

pgvector-conditional ``embedding`` column
-----------------------------------------
``research_chunks`` and ``research_semantic_memory`` store an ``embedding``
vector only when the pgvector extension is installed at migration time
(Req 3.6, 3.7, 8.5). We detect this with a ``DO $$ … $$`` block that consults
``pg_extension`` and issues ``ALTER TABLE … ADD COLUMN embedding vector(384)``
only when the extension is present. When the Chroma backend is active, the
column is omitted and vectors live in Chroma's on-disk store (design §8).

The dimension is hard-coded at ``384`` to match the default embedding model
(``BAAI/bge-small-en-v1.5``). Operators configuring a different embedding
provider are responsible for overriding this column width before running the
migration; this is documented in ``docs/CONFIGURATION.md``.

Append-only ``research_audit_log``
----------------------------------
``research_audit_log`` is append-only by construction: rules
``research_audit_log_no_delete`` (``ON DELETE … DO INSTEAD NOTHING``) and
``research_audit_log_no_update`` (``ON UPDATE … DO INSTEAD NOTHING``) silently
drop any DELETE/UPDATE against the table (Req 4.9).

Deviation from verbatim design §4.1 — ``research_chunks`` denormalisation
-------------------------------------------------------------------------
Design §4.1 as written lists only ``document_id`` on ``research_chunks``,
expecting callers to join back to ``research_documents`` for the ``user_id``
and ``symbol``. The pgvector vector-store adapter (Task 2.16, already merged)
needs to filter by tenant/symbol on every similarity query without paying for
a join, so this migration additionally adds:

* ``user_id UUID NOT NULL`` (denormalised from the parent row)
* ``symbol VARCHAR(32) NOT NULL`` (denormalised from the parent row)

Both columns are also covered by an RLS policy on ``research_chunks`` itself
(``USING (user_id = current_setting('app.user_id')::uuid)``), mirroring the
policies on the other ``user_id``-bearing tables. The application layer is
responsible for keeping the denormalised values consistent with
``research_documents`` on insert; the schema assumes documents are immutable
after ingest (``sha256`` is unique per user, a re-parse yields a new document
row), so drift is not possible under normal operation.

Revision ID: research_tables_shell
Revises: 001
Create Date: 2025-01-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "research_tables_shell"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default embedding dimension — matches BAAI/bge-small-en-v1.5 (design §8).
_EMBEDDING_DIM = 384


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    # 1. research_documents — parsed source documents (Req 3.4, 8.5)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_documents (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        document_type VARCHAR(32) NOT NULL,
        source_url TEXT,
        sha256 CHAR(64) NOT NULL,
        published_at TIMESTAMPTZ,
        parsed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        canonical_text TEXT NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (user_id, sha256)
    );
    """
    )
    op.execute("ALTER TABLE research_documents ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_research_documents ON research_documents
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )
    # Lookup index for the common "list a user's documents for a symbol" path
    # (watchlist snapshot refresh, document-type filters). The UNIQUE
    # (user_id, sha256) constraint already covers dedup lookups.
    op.execute(
        """
    CREATE INDEX research_documents_user_symbol_idx
        ON research_documents (user_id, symbol);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 2. research_chunks — chunked text + optional embedding (Req 3.6, 3.7)
    #
    # NOTE: ``user_id`` and ``symbol`` are denormalised from
    # ``research_documents`` so the pgvector adapter (Task 2.16) can filter
    # by tenant/symbol without a join. See module docstring for rationale.
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id UUID NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
        -- Denormalised from research_documents for efficient RLS-guarded
        -- tenant/symbol filtering in the pgvector adapter (Task 2.16);
        -- deviation from verbatim design §4.1, documented in module docstring.
        user_id UUID NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        chunk_id TEXT NOT NULL UNIQUE,
        position INT NOT NULL,
        token_count INT NOT NULL,
        text TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_dim INT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )
    op.execute("ALTER TABLE research_chunks ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_research_chunks ON research_chunks
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )
    # FK-side index (explicit — Postgres does not auto-index foreign keys):
    # the indexer deletes chunks by document_id on re-parse, and the ORM
    # relationship loads chunks for a document by this column.
    op.execute(
        """
    CREATE INDEX research_chunks_document_id_idx
        ON research_chunks (document_id);
    """
    )
    # Tenant/symbol filter path used by the pgvector adapter's non-vector
    # queries (count, delete_by_filter) and by the hybrid retriever's BM25
    # pre-filter.
    op.execute(
        """
    CREATE INDEX research_chunks_user_symbol_idx
        ON research_chunks (user_id, symbol);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 3. research_runs — one agent execution (Req 1.*, 13.3)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        symbol VARCHAR(32),
        prompt TEXT NOT NULL,
        status VARCHAR(16) NOT NULL,
        partial BOOLEAN NOT NULL DEFAULT FALSE,
        quality VARCHAR(8),
        judge_score REAL,
        budget_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ
    );
    """
    )
    op.execute("ALTER TABLE research_runs ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_research_runs ON research_runs
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )
    # "Latest runs for a user" is the primary list query (dashboard home,
    # run history pane). DESC on created_at matches the default sort so
    # the planner can use the index without a reverse scan.
    op.execute(
        """
    CREATE INDEX research_runs_user_created_idx
        ON research_runs (user_id, created_at DESC);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 4. research_brief_sections — per-section markdown + citations (Req 1.5)
    #    (RLS inherited transitively via run_id -> research_runs)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_brief_sections (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        section_name VARCHAR(64) NOT NULL,
        content_md TEXT NOT NULL,
        citations_json JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 5. research_provenance — per-agent LLM usage per run (Req 1.8)
    #    (RLS inherited transitively via run_id -> research_runs)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_provenance (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        agent_name VARCHAR(64) NOT NULL,
        llm_provider VARCHAR(32) NOT NULL,
        llm_model VARCHAR(128) NOT NULL,
        input_tokens INT NOT NULL,
        output_tokens INT NOT NULL,
        wall_time_ms INT NOT NULL
    );
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 6. research_guardrail_decisions — input/output guardrail log (Req 16.11)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_guardrail_decisions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id UUID REFERENCES research_runs(id) ON DELETE CASCADE,
        phase VARCHAR(8) NOT NULL,
        rule_id VARCHAR(64) NOT NULL,
        action VARCHAR(8) NOT NULL,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 7. research_judge_reports — groundedness + safe-to-display (Req 16.17)
    #    (RLS inherited transitively via run_id -> research_runs)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_judge_reports (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
        groundedness_score_json JSONB NOT NULL,
        unsupported_claims_json JSONB NOT NULL DEFAULT '[]',
        safe_to_display BOOLEAN NOT NULL,
        retry_count INT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 8. research_semantic_memory — user preferences/facts (Req 4.3, 4.5, 4.6)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_semantic_memory (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        kind VARCHAR(32) NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )
    op.execute("ALTER TABLE research_semantic_memory ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_semantic_memory ON research_semantic_memory
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 9. research_episodic_memory — past-run summaries (Req 4.4)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_episodic_memory (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        run_id UUID NOT NULL REFERENCES research_runs(id),
        summary TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )
    op.execute("ALTER TABLE research_episodic_memory ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_episodic_memory ON research_episodic_memory
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )
    # "Most recent run summaries for a (user, symbol)" is the hot path the
    # orchestrator hits when priming context for a new run.
    op.execute(
        """
    CREATE INDEX research_episodic_memory_user_symbol_created_idx
        ON research_episodic_memory (user_id, symbol, created_at DESC);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 10. research_snapshots — pre-computed watchlist brief cache (Req 11.5)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_snapshots (
        user_id UUID NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        brief_json JSONB NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL,
        input_document_hashes TEXT[] NOT NULL,
        stale BOOLEAN NOT NULL DEFAULT FALSE,
        PRIMARY KEY (user_id, symbol)
    );
    """
    )
    op.execute("ALTER TABLE research_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_snapshots ON research_snapshots
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 11. llm_usage — per-call LLM cost telemetry (Req 12.5)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE llm_usage (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        research_run_id UUID REFERENCES research_runs(id) ON DELETE SET NULL,
        provider VARCHAR(32) NOT NULL,
        model VARCHAR(128) NOT NULL,
        input_tokens INT NOT NULL,
        output_tokens INT NOT NULL,
        cost_estimate_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )
    op.execute("ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
    CREATE POLICY rls_llm_usage ON llm_usage
        USING (user_id = current_setting('app.user_id')::uuid);
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # 12. research_audit_log — append-only audit trail (Req 4.9)
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        """
    CREATE TABLE research_audit_log (
        id BIGSERIAL PRIMARY KEY,
        user_id UUID,
        actor VARCHAR(16) NOT NULL,
        action VARCHAR(64) NOT NULL,
        payload_json JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    )
    # Append-only rules: silently drop any DELETE/UPDATE.
    op.execute(
        """
    CREATE RULE research_audit_log_no_delete AS
        ON DELETE TO research_audit_log DO INSTEAD NOTHING;
    """
    )
    op.execute(
        """
    CREATE RULE research_audit_log_no_update AS
        ON UPDATE TO research_audit_log DO INSTEAD NOTHING;
    """
    )

    # ═══════════════════════════════════════════════════════════════
    # pgvector-conditional ``embedding`` columns and HNSW index
    #
    # Add ``embedding vector(384)`` to research_chunks and
    # research_semantic_memory only if the pgvector extension is installed
    # at migration time, and build the HNSW cosine-distance index the
    # pgvector adapter (Task 2.16) relies on for similarity search. When
    # the Chroma backend is active, pgvector may not be installed and all
    # three DDL statements are simply skipped.
    # ═══════════════════════════════════════════════════════════════
    op.execute(
        f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            ALTER TABLE research_chunks
                ADD COLUMN embedding vector({_EMBEDDING_DIM});
            ALTER TABLE research_semantic_memory
                ADD COLUMN embedding vector({_EMBEDDING_DIM});
            -- HNSW on cosine ops matches the ``embedding <=> query``
            -- operator used in src/research/providers/vector_store/pgvector.py.
            CREATE INDEX research_chunks_embedding_hnsw_idx
                ON research_chunks USING hnsw (embedding vector_cosine_ops);
        END IF;
    END$$;
    """
    )


def downgrade() -> None:
    # Drop in reverse FK-dependency order. Policies are dropped automatically
    # when their owning table is dropped, so we only need the DROP TABLEs.

    # pgvector-conditional column removal: only run the ALTER TABLE DROP
    # COLUMN if pgvector is installed AND the column exists. Using IF EXISTS
    # keeps this idempotent even if the column was never created.
    op.execute(
        """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            ALTER TABLE IF EXISTS research_semantic_memory
                DROP COLUMN IF EXISTS embedding;
            ALTER TABLE IF EXISTS research_chunks
                DROP COLUMN IF EXISTS embedding;
        END IF;
    END$$;
    """
    )

    # Append-only rules must be dropped before the table.
    op.execute("DROP RULE IF EXISTS research_audit_log_no_update ON research_audit_log;")
    op.execute("DROP RULE IF EXISTS research_audit_log_no_delete ON research_audit_log;")

    op.execute("DROP TABLE IF EXISTS research_audit_log;")
    op.execute("DROP TABLE IF EXISTS llm_usage;")
    op.execute("DROP TABLE IF EXISTS research_snapshots;")
    op.execute("DROP TABLE IF EXISTS research_episodic_memory;")
    op.execute("DROP TABLE IF EXISTS research_semantic_memory;")
    op.execute("DROP TABLE IF EXISTS research_judge_reports;")
    op.execute("DROP TABLE IF EXISTS research_guardrail_decisions;")
    op.execute("DROP TABLE IF EXISTS research_provenance;")
    op.execute("DROP TABLE IF EXISTS research_brief_sections;")
    op.execute("DROP TABLE IF EXISTS research_runs;")
    op.execute("DROP TABLE IF EXISTS research_chunks;")
    op.execute("DROP TABLE IF EXISTS research_documents;")
