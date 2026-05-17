"""Redis stream, pubsub channel, and key-template constants for Lohi-Research.

This module is the single source of truth for every Redis stream, pubsub
channel, and key template introduced by the Lohi-Research subsystem. It
contains module-level string constants only — no client code, no side
effects, and no imports from ``redis``.

Design reference: `.kiro/specs/lohi-research-dashboard/design.md` §3.11
(Redis caches) and §4.3 (Redis key schemas).

Satisfies:
    - Req 5.6 — Embedding cache key shape (design §3.11, §4.3).
    - Req 5.7 — Retrieval cache key shape (design §3.11, §4.3).
    - Req 5.8 — LLM response cache key shape (design §3.11, §4.3).
    - Req 5.9 — ``latency_budget_exceeded`` events on a dedicated pubsub
      channel (design §3.11, §4.3, §13.4).

Naming conventions:
    - Stream names end with ``_STREAM``.
    - Pubsub channels end with ``_CHANNEL``.
    - Key templates that require ``str.format(**kwargs)`` substitution end
      with ``_KEY_TEMPLATE`` and use the field names documented in design
      §4.3. Call ``template.format(...)`` at the call site.
"""

# ---------------------------------------------------------------------------
# Streams (design §4.3, Req 1.7, Req 5.1–5.3, Req 11.2)
# ---------------------------------------------------------------------------

# Run fan-out stream. The gateway ``xadd``s a run request onto this stream;
# the `research-orchestrator` worker consumes it (design §2.2, §3.12).
RESEARCH_RUNS_STREAM = "research:runs"

# Partial-result stream. The Orchestrator ``xadd``s each Sub_Agent partial
# onto this stream; the gateway re-emits partials as Socket.IO events on
# ``research:<run_id>`` channels (design §2.1, §3.12, Req 1.7, Req 6.4).
RESEARCH_PARTIALS_STREAM = "research:partials"

# Index events stream. The `research-indexer` worker ``xadd``s
# ``{document_url, symbol, document_type, published_at}`` events here
# when a new filing/announcement/upload is discovered (design §3.2, §4.3).
RESEARCH_INDEX_EVENTS_STREAM = "research:index_events"

# Snapshot invalidation stream. Publishers: ingestion (on new document for
# a watchlist symbol) and snapshot service (on bias / sentiment triggers).
# Consumer: `research-snapshotter` worker which debounces regeneration
# (design §3.10, Req 11.2, Req 11.3).
RESEARCH_SNAPSHOT_INVALIDATIONS_STREAM = "research:snapshot_invalidations"


# ---------------------------------------------------------------------------
# Pubsub channels (design §4.3, §13.4, Req 5.9)
# ---------------------------------------------------------------------------

# Latency-budget pubsub channel. Carries ``latency_budget_exceeded`` events
# of shape ``{phase, observed_ms, budget_ms}`` whenever any latency budget
# from Req 5.1–5.3 is exceeded (design §3.11, §13.4, Req 5.9).
RESEARCH_LATENCY_BUDGET_CHANNEL = "research:latency_budget"

# Judge report pubsub channel. Carries the JSON-serialised ``JudgeReport``
# when the Orchestrator runs the Judge asynchronously in the background
# (design §5.2 Socket.IO event ``research:judge_report``, §11.3 async
# fallback for Req 15.7/15.8). Subscribers (gateway Socket.IO bridge,
# persistence writer) consume the channel to finalise a brief that was
# emitted with ``judge_pending=true``.
RESEARCH_JUDGE_REPORT_CHANNEL = "research:judge_report"


# ---------------------------------------------------------------------------
# Key templates (design §4.3)
# ---------------------------------------------------------------------------
#
# Each template below is a plain Python ``str.format``-style template. Pass
# the documented fields to ``.format(**kwargs)`` at the call site. Fields
# marked ``sha256(...)`` are the hex digest of the respective bytes, per
# design §3.11.

# Working memory list: sliding window of the last N turns plus a running
# summary for a given user/conversation (design §3.4, §4.3, Req 4.1–4.2).
# Fields: user_id, conv_id.
WORKING_MEMORY_KEY_TEMPLATE = "research:wm:{user_id}:{conv_id}"

# Embedding cache (string). Keyed by the embedding model id and the SHA-256
# hex digest of the source text (design §3.11, §4.3, Req 5.6).
# Fields: embedding_model, text_sha256.
EMBEDDING_CACHE_KEY_TEMPLATE = "research:emb:{embedding_model}:{text_sha256}"

# Retrieval cache (string). Keyed by symbol, a hash of the query template,
# and a hash of the sorted document hashes participating in retrieval
# (design §3.11, §4.3, Req 5.7).
# Fields: symbol, query_template_hash, sorted_doc_hashes_sha256.
RETRIEVAL_CACHE_KEY_TEMPLATE = (
    "research:ret:{symbol}:{query_template_hash}:{sorted_doc_hashes_sha256}"
)

# LLM response cache (string). Keyed by provider, model, and SHA-256 hex
# digests of the prompt and context (design §3.11, §4.3, Req 5.8). Bypassed
# when the caller requests streaming.
# Fields: provider, model, prompt_sha256, context_sha256.
LLM_RESPONSE_CACHE_KEY_TEMPLATE = "research:llm:{provider}:{model}:{prompt_sha256}:{context_sha256}"

# Guardrail rate-limit counter (integer). One counter per user per time
# window (design §3.6, §4.3, Req 16.5). ``window_epoch`` is the unix-epoch
# start of the rate-limit window.
# Fields: user_id, window_epoch.
GUARDRAIL_RATE_LIMIT_KEY_TEMPLATE = "research:gr:rl:{user_id}:{window_epoch}"
