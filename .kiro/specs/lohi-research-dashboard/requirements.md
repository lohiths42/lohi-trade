# Requirements Document

## Introduction

Lohi-Research is a multi-agent, Retrieval-Augmented-Generation (RAG) research dashboard that sits alongside the existing LOHI-TRADE trading dashboard. Inspired by public capabilities of multibagg.ai (AI-native equity research over Indian markets), it ingests corporate filings, announcements, annual reports, investor presentations, concall transcripts, shareholding patterns, and auto-linkable news, and produces synthesised, cited research briefs for Indian equities (NSE/BSE).

The feature is fully open-source, plug-and-play locally via a single launcher, and provider-agnostic: users choose LLM, embedding, and vector-store backends through the existing `config/settings.yaml` + `.env` loader. The zero-cost default path uses the NVIDIA NIM free tier for LLMs and local `sentence-transformers` for embeddings. For storage, the default is auto-selected per deployment profile: **Chroma** (DuckDB+Parquet backend, embedded, zero external process) is the default for `Persona_Self_Hosted` because it is the simplest plug-and-play local option and needs no external service; **pgvector** remains the default for `Persona_Cloud_SaaS` because it reuses the Postgres that is already running in the existing multi-user LOHI-TRADE deployment. **Qdrant** and **LanceDB** remain supported pluggable backends for users who prefer them. A fully offline mode is supported via Ollama and local embeddings.

Lohi-Research applies an explicit hallucination-control stack: a `Guardrail_Layer` in front of every Sub_Agent (input + output filtering, prompt-injection detection, tool allow-listing, refusal policy), closed-book retrieval-grounded prompting, a deterministic numeric-fidelity validator, and an `LLM-as-Judge` pass that scores every `Research_Brief` for groundedness and citation coverage before it is shown to the user. The default approach is framework-light (Pydantic-validated prompt templates + a thin guard module); LangChain, Guardrails-AI, and NeMo-Guardrails are supported as opt-in adapters behind the same contract.

Lohi-Research integrates with the existing stack rather than replacing it:

- Extends the existing `ChatbotService` and `/api/v2/chatbot` router instead of forking a parallel chat system.
- Reuses the Commander's `news_raw` / `news_clean` / `sentiment` Redis streams as an input to the News & Sentiment Agent.
- Reuses the Soldier's indicator outputs as an input to the Technicals Agent.
- Respects the existing JWT auth, PostgreSQL Row-Level Security, Fernet credential encryption, and single-launcher (`start.sh`, `docker-compose.yml`) conventions.
- Adds no paid or telemetry dependencies; every dependency is OSI-approved.

## Glossary

- **Lohi_Research**: The research subsystem defined by this spec, comprising backend agents, RAG pipeline, memory, API endpoints, and web UI.
- **Research_Dashboard**: The set of new web pages at `/research`, `/research/:symbol`, and `/research/chat`.
- **Orchestrator**: The top-level agent that plans, fans out to sub-agents, aggregates partial results, and produces a final brief.
- **Sub_Agent**: A specialised agent invoked by the Orchestrator (Filings Agent, Fundamentals Agent, News_Sentiment Agent, Technicals Agent, Peer_Sector Agent, Macro Agent, Report_Synthesizer).
- **Research_Brief**: The final structured, cited output produced for a symbol or query.
- **Citation**: A reference from a claim in a brief back to one or more indexed document chunks, carrying chunk_id, document_id, source_url (if any), and character offsets.
- **LLM_Provider**: A pluggable backend that implements the `LLMProvider` contract for chat-completion and streaming.
- **Embeddings_Provider**: A pluggable backend that implements the `EmbeddingsProvider` contract.
- **Vector_Store**: A pluggable backend that implements the `VectorStore` contract for upsert, similarity search, and deletion. Defaults are profile-dependent: Chroma for `Persona_Self_Hosted` (embedded, on-disk), pgvector for `Persona_Cloud_SaaS` (reuses existing Postgres). Supported alternates: Qdrant, LanceDB.
- **Agent_Framework**: The orchestration library used to compose agents. Default: LangGraph.
- **Local_LLM_Runtime**: The offline model runtime. Default: Ollama.
- **Default_Cloud_Provider**: The first-class zero-cost cloud LLM provider. Default: NVIDIA NIM (build.nvidia.com).
- **Filings_Source**: A public, legally accessible source of Indian-market corporate disclosures. Scope in v1: BSE public announcement feed, NSE public announcement feed, and user-uploaded PDFs. SEBI EDIFAR and company IR PDFs are optional.
- **Document_Store**: The normalised, per-document record (metadata + canonical text + source URL + hash) persisted in Postgres.
- **Chunk**: A bounded text segment produced by the chunker, carrying document_id, position, token count, and embedding vector.
- **Working_Memory**: Short-term per-conversation state stored in Redis with a sliding window plus running summary.
- **Semantic_Memory**: Long-term per-user store of summarised prior research sessions, preferences, and watchlist-linked facts.
- **Episodic_Memory**: Per-symbol timeline of prior conclusions, citations, and timestamps, user-scoped.
- **Persona_Self_Hosted**: A single-user running Lohi-Research on their own machine via Docker Compose.
- **Persona_Cloud_SaaS**: A multi-user installation where many users share the cloud deployment with Postgres RLS isolation.
- **Persona_Algo_Trader**: A user who invokes Lohi-Research programmatically to justify or filter trading signals emitted by the Soldier/Commander pipeline.
- **Research_Run**: A single end-to-end request (prompt + symbols) that produces a Research_Brief with citations and a set of partial agent outputs.
- **Snapshot**: A precomputed, cached Research_Brief per watchlisted symbol, refreshed when new filings or significant news arrive.
- **Provider_Contract**: The Pydantic-defined response shape that every LLM_Provider must produce, independent of the concrete backend.
- **Config_Loader**: The existing YAML + `${ENV_VAR}` loader at `src/utils` that resolves settings from `config/settings.yaml` and `.env`.
- **RLS**: PostgreSQL Row-Level Security, already enforced per user via `request.state.user_id` from JWT middleware.
- **Judge_LLM**: An LLM configured in a separate `research.providers.judge.*` role that evaluates a `Research_Brief` after synthesis for groundedness, citation coverage, contradictions, and off-policy content. May be a different (stronger or cheaper) model than the synthesis model.
- **Groundedness_Score**: A structured score in `[0, 1]` produced per `Research_Brief` section by the `Judge_LLM`, reflecting how well each cited claim is supported by the cited chunk text.
- **Guardrail_Layer**: The input-and-output filtering layer that every user prompt and every Sub_Agent output passes through. Responsible for prompt-injection detection, system-prompt-override rejection, tool allow-list enforcement, rate limiting, PII redaction, and banned-content blocking. Defaults to a Pydantic-validated thin guard module; LangChain, Guardrails-AI, and NeMo-Guardrails are supported as opt-in adapters behind the same contract.
- **Prompt_Template**: A versioned, immutable-at-runtime prompt file under `src/research/prompts/` loaded by Sub_Agents. Every template encodes the constraints "answer only from provided context", "cite every claim", and "refuse off-topic or unsafe requests per `Refusal_Policy`".
- **Jailbreak_Attempt**: An input prompt that attempts to override the system prompt, escape the `Refusal_Policy`, request actions outside the `Tool_Allowlist`, or extract prompts/secrets. Detected by the `Guardrail_Layer` using a versioned regex ruleset and an optional small-model classifier.
- **Refusal_Policy**: The documented, user-visible set of requests that `Lohi_Research` will refuse — including buy/sell/hold recommendations, price targets, trade suggestions, order placement, fund transfer, and code execution.
- **Tool_Allowlist**: The explicit, configurable list of tools and side-effects Sub_Agents are permitted to invoke. Requests for actions outside this list are refused by the `Guardrail_Layer`.

---

## Requirements

### Requirement 1: Multi-Agent Research Pipeline

**User Story:** As a Persona_Self_Hosted investor, I want an orchestrated set of specialised agents to analyse an Indian-market symbol end to end, so that I get a single cited research brief instead of fragmented outputs.

#### Acceptance Criteria

1. THE Lohi_Research SHALL expose a `research.run(symbol, prompt, user_id)` operation that produces exactly one Research_Brief per Research_Run.
2. THE Orchestrator SHALL dispatch to the following Sub_Agents when their inputs are available: Filings Agent, Fundamentals Agent, News_Sentiment Agent, Technicals Agent, Peer_Sector Agent, Macro Agent, and Report_Synthesizer.
3. WHEN a Sub_Agent has no input data available for the requested symbol, THE Orchestrator SHALL record a structured "no_data" result for that Sub_Agent and continue with the remaining Sub_Agents.
4. THE Report_Synthesizer SHALL consume only the outputs of the other Sub_Agents and SHALL NOT issue its own retrieval calls.
5. THE Orchestrator SHALL return a Research_Brief containing sections: summary, thesis, risks, financial_highlights, management_commentary, technical_view, peers, macro_context, and citations.
6. WHEN any Sub_Agent raises an exception, THE Orchestrator SHALL capture the exception in the per-agent trace and SHALL still produce a Research_Brief marked as `partial=true`.
7. THE Orchestrator SHALL emit partial results to the caller as each Sub_Agent completes (streaming fan-out).
8. THE Research_Brief SHALL include a `provenance` block listing, for every Sub_Agent invoked: agent_name, llm_provider, llm_model, input_token_count, output_token_count, and wall_time_ms.

---

### Requirement 2: Provider-Agnostic LLM, Embeddings, and Vector-Store Framework

**User Story:** As a Persona_Self_Hosted user, I want to plug in any LLM or embedding backend with just a config change and an API key, so that I can use free tiers today and switch providers later without code changes.

#### Acceptance Criteria

1. THE Lohi_Research SHALL define an `LLMProvider` abstraction with methods `complete(messages, params) -> Completion` and `stream(messages, params) -> AsyncIterator[CompletionChunk]`.
2. THE Lohi_Research SHALL define an `EmbeddingsProvider` abstraction with method `embed(texts: list[str]) -> list[list[float]]`.
3. THE Lohi_Research SHALL define a `VectorStore` abstraction with methods `upsert`, `similarity_search`, `delete_by_filter`, and `count`.
4. THE Lohi_Research SHALL ship built-in implementations for LLM_Provider: NVIDIA NIM, OpenAI, Anthropic, Google Gemini, Groq, Together, OpenRouter, Ollama.
5. THE Lohi_Research SHALL ship built-in implementations for Embeddings_Provider: local sentence-transformers (BAAI/bge-small-en-v1.5 default), NVIDIA NIM embeddings, OpenAI embeddings, Ollama embeddings.
6. THE Lohi_Research SHALL ship built-in implementations for Vector_Store: Chroma (local default, embedded, on-disk), pgvector (server default, reuses existing Postgres), Qdrant (optional), LanceDB (optional).
7. THE Default_Cloud_Provider SHALL be NVIDIA NIM; WHEN no provider is configured, THE Lohi_Research SHALL select NVIDIA NIM.
8. WHERE a user configures a per-role provider (chat, summarisation, reranker, embeddings), THE Lohi_Research SHALL use the role-specific provider instead of the global default.
9. THE Config_Loader SHALL resolve provider API keys exclusively through `${ENV_VAR}` references in `config/settings.yaml` so that no secret is committed to `config/settings.yaml`.
10. IF a configured provider returns an authentication error, THEN THE Lohi_Research SHALL fail closed with a structured error containing `provider`, `model`, and `error_code`, and SHALL NOT fall back silently to a different provider.
11. THE response shape returned by any LLM_Provider SHALL conform to the Provider_Contract Pydantic model so that swapping providers does not change the API contract surfaced to callers.
12. WHEN a new provider is added, THE Lohi_Research SHALL require no changes outside a single new file under `src/research/providers/` and a single registration line in the provider registry.
13. WHEN the launcher is started with default local settings and no external Postgres is forced, THE Lohi_Research SHALL select Chroma as the Vector_Store and SHALL persist its on-disk data under `data/research/chroma/`.
14. WHEN the existing LOHI-TRADE Postgres is detected at startup, THE Lohi_Research SHALL default to pgvector as the Vector_Store instead of Chroma.
15. WHERE `research.vector_store.backend` is set in `config/settings.yaml`, THE Lohi_Research SHALL use the configured backend and SHALL override the auto-selection defined in criteria 13 and 14.

---

### Requirement 3: RAG Pipeline Over Indian Corporate Filings

**User Story:** As a Persona_Self_Hosted investor, I want filings and announcements for my watched companies indexed and retrievable with citations, so that the brief I read is grounded in primary sources.

#### Acceptance Criteria

1. THE Lohi_Research SHALL ingest documents from the following Filings_Sources in v1: BSE public announcement feed, NSE public announcement feed, and user-uploaded PDFs in a watch folder.
2. WHERE the user enables optional sources, THE Lohi_Research SHALL also ingest SEBI EDIFAR disclosures and company investor-relations PDFs configured per symbol.
3. THE Lohi_Research SHALL respect each source's `robots.txt` and SHALL skip any URL disallowed for the configured user-agent.
4. WHEN a new document is fetched, THE Lohi_Research SHALL parse it (PDF, HTML, or XBRL), normalise whitespace, detect language, and persist a Document_Store record with SHA-256 content hash, source_url, symbol, document_type, and published_at.
5. IF a Document_Store record with the same content hash already exists, THEN THE Lohi_Research SHALL skip re-parsing and re-embedding for that document.
6. THE Lohi_Research SHALL chunk documents using a configurable strategy (default: recursive character splitter, 800 tokens per chunk, 120-token overlap) and SHALL persist each chunk with document_id, position, and token_count.
7. THE Lohi_Research SHALL embed every chunk via the configured Embeddings_Provider and SHALL store the vector, its dimensionality, and the embedding model identifier in the Vector_Store.
8. THE Lohi_Research SHALL support hybrid retrieval combining BM25 (lexical) and dense-vector similarity, and SHALL expose the weighting as a configurable parameter.
9. WHERE a cross-encoder reranker is configured, THE Lohi_Research SHALL rerank the top-k hybrid results before returning them to the Orchestrator.
10. THE Lohi_Research SHALL namespace every chunk by symbol and by user_id so that retrieval queries always include both filters.
11. THE Research_Brief SHALL include at least one Citation for every non-boilerplate claim, and every Citation SHALL resolve to an existing chunk in the Vector_Store at the time of generation.
12. THE Lohi_Research SHALL provide a re-index operation that, for a given symbol, re-parses and re-embeds all documents and SHALL produce the same set of chunk_ids (idempotent re-indexing at the chunk-id level for unchanged source content).

---

### Requirement 4: Memory Architecture (Working, Semantic, Episodic)

**User Story:** As a Persona_Self_Hosted investor, I want the system to remember my prior research, preferences, and per-symbol conclusions, so that follow-up research is incremental rather than starting from scratch.

#### Acceptance Criteria

1. THE Lohi_Research SHALL maintain Working_Memory per conversation in Redis using a sliding window of the last N turns (default N=12) plus a running summary of older turns.
2. WHEN Working_Memory exceeds the configured token budget, THE Lohi_Research SHALL summarise the oldest turns via the configured summarisation LLM_Provider and SHALL replace them with the summary.
3. THE Lohi_Research SHALL maintain Semantic_Memory per user as summarised vectors linked to user_id, preferences (risk appetite, horizon, sectors of interest), and watchlist membership.
4. THE Lohi_Research SHALL maintain Episodic_Memory as a per-(user_id, symbol) timeline of prior Research_Briefs with timestamps, summary, and citations.
5. IF a retrieval request targets Semantic_Memory or Episodic_Memory, THEN THE Lohi_Research SHALL scope every query by user_id and SHALL never return a row whose user_id does not match the caller.
6. THE Lohi_Research SHALL enforce user scoping at the Postgres RLS layer so that Semantic_Memory and Episodic_Memory tables are inaccessible across users even when RLS-bypassing queries are attempted from the service layer.
7. WHEN a Research_Run completes successfully, THE Lohi_Research SHALL append a summary entry to Episodic_Memory for that (user_id, symbol).
8. THE Lohi_Research SHALL expose a `memory.forget(user_id, scope)` operation that deletes the user's Working_Memory, Semantic_Memory, and Episodic_Memory entries for the given scope.
9. WHEN a user invokes `memory.forget`, THE Lohi_Research SHALL complete the deletion within 5 seconds for scopes up to 10,000 rows and SHALL write an audit_log entry with actor=user and action=memory_forget.

---

### Requirement 5: Low-Latency Response and Streaming

**User Story:** As a Persona_Algo_Trader, I want research responses to stream quickly so that I can use them to justify or filter live signals without blocking the trading loop.

#### Acceptance Criteria

1. WHEN a Research_Run is initiated through the API, THE Lohi_Research SHALL emit the first Socket.IO token event within 800 ms under the reference configuration (Chroma (local) or pgvector (server) + sentence-transformers + NVIDIA NIM, 10 chunks retrieved).
2. THE Lohi_Research SHALL produce the first Sub_Agent partial result within 2 seconds of Research_Run start under the reference configuration.
3. THE Lohi_Research SHALL produce a full Research_Brief within 15 seconds of Research_Run start under the reference configuration for a single symbol with ≤50 indexed documents.
4. THE Lohi_Research SHALL execute Sub_Agents concurrently using asyncio, subject to a configurable per-run concurrency limit (default 6).
5. WHERE a Snapshot exists for the requested symbol and was refreshed within the configured staleness window (default 15 minutes), THE Lohi_Research SHALL serve the Snapshot directly and SHALL skip Sub_Agent fan-out.
6. THE Lohi_Research SHALL cache embedding results in Redis keyed by `(embedding_model, sha256(text))` with a configurable TTL (default 7 days).
7. THE Lohi_Research SHALL cache retrieval results in Redis keyed by `(symbol, query_template, sorted_doc_hashes)` with a configurable TTL (default 5 minutes).
8. THE Lohi_Research SHALL cache LLM responses in Redis keyed by `(provider, model, hash(prompt), hash(context))` with a configurable TTL (default 30 minutes), except when streaming is requested.
9. WHEN any latency budget in criteria 1–3 is exceeded, THE Lohi_Research SHALL emit a structured `latency_budget_exceeded` event with `phase`, `observed_ms`, and `budget_ms` fields.

---

### Requirement 6: Research Dashboard Web UI

**User Story:** As a Persona_Self_Hosted investor, I want a dedicated research dashboard in the existing web app so that I can run briefs, chat about a company, and see my watchlist-driven alerts without leaving LOHI-TRADE.

#### Acceptance Criteria

1. THE Research_Dashboard SHALL add a `/research` page listing recent Research_Briefs, watchlist-driven alerts, and an "Ask anything" input.
2. THE Research_Dashboard SHALL add a `/research/:symbol` page showing filings timeline, financial highlights, management-commentary summary, risks, peer comparison, and inline citations.
3. THE Research_Dashboard SHALL add a `/research/chat` page for multi-turn research conversation with tool-call transparency (each Sub_Agent invocation rendered as a collapsible card showing agent name, inputs, retrieved chunks, and wall time).
4. THE Research_Dashboard SHALL stream tokens and partial Sub_Agent results over the existing Socket.IO connection using a new namespace or event channel prefixed with `research:`.
5. THE Research_Dashboard SHALL reuse the existing shadcn/ui component set, Zustand stores pattern, and dark/light theming already used by the LOHI-TRADE web app.
6. WHEN a Citation is clicked in the UI, THE Research_Dashboard SHALL open the source document at the cited chunk's character offset or, WHERE no source URL is available, SHALL display the chunk text in a drawer.
7. WHERE a Sub_Agent returned `no_data`, THE Research_Dashboard SHALL render an explicit "No data available for <agent>" state rather than an empty section.
8. IF the user is not authenticated, THEN THE Research_Dashboard SHALL redirect to `/login` and SHALL preserve the intended `/research*` URL in the `?next=` query parameter.

---

### Requirement 7: Plug-and-Play Local Deployment

**User Story:** As a Persona_Self_Hosted investor, I want a single command to bring up the whole research stack on my laptop, so that I can evaluate Lohi-Research without any paid dependency.

#### Acceptance Criteria

1. THE Lohi_Research SHALL ship a `start-research.sh` launcher at the repository root (or an equivalent flag on the existing `start.sh`) that starts all services required by Lohi-Research alongside the existing stack.
2. THE Lohi_Research SHALL ship a `docker-compose.research.yml` overlay that declares any new services (reranker sidecar if enabled, optional Qdrant, optional Ollama) without modifying the existing `docker-compose.yml`. Chroma SHALL be run embedded in-process and SHALL NOT require a separate container in the overlay.
3. THE Lohi_Research SHALL ship a `.env.research.template` listing the minimum keys required to run, with NVIDIA NIM as the default provider and all other keys optional.
4. WHEN the launcher is invoked with default settings, THE Lohi_Research SHALL run end-to-end on a laptop with Docker Desktop, 8 GB RAM, and no paid subscriptions beyond a free NVIDIA NIM key.
5. WHERE the user sets `LOHI_RESEARCH_OFFLINE=true`, THE Lohi_Research SHALL perform zero outbound calls to any LLM or embedding provider and SHALL use Ollama plus local sentence-transformers for all model calls.
6. THE Lohi_Research SHALL fail fast at startup with a clear, structured error IF a required configuration key is missing, naming the key and the file it is expected in.
7. THE Lohi_Research SHALL expose a health endpoint at `GET /api/v2/research/health` that returns the status of: vector_store, embeddings_provider, llm_provider, redis, and postgres.

---

### Requirement 8: Integration With Existing LOHI-TRADE Modules

**User Story:** As a Persona_Algo_Trader, I want Lohi-Research to reuse existing trading signals, sentiment, and chat infrastructure, so that research and trading operate on a single source of truth.

#### Acceptance Criteria

1. THE Lohi_Research SHALL extend the existing `ChatbotService` in `backend-gateway/app/services/chatbot_service.py` rather than introduce a second parallel chat service.
2. THE Lohi_Research SHALL mount its API endpoints under the existing `/api/v2` prefix, using a new router module `research.py` in `backend-gateway/app/routers/`.
3. THE News_Sentiment Agent SHALL consume the existing Redis streams `news_clean`, `sentiment`, and `bias` produced by the Commander and SHALL NOT re-ingest news feeds that the Commander already covers.
4. THE Technicals Agent SHALL consume the existing `indicators` Redis stream produced by the Soldier.
5. THE Lohi_Research SHALL persist all new tables under the existing Postgres database with Alembic migrations in `backend-gateway/alembic/versions/` and SHALL declare RLS policies keyed on `user_id`.
6. THE Lohi_Research SHALL read configuration exclusively through the existing Config_Loader and SHALL place all new settings under a top-level `research:` section in `config/settings.yaml`.
7. THE Lohi_Research SHALL encrypt any stored third-party API keys at rest using the existing Fernet helper and the existing `MASTER_ENCRYPTION_KEY`.
8. IF a provider API key is required but not configured, THEN THE Lohi_Research SHALL surface the error through the same structured error envelope used by the existing gateway routers.

---

### Requirement 9: Open-Source, Privacy, and Licensing Constraints

**User Story:** As a Persona_Cloud_SaaS operator, I want strong guarantees that the feature introduces no paid or telemetry dependencies and respects user data locality, so that I can ship it under the project's open-source licence.

#### Acceptance Criteria

1. THE Lohi_Research SHALL depend only on packages whose licence is OSI-approved.
2. THE Lohi_Research SHALL emit no outbound network calls at runtime other than to explicitly user-configured LLM, embedding, or Filings_Source endpoints.
3. THE Lohi_Research SHALL log no request body, prompt, completion, or citation text to any third-party service.
4. WHERE `LOHI_RESEARCH_OFFLINE=true`, THE Lohi_Research SHALL refuse to initialise any cloud-hosted LLM_Provider or Embeddings_Provider at startup.
5. THE Lohi_Research SHALL document the data-locality boundary for every provider in `docs/research/PROVIDERS.md`, including what data leaves the host when that provider is configured.
6. THE Lohi_Research SHALL redact secrets from all logs using the existing redaction formatter pattern (`api_key|secret|token|password|totp`).

---

### Requirement 10: Filings Parsing and Round-Trip Integrity

**User Story:** As a Persona_Self_Hosted investor, I want the filings parser to be correct and reversible where applicable, so that I trust the chunks the brief cites.

#### Acceptance Criteria

1. THE Filings_Parser SHALL convert a PDF or HTML document into a canonical text representation plus a structured metadata record.
2. THE Filings_Pretty_Printer SHALL format a canonical text plus metadata record back into a stable, human-readable Markdown representation.
3. FOR ALL canonical text plus metadata records produced by the Filings_Parser, parsing the Markdown produced by the Filings_Pretty_Printer SHALL yield an equivalent canonical text plus metadata record (round-trip property).
4. IF the Filings_Parser encounters an unparseable document, THEN THE Filings_Parser SHALL return a structured error with `document_id`, `source_url`, and `reason` and SHALL NOT raise an uncaught exception.
5. THE Filings_Parser SHALL preserve table structure for tabular data (results, shareholding patterns) as Markdown tables in the canonical representation.
6. THE Filings_Parser SHALL detect and tag management-commentary sections separately from numerical-results sections using a configurable set of section headings.

---

### Requirement 11: Snapshot Precomputation for Watchlist Symbols

**User Story:** As a Persona_Self_Hosted investor, I want common per-symbol questions answered near-instantly for symbols on my watchlist, so that I do not wait 15 seconds for routine lookups.

#### Acceptance Criteria

1. THE Lohi_Research SHALL precompute a Snapshot per (user_id, symbol) for every symbol on the user's active watchlist.
2. WHEN a new document is indexed for a watchlist symbol, THE Lohi_Research SHALL invalidate the corresponding Snapshot and SHALL schedule regeneration within the configured debounce window (default 60 seconds).
3. WHEN the Commander publishes a new bias or a high-impact sentiment event for a watchlist symbol, THE Lohi_Research SHALL invalidate the corresponding Snapshot.
4. WHERE a Snapshot has not been invalidated within the configured staleness window (default 15 minutes), THE Lohi_Research SHALL treat it as fresh and SHALL serve it for matching queries.
5. THE Snapshot SHALL include the same sections as a full Research_Brief and SHALL be persisted with `generated_at` and `input_document_hashes`.
6. IF a Snapshot fails to regenerate, THEN THE Lohi_Research SHALL retain the previous Snapshot, mark it `stale=true`, and surface the staleness to the UI.

---

### Requirement 12: Configurable Per-Agent Models and Cost Controls

**User Story:** As a Persona_Cloud_SaaS operator, I want to pick different models for different agents and cap usage so that I can control cost and latency per tenant.

#### Acceptance Criteria

1. THE Lohi_Research SHALL allow configuring `llm_provider`, `llm_model`, `temperature`, `max_tokens`, and `timeout_ms` per Sub_Agent role.
2. WHERE a per-agent override is absent, THE Lohi_Research SHALL fall back to the global default for that role.
3. THE Lohi_Research SHALL enforce per-Research_Run token budgets (default: 32,000 input tokens, 8,000 output tokens, configurable).
4. IF a Research_Run exceeds its token budget, THEN THE Lohi_Research SHALL halt further Sub_Agent calls, mark the Research_Brief `budget_exhausted=true`, and return the partial result.
5. THE Lohi_Research SHALL record per-run token usage, per-provider, in an `llm_usage` table with columns (user_id, research_run_id, provider, model, input_tokens, output_tokens, cost_estimate_usd, created_at).

---

### Requirement 13: Error Handling and Observability

**User Story:** As a Persona_Self_Hosted investor, I want clear errors and visibility into what each agent did, so that I can diagnose bad briefs without reading source code.

#### Acceptance Criteria

1. IF an LLM_Provider request times out, THEN THE Lohi_Research SHALL record a structured `provider_timeout` error with `provider`, `model`, `attempt`, and `elapsed_ms`.
2. WHEN an LLM_Provider request fails with a retryable error, THE Lohi_Research SHALL retry up to a configurable number of times (default 2) with exponential backoff (default base 500 ms, cap 4 s).
3. THE Lohi_Research SHALL write one trace record per Research_Run containing the plan, each Sub_Agent invocation, its retrieval results, its LLM call, and its output.
4. THE Research_Dashboard SHALL expose the trace for a Research_Run via `GET /api/v2/research/runs/:run_id/trace` scoped to the requesting user.
5. THE Lohi_Research SHALL emit structured logs via the existing `src/utils/logger.py` and SHALL NOT introduce a second logging framework.

---

### Requirement 14: Testable Correctness Properties

**User Story:** As a maintainer, I want executable correctness properties that guard the feature end to end so that regressions in retrieval, memory scoping, and provider contracts are caught automatically.

#### Acceptance Criteria

1. THE Lohi_Research test suite SHALL include a property that every Citation in a Research_Brief resolves to an existing chunk_id in the Vector_Store at generation time (citation integrity).
2. THE Lohi_Research test suite SHALL include a property that swapping LLM_Provider or Embeddings_Provider does not change the shape of the Provider_Contract returned to callers (provider-swap invariance).
3. THE Lohi_Research test suite SHALL include a property that for any two distinct users `u_a` and `u_b`, a retrieval request by `u_a` returns zero rows whose `user_id == u_b` across Working_Memory, Semantic_Memory, and Episodic_Memory (memory scoping).
4. THE Lohi_Research test suite SHALL include a property that re-indexing a document whose content hash has not changed produces exactly the same set of chunk_ids (idempotent re-indexing).
5. THE Lohi_Research test suite SHALL include a property that parsing a canonical text plus metadata record, pretty-printing it, and parsing it again yields an equivalent canonical text plus metadata record (parser round-trip).
6. THE Lohi_Research test suite SHALL include a property that for the reference configuration, the observed first-token latency is less than or equal to the configured budget on at least 95 out of 100 simulated runs (latency SLO property, with mocked provider latencies).
7. THE Lohi_Research test suite SHALL use Hypothesis for Python-side properties and fast-check for TypeScript-side properties, following the patterns already established under `tests/` and `Lohi-TRADE Web App Design/`.
8. THE Lohi_Research test suite SHALL include a guardrail-bypass-invariance property: for a corpus of known Jailbreak_Attempt prompts fuzzed via Hypothesis strategies over prompt mutations, the `Guardrail_Layer` SHALL refuse or sanitise 100% of them.
9. THE Lohi_Research test suite SHALL include a judge-groundedness property: on a synthetic dataset of `(context, claim)` pairs where the claim does not appear in the context, the Judge_LLM SHALL flag the claim as `unsupported` with recall ≥ 95%.
10. THE Lohi_Research test suite SHALL include a numeric-fidelity property: for every numeric value that appears in a Research_Brief, the same value (within a configurable epsilon) SHALL appear verbatim in at least one cited chunk; any violation SHALL fail the property.
11. THE Lohi_Research test suite SHALL include a refusal property: for prompts matching the `Refusal_Policy` (e.g., "should I buy RELIANCE tomorrow?"), the system SHALL return a refusal with an explanation and SHALL NOT produce a recommendation, price target, or trade suggestion.

---

### Requirement 15: Non-Functional Requirements

**User Story:** As a Persona_Cloud_SaaS operator, I want explicit non-functional requirements so that I can verify Lohi-Research meets operational expectations.

#### Acceptance Criteria

1. THE Lohi_Research SHALL sustain at least 5 concurrent Research_Runs per single gateway instance under the reference configuration without breaching Requirement 5 latency budgets.
2. THE Lohi_Research SHALL recover automatically from transient vector-store disconnections via connection-pool retry, without manual intervention.
3. THE Lohi_Research SHALL operate with total disk footprint under 5 GB for a default installation (excluding user documents and optional local LLM weights).
4. THE Lohi_Research SHALL target first-token latency ≤ 800 ms, first-agent latency ≤ 2 s, and full-brief latency ≤ 15 s under the reference configuration, as defined in Requirement 5.
5. THE Lohi_Research SHALL remain functional in fully-offline mode using Ollama and local sentence-transformers, at the cost of slower full-brief latency (budget relaxed to 60 s in offline mode).
6. THE Lohi_Research SHALL introduce no new paid or telemetry dependencies as defined in Requirement 9.
7. THE Judge_LLM invocation SHALL add ≤ 2 seconds to full-brief latency under the reference configuration.
8. WHEN the Judge_LLM would exceed the latency budget defined in criterion 7, THE Lohi_Research SHALL run the Judge_LLM asynchronously, SHALL surface a "verifying…" state in the UI, and SHALL finalise the Research_Brief once the Judge_LLM returns.
9. THE Guardrail_Layer SHALL add ≤ 50 ms p95 overhead per request under the reference configuration.

---

### Requirement 16: LLM-as-Judge, Hallucination Controls, and Prompt Guardrails

**User Story:** As a Persona_Self_Hosted investor, I want every research brief to pass through explicit input guardrails, retrieval-grounded prompting, deterministic numeric checks, and an independent LLM-as-Judge pass, so that I can trust the brief has no jailbreaks, hallucinations, or disallowed trade advice.

#### Acceptance Criteria

**A. Generation-time guardrails (input + output filtering)**

1. THE Lohi_Research SHALL route every user-submitted prompt through the `Guardrail_Layer` before the prompt reaches any Sub_Agent.
2. THE `Guardrail_Layer` SHALL detect Jailbreak_Attempt patterns against a versioned ruleset composed of a regex set and an optional small-model classifier, both independently configurable.
3. THE `Guardrail_Layer` SHALL strip or refuse any input that attempts to override a Sub_Agent system prompt.
4. IF an input requests an action outside the `Tool_Allowlist` (including order placement, fund transfer, or code execution), THEN THE `Guardrail_Layer` SHALL reject the request with a structured refusal.
5. THE `Guardrail_Layer` SHALL rate-limit guardrail decisions per `user_id` against configurable thresholds.
6. THE Sub_Agent system prompts SHALL be loaded from versioned `Prompt_Template` files under `src/research/prompts/`, SHALL be immutable at runtime, and SHALL include explicit instructions to "answer only from provided context", "cite every claim", and "refuse off-topic or unsafe requests per `Refusal_Policy`".
7. THE Lohi_Research SHALL ship a framework-light default `Guardrail_Layer` implementation built on Pydantic-validated prompts plus a thin guard module and SHALL NOT mandate a heavy framework.
8. WHERE a user opts in, THE Lohi_Research SHALL expose LangChain, Guardrails-AI, and NeMo-Guardrails as adapter implementations behind the same `Guardrail_Layer` contract.
9. THE output-side `Guardrail_Layer` SHALL strip tool-call and function-call tokens that the caller did not authorise.
10. THE output-side `Guardrail_Layer` SHALL redact PII patterns and SHALL block outputs that contain banned content per the configured policy.
11. THE Lohi_Research SHALL log every guardrail decision (allow, modify, or refuse) with `rule_id`, `action`, and `reason`, and SHALL include a summary of guardrail decisions in the `provenance` block of the resulting Research_Brief.

**B. LLM-as-Judge for hallucination detection**

12. THE Lohi_Research SHALL score every Research_Brief with the Judge_LLM after the Report_Synthesizer has produced the brief.
13. THE Judge_LLM SHALL assess groundedness by checking that every cited claim appears in the cited chunk text.
14. THE Judge_LLM SHALL assess citation coverage by checking that every non-boilerplate sentence in the Research_Brief is cited.
15. THE Judge_LLM SHALL assess contradiction by checking that no two claims in the Research_Brief contradict each other.
16. THE Judge_LLM SHALL assess off-policy output by checking that the Research_Brief contains no disallowed content (trade recommendations worded as advice, price predictions dressed as fact, or any content enumerated in the `Refusal_Policy`).
17. THE Judge_LLM SHALL return a structured result containing a Groundedness_Score in `[0, 1]` per section, a list of `unsupported_claims` with character offsets, and a boolean `safe_to_display` flag.
18. IF `safe_to_display` is false OR the minimum Groundedness_Score across sections is below `research.judge.min_score` (default 0.7), THEN THE Lohi_Research SHALL re-synthesise the Research_Brief once with the Judge_LLM's `unsupported_claims` list fed back into the Report_Synthesizer's context.
19. IF the re-synthesised Research_Brief still fails Judge_LLM validation, THEN THE Lohi_Research SHALL mark the Research_Brief `quality=low`, SHALL redact or label the unsupported sections as "insufficient evidence", and THE Research_Dashboard SHALL surface the warning to the user.
20. THE Judge_LLM SHALL be configured as a separate `LLM_Provider` role under `research.providers.judge.*` so that operators may select a different (stronger or cheaper) model for judging than for synthesis.
21. WHEN no Judge_LLM is configured, THE Lohi_Research SHALL default to NVIDIA NIM for the Judge_LLM role.
22. WHERE `LOHI_RESEARCH_OFFLINE=true`, THE Lohi_Research SHALL use a deterministic rule-based fallback Judge that performs citation-coverage checks and regex policy checks instead of invoking any cloud LLM.

**C. Hallucination defences in retrieval and synthesis**

23. THE Orchestrator SHALL pass retrieved chunks to Sub_Agents verbatim and SHALL NOT paraphrase or summarise chunks before passing them.
24. WHEN retrieval returns zero chunks above the configured similarity floor (default 0.25 cosine for bge-small), THE Orchestrator SHALL instruct the affected Sub_Agent to refuse to answer for that input.
25. THE Sub_Agent Prompt_Templates SHALL be closed-book: Sub_Agents SHALL NOT be asked to draw on parametric knowledge of specific companies, prices, or filings that are not in the provided context.
26. THE Lohi_Research SHALL run a deterministic numeric-extraction validator over every Research_Brief that double-checks each numerical claim (revenue, EPS, growth percentage, dates) against the cited chunks.
27. IF a numerical claim does not match any cited chunk within the configured epsilon, THEN THE Lohi_Research SHALL mark that claim `unsupported` and SHALL trigger Judge_LLM re-synthesis as defined in criterion 18.
28. THE Lohi_Research SHALL refuse to produce buy/sell/hold recommendations, price targets, or trade suggestions.
29. THE Lohi_Research SHALL document the `Refusal_Policy` in `docs/research/REFUSAL_POLICY.md` and SHALL surface its user-visible summary in the Research_Dashboard.

