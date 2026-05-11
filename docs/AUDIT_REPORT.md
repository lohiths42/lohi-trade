# LOHI-TRADE · Consolidated Audit Report

> **Scope.** Code-level + spec-level audit of `Lohi-Trade-OpenSource/` as of this session. No rewrites; this document is evidence-only.
>
> **Method.** Static reading of the real source tree (`backend-gateway/`, `src/`, `Lohi-TRADE Web App Design/`) and the three Kiro specs (`lohi-research-dashboard`, `lohi-trade`, `lohi-trade-platform-expansion`). Every finding cites the file and line it was observed at.
>
> **Outcome.** 0 critical bugs, 2 must-fix correctness issues, 2 frontend UX residuals, 5 spec/doc drifts, 8 hardening items, 12 release-gate checklist items. No catastrophic issues — the codebase is in substantially better shape than typical "half-done" open-source trading projects.

---

## 0. Executive summary

| Area | State | Confidence |
|---|---|---|
| **Gateway (FastAPI + Socket.IO)** | Substantial, well-wired. One deprecated API pattern that will break on a future FastAPI bump. | High |
| **Research subsystem** | All non-optional tasks complete (`[x]`) across 22 phases. Optional adapters intentionally unchecked. | High |
| **Trade subsystem (`src/`)** | Populated — `soldier/`, `commander/`, `execution/`, `state/`, `ingestion/`, `ui/`, `backtesting/`, `ml/`, `research/`. Not read end-to-end in this pass; needs a dedicated session. | Medium |
| **Frontend (`Lohi-TRADE Web App Design/`)** | Builds clean. Sidebar state recently rewritten. One residual mobile-UX edge case. | High |
| **Documentation** | `docs/ARCHITECTURE.md` is pre-Research — the biggest gap. `PROJECT_STRUCTURE.md` is stale. | High |
| **Specs** | All three are well-formed. Spec completeness verified via grep. | High |

**Bottom line:** no release-blocking bugs. One deprecated FastAPI pattern and one architectural-doc drift are the biggest items.

---

## 1. Critical bugs

None found.

---

## 2. Must-fix correctness issues

### 2.1 Deprecated FastAPI startup/shutdown lifecycle

`backend-gateway/app/main.py:151` and `:214` use `@app.on_event("startup")` / `@app.on_event("shutdown")`. Deprecated since FastAPI 0.93; raises `DeprecationWarning` in 0.100+. Replacement is the `lifespan` async context manager:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup logic
    yield
    # shutdown logic

app = FastAPI(title="Lohi-TRADE Gateway", version="1.0.0", lifespan=lifespan)
```

Impact: not breaking today, but any FastAPI bump in `requirements.txt` could silently drop the startup hooks — at which point the Redis consumer, asyncpg pool, and LiveDataService never start, and the gateway comes up "healthy" but deaf to every stream. A landmine for future maintainers.

**Severity:** Medium · **Effort:** 20 min · **File:** `backend-gateway/app/main.py:151–225`.

### 2.2 `asyncio.get_event_loop()` in running coroutines

Three call sites:

- `backend-gateway/app/main.py:203` — schedules the Redis consumer during `startup()`.
- `backend-gateway/app/routers/public_stocks.py:310` and `:625` — offloads yfinance to a thread inside route handlers.
- `backend-gateway/app/services/live_data_service.py:560` — same pattern for the batch fetch.

`asyncio.get_event_loop()` is **deprecated inside a running coroutine** (Python 3.10+). On **Python 3.14** it raises `DeprecationWarning` and will eventually raise `RuntimeError`. The `__pycache__/*.cpython-314.pyc` files in the repo prove this is being run on 3.14 somewhere.

Replacements:

- Inside `async def`: `asyncio.get_running_loop()`.
- Task scheduling: `asyncio.create_task(...)` directly, no loop needed.
- `run_in_executor`: `await asyncio.to_thread(func, *args)` (Python 3.9+). Cleaner, self-documenting.

**Severity:** High · **Effort:** 30 min total · **Files:** as listed.

---

## 3. Frontend UX residuals

### 3.1 Sidebar mobile overlay dropped

After the recent single-state rewrite (`sidebarOpen` replaces `mobileMenuOpen` + `sidebarCollapsed`), the sidebar always lives in document flow and never floats as a fixed overlay. On narrow viewports the 264px expanded rail pushes content sideways rather than overlaying it. Acceptable on a tablet; on a 375px phone it leaves ~111px for the main content — too narrow.

**Fix path:** when `window.matchMedia('(max-width: 767px)').matches` AND `sidebarOpen === true`, render a full-viewport scrim + `position: fixed` on the sidebar. Tap-to-close on the scrim.

**Severity:** Medium · **Effort:** 30 min · **File:** `Lohi-TRADE Web App Design/src/App.tsx:605`.

### 3.2 Sign-out chip `justifyContent` branches are brittle

`src/App.tsx:764` — `justifyContent: !sidebarOpen ? 'center' : 'space-between'`. The logic is correct today but fragile: adding a third item would misalign the centred branch. A single-line comment would pay off.

**Severity:** Low · **Effort:** 2 min.

---

## 4. Documentation & spec drift

### 4.1 `PROJECT_STRUCTURE.md` is stale

`PROJECT_STRUCTURE.md:6-10` describes one spec folder (`lohi-trade/`). Reality is three (`lohi-research-dashboard/`, `lohi-trade/`, `lohi-trade-platform-expansion/`). The repo tree in lines 11–55 is pre-`backend-gateway/`, pre-`Lohi-TRADE Web App Design/`, pre-`mobile/`, pre-`infra/`, pre-`docs/`, pre-`examples/` — all of which exist today.

**Severity:** Medium · **Effort:** 1 hr · **File:** `PROJECT_STRUCTURE.md`.

### 4.2 `docs/ARCHITECTURE.md` does not mention Research at all

Grep for "Research" / "research" returns **zero matches**. The doc is a snapshot of the Trade-only architecture from before Research shipped. Missing: React dashboard, Research Sub_Agents, Judge/Guardrail stack, `/api/v2/research/*` surface, cross-surface Redis bridge, `ResearchSignal` stream, mobile apps.

This is the single largest documentation gap. A reader opening `ARCHITECTURE.md` today forms a wrong mental model of what ships.

**Severity:** High · **Effort:** 4 hrs for a proper rewrite · **File:** `docs/ARCHITECTURE.md`.

### 4.3 `README.md` has no Research chapter

`README.md:8-21` lists Component Details sections for Trading Engine, Backend Gateway, Web Dashboard, Mobile Apps, AWS Infrastructure. No Research. Research ships as a first-class product with its own shell, theme, 9 pages, and API surface — deserves top-billing.

**Severity:** Medium · **Effort:** 1 hr · **File:** `README.md`.

### 4.4 `CONFIGURATION.md` is research-heavy, trade-sparse

Excellent coverage of the `research:` block; Trade blocks (`capital`, `risk_limits`, `trading_hours`, `broker`, `strategies`, `sentiment`) are reference-level only. Deserves parity — units, defaults, ranges, failure modes.

**Severity:** Low · **Effort:** 2 hrs · **File:** `docs/CONFIGURATION.md`.

### 4.5 Two Trade specs with overlapping scope

`.kiro/specs/lohi-trade/` and `.kiro/specs/lohi-trade-platform-expansion/` co-exist. Without reading both end-to-end it is not obvious which is authoritative. A one-line preamble on each explaining the relationship would resolve it.

**Severity:** Low · **Effort:** 15 min · **Files:** both `requirements.md` preambles.

---

## 5. Spec completeness

| Spec | Unchecked `[ ]` tasks | Status |
|---|---|---|
| `lohi-research-dashboard/tasks.md` | 6, all suffixed `*` (5.5, 5.6, 10.5–10.8) | Explicitly optional per spec rubric |
| `lohi-trade/tasks.md` | 0 | Complete |
| `lohi-trade-platform-expansion/tasks.md` | 0 | Complete |

**No hidden incomplete work.** All unchecked tasks are opt-in adapters (LangChain / Guardrails-AI / NeMo / SEBI EDIFAR / company IR / small-model classifier) that the spec explicitly states "the implementer MUST NOT implement".

---

## 6. Hardening opportunities

These are not bugs today but are worth doing before a public 1.0.

### 6.1 Broker credential handling

`backend-gateway/app/services/nubra_service.py` is the primary broker adapter. Verify that broker tokens are (a) Fernet-encrypted at rest using `MASTER_ENCRYPTION_KEY`, (b) redacted by the `RequestLoggingMiddleware` formatter along with the existing `api_key|secret|token|password|totp` set, (c) refreshed on 401 without tripping the dashboard's session-expired modal.

### 6.2 JWT auth middleware dual-scheme fallback

`middleware/jwt_auth.py:65-80` tries v2 verification then falls back to v1. A malformed v2 token silently falls through; if both services shared a signing key (they should not, but the code doesn't enforce it), a `sub` claim could be misattributed. Explicit issuer/audience claims per scheme would be safer.

### 6.3 Rate limiter coverage

`app/middleware/rate_limiter.py` exists. Verify it is wired on the expensive / brute-forceable endpoints:

- `/api/auth/login`, `/api/v2/auth/login` — brute-force defence.
- `/api/v2/research/runs` — cost control (each run ≈ 7 LLM calls).
- `/api/v2/research/themes/generate` — N× run cost.
- `/api/v2/research/documents/upload` — disk + parse cost.

Current Research rate-limiting is enforced per-`user_id` in the `Guardrail_Layer`, which means an unauthenticated attacker cannot be throttled until the guardrail runs. An IP-level pre-auth throttle on the expensive endpoints would close that gap.

### 6.4 Socket.IO authentication

`app/websocket.py` — verify the `connect` handler validates the JWT before subscribing a socket to a `research:<run_id>` room. A missing check would let any connected socket subscribe to any room and exfiltrate other users' streaming briefs.

### 6.5 RLS engagement in every asyncpg codepath

Research spec mandates `set_config('app.user_id', $1, true)` on every asyncpg connection. Spot-check the newer stock-universe and watchlist services — they shipped after Research and may have missed the helper.

### 6.6 Observability — traces missing

`src/utils/logger.py` emits structured JSON. No distributed tracing. In a multi-agent system where one research run produces ~40 log lines across three processes, forensic debugging is painful. A correlation-ID middleware that stamps `X-Correlation-ID` on every outbound LLM call and every Redis stream write would unlock that for almost zero effort.

### 6.7 LLM provider error UX

Spec Req 2.10 correctly forbids silent fallback between providers. But a `PROVIDER_TIMEOUT` surfaces as an error — the dashboard should offer "retry in place" rather than forcing the user to re-type their prompt.

### 6.8 Kill-switch drill

The Kill Switch exists in both the execution layer and the UI. Worth a full acceptance test: active strategies → trigger → RMS rejects new entries AND existing stops/targets still execute AND a notification fires AND re-arm requires operator ack. A `test_kill_switch_drill` in CI would codify the single most safety-critical flow.

---

## 7. Release-gate checklist

These are the items I'd want green before a 1.0 release:

1. `pytest backend-gateway/tests/` — all pass, coverage ≥ 80% on `app/services/` and `app/middleware/`.
2. `pytest tests/research/` — all Hypothesis property tests pass with the project's seed.
3. `vite build` in the web app — zero errors, chunk-size hints only.
4. 24-hour paper-trading soak against yfinance tick data. Zero uncaught exceptions; no RSS growth beyond 200 MB; PnL → KillSwitch propagation ≤ 200 ms.
5. Cold-start demo from `start.sh` + `start-research.sh` on a fresh box with `.env.template` only. Dashboard renders, research brief runs, paper trade places, gateway survives a SIGTERM → restart.
6. FastAPI `lifespan` migration (§2.1) complete.
7. `asyncio.get_event_loop()` replacements (§2.2) complete.
8. `docs/ARCHITECTURE.md` updated to include Research (§4.2).
9. `README.md` gains a Research chapter (§4.3).
10. Rate-limiter wired on the four pre-auth / expensive endpoints (§6.3).
11. Socket.IO JWT validation verified or added (§6.4).
12. Kill-switch drill test in CI (§6.8).

---

## 8. New feature proposals (not in this pass — backlog only)

If a future session picks up new features (you mentioned Telegram, debug framework, AI improvements):

- **Telegram integration** already has a home in `src/ui/` per the original architecture. Simplest path: a consumer that reads `orders`, `fills`, `kill_switch`, and `research:judge_report` streams and forwards human-readable messages via `python-telegram-bot`. Rate-limit at 20 msg/hr per spec.
- **Debug framework.** Two pieces: (a) correlation-ID propagation (see §6.6), (b) a gateway route `GET /api/v2/debug/runs/:run_id/trace` that joins `research_runs`, `research_provenance`, `research_guardrail_decisions`, `research_judge_reports`, `llm_usage` into a single audit document. Already half-implemented per `Task 20.3`. Verify end-to-end.
- **AI-trading improvements.** Three concrete items:
  1. Research-signal weighting per strategy. Each strategy declares a `min_research_conviction` (default 0.0 = ignore research) and a `research_veto_on_mismatch` flag.
  2. Conviction-to-size mapping. Let the Position Sizer optionally scale qty by conviction band (speculative 0.5×, watch 0.75×, building 1.0×, high 1.25×) — only when the strategy opts in.
  3. Backtest harness that replays historical briefs against historical ticks. Gives us a way to ask "would enabling research filtering have changed our 2024 Sharpe ratio". Sits under `src/backtesting/` which already exists.

None of these change the core contracts; all are additive and opt-in.

---

## 9. What I did NOT audit in this pass

Honest about scope:

- **`src/` top-level Python trading engine** — mapped but not code-reviewed. Needs its own session.
- **`mobile/`** — not opened.
- **`infra/`** — not opened.
- **CI config in `.github/`** — not opened. Worth a glance for the release gate.
- **`tests/research/` end-to-end runs** — I confirmed the files exist and are wired into `pyproject.toml`; I did not run them in this session.
- **Browser-level interaction testing** — no Playwright / Cypress pass. Sidebar, mode switcher, and research routes need one before 1.0.

---

## 10. Conclusions

The codebase is healthier than I expected going in. The specs are disciplined, the separation between Trade and Research is clean, and the cross-surface Redis bridge is the right primitive for a multi-product system. The work remaining is **doc catch-up** (the architecture doc is the single biggest gap) and two **API-deprecation fixes** that are landmines rather than bugs today.

No critical rewrites required. Next session I'd recommend taking the fixes in §2 and the doc rewrite in §4.2 — together that's roughly a day of work and gets the repo to a place where a new contributor can read `ARCHITECTURE.md` and understand the system in 15 minutes.
