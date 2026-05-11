
# LOHI-TRADE · System Architecture

> **This document supersedes the Trade-only architecture doc that preceded it.** It covers the full system — **LOHI-TRADE** (algorithmic execution) and **Lohi-Research** (multi-agent equity research) — as one product built on a shared Redis backbone and a shared Postgres/SQLite state layer, with a single React web app and native mobile clients.
>
> Last updated: during the post-audit consolidation (see `AUDIT_REPORT.md`).

---

## 0. One-page summary

LOHI-TRADE is a **two-surface** open-source platform for Indian equity markets:

| Surface | What it does | Primary artefact |
|---|---|---|
| **Trade** | Executes live / paper algo trades from a deterministic pipeline | `Fill` |
| **Research** | Produces cited, Judge-scored research briefs over filings + news | `ResearchBrief` |

The two surfaces are **independently runnable** (you can ship Trade without Research, or Research without Trade) but are designed to compose:

- Trade's Commander publishes sentiment streams that Research's News agent consumes without re-ingestion.
- Trade's Soldier publishes indicator streams that Research's Technicals agent consumes.
- Research's Judge-approved high-conviction briefs publish a `ResearchSignal` back onto the event bus, which Trade's Risk Management System can optionally consume as a veto/boost.

All of this flows through **Redis Streams** (low-latency event bus) and a shared **PostgreSQL + SQLite + DuckDB** state layer. Every user-typed prompt passes through a **Guardrail Layer**; every order passes through a **Risk Management System**. Both are pure-function, non-LLM boundaries — the deterministic spine the rest of the system bends around.

The surfaces share one React SPA (the *Trade* shell and the *Research* shell are two layouts with a mode switcher in the top chrome), one mobile app codebase, and one gateway process.


---

## 1. High-level topology

```
                     ┌───────────────────────────────────────────┐
                     │                Clients                     │
                     │ ┌──────────────┐  ┌───────────────────┐   │
                     │ │ React web app │  │ iOS + Android app │   │
                     │ │  (Trade shell │  │  (React Native)   │   │
                     │ │  + Research   │  └───────┬───────────┘   │
                     │ │   shell)      │          │               │
                     │ └───┬───────────┘          │               │
                     └─────┼──────────────────────┼───────────────┘
                           │ HTTPS + Socket.IO    │ HTTPS
                           ▼                      ▼
                   ┌───────────────────────────────────────┐
                   │        FastAPI Gateway (single         │
                   │         process, Socket.IO-mounted)    │
                   │                                        │
                   │  Middleware: JWT · RLS · RateLimit ·   │
                   │  InputSanitisation · GZip · Caching    │
                   │                                        │
                   │  Routers:                              │
                   │   /api/{auth,positions,orders,trades,  │
                   │         bias,signals,analytics,logs,   │
                   │         kill-switch,paper-trading,…}   │
                   │   /api/v2/{auth,verification,bank,     │
                   │            stock-universe,watchlist,   │
                   │            screener,broker,market-data,│
                   │            chatbot,admin,public,…}     │
                   │   /api/v2/research/*   (Lohi-Research) │
                   └───────┬─────────────────────┬──────────┘
                           │                     │
                           ▼                     ▼
          ┌────────────────────────┐   ┌────────────────────────────┐
          │   Redis Streams        │   │   Postgres (RLS) + SQLite  │
          │   (event bus)          │   │   + DuckDB                 │
          │                        │   │                             │
          │ Trade side:            │   │ Trade tables: trades,       │
          │  ticks · news_raw ·    │   │  orders, positions,         │
          │  news_clean · sentiment│   │  sentiment, audit_log, …    │
          │  · bias · indicators · │   │                             │
          │  signals · orders ·    │   │ Research tables:            │
          │  fills                 │   │  research_documents,        │
          │                        │   │  research_chunks,           │
          │ Research side:         │   │  research_runs,             │
          │  research:runs ·       │   │  research_brief_sections,   │
          │  research:partials ·   │   │  research_provenance,       │
          │  research:index_events │   │  research_guardrail_        │
          │  · research:judge_     │   │  decisions,                 │
          │  report (pubsub) ·     │   │  research_judge_reports,    │
          │  research:latency_     │   │  research_snapshots,        │
          │  budget (pubsub)       │   │  research_semantic_memory,  │
          │                        │   │  research_episodic_memory,  │
          │ Bridge:                │   │  llm_usage,                 │
          │  research_signal       │   │  research_audit_log         │
          │                        │   │                             │
          └──────┬───────────┬─────┘   │ DuckDB: historical OHLCV    │
                 │           │         │ (Parquet, partitioned)      │
                 │           │         └────────────────────────────┘
                 │           │
                 ▼           ▼
   ┌──────────────────────┐   ┌────────────────────────────────────┐
   │   Trade workers      │   │   Research workers                 │
   │                      │   │                                    │
   │ • Ingestion          │   │ • Orchestrator (LangGraph, 7 agents│
   │   (ticks, news)      │   │   with concurrency cap = 6)        │
   │ • Soldier            │   │ • Indexer                           │
   │   (candles,          │   │   (BSE/NSE feeds + user uploads    │
   │    indicators,       │   │    → parse → chunk → embed)         │
   │    strategies)       │   │ • Snapshotter                       │
   │ • Commander          │   │   (per-symbol brief cache,         │
   │   (FinBERT,          │   │    invalidation on new docs /      │
   │    bias decay)       │   │    bias events)                    │
   │ • Execution          │   │                                    │
   │   (RMS, sizer, OMS,  │   │ All agents / workers reuse the     │
   │    kill switch,      │   │ gateway's Redis + Postgres pools;  │
   │    position mgr)     │   │ every connection sets              │
   │                      │   │ `app.user_id` so RLS engages.      │
   └──────┬───────────────┘   └────────────────────────────────────┘
          │
          ▼
   ┌──────────────────────┐
   │   Broker adapters    │
   │   (Shoonya / Angel / │
   │    Nubra)            │
   │                      │
   │   + Telegram bot     │
   │   (fills + kill-     │
   │    switch alerts)    │
   └──────────────────────┘
```


---

## 2. Repository layout

```
Lohi-Trade-OpenSource/
├── backend-gateway/              # FastAPI + Socket.IO gateway (the API server)
│   ├── app/
│   │   ├── main.py               #  Lifespan, middleware stack, router mount
│   │   ├── config.py             #  Settings loader (YAML + env)
│   │   ├── websocket.py          #  Socket.IO event handlers + room bridge
│   │   ├── middleware/           #  JWT, RLS, rate-limit, input-sanitisation,
│   │   │                         #  caching, error envelope
│   │   ├── models/               #  SQLAlchemy models (trade + research)
│   │   ├── routers/              #  28 REST routers — every page has one
│   │   └── services/             #  Business logic, DB access, external APIs
│   ├── alembic/                  #  Migrations (trade + research schemas)
│   └── tests/                    #  ~50 test modules, property + integration
│
├── src/                          # Trade workers + Research agents (Python)
│   ├── ingestion/                #  WebSocket tick clients, RSS pollers
│   ├── soldier/                  #  Candle builder, indicator engine, strategies
│   ├── commander/                #  FinBERT sentiment, bias decay
│   ├── execution/                #  RMS, position sizer, OMS, kill switch
│   ├── state/                    #  Redis client wrappers, DB helpers
│   ├── ui/                       #  Streamlit dashboard, Telegram bot
│   ├── backtesting/              #  Historical replay engine
│   ├── ml/                       #  FinBERT model loading, ONNX runtime
│   ├── utils/                    #  Config loader, structured logger
│   └── research/                 #  Lohi-Research agents + workers
│       ├── agents/               #   Orchestrator + 7 Sub_Agents
│       ├── providers/            #   LLM / embeddings / vector-store adapters
│       ├── ingest/               #   BSE/NSE feeds, parser, chunker
│       ├── index/                #   Hybrid retriever + reranker
│       ├── memory/               #   Working / Semantic / Episodic
│       ├── guardrails/           #   Pydantic guard + opt-in adapters
│       ├── judge/                #   Judge LLM + rule-based fallback
│       ├── validators/           #   Numeric + citation + refusal
│       ├── prompts/v1/           #   Versioned, immutable at runtime
│       ├── snapshot/             #   Per-symbol brief cache
│       ├── cache/                #   Embedding / retrieval / LLM caches
│       ├── observability/        #   Prometheus counters + histograms
│       └── workers/              #   Process entrypoints
│
├── Lohi-TRADE Web App Design/    # React SPA (Vite + Socket.IO client)
│   └── src/
│       ├── App.tsx               #  Trade shell (top bar, sidebar, routes)
│       ├── main.tsx              #  Router + Research shell wiring
│       ├── components/
│       │   ├── shared/           #   ModeSwitcher, LohiAvatarAuto,
│       │   │                     #   WorkflowCanvas/Simulator, PageHeader,…
│       │   └── research/         #   ResearchShell, BriefViewer, AgentCard,
│       │                         #   CitationDrawer, LohiAvatarResearch,…
│       ├── pages/                #  36 Trade pages + 9 Research pages
│       │   └── research/         #   Research Feed, Ideas, Themes, Sectors,
│       │                         #   Coverage, Briefs, Filings, Chat,
│       │                         #   Symbol, Architecture, Policy
│       ├── stores/               #  Zustand stores (12 of them)
│       └── styles/
│           ├── design-tokens.css #   Trade palette (indigo + neon)
│           └── research-theme.css #  Research palette (monochrome Quartr)
│
├── mobile/                       # React Native clients (iOS + Android)
├── infra/                        # AWS / Terraform bits (optional)
├── docs/                         # This folder
│   ├── ARCHITECTURE.md           #   THIS file
│   ├── CONFIGURATION.md          #   Per-setting reference
│   ├── BACKTESTING.md            #   Historical replay
│   ├── STRATEGIES.md             #   Strategy reference
│   ├── REDIS_SETUP.md            #   Redis bringup
│   ├── AUDIT_REPORT.md           #   Post-audit findings
│   ├── FAQ.md
│   └── research/                 #   PROVIDERS, REFUSAL_POLICY, TRACEABILITY
│
├── .kiro/specs/                  # Kiro product specs (source of truth)
│   ├── lohi-trade/               #   Core Trade spec
│   ├── lohi-trade-platform-expansion/  # Multi-user expansion
│   └── lohi-research-dashboard/  #   Research spec (22 phases, 100+ tasks)
│
├── config/settings.yaml          # Single operator-facing config file
├── .env.template                 # Trade secrets (broker, Telegram)
├── .env.research.template        # Research secrets (LLM API keys)
├── docker-compose.yml            # Redis + optional Postgres
├── docker-compose.research.yml   # Qdrant / Ollama overlay
├── start.sh                      # Trade bringup
└── start-research.sh             # Research bringup (adds workers)
```


---

## 3. Trade subsystem

### 3.1 Ingestion layer

| Worker | Source | Output stream | Cadence |
|---|---|---|---|
| WebSocket client | Shoonya / Angel One / Nubra | `ticks` | Every tick (sub-100 ms) |
| RSS poller | MoneyControl, Economic Times, LiveMint, Mint | `news_raw` | 60 s |
| Instrument master | Broker EoD dump | Local + DB | Daily |

All three ingestion workers are non-blocking — they never await downstream consumers. Redis Streams absorb the backlog; `XTRIM` caps stream length so memory stays bounded even under a day-long Commander outage.

### 3.2 Soldier — fast path (technicals)

```
ticks → Candle Builder → Indicator Engine → Strategy Engine → Signal Pipeline → signals
```

| Stage | Input | Output | Responsibility |
|---|---|---|---|
| Candle Builder | Ticks | 1m / 5m / 15m OHLCV | Aggregate ticks into multi-TF candles; emit on bar close to `candles` |
| Indicator Engine | Candles | Indicator values | RSI, MACD, Bollinger, VWAP, EMA(9/21), Supertrend(7,3), ATR(14); emit to `indicators` |
| Strategy Engine | Candles + indicators | Raw signal | Run enabled strategies (Mean Reversion, Trend Following, ORB, …); emit one raw signal per crossing |
| Signal Pipeline | Raw signals | Validated signal | Dedup, trading-hours gate, emit to `signals` |

Strategies are **pure functions** of `(candles, config)` — no shared state, no side effects, no order placement. That's what lets backtests and paper-trading run bit-identical to live.

### 3.3 Commander — slow path (sentiment)

```
news_raw → Deduplicator → Entity Resolver → FinBERT → Bias Calculator → bias
```

| Stage | Input | Output | Responsibility |
|---|---|---|---|
| Deduplicator | Articles | Unique articles | SHA-256 over normalised title+summary |
| Entity Resolver | Article text | `(article, ticker)` pairs | spaCy NER → fuzzy-match to NSE symbols |
| Sentiment Analyzer | Article text | Score ∈ [−1, +1] | FinBERT ONNX + Indian-market keyword boosters ("FII buying" → +0.1 nudge) |
| Bias Calculator | Per-ticker scores | `BULLISH | BEARISH | NEUTRAL` | Time-decayed aggregate, half-life 4 h, threshold ±0.2 |
| Bias Scheduler | Timer | Updated bias | Recalc every 5 min, emit to `bias` |

Bias is a **soft** input — it can't place trades. It's only consumed by (a) the RMS as a veto/boost filter and (b) the Research News agent as fold-in context.

### 3.4 Execution layer

```
signals + bias (+ optional ResearchSignal) → RMS (9 checks) → Position Sizer → OMS → Broker
                                                                                     → Paper Trading Engine
                                                                                     → fills → Position Manager
                                                                                            → PnL → Kill Switch
```

**RMS pre-order checks (in order):**

| # | Check | Failure mode |
|---|---|---|
| 1 | Kill Switch state | Reject all orders |
| 2 | Trading hours window | Reject outside configured window |
| 3 | Daily loss limit | Reject if PnL ≤ −`max_daily_loss_pct` × capital |
| 4 | Open position count | Reject if ≥ `max_open_positions` |
| 5 | Position size | Reject if notional > `max_position_size_pct` × capital |
| 6 | Daily order count | Reject if ≥ `max_orders_per_day` |
| 7 | Post-loss cooldown | Reject within `cooldown_after_loss_minutes` of a loss |
| 8 | Volatility guard | Reject if Nifty dropped > threshold inside the rolling window |
| 9 | Bias / Research filter | Reject when Commander bias or Research signal conflicts |

Every rejection writes a row to the audit log with the rule_id that fired. **No order ever reaches the broker without passing all nine.**

**Position Sizer:** `qty = floor((capital × risk%) / |entry − stop|)`. Clamped to `max_position_size_pct`. Pure function.

**OMS:** rate-limited (8 req/s), retries 3× with exponential backoff, reconciles fills against the local book, publishes every state change to `orders` and `fills` streams.

**Position Manager:** tracks open positions, drives stop-loss + target + trailing stop (50% of unrealised profit), OCO one-cancels-other, and forced square-off at 15:15 IST.

**Kill Switch:** active state in Redis. Auto-trips on (a) daily PnL ≤ −`max_daily_loss_pct`, (b) Nifty drop > 2% in 10 min. Manual toggle via `/api/kill-switch` or the dashboard. **Re-arming always requires operator acknowledgement** — no auto-recovery from a halted state.

**Paper Trading Engine:** simulates fills with configurable `simulated_fill_delay_ms` and `simulated_slippage_pct`. Activates when `paper_trading.enabled=true` OR the OMS is handed a `PaperOrder` instance — the two code paths are bit-identical below the Broker boundary.


---

## 4. Research subsystem

### 4.1 Graph shape (not a pipeline)

```
User prompt ─► Guardrail(in) ─► Orchestrator plan ─┬─► Filings ──────┐
                                                    ├─► Fundamentals ─┤
                Working / Semantic / Episodic       ├─► News          │  (6 concurrent
                memory (peer source) ───►───────────┤   Sentiment     ┤   Sub_Agents,
                                                    ├─► Technicals ───┤   asyncio
                Embedding / Retrieval / LLM cache   ├─► Peer / Sector─┤   semaphore
                (peer source) ───►───────────────────┤                │   cap = 6)
                                                    └─► Macro ────────┘
                                                                       │
                                                                       ▼
                                Report Synthesiser ─► Numeric Validator ─► Judge LLM
                                     ▲                                    │
                                     └──── feedback (≤ 1 re-synth) ◄──────┘
                                                                       │
                                                                       ▼
                                                   Guardrail(out) ─► Emit / Persist /
                                                                    Stream (SocketIO)
                                                                       │
                                                                       ▼
                                                    ResearchSignal ─► Trade event bus
                                                    (high-conviction, Judge-approved)
```

### 4.2 Six Sub_Agents, concurrent

| Agent | Retrieves | Produces | Cross-surface link |
|---|---|---|---|
| **Filings** | BM25 + dense chunks from filings docs | `AgentResult` | — |
| **Fundamentals** | Annual-report + results chunks | `AgentResult` | — |
| **News · Sentiment** | Semantic filter over news chunks | `AgentResult` | Subscribes to Commander's `news_clean` / `sentiment` / `bias` streams (no re-ingestion) |
| **Technicals** | Latest indicators from Soldier | `AgentResult` | Subscribes to Soldier's `indicators` stream |
| **Peer · Sector** | Peer + sector-classified chunks | `AgentResult` | Powers the "pharma combined" cohort views |
| **Macro** | Rates / GDP / regulatory chunks | `AgentResult` | — |

Agents return `kind: 'no_data'` cleanly when retrieval misses the similarity floor. The UI renders an explicit "No data available for &lt;agent&gt;" panel rather than hallucinated filler.

### 4.3 Hallucination-control stack

Four deterministic boundaries sit in the path from prompt to published brief:

| Layer | What it does | Non-LLM? |
|---|---|---|
| **1. Guardrail (input)** | Versioned regex ruleset + optional classifier. Jailbreaks, tool-allowlist violations, refusal-policy prompts short-circuit the run | Yes |
| **2. Closed-book prompts** | Every Sub_Agent prompt instructs the model to answer only from `<|CONTEXT|>` and write `INSUFFICIENT_EVIDENCE` where context is missing | N/A (prompt template) |
| **3. Numeric Validator** | Extracts every numeric token from the draft brief (₹, %, Cr, lakh, quarter codes) and checks against cited chunks within epsilon | Yes |
| **4. Judge LLM** | Scores groundedness, citation coverage, contradictions, off-policy; ≤ 1 re-synthesis; async fallback when over latency budget; deterministic rule-based judge under `LOHI_RESEARCH_OFFLINE=true` | Judge is an LLM, fallback is not |

Plus a **fifth** boundary at the exit: **Guardrail (output)** redacts PII (PAN, Aadhaar, phone), strips unauthorised tool-call tokens, and blocks banned content.

### 4.4 Provider-agnostic framework

Every LLM, embedding, and vector-store backend is a thin Pydantic-contracted adapter (`src/research/providers/`). Switching from NVIDIA NIM to Ollama to Anthropic is a config change, not a code change:

```yaml
research:
  providers:
    chat:          { provider: nvidia_nim, model: meta/llama-3.1-70b-instruct }
    summarisation: { provider: nvidia_nim, model: meta/llama-3.1-8b-instruct }
    embeddings:    { provider: sentence_transformers, model: BAAI/bge-small-en-v1.5 }
    judge:         { provider: nvidia_nim, model: meta/llama-3.1-70b-instruct, min_score: 0.7 }
  vector_store:
    backend: auto  # auto | chroma | pgvector | qdrant | lancedb
```

Default cloud path: **NVIDIA NIM** (free tier) + local sentence-transformers embeddings. Fully-offline path: **Ollama** + sentence-transformers. Vector store auto-detects pgvector on the existing Postgres and falls back to embedded Chroma otherwise.

### 4.5 Snapshot cache

Per-`(user_id, symbol)` pre-computed briefs live in `research_snapshots`. Fresh snapshots short-circuit the whole Sub_Agent fan-out — the Orchestrator serves the cached brief directly, which is how the 800 ms first-token SLO is hit under load.

Invalidation events:
- New document indexed for the symbol → `research:snapshot_invalidations`
- New Commander bias on a watchlist symbol → same channel
- High-impact sentiment spike → same channel

The Snapshotter worker debounces (default 60 s) and regenerates. On regeneration failure, the previous snapshot is retained and flagged `stale=true` so the UI can warn the user.

### 4.6 Memory

| Layer | Backend | Scope | Use |
|---|---|---|---|
| Working | Redis | `(user_id, conv_id)` | Sliding-window last N=12 turns + running summary |
| Semantic | Postgres + vectors | `user_id` (RLS) | Prior research summaries, preferences, watchlist facts |
| Episodic | Postgres | `(user_id, symbol)` (RLS) | Per-symbol brief timeline |

`memory.forget(user_id, scope)` deletes across all three within a 5 s SLA for scopes up to 10 k rows. Every call is audited.

## 5. Cross-surface bridge

The two surfaces share the same Redis backbone, and three explicit bridges tie them together:

| Bridge | Direction | What crosses |
|---|---|---|
| **News / sentiment / bias streams** | Trade → Research | Commander's `news_clean`, `sentiment`, `bias` Redis streams are consumed verbatim by the Research News_Sentiment agent. No duplicate ingestion, no double FinBERT inference. |
| **Indicators stream** | Trade → Research | Soldier's `indicators` stream feeds the Research Technicals agent. Live RSI / MACD / ATR values drop into the agent prompt as a `{{technicals_snapshot}}` block. |
| **ResearchSignal stream** | Research → Trade | Judge-approved briefs with `conviction ≥ 0.5` and a clear direction emit a `ResearchSignal` onto `research_signal`. The RMS's bias filter (check #9) consumes this as a boost or veto, per-strategy opt-in. |

All three are **opt-in**. Disabling the Research subsystem has no effect on Trade; disabling Trade does not break Research (the News and Technicals agents just fall back to their own retrieval paths).

### 5.1 ResearchSignal contract

```python
class ResearchSignal(BaseModel):
    signal_id: str
    symbol: str
    direction: Literal["bullish", "bearish", "neutral"]
    conviction: float              # [0.0, 1.0], Judge groundedness-derived
    archetype: StockArchetype      # compounder | value | growth | …
    sector: Sector | None
    source_run_id: str             # FK back to research_runs for audit
    thesis_short: str              # One-sentence human-readable
    emitted_at: int                # Epoch ms
    expires_at: int                # Epoch ms (default +24 h)
    consumed_by_algo: bool         # Set by the RMS filter on first read
```

Each strategy declares its own floor and direction policy:

```yaml
strategies:
  mean_reversion:
    enabled: true
    research_filter:
      enabled: false          # opt-in per strategy
      min_conviction: 0.6
      veto_on_mismatch: true  # bullish research + sell signal → veto
      boost_on_match: 1.2     # bullish research + buy signal → 1.2× signal weight
```

### 5.2 Failure isolation

A crashed Research bridge task in the gateway's `lifespan` (see `_start_research_bridge`) is logged but never crashes the gateway itself. Conversely, if the Commander dies, the Research News agent degrades gracefully: its retrieval layer still has the old chunks, and the `AgentResult` is tagged `stale_sentiment=true` rather than failing the whole brief.


---

## 6. Gateway (FastAPI + Socket.IO)

Single process, single entry point: `backend-gateway/app/main.py`. Uses FastAPI's **`lifespan` async context manager** (post the deprecation fix in `AUDIT_REPORT.md §2.1`) to orchestrate startup and shutdown deterministically.

### 6.1 Middleware stack

Starlette runs `add_middleware` in reverse order, so the *last* added is the *outermost*. The install order in `main.py` gives this effective pipeline (outermost → innermost):

```
RequestLoggingMiddleware  →  CORS  →  JWTAuth  →  GZip  →  CacheHeaders  →  InputSanitisation  →  route handler
```

- `RequestLoggingMiddleware` — structured JSON log per request (method, path, status, elapsed_ms, user_id).
- `CORS` — allow the React app + mobile app origins.
- `JWTAuthMiddleware` — extracts the Bearer token, sets `request.state.user_id` and `app.state.current_user_id` (the latter is how asyncpg RLS picks up the scope). Never rejects — rejection is a per-route dependency so unauthenticated public endpoints keep working.
- `GZip` — compress responses > 1 KB.
- `CacheHeaders` — `Cache-Control` per-route.
- `InputSanitisationMiddleware` — strip well-known XSS / SQL-injection tokens from headers + body; last defence before a handler sees user input.

### 6.2 Router surface

Counted in `main.py`: 28 REST routers (`/api/*` + `/api/v2/*`) plus the Research router at `/api/v2/research/*`. Highlights:

| Prefix | Purpose |
|---|---|
| `/api/auth`, `/api/v2/auth` | Login (legacy + v2), TOTP, social login, refresh |
| `/api/positions`, `/orders`, `/trades` | Core trading CRUD |
| `/api/v2/stock-universe`, `/watchlist`, `/screener`, `/market-data` | Market-data surface |
| `/api/v2/broker`, `/broker-v2` | Broker connection management |
| `/api/v2/verification`, `/bank-fund` | KYC, bank accounts, fund transactions |
| `/api/v2/chatbot` | Cross-surface chat (inherited by ResearchService) |
| `/api/v2/admin`, `/users` | RBAC-gated admin surface |
| `/api/v2/public/*` | Pre-auth read-only (public stock search, charts) |
| `/api/v2/research/*` | Full Research surface (runs, snapshots, ideas, themes, sectors, filings, signals, memory, health) |

### 6.3 Socket.IO bridge

The gateway mounts Socket.IO as an ASGI app wrapping FastAPI (`socket_app = socketio.ASGIApp(sio, app)`). Two background tasks keep it fed:

- **`_start_consumer`** — pumps the Trade streams (`ticks`, `orders`, `fills`, `kill_switch`, `bias`, `signals`, …) into Socket.IO events for the Trade dashboard.
- **`_start_research_bridge`** — forwards `research:partials`, `research:judge_report` pubsub, and `research:latency_budget` pubsub into per-run Socket.IO rooms (`research:<run_id>`).

Both are scheduled via `asyncio.create_task` inside the lifespan and cancelled with `.cancel()` + `await` on shutdown, so Redis connections drain before the pools close.

### 6.4 Error envelope

Every research-surface exception (provider auth failed, latency budget exceeded, config missing) goes through `register_research_exception_handlers` to produce a uniform `{"error": {code, message, provider?, model?}}` shape. The Trade side uses the standard FastAPI `HTTPException` with a `{"detail": ...}` shape. A next iteration should unify the two — tracked in `AUDIT_REPORT §7`.

---

## 7. Frontend (React SPA)

### 7.1 Shells — one app, two surfaces

`App.tsx` is the **Trade shell**: indigo/neon palette, OLED-black background, 8-group left sidebar with Dashboard / Trade / Positions / Orders / Markets / Trading / Watchlist / System / Account / Help.

`ResearchShell.tsx` is the **Research shell**: monochrome Quartr-inspired palette, editorial masthead with the Q-mark, 3-group left sidebar (Research / Workspace / Governance). Enters via the **ModeSwitcher** in the top chrome or any `/research/*` URL.

Both shells render the same `<Outlet />` of routed pages, share the same Zustand stores, and flip their surface tokens via `<html data-surface="trade|research">`.

### 7.2 Pages

**Trade (36 pages):** Dashboard · Trade · Positions · Orders · Strategies · Soldier · Commander · Algo Performance · Trade History · Analytics · Backtest (new / result) · Watchlist · Stock Universe · Screener · Stock Detail · Market Data · Chatbot (via panel) · Settings · Risk Settings · Broker Settings · Notifications · Profile · Verification · Bank Accounts · Fund Transactions · Brokers · Logs & Audit · System Status · Help · Architecture · Landing · Login · 2FA · Create Account · Onboarding · Setup Wizard.

**Research (9 pages):** Feed · Ideas · Sectors · Themes · Coverage · Briefs · Filings · Symbol · Chat · Architecture · Refusal Policy.

### 7.3 Component primitives

The app is built on a few repeated primitives that propagate the design system:

- `BentoCard` — the atomic bordered card. Hairline border, 7 % accent-tinted gradient, hover-lift, optional corner glow.
- `AnimatedNumber` — spring-interpolated number ticker driven by a MotionValue, so hundreds of instances at 20 Hz don't re-render React.
- `VirtualTable` — `@tanstack/react-virtual` + sticky glass header + drag-to-reorder columns persisted to localStorage.
- `PageHeader` — sticky glass header with icon tile, title, subtitle, right-side actions slot.
- `LohiAvatar` + `LohiAvatarResearch` — surface-aware SVG mascot. Auto-switcher picks the right one based on `AppMode`.
- `WorkflowCanvas` + `WorkflowSimulator` — DAG renderer used by both Architecture pages. Topological column layout, primary + sideband edges, travelling isometric cubes only on edges touching the active node.

### 7.4 Design tokens

Everything reads from `styles/design-tokens.css` for the Trade surface and `styles/research-theme.css` for the Research surface. Flipping the theme (light/dark) or the surface (trade/research) swaps CSS variables only — no component code branches on theme.

The **shadcn/ui token bridge** in the same file maps Tailwind's `--primary`, `--card`, `--popover`, `--border`, `--ring`, etc. onto Lohi's tokens, so shadcn primitives inherit the look with zero file edits.

---

## 8. State layer

| Store | Technology | Purpose | Access pattern |
|---|---|---|---|
| **Event bus** | Redis Streams + pubsub | Inter-component messaging, kill-switch state, Socket.IO feed | Ordered writes, consumer groups |
| **Operational DB** | PostgreSQL (production) / SQLite (dev) | Trades, orders, positions, users, verification, research runs + sections + provenance + judge reports + memory + snapshots | Transactional read/write with RLS |
| **Historical DB** | DuckDB | Historical OHLCV in Parquet-partitioned-by-date | Analytical queries for backtesting + charting |

### 8.1 Row-Level Security

Every `research_*` table and every multi-user `*_v2` table is protected by a Postgres RLS policy of the form:

```sql
USING (user_id = current_setting('app.user_id')::uuid)
```

The JWT middleware sets `app.state.current_user_id` at request scope; a helper in `services/research/rls.py` invokes `SELECT set_config('app.user_id', $1, true)` on each acquired asyncpg connection. **A service that forgets to set `app.user_id` sees zero rows**, not all rows — safe-by-default.

### 8.2 Memory layers (Research)

Covered in §4.6. All three layers are RLS-scoped; `memory.forget(user_id, scope)` is the single audit-logged delete path.


---

## 9. Configuration & secrets

**Single config file:** `config/settings.yaml`. Every knob in the system is documented there. Details live in `docs/CONFIGURATION.md`.

**Secrets resolution:** any `${ENV_VAR}` reference in `settings.yaml` is resolved at load time from (a) the `.env` file in the repo root, then (b) the process environment. Missing required env vars raise a structured error at startup — no silent fallbacks.

- `.env.template` — Trade secrets (broker API keys, TOTP seeds, Telegram token).
- `.env.research.template` — Research secrets (NVIDIA NIM / OpenAI / Anthropic / Gemini / Groq / Together / OpenRouter keys).

Broker tokens are **Fernet-encrypted at rest** using `MASTER_ENCRYPTION_KEY`. The structured log formatter redacts `api_key|secret|token|password|totp` so tokens never leak into logs.

---

## 10. Observability

### 10.1 Structured logs

Single logger (`src/utils/logger.py`) emits JSON lines with canonical fields: `timestamp`, `level`, `component`, `user_id`, `request_id`, `message`, plus per-event metadata. The Dashboard's Logs & Audit page reads the same log stream and surfaces per-strategy / per-component filters.

### 10.2 Prometheus metrics

Research-side counters and histograms are wired via `src/research/observability/metrics.py`:

- `research_runs_total{status}` — count of run terminations by status.
- `research_guardrail_blocks_total{rule_id}` — Guardrail refusals, by rule.
- `research_judge_failures_total` — Judge re-synthesis triggers.
- `research_first_token_ms` (histogram) — first Socket.IO `research:token` latency.
- `research_first_agent_ms` (histogram) — first Sub_Agent partial latency.
- `research_full_brief_ms` (histogram) — end-to-end brief latency.
- `research_guardrail_overhead_ms` (histogram) — Guardrail layer overhead.

Exposed through the gateway's existing Prometheus endpoint.

### 10.3 Per-run trace

`GET /api/v2/research/runs/:id/trace` returns a replayable trace joining `research_runs`, `research_provenance`, `research_guardrail_decisions`, `research_judge_reports`, and `llm_usage`. The Research dashboard exposes this as a drawer on the Chat and Symbol pages. This is also the foundation for the "better debugging framework" proposed in `AUDIT_REPORT §8`.

### 10.4 Telegram notifications

The Trade-side Telegram bot consumes `orders`, `fills`, and `kill_switch` streams and forwards them as human-readable messages. Rate-limited at `rate_limit_messages_per_hour` (default 20). A similar consumer could forward Research-side `research:judge_report` failures and high-conviction `ResearchSignal` events — drafted in `AUDIT_REPORT §8` as a follow-up.

---

## 11. Deployment topology

### 11.1 Developer / single-user self-hosted

```
docker-compose up -d         # Redis + Postgres
./start.sh                   # Trade: gateway + all workers
./start-research.sh          # Research: Orchestrator + Indexer + Snapshotter
cd 'Lohi-TRADE Web App Design' && npm run dev
```

Postgres optional — the gateway falls back to SQLite + in-memory stock universe for UI demos, warning loudly in logs.

### 11.2 Production / multi-user cloud

The `lohi-trade-platform-expansion` spec covers the multi-user story:
- Postgres with RLS for user-scoped isolation
- JWT v2 access + refresh token pair
- Social login (Google / Apple) + email/password
- Per-user broker credentials (Fernet-encrypted)
- Rate-limited pre-auth endpoints
- RBAC roles: user / admin

AWS infra lives under `infra/` (Terraform) — not covered in depth here.

### 11.3 Offline mode

Setting `LOHI_RESEARCH_OFFLINE=true`:
- Provider registry refuses every cloud LLM and cloud embeddings adapter at boot (throws `CloudProviderForbiddenError`, names the offending provider + role).
- Judge switches from the LLM to the deterministic rule-based judge.
- Full-brief latency budget relaxes from 15 s to 60 s.
- Ollama + local sentence-transformers serve every model call.

Trade has no offline switch — it always needs live broker / market-data connections.

---

## 12. Security & safety posture

1. **RLS by default.** Every research and v2 multi-user table requires `app.user_id`; a service that forgets to set it sees nothing.
2. **Kill Switch.** Manual re-arm only. Auto-trips on daily-loss and volatility-guard breaches.
3. **Paper trading.** First-class, always-on option — no accidental live orders during development.
4. **Guardrail Layer.** Every user prompt through input + output regex + optional classifier. Refused prompts never reach a Sub_Agent.
5. **Judge LLM.** Every brief scored for groundedness and off-policy content; failures get one re-synthesis attempt, then fall to `quality=low`.
6. **Numeric validator.** Deterministic check on every numeric token in a brief.
7. **Closed-book prompts.** Models are told to answer only from provided context; unsupported claims are written as `INSUFFICIENT_EVIDENCE` and stripped.
8. **Refusal policy.** No buy/sell/hold, no price targets, no trade suggestions in Research output. Documented in `docs/research/REFUSAL_POLICY.md`.
9. **Secrets.** Fernet-encrypted at rest, redacted in logs, never in `settings.yaml` directly.
10. **Audit log.** Every guardrail decision, memory.forget, kill-switch toggle, and order rejection is append-only audited.

---

## 13. Non-functional targets

| SLO | Cloud path (reference config) | Offline path |
|---|---|---|
| Research first-token latency | ≤ 800 ms | relaxed |
| Research first-agent latency | ≤ 2 s | relaxed |
| Research full-brief latency | ≤ 15 s | ≤ 60 s |
| Research concurrent runs / gateway | ≥ 5 | same |
| Guardrail overhead p95 | ≤ 50 ms | same |
| Judge overhead | ≤ 2 s (async fallback above budget) | N/A (rule-based) |
| Trade tick → signal latency | ≤ 500 ms | N/A |
| Trade signal → order placed | ≤ 200 ms | same |
| Kill-switch trip → RMS reject | ≤ 200 ms | same |
| PnL tick → KillSwitch check | ≤ 200 ms | same |

---

## 14. Where to go next

| If you want to… | Read |
|---|---|
| Tune any setting | `docs/CONFIGURATION.md` |
| Add a new strategy | `docs/STRATEGIES.md` |
| Replay historical ticks | `docs/BACKTESTING.md` |
| Understand the Research brief pipeline in code | `src/research/agents/orchestrator.py` + `.kiro/specs/lohi-research-dashboard/design.md` |
| Add a new LLM or vector-store adapter | `src/research/providers/` + its 1-line registry entry |
| Trace a production incident | `GET /api/v2/research/runs/:id/trace` + `Logs & Audit` page + Prometheus |
| Understand the refusal policy | `docs/research/REFUSAL_POLICY.md` |
| See what each provider sends where | `docs/research/PROVIDERS.md` |
| See what's still open | `docs/AUDIT_REPORT.md` |
| Spec source of truth | `.kiro/specs/{lohi-trade, lohi-trade-platform-expansion, lohi-research-dashboard}/` |
