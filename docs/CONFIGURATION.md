# Configuration Guide

## Overview

LOHI-TRADE uses a YAML configuration file at `config/settings.yaml`. All system behavior — capital limits, risk parameters, strategy tuning, broker credentials, and infrastructure settings — is controlled from this single file.

Sensitive values (API keys, passwords) can be overridden with environment variables using `${ENV_VAR}` syntax. At startup, the config loader resolves these placeholders from the process environment or a `.env` file in the project root.

---

## Configuration Sections

### Capital

Controls overall capital allocation and risk budgeting.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `total` | float | `200000` | Total trading capital in INR |
| `risk_per_trade_pct` | float | `1.0` | Maximum risk per trade as percentage of total capital |
| `max_position_size_pct` | float | `20.0` | Maximum single position size as percentage of total capital |
| `max_daily_loss_pct` | float | `2.0` | Maximum daily loss as percentage of total capital (triggers kill switch) |

**Example:**
```yaml
capital:
  total: 200000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0
```

---

### Risk Limits

Guardrails that the RMS (Risk Management System) enforces on every order.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_open_positions` | int | `5` | Maximum concurrent open positions |
| `max_orders_per_day` | int | `20` | Maximum orders allowed per trading day |
| `cooldown_after_loss_minutes` | int | `5` | Cooldown period (minutes) after a losing trade before new entries |
| `volatility_guard_threshold_pct` | float | `2.0` | Nifty 50 drop percentage that triggers the volatility guard |
| `volatility_guard_window_minutes` | int | `10` | Rolling window (minutes) for measuring Nifty volatility |

**Example:**
```yaml
risk_limits:
  max_open_positions: 5
  max_orders_per_day: 20
  cooldown_after_loss_minutes: 5
  volatility_guard_threshold_pct: 2.0
  volatility_guard_window_minutes: 10
```

---

### Trading Hours

Defines the trading session boundaries. All times are in IST (Indian Standard Time).

| Parameter | Type | Format | Default | Description |
|-----------|------|--------|---------|-------------|
| `market_open` | str | `HH:MM` | `09:15` | NSE market open time |
| `trading_start` | str | `HH:MM` | `09:30` | Signal generation begins (15 min after open for candle warmup) |
| `trading_end` | str | `HH:MM` | `15:10` | Signal generation stops (no new entries after this) |
| `square_off_time` | str | `HH:MM` | `15:15` | All open positions are force-closed |
| `market_close` | str | `HH:MM` | `15:30` | NSE market close time |

**Example:**
```yaml
trading_hours:
  market_open: "09:15"
  trading_start: "09:30"
  trading_end: "15:10"
  square_off_time: "15:15"
  market_close: "15:30"
```

---

### Broker

Broker API credentials and selection. Supports Shoonya and Angel One with automatic failover.

| Parameter | Type | Description |
|-----------|------|-------------|
| `primary` | str | Primary broker name (`shoonya` or `angelone`) |
| `backup` | str | Backup broker name (used on primary failure) |

**Shoonya credentials:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | str | Shoonya API key (use `${SHOONYA_API_KEY}`) |
| `client_id` | str | Shoonya client ID (use `${SHOONYA_CLIENT_ID}`) |
| `password` | str | Shoonya password (use `${SHOONYA_PASSWORD}`) |
| `totp_key` | str | TOTP secret for 2FA (use `${SHOONYA_TOTP_KEY}`) |
| `imei` | str | IMEI for Shoonya API (use `${SHOONYA_IMEI}`) |

**Angel One credentials:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | str | Angel One API key (use `${ANGELONE_API_KEY}`) |
| `client_id` | str | Angel One client ID (use `${ANGELONE_CLIENT_ID}`) |
| `password` | str | Angel One password (use `${ANGELONE_PASSWORD}`) |
| `totp_key` | str | TOTP secret for 2FA (use `${ANGELONE_TOTP_KEY}`) |

**Example:**
```yaml
broker:
  primary: shoonya
  backup: angelone
  shoonya:
    api_key: ${SHOONYA_API_KEY}
    client_id: ${SHOONYA_CLIENT_ID}
    password: ${SHOONYA_PASSWORD}
    totp_key: ${SHOONYA_TOTP_KEY}
    imei: ${SHOONYA_IMEI}
  angelone:
    api_key: ${ANGELONE_API_KEY}
    client_id: ${ANGELONE_CLIENT_ID}
    password: ${ANGELONE_PASSWORD}
    totp_key: ${ANGELONE_TOTP_KEY}
```

> **Security:** Never commit plaintext credentials. Always use `${ENV_VAR}` references and store actual values in `.env` (which is gitignored).

---

### Strategies

Tuning parameters for each trading strategy.

#### Mean Reversion

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rsi_period` | int | `14` | RSI lookback period |
| `rsi_oversold` | float | `30` | RSI threshold for oversold condition |
| `bb_period` | int | `20` | Bollinger Bands lookback period |
| `bb_std` | float | `2.0` | Bollinger Bands standard deviation multiplier |
| `volume_multiplier` | float | `1.5` | Required volume spike (multiple of 20-period average) |

#### Trend Following

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ema_fast` | int | `9` | Fast EMA period |
| `ema_slow` | int | `21` | Slow EMA period |
| `macd_fast` | int | `12` | MACD fast period |
| `macd_slow` | int | `26` | MACD slow period |
| `macd_signal` | int | `9` | MACD signal line period |
| `volume_multiplier` | float | `1.0` | Required volume (multiple of 20-period average) |

#### Opening Range Breakout (ORB)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `range_start` | str | `09:15` | Opening range start time |
| `range_end` | str | `09:30` | Opening range end time |
| `volume_multiplier` | float | `2.0` | Required volume spike at breakout |
| `breakout_buffer_pct` | float | `0.1` | Buffer beyond range high/low to confirm breakout |

**Example:**
```yaml
strategies:
  mean_reversion:
    rsi_period: 14
    rsi_oversold: 30
    bb_period: 20
    bb_std: 2.0
    volume_multiplier: 1.5
  trend_following:
    ema_fast: 9
    ema_slow: 21
    macd_fast: 12
    macd_slow: 26
    macd_signal: 9
    volume_multiplier: 1.0
  opening_range_breakout:
    range_start: "09:15"
    range_end: "09:30"
    volume_multiplier: 2.0
    breakout_buffer_pct: 0.1
```

---

### Sentiment

Controls The Commander's sentiment analysis and bias calculation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bias_bullish_threshold` | float | `0.2` | Aggregated score above this → BULLISH bias |
| `bias_bearish_threshold` | float | `-0.2` | Aggregated score below this → BEARISH bias |
| `time_decay_half_life_hours` | int | `4` | Exponential decay half-life for sentiment scores |
| `lookback_hours` | int | `24` | How far back to consider news articles |
| `recalculation_interval_minutes` | int | `5` | How often bias is recalculated |

**Example:**
```yaml
sentiment:
  bias_bullish_threshold: 0.2
  bias_bearish_threshold: -0.2
  time_decay_half_life_hours: 4
  lookback_hours: 24
  recalculation_interval_minutes: 5
```

---

### Telegram

Notification bot configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bot_token` | str | — | Telegram bot token (use `${TELEGRAM_BOT_TOKEN}`) |
| `chat_id` | str | — | Target chat/group ID (use `${TELEGRAM_CHAT_ID}`) |
| `rate_limit_messages_per_hour` | int | `20` | Maximum messages per hour to avoid flooding |

**Example:**
```yaml
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  rate_limit_messages_per_hour: 20
```

---

### Redis

Event bus and real-time state store configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | `localhost` | Redis server hostname |
| `port` | int | `6379` | Redis server port |
| `db` | int | `0` | Redis database number |

**Example:**
```yaml
redis:
  host: localhost
  port: 6379
  db: 0
```

---

### Database

Persistent storage paths and backup configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sqlite_path` | str | `data/lohi_trade.db` | SQLite database for operational data |
| `duckdb_path` | str | `data/historical.duckdb` | DuckDB database for historical OHLCV |
| `backup_path` | str | `data/backups` | Directory for automated backups |
| `backup_time` | str | `16:00` | Daily backup time (IST) |

**Example:**
```yaml
database:
  sqlite_path: data/lohi_trade.db
  duckdb_path: data/historical.duckdb
  backup_path: data/backups
  backup_time: "16:00"
```

---

### Logging

Application logging configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | str | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `log_dir` | str | `logs` | Directory for log files |
| `max_file_size_mb` | int | `10` | Maximum log file size before rotation |
| `backup_count` | int | `5` | Number of rotated log files to keep |

**Example:**
```yaml
logging:
  level: INFO
  log_dir: logs
  max_file_size_mb: 10
  backup_count: 5
```

---

### Paper Trading

Simulated trading mode for strategy validation without real broker orders.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable paper trading mode |
| `simulated_fill_delay_ms` | list | `[100, 500]` | Random fill delay range in milliseconds `[min, max]` |
| `simulated_slippage_pct` | float | `0.05` | Simulated slippage percentage on fills |

**Example:**
```yaml
paper_trading:
  enabled: true
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05
```

---

### Symbols

List of NSE symbols to trade. The system subscribes to real-time data for these symbols and runs all enabled strategies against them.

**Example:**
```yaml
symbols:
  - RELIANCE
  - TCS
  - INFY
  - HDFCBANK
  - ICICIBANK
  - SBIN
  - BHARTIARTL
  - ITC
  - KOTAKBANK
  - LT
```

---

## Environment Variables

### How It Works

The config loader scans all string values in `settings.yaml` for the pattern `${VARIABLE_NAME}`. At load time, it replaces these with the corresponding environment variable value.

**Resolution order:**
1. `.env` file in project root (loaded via `python-dotenv`)
2. System environment variables
3. If neither is found, the application raises an error at startup

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `SHOONYA_API_KEY` | Shoonya broker API key |
| `SHOONYA_CLIENT_ID` | Shoonya client ID |
| `SHOONYA_PASSWORD` | Shoonya account password |
| `SHOONYA_TOTP_KEY` | Shoonya TOTP secret |
| `SHOONYA_IMEI` | Shoonya IMEI identifier |
| `ANGELONE_API_KEY` | Angel One API key |
| `ANGELONE_CLIENT_ID` | Angel One client ID |
| `ANGELONE_PASSWORD` | Angel One account password |
| `ANGELONE_TOTP_KEY` | Angel One TOTP secret |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID |

### Setting Up `.env`

Create a `.env` file in the project root:

```bash
# Broker - Shoonya
SHOONYA_API_KEY=your_api_key_here
SHOONYA_CLIENT_ID=your_client_id
SHOONYA_PASSWORD=your_password
SHOONYA_TOTP_KEY=your_totp_secret
SHOONYA_IMEI=your_imei

# Broker - Angel One
ANGELONE_API_KEY=your_api_key_here
ANGELONE_CLIENT_ID=your_client_id
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_KEY=your_totp_secret

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

> **Important:** The `.env` file is listed in `.gitignore` and must never be committed to version control.

---

### Lohi-Research

The `research:` block in `config/settings.yaml` controls every knob of
the Lohi-Research dashboard (multi-agent RAG over Indian corporate
filings). Secrets are never inlined — every API key is a `${ENV_VAR}`
reference resolved from `.env.research` (see
[`.env.research.template`](../.env.research.template)). For provider
data-locality and offline-mode behavior, see
[`docs/research/PROVIDERS.md`](research/PROVIDERS.md).

#### Root

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Master switch for the research subsystem. When `false` the gateway mounts no `/api/v2/research/*` routes and the workers are not started. |
| `offline_mode` | bool (env-expanded) | `${LOHI_RESEARCH_OFFLINE:false}` | When truthy (`true` / `1` / `yes`), the provider registry refuses every cloud LLM and cloud embeddings adapter at boot and the offline latency budget applies. See PROVIDERS.md. |

**Example:**
```yaml
research:
  enabled: true
  offline_mode: ${LOHI_RESEARCH_OFFLINE:false}
```

#### Providers

Per-role LLM / embeddings selection. Each role can name a different
provider / model; missing role overrides fall back to the global
default for that role (Req 12.1–12.2). See
[`docs/research/PROVIDERS.md`](research/PROVIDERS.md) for supported
provider names.

##### `research.providers.chat`

LLM used by the Orchestrator and the Report_Synthesizer for chat-style
turns.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `nvidia_nim` | Registered LLM provider name (`nvidia_nim`, `openai`, `anthropic`, `gemini`, `groq`, `together`, `openrouter`, `ollama`). |
| `model` | str | `meta/llama-3.1-70b-instruct` | Model identifier understood by the selected provider. |
| `api_key` | str | `${NVIDIA_NIM_API_KEY}` | `${ENV_VAR}`-expanded secret. Must match the selected provider's key (Req 2.9). |
| `temperature` | float | `0.2` | Sampling temperature. Range `[0.0, 2.0]`. |
| `max_tokens` | int | `2048` | Max output tokens per call. |
| `timeout_ms` | int | `15000` | Per-call timeout in milliseconds. |

##### `research.providers.summarisation`

LLM used for section synthesis and Working_Memory summarisation
(Req 4.2). Typically a smaller, cheaper model than `chat`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `nvidia_nim` | Registered LLM provider name. |
| `model` | str | `meta/llama-3.1-8b-instruct` | Model identifier. |
| `api_key` | str | `${NVIDIA_NIM_API_KEY}` | `${ENV_VAR}`-expanded secret. |

##### `research.providers.reranker`

Cross-encoder reranker applied after hybrid retrieval (Req 3.9). Runs
locally via sentence-transformers when enabled. Disabled by default to
stay within the reference-config RAM budget (design Open Issue #2).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `false` | Set `true` to rerank the top-k hybrid hits. |
| `provider` | str | `sentence_transformers` | Currently the only supported reranker backend. |
| `model` | str | `BAAI/bge-reranker-base` | Cross-encoder model identifier. |

##### `research.providers.embeddings`

Embeddings provider used at ingest and query time. The default path
is fully local.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `sentence_transformers` | Registered embeddings provider (`sentence_transformers`, `nvidia_nim`, `openai`, `ollama`). |
| `model` | str | `BAAI/bge-small-en-v1.5` | Embedding model identifier. The similarity floor in `research.retrieval.similarity_floor` must include this model. |

##### `research.providers.judge`

LLM role used by `Judge_LLM` for groundedness and refusal scoring
(Req 16.12–16.21). Operators can pick a different (stronger or
cheaper) model than `chat`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `nvidia_nim` | Registered LLM provider name. |
| `model` | str | `meta/llama-3.1-70b-instruct` | Model identifier. |
| `api_key` | str | `${NVIDIA_NIM_API_KEY}` | `${ENV_VAR}`-expanded secret. |
| `min_score` | float | `0.7` | Minimum per-section groundedness score required for `safe_to_display=true`. Range `[0.0, 1.0]`. Duplicated under `research.judge.min_score` for convenience — both resolve to the same value. |

**Example (providers block):**
```yaml
research:
  providers:
    chat:
      provider: nvidia_nim
      model: meta/llama-3.1-70b-instruct
      api_key: ${NVIDIA_NIM_API_KEY}
      temperature: 0.2
      max_tokens: 2048
      timeout_ms: 15000
    summarisation:
      provider: nvidia_nim
      model: meta/llama-3.1-8b-instruct
      api_key: ${NVIDIA_NIM_API_KEY}
    reranker:
      provider: sentence_transformers
      model: BAAI/bge-reranker-base
      enabled: false
    embeddings:
      provider: sentence_transformers
      model: BAAI/bge-small-en-v1.5
    judge:
      provider: nvidia_nim
      model: meta/llama-3.1-70b-instruct
      api_key: ${NVIDIA_NIM_API_KEY}
      min_score: 0.7
```

#### Vector store

Selects the backing `VectorStore` adapter. The default `auto` probes
Postgres for the `vector` extension once at boot and picks `pgvector`
on hit, `chroma` on miss (design §8). Operator overrides always win
(Req 2.15).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | str | `auto` | One of `auto`, `chroma`, `pgvector`, `qdrant`, `lancedb`. |
| `chroma.path` | str | `data/research/chroma` | On-disk directory for embedded Chroma. Created at boot if missing. |
| `pgvector.schema` | str | `public` | Postgres schema. Reuses the gateway's `DATABASE_URL`; no separate connection. |
| `qdrant.url` | str | `http://localhost:6333` | Qdrant endpoint. Local by default; may point at Qdrant Cloud (see PROVIDERS.md). |
| `lancedb.path` | str | `data/research/lance` | On-disk directory for LanceDB. |

**Example:**
```yaml
research:
  vector_store:
    backend: auto
    chroma:
      path: data/research/chroma
    pgvector:
      schema: public
    qdrant:
      url: http://localhost:6333
    lancedb:
      path: data/research/lance
```

#### Ingest

Sources polled and watched by `research-indexer` (Req 3.1–3.2) plus
the outbound User-Agent used for HTTP fetches (Req 3.3).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sources.bse_feed.enabled` | bool | `true` | Poll the BSE public announcement feed. |
| `sources.bse_feed.poll_interval_sec` | int | `300` | Seconds between polls. Minimum 60. |
| `sources.nse_feed.enabled` | bool | `true` | Poll the NSE public announcement feed. |
| `sources.nse_feed.poll_interval_sec` | int | `300` | Seconds between polls. Minimum 60. |
| `sources.user_uploads.enabled` | bool | `true` | Watch a local directory for user-dropped PDFs. |
| `sources.user_uploads.watch_dir` | str | `data/research/uploads` | Directory watched for new files. |
| `sources.sebi_edifar.enabled` | bool | `false` | Optional — ingest SEBI EDIFAR disclosures when enabled. |
| `sources.company_ir.enabled` | bool | `false` | Optional — ingest per-symbol company IR PDFs. |
| `robots_user_agent` | str | `Lohi-ResearchBot/0.1 (+https://github.com/...)` | User-Agent used for robots.txt evaluation and outbound fetches. |

**Example:**
```yaml
research:
  ingest:
    sources:
      bse_feed:     { enabled: true,  poll_interval_sec: 300 }
      nse_feed:     { enabled: true,  poll_interval_sec: 300 }
      user_uploads: { enabled: true,  watch_dir: data/research/uploads }
      sebi_edifar:  { enabled: false }
      company_ir:   { enabled: false }
    robots_user_agent: "Lohi-ResearchBot/0.1 (+https://github.com/...)"
```

#### Chunking

Document-splitting strategy applied at ingest (Req 3.6). The
`chunker_version` participates in the deterministic `chunk_id` hash,
so changing it invalidates previously-indexed chunks on the next
re-index (Req 3.12, Req 14.4).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategy` | str | `recursive_character` | Splitter strategy; `recursive_character` is the only v1 value. |
| `chunk_size_tokens` | int | `800` | Target tokens per chunk. Typical range `400–1200`. |
| `chunk_overlap_tokens` | int | `120` | Overlap between adjacent chunks. Must be `< chunk_size_tokens`. |
| `chunker_version` | str | `v1` | Version tag mixed into `chunk_id = sha256(doc_sha256 \|\| chunker_version \|\| position)`. Bump to force a full re-chunk. |

**Example:**
```yaml
research:
  chunking:
    strategy: recursive_character
    chunk_size_tokens: 800
    chunk_overlap_tokens: 120
    chunker_version: "v1"
```

#### Retrieval

Hybrid (BM25 + dense) retrieval weighting, rerank cutoff, and the
per-embedding-model similarity floor that the Orchestrator uses to
short-circuit to refusal when retrieval is empty (Req 3.8, Req 16.24).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hybrid.bm25_weight` | float | `0.4` | Weight of BM25 score in the hybrid merge. Must sum to 1.0 with `dense_weight`. |
| `hybrid.dense_weight` | float | `0.6` | Weight of dense cosine score in the hybrid merge. |
| `hybrid.top_k` | int | `40` | Hits returned from the hybrid stage before reranking. |
| `rerank_top_k` | int | `10` | Hits kept after cross-encoder reranking. Must be `<= hybrid.top_k`. |
| `similarity_floor` | map[str, float] | `{"BAAI/bge-small-en-v1.5": 0.25}` | Per-embedding-model minimum cosine similarity. Queries producing zero hits at or above the floor trigger a per-agent refusal (Req 16.24). The active `research.providers.embeddings.model` must have an entry. |

**Example:**
```yaml
research:
  retrieval:
    hybrid:
      bm25_weight: 0.4
      dense_weight: 0.6
      top_k: 40
    rerank_top_k: 10
    similarity_floor:
      "BAAI/bge-small-en-v1.5": 0.25
```

#### Memory

Working / Semantic / Episodic memory toggles (Req 4.1–4.4).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `working.window_turns` | int | `12` | Sliding-window size for per-conversation Working_Memory. |
| `working.max_tokens` | int | `4096` | Token budget for Working_Memory. When exceeded, oldest turns are summarised via `providers.summarisation` and replaced. |
| `semantic.enabled` | bool | `true` | Toggle Semantic_Memory (RLS-scoped session summaries, preferences). |
| `episodic.enabled` | bool | `true` | Toggle Episodic_Memory (per-(user, symbol) brief timeline). |

**Example:**
```yaml
research:
  memory:
    working:
      window_turns: 12
      max_tokens: 4096
    semantic:
      enabled: true
    episodic:
      enabled: true
```

#### Guardrails

`Guardrail_Layer` configuration (Req 16.1–16.11). The default
framework-light path uses the versioned regex ruleset; LangChain /
Guardrails-AI / NeMo adapters are opt-in via `enabled_adapters`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ruleset` | str | `src/research/guardrails/rules/v1.yaml` | Path to the versioned regex ruleset. See [`REFUSAL_POLICY.md`](research/REFUSAL_POLICY.md) for the rule ID registry. |
| `enabled_adapters` | list[str] | `[]` | Opt-in guardrail adapters. Valid values: `langchain`, `guardrails_ai`, `nemo`. Empty list = framework-light default. |
| `classifier.enabled` | bool | `false` | Enable the optional zero-shot jailbreak classifier. |
| `classifier.model` | str | `cross-encoder/nli-MiniLM2-L6-H768` | Sentence-transformers model used by the classifier. |
| `rate_limits.requests_per_minute` | int | `30` | Per-user guardrail rate limit (Req 16.5). |

**Example:**
```yaml
research:
  guardrails:
    ruleset: src/research/guardrails/rules/v1.yaml
    enabled_adapters: []
    classifier:
      enabled: false
      model: cross-encoder/nli-MiniLM2-L6-H768
    rate_limits:
      requests_per_minute: 30
```

#### Judge

`Judge_LLM` threshold and retry policy (Req 16.17–16.22, Req 15.8).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_score` | float | `0.7` | Minimum per-section groundedness score for `safe_to_display=true`. Range `[0.0, 1.0]`. |
| `max_retries` | int | `1` | Maximum re-synthesis loops after a Judge failure. Spec caps this at 1 (Req 16.18–16.19). |
| `async_fallback_budget_ms` | int | `2000` | When a synchronous Judge would push the run over `latency_budgets.full_brief_ms`, the Judge runs asynchronously and the brief is emitted with `judge_pending=true`. |

**Example:**
```yaml
research:
  judge:
    min_score: 0.7
    max_retries: 1
    async_fallback_budget_ms: 2000
```

#### Snapshot

Per-symbol precomputed-brief cache (Req 11.1–11.6).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `staleness_window_sec` | int | `900` | Seconds a Snapshot is treated as fresh and served directly (default 15 minutes). |
| `debounce_sec` | int | `60` | Debounce window between a Snapshot invalidation event and regeneration. |

**Example:**
```yaml
research:
  snapshot:
    staleness_window_sec: 900
    debounce_sec: 60
```

#### Latency budgets

Soft budgets enforced by the Orchestrator (Req 5.1–5.3, Req 15.4–15.5).
Exceeding any budget emits a structured `latency_budget_exceeded` event
(Req 5.9) rather than failing the run.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `first_token_ms` | int | `800` | First Socket.IO `research:token` event budget, cloud path. |
| `first_agent_ms` | int | `2000` | First Sub_Agent partial result budget, cloud path. |
| `full_brief_ms` | int | `15000` | Full brief budget, cloud path (Req 15.4). |
| `offline_full_brief_ms` | int | `60000` | Full brief budget when `offline_mode: true` (Req 15.5). |

**Example:**
```yaml
research:
  latency_budgets:
    first_token_ms: 800
    first_agent_ms: 2000
    full_brief_ms: 15000
    offline_full_brief_ms: 60000
```

#### Concurrency

Per-run and per-gateway concurrency caps (Req 5.4, Req 15.1).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `per_run_max_subagents` | int | `6` | Maximum Sub_Agents fanned out concurrently within a single Research_Run. |
| `gateway_max_concurrent_runs` | int | `5` | Maximum concurrent Research_Runs per gateway instance. |

**Example:**
```yaml
research:
  concurrency:
    per_run_max_subagents: 6
    gateway_max_concurrent_runs: 5
```
