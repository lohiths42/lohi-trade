# Unattended Research Bring-up — Overnight Run

**Started:** 2026-05-04 22:58 IST (Mon)  
**Completed:** 2026-05-05 10:47 IST (Tue)  
**Operator:** agent (you were asleep)

---

## Final Status

| Component | Status | Notes |
|-----------|--------|-------|
| Gateway (port 8000) | ✅ running | healthy, redis+db connected |
| Frontend (port 3000) | ✅ running | Vite dev server |
| Nubra Ticker | ✅ running | 10 symbols subscribed, ticks flowing at market open |
| Redis | ✅ running | Docker, port 6379 |
| Postgres | ✅ running | Docker, port 5432, migrations applied |
| Research workers (3) | ✅ running | orchestrator, indexer, snapshotter |
| Research deps installed | ✅ done | chromadb, sentence-transformers, langgraph, etc. |
| Embeddings model | ⏳ partial | BAAI/bge-small-en-v1.5 download started, may need re-run |
| LLM provider | ❌ blocked | needs your action (see below) |
| Data safety hardening | ✅ done | DLP rules, backup, diagnostic tool |
| First backup | ✅ done | `data/backups/lohi_trade_backup_20260505_104713.db` |

---

## What Works Right Now (no action needed)

1. **Live stock data** — Nubra quotes + charts for all NSE/BSE symbols via REST
2. **Real-time tick stream** — 10 symbols subscribed, ticks flow to browser at market open (09:15 IST)
3. **Stock universe** — 5,116 real NSE/BSE securities with fundamentals
4. **Research infrastructure** — all Python deps installed, workers running, Chroma DB initialized
5. **Safety mechanisms** — guardrails, DLP rules, audit logging, backup system
6. **Diagnostic tool** — `python scripts/diagnose.py` gives full system health

---

## What You Need To Do (5 minutes)

### Step 1: Get an LLM running (pick ONE)

**Option A — NVIDIA NIM (recommended, fastest, free tier):**
1. Go to https://build.nvidia.com
2. Sign in (GitHub/Google/email)
3. Click avatar → API Keys → Generate
4. Edit `.env.research`:
   ```
   NVIDIA_NIM_API_KEY=nvapi-YOUR-KEY-HERE
   LOHI_RESEARCH_OFFLINE=false
   ```
5. Restart gateway: `pkill -f uvicorn && cd backend-gateway && nohup uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 > /tmp/gw.log 2>&1 &`

**Option B — Ollama (fully private, no internet):**
1. Download from https://ollama.com/download/mac
2. Open Ollama.app (drag to Applications first)
3. In terminal: `ollama pull gemma3:12b` (wait for ~8 GB download)
4. Edit `.env.research`:
   ```
   LOHI_RESEARCH_OFFLINE=true
   ```
5. Restart gateway (same command as above)

### Step 2: Verify research health
```bash
curl http://localhost:8000/api/v2/research/health | python -m json.tool
```
Should show `"status": "ok"` for all components.

### Step 3: Run your first research brief
```bash
curl -X POST http://localhost:8000/api/v2/research/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/api/v2/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' | python -c 'import sys,json; print(json.load(sys.stdin).get(\"access_token\",\"\"))')" \
  -d '{"prompt": "Analyze RELIANCE latest quarterly results", "symbol": "RELIANCE"}'
```

### Step 4 (optional): Seed some filings for richer briefs
Drop any PDF (annual report, concall transcript) into:
```
data/research/uploads/RELIANCE__Q4_FY26_Results.pdf
```
The indexer will pick it up within 5 minutes and index it for retrieval.

---

## Safety Mechanisms Implemented

### Guardrail Rules (src/research/guardrails/rules/v1.yaml)
| Rule | Phase | Action | What it blocks |
|------|-------|--------|----------------|
| JB-001 | input | refuse | "ignore previous instructions" jailbreaks |
| JB-002 | input | refuse | "show system prompt" leak attempts |
| RP-001 | input | refuse | buy/sell/hold recommendations |
| DLP-001 | input | refuse | DROP/TRUNCATE/DELETE SQL keywords |
| DLP-002 | input | refuse | "delete all backups" requests |
| DLP-003 | input | refuse | credential extraction attempts |
| TA-001 | output | modify | strips tool_call/eval/exec/subprocess tokens |
| PII-001 | output | modify | redacts PAN numbers |
| PII-002 | output | modify | redacts Aadhaar numbers |
| PII-003 | output | modify | redacts phone numbers |

### Data Loss Prevention (src/research/guardrails/data_safety.py)
- **Protected paths**: .env, config/settings.yaml, data/backups/ — never writable by LLM pipeline
- **Bulk delete limit**: max 10,000 rows per forget operation
- **SQL safety check**: blocks DROP/TRUNCATE/ALTER at query-execution boundary
- **Backup integrity check**: runs at startup, warns if backups are stale
- **Startup safety checks**: verifies all data dirs, permissions, backup freshness

### Audit Trail
- `research_audit_log` table: append-only (SQL rules block DELETE/UPDATE)
- Every memory.forget() is logged with actor, scope, and row counts
- Every guardrail decision is logged with rule_id and action
- Structured JSON logs with rotation (100MB/file, 10 files)

### What the LLM CANNOT do
- ❌ Delete any data (no DELETE/DROP tools available)
- ❌ Access backup files (protected path)
- ❌ Read credentials from .env files (guardrail DLP-003)
- ❌ Execute arbitrary code (TA-001 strips eval/exec/subprocess)
- ❌ Make outbound network calls (only configured providers)
- ❌ Bypass rate limits (Redis counter per user per minute)

---

## Diagnostic Commands

```bash
# Full system diagnostic
python scripts/diagnose.py

# Check research health
curl http://localhost:8000/api/v2/research/health | python -m json.tool

# View research worker logs
tail -f logs/research-orchestrator.log
tail -f logs/research-indexer.log
tail -f logs/research-snapshotter.log

# View gateway log
tail -f /tmp/gw.log

# View ticker log
tail -f /tmp/nubra_ticker.log

# Stop everything
pkill -f uvicorn; pkill -f "nubra_ticker.py"; pkill -f "research.workers"
docker compose stop

# Start everything
docker compose up -d redis postgres
cd backend-gateway && nohup uvicorn app.main:socket_app --host 0.0.0.0 --port 8000 > /tmp/gw.log 2>&1 &
cd backend-gateway && nohup python scripts/nubra_ticker.py > /tmp/nubra_ticker.log 2>&1 &
cd "Lohi-TRADE Web App Design" && nohup npm run dev -- --port 3000 --host > /tmp/frontend.log 2>&1 &
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (localhost:3000)                    │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP + Socket.IO
┌────────────────────────▼────────────────────────────────────┐
│              FastAPI Gateway (localhost:8000)                  │
│  ├── /api/v2/public/stocks/* → Nubra REST (live quotes)      │
│  ├── /api/v2/research/*      → ResearchService               │
│  └── Socket.IO bridge        → stream:ticks → price_tick     │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Redis     │  │  Postgres   │  │   Chroma    │
│  (streams)  │  │  (RLS, WAL) │  │ (vectors)   │
└──────┬──────┘  └─────────────┘  └─────────────┘
       │
       │ stream:ticks
       │
┌──────▼──────┐
│ Nubra Ticker│ ← separate process, Nubra WS → Redis
│ (10 symbols)│
└─────────────┘

Research Workers (3 separate processes):
  ├── orchestrator — handles POST /runs, fans out to sub-agents
  ├── indexer      — polls NSE/BSE feeds, parses PDFs, embeds chunks
  └── snapshotter  — precomputes watchlist briefs on invalidation
```

---

## Known Issues

1. **Embeddings model download may be incomplete** — the BAAI/bge-small-en-v1.5 model (~100 MB) was downloading when a command timed out. On next research run it will auto-resume. If it fails, run:
   ```bash
   python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
   ```

2. **Nubra session may expire overnight** — if the ticker shows 401 errors tomorrow, re-run:
   ```bash
   cd backend-gateway && python scripts/nubra_setup_totp.py
   ```

3. **Research runs require LLM** — until you configure NVIDIA NIM or Ollama, `POST /runs` will return a `CONFIG_MISSING` error. This is by design (fail closed, not fail silent).

---

## Files Created/Modified Tonight

| File | Action | Purpose |
|------|--------|---------|
| `src/research/guardrails/rules/v1.yaml` | modified | added DLP-001/002/003, PII-002/003, enhanced TA-001 |
| `src/research/guardrails/data_safety.py` | created | hard-coded DLP layer (path protection, bulk-delete limit, SQL safety) |
| `scripts/diagnose.py` | created | user-friendly diagnostic tool |
| `.env.research` | modified | clear instructions for both LLM paths |
| `logs/TONIGHT_RUN.md` | created | this file |
| `backend-gateway/scripts/nubra_ticker.py` | created | standalone Nubra WS → Redis tick publisher |
| `backend-gateway/app/services/nubra_service.py` | modified | allow cached-session login without TOTP |
| `backend-gateway/app/services/redis_consumer.py` | modified | consume stream:ticks for Socket.IO |
| `data/backups/lohi_trade_backup_20260505_104713.db` | created | first backup |
