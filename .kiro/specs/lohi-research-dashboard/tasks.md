# Implementation Plan: Lohi-Research Dashboard

## Overview

This plan realises `requirements.md` and `design.md` for the Lohi-Research multi-agent RAG
dashboard. Phases are ordered so prerequisites land first; within a phase, independent sub-tasks
are parallelisable (marked in each task's "What" paragraph). Backend code is Python 3.11+ with
Hypothesis for property tests; frontend code is TypeScript/React with `@fast-check/vitest`,
matching the existing project conventions.

Every task lists:

- **What**: concrete outcome the task must produce.
- **Satisfies**: requirement IDs from `requirements.md` and design sections from `design.md`.
- **Property tests**: (when applicable) the exact property from design §17.1 that must pass.
- **Files**: exact paths created or modified.
- **Blocked by**: earlier task numbers this task depends on (when applicable).

Sub-tasks postfixed with `*` are optional (primarily tests); the implementer MUST implement
un-starred sub-tasks and MUST NOT implement starred sub-tasks.

---

## Tasks

### Phase 1 — Scaffolding

- [x] 1. Project scaffolding for the `research` subsystem
  - [x] 1.1 Create `src/research/` package skeleton
    - What: Create the top-level package with empty `__init__.py` files and the subpackage tree
      matching design §3 — `providers/{llm,embeddings,vector_store}`, `ingest/{sources,parser}`,
      `index/`, `memory/`, `agents/`, `guardrails/{adapters,rules}`, `judge/`, `validators/`,
      `prompts/v1/`, `snapshot/`, `cache/`, `workers/`. No implementation; placeholder modules
      with docstrings only.
    - Satisfies: Req 8.6, design §3, §16.3.
    - Files: `src/research/__init__.py`, `src/research/providers/__init__.py`,
      `src/research/providers/llm/__init__.py`, `src/research/providers/embeddings/__init__.py`,
      `src/research/providers/vector_store/__init__.py`, `src/research/ingest/__init__.py`,
      `src/research/ingest/sources/__init__.py`, `src/research/ingest/parser/__init__.py`,
      `src/research/index/__init__.py`, `src/research/memory/__init__.py`,
      `src/research/agents/__init__.py`, `src/research/guardrails/__init__.py`,
      `src/research/guardrails/adapters/__init__.py`, `src/research/guardrails/rules/.gitkeep`,
      `src/research/judge/__init__.py`, `src/research/validators/__init__.py`,
      `src/research/prompts/__init__.py`, `src/research/prompts/v1/.gitkeep`,
      `src/research/snapshot/__init__.py`, `src/research/cache/__init__.py`,
      `src/research/workers/__init__.py`.

  - [x] 1.2 Redis stream + pubsub channel constants
    - What: Define module-level string constants for every new Redis key/stream from design §4.3
      (`research:runs`, `research:partials`, `research:index_events`,
      `research:snapshot_invalidations`, `research:latency_budget`, plus the
      `research:wm:*`, `research:emb:*`, `research:ret:*`, `research:llm:*`, `research:gr:rl:*`
      key templates). Values only; no client code.
    - Satisfies: Req 5.6–5.9, design §3.11, §4.3.
    - Files: `src/research/constants.py`.

  - [x] 1.3 Add `research:` block to `config/settings.yaml`
    - What: Append the full `research:` section from design §7.1 to `config/settings.yaml`
      (providers, vector_store with `backend: auto`, ingest, chunking, retrieval, memory,
      guardrails, judge, snapshot, latency_budgets, concurrency). All secrets reference
      `${ENV_VAR}` per Req 2.9.
    - Satisfies: Req 2.8, Req 2.9, Req 8.6, design §7.1.
    - Files: `config/settings.yaml`.

  - [x] 1.4 Create `.env.research.template`
    - What: Copy the template from design §7.2 verbatim — NVIDIA NIM key plus optional
      alternates, `LOHI_RESEARCH_OFFLINE=false`, optional external vector-store URLs.
    - Satisfies: Req 7.3, design §7.2.
    - Files: `.env.research.template`.

  - [x] 1.5 Alembic migration shell
    - What: Create an empty-bodied Alembic revision file that will host the 11 research tables
      in Phase 4. File should contain the standard Alembic header, `revision`/`down_revision`
      wired to the latest existing revision, and `upgrade()`/`downgrade()` that currently pass.
      The actual schema is added in Task 4.1.
    - Satisfies: Req 8.5, design §4.1.
    - Files: `backend-gateway/alembic/versions/00X_research_tables.py` (renumber against the
      current head revision at author time).

  - [x] 1.6 Feature flag + no-op health router
    - What: Add `research.enabled` config flag (default true), wire a minimal router mounted at
      `/api/v2/research/health` that returns a stub `HealthReport` with every component set to
      `"pending"`. The router must be loaded by `backend-gateway/app/main.py` only when
      `settings.research.enabled` is true. No dependency on the rest of Phase 1–20 at this
      point; this unblocks end-to-end wiring tests downstream.
    - Satisfies: Req 7.7, Req 8.2, design §3.12, §5.1.
    - Files: `backend-gateway/app/routers/research.py` (stub), `backend-gateway/app/main.py`
      (registration only), `backend-gateway/app/services/research_service.py` (stub with a
      single `async def health()` returning the pending payload), `config/settings.yaml`
      (add `research.enabled`).

  - [x] 1.7 Test harness directories
    - What: Create empty `tests/research/` and
      `Lohi-TRADE Web App Design/tests/research/` directories with `fixtures/` subfolders
      (`filings/`, `jailbreak/`, `refusal/`), a `conftest.py` skeleton for pytest that loads the
      in-memory fakes once they exist, and an empty Vitest suite stub. Actual fakes are added in
      Task 2.8.
    - Satisfies: Req 14.7, design §17.
    - Files: `tests/research/__init__.py`, `tests/research/conftest.py`,
      `tests/research/fixtures/filings/.gitkeep`, `tests/research/fixtures/jailbreak/.gitkeep`,
      `tests/research/fixtures/refusal/.gitkeep`,
      `Lohi-TRADE Web App Design/tests/research/.gitkeep`.

---

### Phase 2 — Provider-Agnostic Framework

- [x] 2. Provider-agnostic LLM, embeddings, and vector-store framework
  Blocked by: 1.1.

  - [x] 2.1 Base protocols and Provider_Contract
    - What: Implement `LLMProvider`, `EmbeddingsProvider`, `VectorStore` `Protocol`s plus the
      Pydantic types `Message`, `LLMParams`, `Completion`, `CompletionChunk`, `ChunkRecord`,
      `ChunkHit`, `RetrievalFilter`, and the `ProviderAuthError` exception class. `Completion`
      is the Provider_Contract surfaced to callers (Req 2.11).
    - Satisfies: Req 2.1–2.3, Req 2.10, Req 2.11, Req 14.2, design §3.1.
    - Files: `src/research/providers/base.py`, `src/research/providers/errors.py`.

  - [x] 2.2 Provider registry with one-line extension pattern
    - What: Implement `src/research/providers/registry.py` holding `LLM_FACTORIES`,
      `EMBEDDINGS_FACTORIES`, and `VECTOR_STORE_FACTORIES` dicts plus `get_llm`, `get_embeddings`,
      `get_vector_store` builders that consume the `research.providers.*` config. New provider
      = new file + one line in this module, as in design §9.
    - Satisfies: Req 2.12, design §3.1, §9.
    - Files: `src/research/providers/registry.py`.

  - [x] 2.3 NVIDIA NIM LLM adapter (default cloud)
    - What: Implement `complete`, `stream`, and auth-error translation hitting the
      `build.nvidia.com` OpenAI-compatible endpoint. Must map 401/403 to `ProviderAuthError`.
      Expose `build(cfg) -> LLMProvider`. Register in `registry.py`.
    - Satisfies: Req 2.4, Req 2.7, Req 2.10, design §3.1.
    - Files: `src/research/providers/llm/nvidia_nim.py`,
      `src/research/providers/registry.py`.

  - [x] 2.4 OpenAI LLM adapter
    - What: Same contract as 2.3 against OpenAI's chat-completions API. Register in
      `registry.py`.
    - Satisfies: Req 2.4, Req 2.10, design §3.1.
    - Files: `src/research/providers/llm/openai.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3 (registry pattern).

  - [x] 2.5 Anthropic LLM adapter
    - What: Same contract as 2.3 against the Anthropic Messages API.
    - Satisfies: Req 2.4, design §3.1.
    - Files: `src/research/providers/llm/anthropic.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.6 Gemini LLM adapter
    - What: Same contract as 2.3 against Google Generative Language API.
    - Satisfies: Req 2.4, design §3.1.
    - Files: `src/research/providers/llm/gemini.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.7 Groq LLM adapter
    - What: Same contract as 2.3 against Groq's OpenAI-compatible endpoint.
    - Satisfies: Req 2.4, design §3.1.
    - Files: `src/research/providers/llm/groq.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.8 Together LLM adapter
    - What: Same contract as 2.3 against Together's OpenAI-compatible endpoint.
    - Satisfies: Req 2.4, design §3.1.
    - Files: `src/research/providers/llm/together.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.9 OpenRouter LLM adapter
    - What: Same contract as 2.3 against OpenRouter's OpenAI-compatible endpoint.
    - Satisfies: Req 2.4, design §3.1.
    - Files: `src/research/providers/llm/openrouter.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.10 Ollama LLM adapter (offline default)
    - What: Same contract as 2.3 against the local Ollama `/api/chat` endpoint. Default model
      `llama3.1:8b` per design Open Issue #3.
    - Satisfies: Req 2.4, Req 7.5, design §3.1.
    - Files: `src/research/providers/llm/ollama.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.3.

  - [x] 2.11 sentence-transformers embeddings adapter (default local)
    - What: Wrap `sentence-transformers` with a model loader that defaults to
      `BAAI/bge-small-en-v1.5` (384-dim). Exposes `embed`, `model_id`, `dim`.
    - Satisfies: Req 2.5, design §3.1.
    - Files: `src/research/providers/embeddings/sentence_transformers.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.1.

  - [x] 2.12 NVIDIA NIM embeddings adapter
    - What: Implementation of `EmbeddingsProvider` hitting NIM embeddings endpoint.
    - Satisfies: Req 2.5, design §3.1.
    - Files: `src/research/providers/embeddings/nvidia_nim.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.11.

  - [x] 2.13 OpenAI embeddings adapter
    - What: Implementation of `EmbeddingsProvider` against OpenAI embeddings API.
    - Satisfies: Req 2.5, design §3.1.
    - Files: `src/research/providers/embeddings/openai.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.11.

  - [x] 2.14 Ollama embeddings adapter
    - What: Implementation of `EmbeddingsProvider` against Ollama `/api/embeddings`.
    - Satisfies: Req 2.5, Req 7.5, design §3.1.
    - Files: `src/research/providers/embeddings/ollama.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.11.

  - [x] 2.15 Chroma vector-store adapter (default self-hosted)
    - What: Embedded, on-disk Chroma at `data/research/chroma/`. Implement
      `upsert`/`similarity_search`/`delete_by_filter`/`count` with `user_id` + `symbol`
      namespacing in every filter.
    - Satisfies: Req 2.6, Req 2.13, Req 3.10, design §3.1.
    - Files: `src/research/providers/vector_store/chroma.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.1.

  - [x] 2.16 pgvector vector-store adapter (default SaaS)
    - What: Use the existing `DATABASE_URL` asyncpg pool; implement the same `VectorStore`
      contract against `research_chunks.embedding` (once column exists in Phase 4). Uses HNSW
      index per design Open Issue #7. Must set `app.user_id` before every query so RLS engages.
    - Satisfies: Req 2.6, Req 2.14, Req 3.10, Req 4.6, Req 8.5, design §3.1, §14.
    - Files: `src/research/providers/vector_store/pgvector.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.1.

  - [x] 2.17 Qdrant vector-store adapter (optional)
    - What: Implement the `VectorStore` contract against `qdrant-client`. Enabled only when
      `research.vector_store.backend: qdrant`.
    - Satisfies: Req 2.6, design §3.1.
    - Files: `src/research/providers/vector_store/qdrant.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.1.

  - [x] 2.18 LanceDB vector-store adapter (optional)
    - What: Implement the `VectorStore` contract against `lancedb`. Enabled only when
      `research.vector_store.backend: lancedb`.
    - Satisfies: Req 2.6, design §3.1.
    - Files: `src/research/providers/vector_store/lancedb.py`,
      `src/research/providers/registry.py`.
    - Blocked by: 2.1.

  - [x] 2.19 Fake providers and vector store for tests
    - What: Implement `FakeLLMProvider` (configurable latency + canned completions),
      `FakeEmbeddingsProvider` (deterministic 384-dim from SHA-256), `FakeVectorStore`
      (in-memory, list-backed). Register them under a `FAKE_FACTORIES` namespace so tests can
      swap them in via config. These are imported by every test in Phase 6–12.
    - Satisfies: Req 14.7, design §17.2.
    - Files: `tests/research/fakes/__init__.py`, `tests/research/fakes/llm.py`,
      `tests/research/fakes/embeddings.py`, `tests/research/fakes/vector_store.py`.
    - Blocked by: 2.1.

  - [x] 2.20 Property test — provider-swap invariance
    - What: Generate N synthetic `(messages, params)` pairs with Hypothesis; call `.complete()`
      against two different fake LLM implementations; assert the `Completion` Pydantic model
      validates in both cases and all field types match. Generate swaps across LLM, embeddings,
      and vector-store backends and assert callers see no shape change.
    - **Property 2: Provider-swap invariance**
    - **Validates: Req 14.2**
    - Files: `tests/research/test_prop_provider_swap.py`.
    - Blocked by: 2.1, 2.19.

---

### Phase 3 — Vector Store Auto-Selection

- [x] 3. Vector-store auto-selection at startup
  Blocked by: 2.2, 2.15, 2.16.

  - [x] 3.1 Postgres `vector` extension probe
    - What: Implement `probe_pgvector(database_url) -> bool` running
      `SELECT 1 FROM pg_extension WHERE extname='vector';` via asyncpg with a short timeout.
      Returns false on connection failure, missing extension, or timeout.
    - Satisfies: Req 2.14, design §8.
    - Files: `src/research/providers/vector_store/autoselect.py`.

  - [x] 3.2 Auto-selection wiring in the registry
    - What: When `research.vector_store.backend == auto`, call `probe_pgvector` once at boot and
      resolve to `pgvector` on hit, `chroma` otherwise. Log the decision once through
      `src/utils/logger.py`. Surface the resolved backend in `GET /api/v2/research/health`.
      Operator override `research.vector_store.backend=<backend>` always wins.
    - Satisfies: Req 2.13, Req 2.14, Req 2.15, Req 7.7, design §8, §15.
    - Files: `src/research/providers/registry.py`,
      `backend-gateway/app/services/research_service.py`.
    - Blocked by: 3.1.

  - [x] 3.3 Operator override path
    - What: Unit tests for each branch of the decision tree: (a) `backend: auto` + pgvector
      available → pgvector; (b) `backend: auto` + pgvector missing → chroma; (c) explicit
      `backend: chroma` even when pgvector available → chroma; (d) explicit `backend: qdrant` →
      qdrant; (e) unknown backend → structured error.
    - Satisfies: Req 2.15, design §8.
    - Files: `tests/research/test_autoselect.py`.
    - Blocked by: 3.2.

---

### Phase 4 — Persistence

- [x] 4. Postgres schema, RLS, and ORM models
  Blocked by: 1.5, 3.2.

  - [x] 4.1 Flesh out the Alembic migration
    - What: Add every DDL statement from design §4.1: `research_documents`, `research_chunks`,
      `research_runs`, `research_brief_sections`, `research_provenance`,
      `research_guardrail_decisions`, `research_judge_reports`, `research_semantic_memory`,
      `research_episodic_memory`, `research_snapshots`, `llm_usage`, `research_audit_log`, plus
      all RLS policies and the append-only `research_audit_log_no_delete`/`_no_update` rules.
      The `embedding VECTOR(dim)` column on `research_chunks` and `research_semantic_memory`
      must be added **only** when the pgvector backend is active at migration time — guard with
      a SQL check on `pg_extension`.
    - Satisfies: Req 3.4, Req 3.6, Req 3.7, Req 4.3–4.6, Req 8.5, Req 11.5, Req 12.5, Req 13.3,
      design §4.1.
    - Files: `backend-gateway/alembic/versions/00X_research_tables.py`.

  - [x] 4.2 SQLAlchemy models
    - What: One model class per table under `backend-gateway/app/models/research/`, matching
      design §4.1 column definitions. Include relationships (`research_runs` → sections,
      provenance, judge reports; `research_documents` → chunks). No query helpers here — those
      live in services.
    - Satisfies: Req 8.5, design §4.1.
    - Files: `backend-gateway/app/models/research/__init__.py`,
      `backend-gateway/app/models/research/document.py`,
      `backend-gateway/app/models/research/chunk.py`,
      `backend-gateway/app/models/research/run.py`,
      `backend-gateway/app/models/research/brief_section.py`,
      `backend-gateway/app/models/research/provenance.py`,
      `backend-gateway/app/models/research/guardrail_decision.py`,
      `backend-gateway/app/models/research/judge_report.py`,
      `backend-gateway/app/models/research/semantic_memory.py`,
      `backend-gateway/app/models/research/episodic_memory.py`,
      `backend-gateway/app/models/research/snapshot.py`,
      `backend-gateway/app/models/research/llm_usage.py`,
      `backend-gateway/app/models/research/audit_log.py`.

  - [x] 4.3 Per-request `app.user_id` helper for asyncpg
    - What: Add a small helper `set_rls_user_id(conn, user_id)` that runs
      `SELECT set_config('app.user_id', $1, true)` on an acquired asyncpg connection; wire it
      into the research service's connection-acquisition path so RLS engages transparently.
    - Satisfies: Req 4.6, Req 8.5, design §14.
    - Files: `backend-gateway/app/services/research/rls.py`,
      `backend-gateway/app/services/research_service.py`.

  - [x] 4.4 Unit + property test — RLS cross-user isolation
    - What: Seed two users `u_a`, `u_b` with rows in each RLS-protected table. Query as `u_a`
      via the helper from 4.3 and assert zero `u_b` rows ever surface. Hypothesis generator
      creates arbitrary `(symbol, content)` tuples for both users and iterates. Covers
      Semantic, Episodic, Working (Redis layer is tested in Phase 7), runs, snapshots,
      documents, chunks.
    - **Property 3: Memory scoping (RLS portion)**
    - **Validates: Req 14.3, Req 4.5, Req 4.6**
    - Files: `tests/research/test_prop_rls_isolation.py`.
    - Blocked by: 4.1, 4.2, 4.3.

---

### Phase 5 — Ingestion Pipeline

- [x] 5. Ingestion, parsing, chunking, and dedup
  Blocked by: 4.2.

  - [x] 5.1 `robots.txt` enforcement
    - What: Implement a per-source `RobotsChecker` with a local cache keyed by origin;
      `is_allowed(url, user_agent)` returns bool. Disallowed URLs are skipped silently and
      logged once per origin.
    - Satisfies: Req 3.3, Req 9.2, design §3.2.
    - Files: `src/research/ingest/robots.py`.

  - [x] 5.2 BSE announcement feed poller
    - What: Periodic poller (interval from `research.ingest.sources.bse_feed.poll_interval_sec`)
      that fetches the BSE public announcements JSON feed, filters by watchlist symbols, and
      publishes `{document_url, symbol, document_type, published_at}` onto
      `research:index_events`.
    - Satisfies: Req 3.1, design §3.2, §4.3.
    - Files: `src/research/ingest/sources/bse_feed.py`.
    - Blocked by: 5.1, 1.2.

  - [x] 5.3 NSE announcement feed poller
    - What: Same as 5.2 against the NSE announcements feed.
    - Satisfies: Req 3.1, design §3.2.
    - Files: `src/research/ingest/sources/nse_feed.py`.
    - Blocked by: 5.1, 1.2.

  - [x] 5.4 User-upload watch folder
    - What: `watchdog`-based observer that watches `data/research/uploads/*.pdf` and publishes
      an index event per new file. File path + symbol derived from filename prefix
      (`SYMBOL__*.pdf`).
    - Satisfies: Req 3.1, design §3.2.
    - Files: `src/research/ingest/sources/user_uploads.py`.
    - Blocked by: 1.2.

  - [ ] 5.5 Optional SEBI EDIFAR source*
    - What: Optional poller gated by `research.ingest.sources.sebi_edifar.enabled`. Same output
      shape as 5.2.
    - Satisfies: Req 3.2, design §3.2.
    - Files: `src/research/ingest/sources/sebi_edifar.py`.
    - Blocked by: 5.1.

  - [ ] 5.6 Optional company IR source*
    - What: Optional poller gated by `research.ingest.sources.company_ir.enabled` that reads a
      per-symbol URL list and publishes index events for new IR PDFs.
    - Satisfies: Req 3.2, design §3.2.
    - Files: `src/research/ingest/sources/company_ir.py`.
    - Blocked by: 5.1.

  - [x] 5.7 PDF parser
    - What: `pypdf`-based extractor producing canonical Markdown with tables preserved (falls
      back to `pdfplumber` for tabular pages per design Open Issue #5). Returns
      `(canonical_text, sections_raw)`.
    - Satisfies: Req 10.1, Req 10.5, design §3.2.
    - Files: `src/research/ingest/parser/pdf.py`.

  - [x] 5.8 HTML parser
    - What: `trafilatura` primary, `readability` fallback. Normalises whitespace, preserves
      tables as Markdown.
    - Satisfies: Req 10.1, design §3.2.
    - Files: `src/research/ingest/parser/html.py`.

  - [x] 5.9 XBRL parser
    - What: `arelle` wrapper that flattens instance documents to a canonical numerical table
      plus text facts.
    - Satisfies: Req 10.1, design §3.2.
    - Files: `src/research/ingest/parser/xbrl.py`.

  - [x] 5.10 Section tagger
    - What: Heading-based classifier that tags `management_commentary` vs `numerical_results`
      sections with `(start_offset, end_offset)` spans. Headings list is config-driven.
    - Satisfies: Req 10.6, design §3.2.
    - Files: `src/research/ingest/parser/sections.py`.
    - Blocked by: 5.7, 5.8, 5.9.

  - [x] 5.11 `CanonicalDoc` + pretty-printer
    - What: Implement the `CanonicalDoc` Pydantic model (design §3.2) plus
      `pretty_print(canonical_doc) -> str` that produces stable Markdown. Provides the
      round-trip pair required by Req 10.3.
    - Satisfies: Req 10.1, Req 10.2, Req 10.3, Req 10.4, design §3.2.
    - Files: `src/research/ingest/parser/canonical.py`.
    - Blocked by: 5.10.

  - [x] 5.12 Chunker
    - What: Recursive character splitter (defaults: 800 tokens, 120 overlap). Derives stable
      `chunk_id = sha256(document_sha256 || chunker_version || position)`.
    - Satisfies: Req 3.6, Req 3.12, design §3.2, §3.3.
    - Files: `src/research/ingest/chunker.py`.

  - [x] 5.13 Content-hash dedup
    - What: SHA-256 over `canonical_text + sorted metadata keys`; before persisting a document,
      check `research_documents` for existing `(user_id, sha256)` and skip parse/embed if hit.
    - Satisfies: Req 3.5, design §3.2.
    - Files: `src/research/ingest/dedup.py`.
    - Blocked by: 4.2.

  - [x] 5.14 Property test — parser round-trip
    - What: Hypothesis generator produces random `CanonicalDoc`s (Markdown with tables,
      section spans, numeric tokens). Property: `parse(pretty_print(doc)) ≡ doc` (equivalent
      modulo whitespace normalisation spelled out in the helper). Uses Hypothesis
      `@composite` strategies.
    - **Property 5: Parser round-trip**
    - **Validates: Req 14.5, Req 10.3**
    - Files: `tests/research/test_prop_parser_roundtrip.py`.
    - Blocked by: 5.11.

  - [x] 5.15 Property test — idempotent re-indexing
    - What: Generate a document, chunk it, re-generate with the same inputs; assert identical
      set of `chunk_id`s. Generator varies `position`, content length, whitespace — all should
      still produce deterministic IDs when content + chunker_version are unchanged.
    - **Property 4: Idempotent re-indexing**
    - **Validates: Req 14.4, Req 3.12**
    - Files: `tests/research/test_prop_reindex_idempotent.py`.
    - Blocked by: 5.12, 5.13.

---

### Phase 6 — Embeddings, Hybrid Retrieval, Reranking

- [x] 6. Index layer — hybrid retrieval + reranker + similarity floor
  Blocked by: 2.15, 2.16, 2.11, 5.12.

  - [x] 6.1 `HybridRetriever`
    - What: Parallel BM25 (rank-bm25 per design Open Issue #1) + dense search via the configured
      `EmbeddingsProvider` and `VectorStore`. Merge by configurable
      `bm25_weight`/`dense_weight`. Returns top-k `ChunkHit`s with per-strategy ranks preserved.
    - Satisfies: Req 3.8, Req 3.9, design §3.3.
    - Files: `src/research/index/retriever.py`.

  - [x] 6.2 Cross-encoder reranker
    - What: Wrapper around sentence-transformers `CrossEncoder` (default
      `BAAI/bge-reranker-base`, disabled by default per config). Consumes `HybridRetriever`
      top-k; re-scores and reorders.
    - Satisfies: Req 3.9, design §3.3.
    - Files: `src/research/index/reranker.py`.

  - [x] 6.3 Similarity-floor centralisation
    - What: Helper `similarity_floor_for(model_id) -> float` reading from
      `research.retrieval.similarity_floor.<model>`. Surfaced in the run trace.
    - Satisfies: Req 16.24, design §3.3, §12.
    - Files: `src/research/index/similarity_floor.py`.

  - [x] 6.4 Property test — citation integrity against the retriever
    - What: Against `FakeVectorStore` seeded with a generated corpus, every
      `Citation.chunk_id` produced by the retriever + synth pipeline must resolve against the
      store for `(user_id, symbol)`. Hypothesis varies corpus size and symbol count.
    - **Property 1: Citation integrity (retriever-side)**
    - **Validates: Req 14.1, Req 3.11**
    - Files: `tests/research/test_prop_citation_integrity.py`.
    - Blocked by: 6.1, 2.19.

---

### Phase 7 — Memory Layer

- [x] 7. Working, semantic, and episodic memory
  Blocked by: 2.11, 2.16, 4.2.

  - [x] 7.1 Working memory (Redis)
    - What: Sliding-window store at `research:wm:{user_id}:{conv_id}` holding the last N=12
      turns + a running summary. When total tokens exceed
      `research.memory.working.max_tokens` (default 4096), summarise the oldest turns via
      `research.providers.summarisation.*` and replace.
    - Satisfies: Req 4.1, Req 4.2, design §3.4, §4.3.
    - Files: `src/research/memory/working.py`.

  - [x] 7.2 Semantic memory (Postgres + vector)
    - What: Read/write on `research_semantic_memory`. Always scopes by `user_id`; writes set
      `app.user_id` via the helper from 4.3.
    - Satisfies: Req 4.3, Req 4.5, Req 4.6, design §3.4, §4.1.
    - Files: `src/research/memory/semantic.py`.

  - [x] 7.3 Episodic memory (Postgres)
    - What: Read/write on `research_episodic_memory` keyed by `(user_id, symbol)` with RLS.
      Append a summary row on each successful `Research_Run`.
    - Satisfies: Req 4.4, Req 4.7, design §3.4, §4.1.
    - Files: `src/research/memory/episodic.py`.

  - [x] 7.4 `memory.forget(user_id, scope)`
    - What: Deletes across Redis working memory, semantic memory, and episodic memory for the
      given scope (`all`, `working`, `semantic`, `episodic`, or `symbol:<SYMBOL>`). Scopes up
      to 10k rows must complete in ≤5 s. Writes a row to `research_audit_log` with
      `actor=user, action=memory_forget`.
    - Satisfies: Req 4.8, Req 4.9, design §3.4, §14.
    - Files: `src/research/memory/forget.py`.
    - Blocked by: 7.1, 7.2, 7.3.

  - [x] 7.5 Property test — memory scoping
    - What: For arbitrary user pairs `(u_a, u_b)` and arbitrary writes into each memory layer,
      a retrieval request as `u_a` returns zero rows whose `user_id == u_b` across Working,
      Semantic, and Episodic memory. Hypothesis strategy generates interleaved writes/reads.
    - **Property 3: Memory scoping**
    - **Validates: Req 14.3, Req 4.5**
    - Files: `tests/research/test_prop_memory_scoping.py`.
    - Blocked by: 7.1, 7.2, 7.3.

- [x] 8. Phase 1–7 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 8 — Caches and Latency Plumbing

- [x] 9. Redis caches + latency-budget plumbing
  Blocked by: 1.2.

  - [x] 9.1 Embedding cache
    - What: `get`/`set` around `research:emb:{embedding_model}:{sha256(text)}` with default TTL
      7 days. Integrated into each `EmbeddingsProvider.embed` via a wrapper.
    - Satisfies: Req 5.6, design §3.11, §4.3.
    - Files: `src/research/cache/embedding.py`.

  - [x] 9.2 Retrieval cache
    - What: `get`/`set` around
      `research:ret:{symbol}:{query_template_hash}:{sha256(sorted_doc_hashes)}`, default TTL
      5 min. Integrated into `HybridRetriever`.
    - Satisfies: Req 5.7, design §3.11.
    - Files: `src/research/cache/retrieval.py`.
    - Blocked by: 6.1.

  - [x] 9.3 LLM response cache
    - What: `get`/`set` around
      `research:llm:{provider}:{model}:{sha256(prompt)}:{sha256(context)}`, default TTL
      30 min. Bypassed when streaming is requested.
    - Satisfies: Req 5.8, design §3.11.
    - Files: `src/research/cache/llm.py`.

  - [x] 9.4 Latency-budget event emission
    - What: Helper `emit_latency_budget_exceeded(phase, observed_ms, budget_ms)` publishes a
      structured event on `research:latency_budget` pubsub and logs once through the structured
      logger. Wired into Orchestrator phases in Phase 12.
    - Satisfies: Req 5.9, design §3.11, §13.4.
    - Files: `src/research/cache/latency_events.py`.

---

### Phase 9 — Prompts and Guardrails

- [x] 10. Prompt templates and guardrails
  Blocked by: 2.1.

  - [x] 10.1 Versioned prompt templates (v1)
    - What: One Markdown file per Sub_Agent and the Judge under `src/research/prompts/v1/`,
      each following the shared skeleton from design §3.9 (fenced `<|CONTEXT|>` markers,
      `{{REFUSAL_POLICY_BLOCK}}`, `{{OUTPUT_SCHEMA}}`, `{{USER_PROMPT}}`, explicit
      closed-book instructions).
    - Satisfies: Req 16.6, Req 16.25, design §3.9.
    - Files: `src/research/prompts/v1/orchestrator.md`,
      `src/research/prompts/v1/filings_agent.md`,
      `src/research/prompts/v1/fundamentals_agent.md`,
      `src/research/prompts/v1/news_sentiment_agent.md`,
      `src/research/prompts/v1/technicals_agent.md`,
      `src/research/prompts/v1/peer_sector_agent.md`,
      `src/research/prompts/v1/macro_agent.md`,
      `src/research/prompts/v1/report_synthesizer.md`,
      `src/research/prompts/v1/judge.md`,
      `src/research/prompts/loader.py`.

  - [x] 10.2 Refusal policy helper
    - What: Export `REFUSAL_POLICY_BLOCK` constant and `refuse(reason, rule_id) -> RefusalResult`
      helper used by every Sub_Agent and the gateway.
    - Satisfies: Req 16.29, Req 14.11, design §10.1.
    - Files: `src/research/guardrails/refusal_policy.py`.

  - [x] 10.3 Jailbreak ruleset v1
    - What: Create the YAML ruleset from design §10.3 (JB-001 system-prompt-override, JB-002
      prompt-leak, RP-001 trade-advice, TA-001 tool-allowlist, PII-001 PAN redaction) at the
      path referenced by `research.guardrails.ruleset`.
    - Satisfies: Req 16.2, Req 16.3, Req 16.4, Req 16.9, Req 16.10, design §10.3.
    - Files: `src/research/guardrails/rules/v1.yaml`.

  - [x] 10.4 Default `PydanticGuardrail`
    - What: Default input+output guard. Loads the YAML from 10.3, applies regex matches in
      order, enforces the rate limit per `user_id` via Redis counters at
      `research:gr:rl:{user_id}:{window_epoch}`, redacts PII in output phase, strips
      unauthorised function/tool-call tokens in output phase.
    - Satisfies: Req 16.1, Req 16.2, Req 16.5, Req 16.7, Req 16.9, Req 16.10, design §3.6,
      §10.1.
    - Files: `src/research/guardrails/pydantic_guard.py`.
    - Blocked by: 10.3.

  - [ ] 10.5 Optional small-model classifier*
    - What: Zero-shot jailbreak classifier using a cross-encoder NLI model, gated by
      `research.guardrails.classifier.enabled`. When enabled, runs in parallel with the regex
      pass; an `unsafe` score above threshold triggers `refuse`.
    - Satisfies: Req 16.2, design §3.6.
    - Files: `src/research/guardrails/classifier.py`.
    - Blocked by: 10.4.

  - [ ] 10.6 LangChain guardrail adapter*
    - What: Optional adapter implementing the `Guardrail` protocol via a LangChain
      `RunnableLambda` + `JsonOutputParser` chain.
    - Satisfies: Req 16.8, design §3.6, §10.2.
    - Files: `src/research/guardrails/adapters/langchain.py`.
    - Blocked by: 10.4.

  - [ ] 10.7 Guardrails-AI adapter*
    - What: Optional adapter wrapping `guardrails.Guard.from_rail(...)` with the same contract
      as `PydanticGuardrail`.
    - Satisfies: Req 16.8, design §3.6, §10.2.
    - Files: `src/research/guardrails/adapters/guardrails_ai.py`,
      `src/research/guardrails/rules/v1.rail`.
    - Blocked by: 10.4.

  - [ ] 10.8 NeMo-Guardrails adapter*
    - What: Optional adapter using `nemoguardrails.LLMRails`. Expects a sibling Rails config
      directory `src/research/guardrails/rules/nemo/`.
    - Satisfies: Req 16.8, design §3.6, §10.2.
    - Files: `src/research/guardrails/adapters/nemo.py`,
      `src/research/guardrails/rules/nemo/config.yml`.
    - Blocked by: 10.4.

  - [x] 10.9 Guardrail decision logging
    - What: Every allow/modify/refuse writes a row to `research_guardrail_decisions` and a
      structured log line; decisions are summarised into the `ResearchBrief.provenance` block.
    - Satisfies: Req 16.11, design §3.6, §4.1.
    - Files: `src/research/guardrails/logging.py`.
    - Blocked by: 4.2, 10.4.

  - [x] 10.10 Property test — guardrail-bypass invariance
    - What: Seed Hypothesis with the fixture jailbreak corpus at
      `tests/research/fixtures/jailbreak/`; generate mutations (character-level,
      homoglyph, whitespace, case, unicode confusables) via a `@composite` strategy; assert
      `PydanticGuardrail.check_input` returns `refuse` or `modify` for 100% of them.
    - **Property 7: Guardrail-bypass invariance**
    - **Validates: Req 14.8**
    - Files: `tests/research/test_prop_guardrail_bypass.py`,
      `tests/research/fixtures/jailbreak/corpus.yaml`.
    - Blocked by: 10.4.

---

### Phase 10 — Validators

- [x] 11. Deterministic validators
  Blocked by: 10.2, 6.1.

  - [x] 11.1 Numeric validator
    - What: Locale-aware parser that handles `₹1,234.56`, `1.2 Cr`, `2.5 lakh`, `2.5%`,
      `FY24`, `Q1 FY25`. Extracts every numeric token from a `ResearchBrief`; asserts each
      value appears within `epsilon` in at least one cited chunk. Violations become
      `UnsupportedClaim(reason="numeric_drift")`.
    - Satisfies: Req 14.10, Req 16.26, Req 16.27, design §3.8, §12.
    - Files: `src/research/validators/numeric_validator.py`.

  - [x] 11.2 Citation validator
    - What: Given a `ResearchBrief` and the run's `(user_id, symbol)` context, asserts every
      `Citation.chunk_id` exists in the active `VectorStore`. Violations become
      `UnsupportedClaim(reason="citation_mismatch")`.
    - Satisfies: Req 14.1, Req 3.11, design §3.8, §12.
    - Files: `src/research/validators/citation_validator.py`.

  - [x] 11.3 Refusal classifier
    - What: Regex + keyword classifier over the user prompt that returns a `RefusalReason`
      when the input matches the `Refusal_Policy` (buy/sell/hold, price targets, trade
      suggestions, order placement, code execution). Used by the Guardrail input phase and by
      the rule-based Judge.
    - Satisfies: Req 14.11, Req 16.28, design §3.8.
    - Files: `src/research/validators/refusal_classifier.py`.

  - [x] 11.4 Property test — numeric fidelity
    - What: Hypothesis generates briefs with assorted numeric tokens and matching/mismatching
      chunks; asserts that the validator flags every numeric value that is not within epsilon
      of at least one cited chunk, and never flags one that is.
    - **Property 9: Numeric fidelity**
    - **Validates: Req 14.10, Req 16.26**
    - Files: `tests/research/test_prop_numeric_fidelity.py`.
    - Blocked by: 11.1.

  - [x] 11.5 Property test — refusal policy
    - What: Hypothesis generates prompts matching the Refusal_Policy (composed of verb + action
      + entity templates). Asserts the system returns a refusal with an explanation and
      produces no recommendation, price target, or trade suggestion.
    - **Property 10: Refusal policy**
    - **Validates: Req 14.11, Req 16.28**
    - Files: `tests/research/test_prop_refusal_policy.py`,
      `tests/research/fixtures/refusal/corpus.yaml`.
    - Blocked by: 11.3.

  - [x] 11.6 Property test — citation integrity (end-to-end)
    - What: Generate synthetic briefs whose citations are a mix of real and fabricated
      `chunk_id`s against a `FakeVectorStore`. Assert the validator flags 100% of fabricated
      citations and 0% of real ones. Complements 6.4 which covers the retriever side.
    - **Property 1: Citation integrity (end-to-end)**
    - **Validates: Req 14.1**
    - Files: `tests/research/test_prop_citation_integrity_e2e.py`.
    - Blocked by: 11.2.

---

### Phase 11 — LLM-as-Judge

- [x] 12. Judge LLM, re-synthesis loop, fallbacks
  Blocked by: 10.1, 11.1, 11.2.

  - [x] 12.1 Judge invocation + `JudgeReport` schema
    - What: Implement `JudgeReport` (design §3.7) and `UnsupportedClaim` Pydantic models, and
      `judge.invoke(brief, chunks, numeric_findings) -> JudgeReport` which calls the role
      `research.providers.judge.*`. The prompt is `prompts/v1/judge.md`.
    - Satisfies: Req 16.12–16.17, Req 16.20, Req 16.21, design §3.7, §11.1.
    - Files: `src/research/judge/judge.py`.

  - [x] 12.2 Single re-synthesis loop
    - What: Pass/fail logic from design §11.2 — `safe_to_display == false` OR min section
      groundedness below `research.judge.min_score` triggers exactly one re-synthesis, feeding
      `unsupported_claims` + numeric findings back into the Report_Synthesizer context. A
      second failure yields `quality=low` with unsupported sections labelled "insufficient
      evidence".
    - Satisfies: Req 16.18, Req 16.19, design §11.2.
    - Files: `src/research/judge/resynthesis.py`.
    - Blocked by: 12.1.

  - [x] 12.3 Async-Judge fallback
    - What: When `elapsed_ms + expected_judge_ms > full_brief_ms` budget, emit the brief with
      `judge_pending=true`, run the Judge in the background, and emit `JudgeReport` on
      `research:judge_report` when done. Used by the Orchestrator in Phase 12.
    - Satisfies: Req 15.7, Req 15.8, design §11.3.
    - Files: `src/research/judge/async_fallback.py`.
    - Blocked by: 12.1.

  - [x] 12.4 Rule-based fallback Judge (offline)
    - What: Deterministic judge implementing design §11.4: citation-coverage regex, delegates
      to numeric validator, applies Refusal_Policy regex. Returns the same `JudgeReport` shape.
      Selected when `LOHI_RESEARCH_OFFLINE=true`.
    - Satisfies: Req 16.22, Req 15.5, design §11.4.
    - Files: `src/research/judge/rule_based.py`.
    - Blocked by: 11.1, 11.3.

  - [x] 12.5 Property test — Judge groundedness recall ≥95%
    - What: Generate synthetic `(context, claim)` pairs where the claim does not appear in
      the context. Run `judge.invoke` against a `FakeLLMProvider` primed with a rule-based
      classifier mimic (so the test is deterministic). Assert `unsupported` recall ≥ 95% over
      at least 100 generated pairs.
    - **Property 8: Judge groundedness recall**
    - **Validates: Req 14.9**
    - Files: `tests/research/test_prop_judge_groundedness.py`.
    - Blocked by: 12.1.

---

### Phase 12 — Orchestrator and Sub_Agents

- [x] 13. LangGraph Orchestrator and seven Sub_Agents
  Blocked by: 6.1, 6.2, 7.*, 9.*, 10.9, 12.*, 11.*.

  - [x] 13.1 Orchestrator graph (LangGraph)
    - What: Implement the graph from design §3.5: `plan` node → concurrent fan-out (cap 6) →
      `synthesise` node → numeric validator → Judge → re-synthesis → emit. Plan node calls
      `research.providers.chat.*`. Writes to `research:partials` as each Sub_Agent completes.
    - Satisfies: Req 1.1, Req 1.5, Req 1.7, Req 5.4, design §2.1, §3.5.
    - Files: `src/research/agents/orchestrator.py`.

  - [x] 13.2 Filings Agent
    - What: Retrieves filings chunks via `HybridRetriever`, calls the configured chat model
      with `prompts/v1/filings_agent.md`. Returns an `AgentResult`. No direct retrieval by
      Report_Synthesizer (design §3.5).
    - Satisfies: Req 1.2, Req 1.3, Req 1.6, Req 12.1, design §3.5.
    - Files: `src/research/agents/filings.py`.
    - Blocked by: 13.1.

  - [x] 13.3 Fundamentals Agent
    - What: Retrieves fundamentals chunks (annual report, results) and generates the
      fundamentals section.
    - Satisfies: Req 1.2, design §3.5.
    - Files: `src/research/agents/fundamentals.py`.
    - Blocked by: 13.1.

  - [x] 13.4 News_Sentiment Agent with Commander stream consumption
    - What: Subscribes to the existing `news_clean`, `sentiment`, and `bias` Redis streams
      (design §2.1) and folds recent events into its context. Does not re-ingest news.
    - Satisfies: Req 1.2, Req 8.3, design §3.5.
    - Files: `src/research/agents/news_sentiment.py`.
    - Blocked by: 13.1.

  - [x] 13.5 Technicals Agent with Soldier stream consumption
    - What: Subscribes to the existing `indicators` Redis stream and produces the
      technical_view section.
    - Satisfies: Req 1.2, Req 8.4, design §3.5.
    - Files: `src/research/agents/technicals.py`.
    - Blocked by: 13.1.

  - [x] 13.6 Peer_Sector Agent
    - What: Retrieves peer/sector chunks and generates the peers section.
    - Satisfies: Req 1.2, design §3.5.
    - Files: `src/research/agents/peer_sector.py`.
    - Blocked by: 13.1.

  - [x] 13.7 Macro Agent
    - What: Retrieves macro chunks and generates the macro_context section.
    - Satisfies: Req 1.2, design §3.5.
    - Files: `src/research/agents/macro.py`.
    - Blocked by: 13.1.

  - [x] 13.8 Report_Synthesizer
    - What: Consumes only the other Sub_Agents' `AgentResult`s; no retrieval calls of its own.
      Produces the combined `ResearchBrief` sections (summary, thesis, risks,
      financial_highlights, management_commentary, technical_view, peers, macro_context,
      citations).
    - Satisfies: Req 1.4, Req 1.5, design §3.5.
    - Files: `src/research/agents/synthesizer.py`.
    - Blocked by: 13.2–13.7.

  - [x] 13.9 Token-budget tracking + `llm_usage` writes
    - What: Central budget tracker (input 32k / output 8k defaults). On overrun, halt further
      Sub_Agent calls and mark the brief `budget_exhausted=true`. Every provider call writes a
      row to `llm_usage`.
    - Satisfies: Req 12.3, Req 12.4, Req 12.5, design §3.5, §4.1.
    - Files: `src/research/agents/budget.py`,
      `src/research/agents/usage_writer.py`.
    - Blocked by: 4.2.

  - [x] 13.10 Partial streaming to `research:partials`
    - What: Each Sub_Agent `yield`s `AgentResult` deltas; the Orchestrator writes them to
      `research:partials` via `xadd`. The gateway (Phase 14) re-emits them as Socket.IO
      events.
    - Satisfies: Req 1.7, Req 5.1, Req 5.2, design §2.1, §3.5.
    - Files: `src/research/agents/partials.py`.
    - Blocked by: 13.1.

  - [x] 13.11 Property test — latency SLO with mocked providers
    - What: With `FakeLLMProvider` configured to realistic latency distributions, run 100
      simulated Research_Runs. Assert `first_token_ms ≤ 800` on ≥ 95 runs, `first_agent_ms
      ≤ 2000` on ≥ 95 runs, `full_brief_ms ≤ 15000` on ≥ 95 runs.
    - **Property 6: Latency SLO**
    - **Validates: Req 14.6, Req 5.1–5.3, Req 15.1, Req 15.4**
    - Files: `tests/research/test_prop_latency_slo.py`.
    - Blocked by: 13.1, 2.19.

- [x] 14. Phase 8–12 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 13 — Snapshot System

- [x] 15. Snapshot precomputation + invalidation
  Blocked by: 13.*.

  - [x] 15.1 `research-snapshotter` worker
    - What: Consumes `research:snapshot_invalidations` and the Commander `bias` pubsub.
      Debounces regeneration by `research.snapshot.debounce_sec` (default 60s). Regenerates
      via a full `Research_Run` path, skipping Sub_Agents that had no new input.
    - Satisfies: Req 11.1, Req 11.2, Req 11.3, design §3.10, §16.1.
    - Files: `src/research/workers/snapshotter.py`.

  - [x] 15.2 Commander bias invalidation hookup
    - What: Add a consumer path on the existing `bias` Redis stream/pubsub that publishes a
      `snapshot_invalidation` event for every `(user_id, symbol)` in that user's active
      watchlist.
    - Satisfies: Req 11.3, Req 8.3, design §3.10.
    - Files: `src/research/snapshot/bias_listener.py`.
    - Blocked by: 15.1.

  - [x] 15.3 Snapshot persistence + stale-on-failure
    - What: Writes to `research_snapshots` with `generated_at`, `input_document_hashes`, and
      `stale=false`. On regeneration failure, retain the previous row and set `stale=true`.
      Reads during a Research_Run short-circuit fan-out when Snapshot is fresh (staleness
      window 15 min default).
    - Satisfies: Req 5.5, Req 11.4, Req 11.5, Req 11.6, design §3.10, §13.3.
    - Files: `src/research/snapshot/store.py`.
    - Blocked by: 4.2, 15.1.

---

### Phase 14 — Gateway API and Socket.IO

- [x] 16. Gateway surface — REST + Socket.IO
  Blocked by: 13.*, 15.*, 1.6 (stub router to replace).

  - [x] 16.1 `ResearchService` extending `ChatbotService`
    - What: `ResearchService(ChatbotService)` exposing `start_run`, `get_run`, `get_run_trace`,
      `get_snapshot`, `upload_document`, `reindex`, `forget_memory`, `health`. Writes runs to
      `research:runs`; reads partials from `research:partials` and forwards as Socket.IO events
      on `research:<run_id>`.
    - Satisfies: Req 8.1, Req 8.2, Req 13.3, design §3.12.
    - Files: `backend-gateway/app/services/research_service.py`.

  - [x] 16.2 REST router replacing the Phase 1 stub
    - What: Implement `POST /runs`, `GET /runs/:id`, `GET /runs/:id/trace`, `GET /snapshot/:symbol`,
      `POST /documents/upload` (multipart), `POST /reindex/:symbol`, `DELETE /memory`,
      `GET /health`. Mounted under `/api/v2/research` using the existing JWT + RLS middleware.
    - Satisfies: Req 3.1, Req 3.12, Req 4.8, Req 5.1, Req 5.5, Req 7.7, Req 13.3, Req 13.4,
      design §5.1.
    - Files: `backend-gateway/app/routers/research.py`.

  - [x] 16.3 Socket.IO event channel wiring
    - What: Wire `research:token`, `research:agent_partial`, `research:agent_done`,
      `research:guardrail_decision`, `research:judge_report`, `research:done`,
      `research:error`, `research:latency_budget_exceeded` on the `research:<run_id>` channel.
      Uses the existing Socket.IO infrastructure; namespaces per design §5.2.
    - Satisfies: Req 5.1, Req 5.2, Req 5.9, Req 6.4, Req 16.11, Req 16.17, design §5.2.
    - Files: `backend-gateway/app/websocket.py`.

  - [x] 16.4 Structured error envelope for known exceptions
    - What: Map `ProviderAuthError` → `PROVIDER_AUTH_FAILED` (design §5.3), provider timeouts →
      `PROVIDER_TIMEOUT`, missing-config → `CONFIG_MISSING`, latency-budget exceedances →
      `LATENCY_BUDGET_EXCEEDED`. Every envelope carries `provider` and `model` where
      applicable.
    - Satisfies: Req 2.10, Req 8.8, Req 13.1, design §5.3, §14.
    - Files: `backend-gateway/app/routers/research.py`,
      `backend-gateway/app/middleware/errors.py`.
    - Blocked by: 16.2.

---

### Phase 15 — Frontend

- [x] 17. React dashboard
  Blocked by: 16.*.

  - [x] 17.1 Zustand store `research-store.ts`
    - What: Holds `runs` map, `activeRunId`, `brief`, `partials`, `judgeReport`,
      `guardrailDecisions`, `streamingState`, `error`. Actions: `startRun`,
      `mergeAgentPartial`, `applyJudgeReport`, `applyGuardrailDecision`, `setError`,
      `reset`.
    - Satisfies: Req 6.4, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/stores/research-store.ts`.

  - [x] 17.2 `use-research-stream` hook
    - What: Wraps the existing `use-websocket` hook. Subscribes to `research:<run_id>` and
      dispatches into `research-store`. Handles reconnect + message replay gracefully.
    - Satisfies: Req 6.4, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/hooks/use-research-stream.ts`.
    - Blocked by: 17.1.

  - [x] 17.3 `ResearchHomePage.tsx`
    - What: Lists recent Research_Briefs, watchlist-driven alerts, and an "Ask anything" input
      that calls `POST /api/v2/research/runs` and subscribes to the returned channel.
    - Satisfies: Req 6.1, Req 6.8, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/pages/research/ResearchHomePage.tsx`.
    - Blocked by: 17.1, 17.2.

  - [x] 17.4 `ResearchSymbolPage.tsx`
    - What: Per-symbol page with filings timeline, financial highlights, management commentary
      summary, risks, peer comparison, inline citations. Renders the Snapshot when fresh.
    - Satisfies: Req 6.2, Req 6.6, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/pages/research/ResearchSymbolPage.tsx`.
    - Blocked by: 17.1, 17.2.

  - [x] 17.5 `ResearchChatPage.tsx`
    - What: Multi-turn research chat with tool-call transparency. Each Sub_Agent invocation is
      a collapsible `AgentCard`.
    - Satisfies: Req 6.3, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/pages/research/ResearchChatPage.tsx`.
    - Blocked by: 17.1, 17.2, 17.7.

  - [x] 17.6 `BriefViewer` component
    - What: Renders `ResearchBrief` sections with inline citation markers. Uses shadcn/ui and
      the existing theming. Partial + streaming states handled via `research-store`.
    - Satisfies: Req 6.2, Req 6.5, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/components/research/BriefViewer.tsx`.
    - Blocked by: 17.1.

  - [x] 17.7 `CitationDrawer` component
    - What: Clicking a citation opens the source document at the cited chunk's character
      offset; when no source URL exists, displays the chunk text in a drawer.
    - Satisfies: Req 6.6, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/components/research/CitationDrawer.tsx`.
    - Blocked by: 17.1.

  - [x] 17.8 `AgentCard` component
    - What: Collapsible card showing agent name, inputs, retrieved chunks, wall time, token
      counts. Driven by `AgentResult` items.
    - Satisfies: Req 6.3, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/components/research/AgentCard.tsx`.

  - [x] 17.9 `JudgeVerifyingBadge` component
    - What: Renders the "verifying…" state when `judge_pending=true`; transitions to
      pass/fail on arrival of `research:judge_report`.
    - Satisfies: Req 15.8, design §3.13, §11.3.
    - Files: `Lohi-TRADE Web App Design/src/components/research/JudgeVerifyingBadge.tsx`.

  - [x] 17.10 `NoDataState` component
    - What: Explicit "No data available for <agent>" rendering when a Sub_Agent returned
      `no_data`.
    - Satisfies: Req 6.7, Req 1.3, design §3.13.
    - Files: `Lohi-TRADE Web App Design/src/components/research/NoDataState.tsx`.

  - [x] 17.11 `RefusalBanner` component
    - What: User-visible summary of the `Refusal_Policy` shown on refusals and always
      accessible from the `/research` shell.
    - Satisfies: Req 16.29, design §3.13, §10.1.
    - Files: `Lohi-TRADE Web App Design/src/components/research/RefusalBanner.tsx`.

  - [x] 17.12 Property test — `research-store` state transitions
    - What: `@fast-check/vitest` arbitraries generate interleaved sequences of
      `mergeAgentPartial`, `applyJudgeReport`, `applyGuardrailDecision`, `startRun`, `reset`.
      Invariants: no cross-run state bleed, citations always monotonically accumulated per
      `run_id`, `reset` fully clears state for a `run_id`.
    - Files: `Lohi-TRADE Web App Design/tests/research/research-store.prop.test.ts`.
    - Blocked by: 17.1.

  - [x] 17.13 Property test — `BriefViewer` citation click-through
    - What: fast-check generates `ResearchBrief`s with N citations, asserts that clicking any
      citation always opens the `CitationDrawer` with the correct `chunk_id` and never falls
      back to "unavailable" when a source URL is present.
    - Files: `Lohi-TRADE Web App Design/tests/research/brief-viewer.prop.test.tsx`.
    - Blocked by: 17.6, 17.7.

---

### Phase 16 — Plug-and-Play Deployment

- [x] 18. Launcher, overlay, health
  Blocked by: 16.*, 13.*, 15.*.

  - [x] 18.1 `start-research.sh`
    - What: Shell launcher per design §16.1 — load `.env` + `.env.research`; pre-flight config
      check that fails fast with a structured error naming any missing key and the file it is
      expected in; `ollama pull` the configured model if offline mode is on;
      `mkdir -p data/research/{chroma,uploads,snapshots}`; delegate to the existing `start.sh`
      for gateway + frontend; start `orchestrator.py`, `indexer.py`, `snapshotter.py` as
      supervised background processes.
    - Satisfies: Req 7.1, Req 7.4, Req 7.6, design §16.1.
    - Files: `start-research.sh`,
      `src/research/workers/orchestrator.py` (worker entrypoint wrapping Task 13.1),
      `src/research/workers/indexer.py`,
      `src/research/workers/snapshotter.py` (wrapping Task 15.1).

  - [x] 18.2 `docker-compose.research.yml` overlay
    - What: Profile-gated services only, per design §16.2 — `qdrant` service (profile
      `qdrant`) and `ollama` service (profile `offline`). Chroma runs embedded, no container.
      Volumes at `./data/research/qdrant` and `./data/research/ollama`.
    - Satisfies: Req 7.2, design §16.2.
    - Files: `docker-compose.research.yml`.

  - [x] 18.3 Finalise `.env.research.template`
    - What: Cross-check against final `settings.yaml`; ensure every secret referenced from the
      `research:` block has a key in the template. Add comments clarifying which keys are
      optional and which are required by the default cloud path.
    - Satisfies: Req 7.3, Req 9.5, design §7.2.
    - Files: `.env.research.template`.
    - Blocked by: 1.4.

  - [x] 18.4 Real `GET /api/v2/research/health`
    - What: Replace the Phase 1 stub with real component checks for `vector_store`,
      `embeddings_provider`, `llm_provider`, `redis`, and `postgres`. Returns the shape from
      design §15.
    - Satisfies: Req 7.7, design §15.
    - Files: `backend-gateway/app/routers/research.py`,
      `backend-gateway/app/services/research_service.py`.
    - Blocked by: 16.1, 3.2.

  - [x] 18.5 End-to-end smoke test
    - What: An automated pytest that starts the gateway against test Redis + Postgres, loads
      the `tests/research/fixtures/filings/` corpus via the ingestion path, runs one
      Research_Run against `FakeLLMProvider`, and asserts: (a) a final `ResearchBrief` is
      emitted; (b) every citation resolves in `FakeVectorStore`; (c) health endpoint is
      `ok`; (d) no cloud provider was instantiated. No external network.
    - Satisfies: Req 7.4, Req 7.7, Req 14.1, design §17.3.
    - Files: `tests/research/test_smoke_e2e.py`.
    - Blocked by: 18.1, 18.4, 16.*.

---

### Phase 17 — Offline Mode Hardening

- [x] 19. Offline mode enforcement
  Blocked by: 2.2, 2.10, 2.14, 12.4.

  - [x] 19.1 Registry offline guard
    - What: When `LOHI_RESEARCH_OFFLINE=true`, the registry refuses to instantiate any cloud
      LLM or cloud embeddings adapter; raises a structured `CloudProviderForbiddenError`
      naming the offending provider and role. Verified at boot, not lazily.
    - Satisfies: Req 9.4, design §14.
    - Files: `src/research/providers/registry.py`,
      `src/research/providers/errors.py`.

  - [x] 19.2 Relaxed offline latency budget
    - What: When offline, the full-brief latency budget is `offline_full_brief_ms` (60s) per
      design §13.1. Read from config and applied in the Orchestrator and async-Judge fallback.
    - Satisfies: Req 15.5, design §13.1.
    - Files: `src/research/agents/orchestrator.py`,
      `src/research/judge/async_fallback.py`.

  - [x] 19.3 Rule-based Judge as active Judge in offline
    - What: When offline, `judge.invoke` dispatches to `judge/rule_based.py` (Task 12.4)
      instead of calling any LLM.
    - Satisfies: Req 16.22, design §11.4.
    - Files: `src/research/judge/judge.py`.
    - Blocked by: 12.4.

---

### Phase 18 — Observability

- [x] 20. Structured logging, metrics, and per-run trace
  Blocked by: 13.*, 16.*.

  - [x] 20.1 Structured-logging additions
    - What: Use the existing `src/utils/logger.py` to emit one structured JSON line per
      Sub_Agent invocation, per Judge call, per guardrail decision, per retrieval call.
      Redaction formatter already covers `api_key|secret|token|password|totp`.
    - Satisfies: Req 13.5, Req 9.6, design §15.
    - Files: `src/research/agents/logging.py`,
      `src/research/guardrails/logging.py` (augment Task 10.9 if needed),
      `src/research/judge/logging.py`.

  - [x] 20.2 Prometheus counters + histograms
    - What: Counters `research_runs_total{status}`, `research_guardrail_blocks_total{rule_id}`,
      `research_judge_failures_total`. Histograms `research_first_token_ms`,
      `research_first_agent_ms`, `research_full_brief_ms`, `research_guardrail_overhead_ms`.
      Exposed through the gateway's existing metrics endpoint.
    - Satisfies: Req 13.2, Req 15.9, design §15.
    - Files: `src/research/observability/metrics.py`,
      `backend-gateway/app/routers/research.py`.

  - [x] 20.3 Per-run trace endpoint + UI wiring
    - What: `GET /api/v2/research/runs/:id/trace` returns the replayable trace composed of
      `research_runs` + `research_provenance` + `research_guardrail_decisions` +
      `research_judge_reports`. UI exposes the trace as a drawer on `ResearchChatPage` and
      `ResearchSymbolPage`.
    - Satisfies: Req 13.3, Req 13.4, design §15.
    - Files: `backend-gateway/app/routers/research.py`,
      `Lohi-TRADE Web App Design/src/components/research/RunTraceDrawer.tsx`.

---

### Phase 19 — Documentation

- [x] 21. Docs
  Blocked by: 18.*.

  - [x] 21.1 `docs/research/PROVIDERS.md`
    - What: Per-provider data-locality notes — for every LLM, embeddings, and vector-store
      adapter, document what data leaves the host when that provider is configured. Include a
      summary table.
    - Satisfies: Req 9.5, design §14.
    - Files: `docs/research/PROVIDERS.md`.

  - [x] 21.2 `docs/research/REFUSAL_POLICY.md`
    - What: Human-readable documentation of the `Refusal_Policy` used by `RefusalBanner` and
      by the rule-based judge. Explicit: no buy/sell/hold, no price targets, no trade
      suggestions, no order placement, no fund transfer, no code execution.
    - Satisfies: Req 16.29, design §3.13, §10.1.
    - Files: `docs/research/REFUSAL_POLICY.md`.

  - [x] 21.3 Extend `docs/CONFIGURATION.md`
    - What: Add a Lohi-Research subsection describing every key under the `research:` block,
      including defaults, value ranges, and cross-references to PROVIDERS.md.
    - Satisfies: Req 8.6, design §7.
    - Files: `docs/CONFIGURATION.md`.

  - [x] 21.4 Top-level `README.md` quick-start
    - What: Add a "Lohi-Research" section pointing at `start-research.sh`, describing the
      default cloud path (NVIDIA NIM + sentence-transformers + auto vector store) and the
      fully-offline path (Ollama + sentence-transformers).
    - Satisfies: Req 7.1, Req 7.5, design §16.
    - Files: `README.md`.

---

### Phase 20 — Acceptance Verification

- [x] 22. Acceptance verification for Req 14
  Blocked by: 20.*.

  - [x] 22.1 Verify Property 1 — Citation integrity
    - What: Confirm `tests/research/test_prop_citation_integrity.py` (Task 6.4) and
      `tests/research/test_prop_citation_integrity_e2e.py` (Task 11.6) run in CI, seeded with
      the project's Hypothesis settings, and are wired into the default `pytest` target.
    - **Validates: Req 14.1**
    - Files: `pyproject.toml` (ensure both test files picked up), CI config as applicable.

  - [x] 22.2 Verify Property 2 — Provider-swap invariance
    - What: Confirm `tests/research/test_prop_provider_swap.py` (Task 2.20) runs in CI.
    - **Validates: Req 14.2**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.3 Verify Property 3 — Memory scoping
    - What: Confirm `tests/research/test_prop_rls_isolation.py` (Task 4.4) and
      `tests/research/test_prop_memory_scoping.py` (Task 7.5) run in CI.
    - **Validates: Req 14.3**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.4 Verify Property 4 — Idempotent re-indexing
    - What: Confirm `tests/research/test_prop_reindex_idempotent.py` (Task 5.15) runs in CI.
    - **Validates: Req 14.4**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.5 Verify Property 5 — Parser round-trip
    - What: Confirm `tests/research/test_prop_parser_roundtrip.py` (Task 5.14) runs in CI.
    - **Validates: Req 14.5**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.6 Verify Property 6 — Latency SLO with mocked providers
    - What: Confirm `tests/research/test_prop_latency_slo.py` (Task 13.11) runs in CI.
    - **Validates: Req 14.6**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.7 Verify Property 7 — Guardrail-bypass invariance
    - What: Confirm `tests/research/test_prop_guardrail_bypass.py` (Task 10.10) runs in CI.
    - **Validates: Req 14.8**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.8 Verify Property 8 — Judge groundedness recall ≥95%
    - What: Confirm `tests/research/test_prop_judge_groundedness.py` (Task 12.5) runs in CI.
    - **Validates: Req 14.9**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.9 Verify Property 9 — Numeric fidelity
    - What: Confirm `tests/research/test_prop_numeric_fidelity.py` (Task 11.4) runs in CI.
    - **Validates: Req 14.10**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.10 Verify Property 10 — Refusal policy
    - What: Confirm `tests/research/test_prop_refusal_policy.py` (Task 11.5) runs in CI.
    - **Validates: Req 14.11**
    - Files: `pyproject.toml`, CI config.

  - [x] 22.11 Traceability audit
    - What: Read `design.md` §19 and cross-check that every requirement in the table
      (`Req 1.1` through `Req 16.29`) maps to at least one completed task in this file. No
      orphan requirements allowed. Emit a short audit report as a Markdown file.
    - Satisfies: Req 14 (overall), design §19.
    - Files: `docs/research/TRACEABILITY_AUDIT.md`.

- [x] 23. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional (primarily property tests and opt-in adapters). The
  implementer MUST implement un-starred sub-tasks and MUST NOT implement starred sub-tasks.
- Every task traces back to requirement IDs and design sections for reviewability.
- Property tests use Hypothesis (backend, Python) or `@fast-check/vitest` (frontend,
  TypeScript), matching the existing project conventions.
- Checkpoints at Task 8, 14, and 23 are points to verify everything is still green before
  moving on.
