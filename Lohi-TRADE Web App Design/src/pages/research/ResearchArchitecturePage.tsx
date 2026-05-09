/**
 * `/research/architecture` — interactive DAG walkthrough of the Research
 * agentic architecture.
 *
 * Graph shape (read left→right):
 *
 *      Prompt ─► Guardrail(in) ─► Orchestrator plan ─┬─► Filings ─────┐
 *                                                    ├─► Fundamentals ┤
 *                                                    ├─► News ════════┤  (6 concurrent
 *                                                    ├─► Technicals ══┤   Sub_Agents
 *                                                    ├─► Peer / Sector┤   via LangGraph)
 *                                                    └─► Macro ═══════┘
 *                                                                      │
 *                                                                      ▼
 *                                 Report Synthesiser ──► Numeric Validator ──► Judge
 *                                        ▲                                      │
 *                                        └──── feedback (≤1 re-synthesis) ◄─────┘
 *                                                                      │
 *                                                                      ▼
 *                                               Guardrail(out) ──► Emit / Persist / Stream
 *
 * Sideband channels the canvas also visualises:
 *
 *   • Working / Semantic / Episodic memory reads (cyan dashed) feeding
 *     the Orchestrator plan.
 *   • Commander `news_clean` / `sentiment` / `bias` Redis streams feeding
 *     the News_Sentiment agent without re-ingestion.
 *   • Soldier `indicators` Redis stream feeding the Technicals agent.
 *   • Retrieval cache / embedding cache writes from every retrieval call.
 *   • llm_usage telemetry from every LLM call.
 *   • ResearchSignal Redis stream published by the emit node, consumed by
 *     the Trade architecture (cross-surface bridge).
 */

import LohiAvatarResearch from '../../components/research/LohiAvatarResearch';
import WorkflowSimulator, {
  type WorkflowStep,
} from '../../components/shared/WorkflowSimulator';

// Node indices are fixed so `upstreams` / `sidebands` can reference them
// by position without magic numbers drifting when the file is edited.
const IDX = {
  PROMPT: 0,
  GUARD_IN: 1,
  MEMORY: 2,           // Working / Semantic / Episodic — peer of the plan
  PLAN: 3,             // Orchestrator plan (fan-out node)
  FILINGS: 4,
  FUNDAMENTALS: 5,
  NEWS: 6,
  TECHNICALS: 7,
  PEER_SECTOR: 8,
  MACRO: 9,
  CACHE: 10,           // Embedding / retrieval / LLM cache — peer of the agents
  SYNTH: 11,
  NUMERIC: 12,
  JUDGE: 13,
  GUARD_OUT: 14,
  EMIT: 15,
};

const STEPS: WorkflowStep[] = [
  // 0 — User prompt
  {
    role: 'User prompt',
    responsibility:
      'Entry point. POST /api/v2/research/runs, or a scheduled refresh from the indexer.',
    incoming: null,
    outgoing: {
      name: 'PromptEnvelope',
      shape: '{ user_id, symbol?, prompt }',
      hint: 'JWT identity is attached so RLS engages automatically.',
    },
    details: (
      <p>
        The envelope is the only artefact allowed to carry user-typed text into the
        system. Memory hints live in a separate `memory_snapshot`, not in the prompt, so
        the Guardrail layer always sees what the user literally asked.
      </p>
    ),
  },

  // 1 — Guardrail (input)
  {
    role: 'Guardrail · input',
    responsibility:
      'Deterministic ruleset. Jailbreaks, tool-allowlist violations, and refusal-policy prompts short-circuit the run here — no agent downstream ever sees them.',
    deterministic: true,
    incoming: {
      name: 'PromptEnvelope',
      shape: '{ user_id, prompt }',
    },
    outgoing: {
      name: 'GuardrailedPrompt',
      shape: "{ prompt, decisions: GuardrailDecision[] }",
    },
    upstreams: [IDX.PROMPT],
    sidebands: [
      { to: IDX.EMIT, kind: 'telemetry', label: 'GuardrailDecision rows' },
    ],
    details: (
      <p>
        Every allow/modify/refuse is written to
        <code> research_guardrail_decisions </code>and surfaced in the final brief's
        provenance block. A refused prompt terminates the run immediately.
      </p>
    ),
  },

  // 2 — Memory (sits in parallel with the Plan as a *source* column)
  {
    role: 'Memory · Working / Semantic / Episodic',
    responsibility:
      'Redis-backed working memory plus RLS-scoped Postgres vectors for semantic and episodic recall. Read concurrently with plan construction; never blocks it.',
    incoming: null,
    outgoing: {
      name: 'MemorySnapshot',
      shape: '{ window, summaries, episodes }',
      hint: 'Sliding-window last N=12 turns + a running LLM-written summary.',
    },
    upstreams: [],
    parallelGroup: 'Sources',
    sidebands: [
      { to: IDX.PLAN, kind: 'memory', label: 'context' },
      { to: IDX.SYNTH, kind: 'memory', label: 'prior briefs' },
    ],
    details: (
      <p>
        Memory is a *peer* of the plan step, not a child of it. That's important —
        retrieval and plan construction both depend on memory, and the Orchestrator
        reads both in parallel. Summarisation kicks in when the working-window token
        budget is exceeded.
      </p>
    ),
  },

  // 3 — Orchestrator plan
  {
    role: 'Orchestrator · plan',
    responsibility:
      'The only strategic LLM call. Reads memory + guardrailed prompt; decides which Sub_Agents to fan out to and what each should retrieve. Also checks Snapshot freshness to short-circuit the whole run when possible.',
    incoming: {
      name: 'GuardrailedPrompt + MemorySnapshot',
      shape: '{ prompt, memory }',
    },
    outgoing: {
      name: 'ResearchPlan',
      shape: '{ agents_requested[], retrieval_plan[] }',
    },
    upstreams: [IDX.GUARD_IN, IDX.MEMORY],
    sidebands: [
      { to: IDX.EMIT, kind: 'telemetry', label: 'llm_usage' },
    ],
    details: (
      <p>
        When a fresh Snapshot exists for <code>(user_id, symbol)</code>, the plan
        emits directly downstream of the emit node, skipping every sub-agent — this is
        how the 800 ms first-token SLO is hit under load.
      </p>
    ),
  },

  // 4-9 — Six concurrent Sub_Agents
  {
    role: 'Filings',
    responsibility:
      'Hybrid retrieval (BM25 + dense) + optional cross-encoder rerank over filings chunks. Writes verbatim chunks into its AgentResult — no paraphrasing at this layer.',
    incoming: {
      name: 'ResearchPlan(filings)',
      shape: '{ intent }',
    },
    outgoing: {
      name: 'AgentResult',
      shape: '{ kind, content_md, citations[] }',
    },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    sidebands: [
      { to: IDX.CACHE, kind: 'cache', label: 'retrieval cache' },
    ],
    details: (
      <p>
        Returns <code>kind: 'no_data'</code> cleanly when retrieval misses the
        similarity floor so the UI renders a labelled empty state instead of
        hallucinated filler.
      </p>
    ),
  },
  {
    role: 'Fundamentals',
    responsibility: 'Retrieves annual-report and results chunks. Runs concurrently with the other five Sub_Agents.',
    incoming: { name: 'ResearchPlan(fundamentals)', shape: '{ intent }' },
    outgoing: { name: 'AgentResult', shape: '{ kind, content_md, citations[] }' },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    sidebands: [{ to: IDX.CACHE, kind: 'cache', label: 'retrieval cache' }],
    details: <p>Same shape as Filings; different retrieval intent string and prompt template.</p>,
  },
  {
    role: 'News · Sentiment',
    responsibility:
      'Subscribes to the Commander\'s existing news_clean / sentiment / bias Redis streams rather than re-ingesting news. Folds recent events into the agent context.',
    incoming: { name: 'ResearchPlan(news)', shape: '{ intent }' },
    outgoing: { name: 'AgentResult', shape: '{ kind, content_md, citations[] }' },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    sidebands: [
      { to: IDX.CACHE, kind: 'cache', label: 'retrieval cache' },
    ],
    details: (
      <p>
        This is the bridge *from* Trade into Research — Commander publishes on the
        same Redis streams the trading loop uses, so the research News agent inherits
        sentiment work for free. No duplicate news ingestion.
      </p>
    ),
  },
  {
    role: 'Technicals',
    responsibility:
      'Subscribes to the Soldier\'s `indicators` Redis stream and produces the technical_view section. Runs in parallel with the retrieval-heavy agents — no retrieval of its own.',
    incoming: { name: 'ResearchPlan(technicals)', shape: '{ intent }' },
    outgoing: { name: 'AgentResult', shape: '{ kind, content_md }' },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    details: (
      <p>
        The second bridge from Trade — live RSI / MACD / ATR values from the Soldier
        drop straight into the agent prompt as a `{'{{technicals_snapshot}}'}` block.
      </p>
    ),
  },
  {
    role: 'Peer · Sector',
    responsibility: 'Retrieves peer and sector-classified chunks; tags the output with a `Sector` enum so the cohort-view pages can pick it up.',
    incoming: { name: 'ResearchPlan(peers)', shape: '{ intent }' },
    outgoing: { name: 'AgentResult', shape: '{ kind, content_md, citations[] }' },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    sidebands: [{ to: IDX.CACHE, kind: 'cache', label: 'retrieval cache' }],
    details: <p>Sector classification is what powers the "pharma combined" cohort pages.</p>,
  },
  {
    role: 'Macro',
    responsibility: 'Pulls macro chunks (rates, GDP prints, sector-level regulatory notes) and produces the macro_context section.',
    incoming: { name: 'ResearchPlan(macro)', shape: '{ intent }' },
    outgoing: { name: 'AgentResult', shape: '{ kind, content_md, citations[] }' },
    upstreams: [IDX.PLAN],
    parallelGroup: 'Sub_Agents',
    sidebands: [{ to: IDX.CACHE, kind: 'cache', label: 'retrieval cache' }],
    details: <p>Runs under the same asyncio semaphore as the other five agents (concurrency cap = 6).</p>,
  },

  // 10 — Cache (peer of the agents)
  {
    role: 'Cache · embeddings · retrieval · LLM',
    responsibility:
      'Three Redis caches keyed by model + query template. Every retrieval and every LLM call consults the cache first, then writes back on miss. Shared across all six agents in parallel.',
    incoming: null,
    outgoing: {
      name: 'CacheHit | CacheMiss',
      shape: '{ hit_rate, size }',
    },
    upstreams: [],
    parallelGroup: 'Sources',
    sidebands: [
      { to: IDX.EMIT, kind: 'telemetry', label: 'hit/miss telemetry' },
    ],
    details: (
      <p>
        Retrieval cache TTL is 5 minutes; LLM response cache is 30 minutes (bypassed
        on streaming); embedding cache is 7 days. Property-level key invariants are
        tested so two identical prompts produce one LLM call, not two.
      </p>
    ),
  },

  // 11 — Report Synthesiser (fan-in)
  {
    role: 'Report Synthesiser',
    responsibility:
      'The only agent allowed to write prose. Fans in all six AgentResults + the retrieved chunks, then assembles the eight ResearchBrief sections. Does not retrieve on its own — that decoupling is what lets the Numeric Validator actually check its numbers.',
    incoming: {
      name: 'AgentResult[]',
      shape: "{ citations[], content_md }[]",
    },
    outgoing: {
      name: 'DraftBrief',
      shape: '{ sections, citations[] }',
    },
    upstreams: [
      IDX.FILINGS,
      IDX.FUNDAMENTALS,
      IDX.NEWS,
      IDX.TECHNICALS,
      IDX.PEER_SECTOR,
      IDX.MACRO,
    ],
    sidebands: [
      { to: IDX.EMIT, kind: 'telemetry', label: 'llm_usage' },
    ],
    details: (
      <p>
        Synthesis prompts are versioned (<code>src/research/prompts/v1/</code>) and
        closed-book: any claim the model can't support must be written as
        <code> INSUFFICIENT_EVIDENCE </code>and is stripped before emit.
      </p>
    ),
  },

  // 12 — Numeric Validator
  {
    role: 'Numeric Validator',
    responsibility:
      'Deterministic parser. Extracts every numeric token (₹, %, Cr / lakh, quarter codes) and checks each against the cited chunks within a configurable epsilon.',
    deterministic: true,
    incoming: {
      name: 'DraftBrief',
      shape: '{ sections, citations[] }',
    },
    outgoing: {
      name: 'UnsupportedClaim[]',
      shape: '{ claim_text, reason }',
    },
    upstreams: [IDX.SYNTH],
    details: (
      <p>
        Runs in parallel with the Judge prompt assembly — both read the same draft.
        Anything flagged here feeds into the Judge as prior evidence.
      </p>
    ),
  },

  // 13 — Judge (with feedback edge back to Synth)
  {
    role: 'Judge LLM',
    responsibility:
      'A separately-configured LLM scores every section for groundedness, checks citation coverage, flags contradictions, and classifies off-policy output. Returns JudgeReport with safe_to_display.',
    incoming: {
      name: 'DraftBrief + UnsupportedClaim[]',
      shape: '{ brief, numeric_findings }',
    },
    outgoing: {
      name: 'JudgeReport',
      shape: '{ groundedness_score, safe_to_display, retry_count }',
    },
    upstreams: [IDX.SYNTH, IDX.NUMERIC],
    sidebands: [
      { to: IDX.SYNTH, kind: 'feedback', label: 'retry ≤ 1' },
      { to: IDX.EMIT, kind: 'telemetry', label: 'judge_report' },
    ],
    details: (
      <p>
        On failure the Orchestrator re-runs the Report Synthesiser exactly once,
        feeding unsupported_claims back as explicit context — the coral feedback edge
        in the canvas. A second failure yields <code>quality=low</code>. Under
        <code> LOHI_RESEARCH_OFFLINE=true </code>this node is a deterministic
        rule-based judge so no cloud LLM is ever required.
      </p>
    ),
  },

  // 14 — Guardrail (output)
  {
    role: 'Guardrail · output',
    responsibility:
      'Strips invented tool-call tokens, redacts PII, blocks banned content. p95 overhead budgeted ≤ 50 ms.',
    deterministic: true,
    incoming: {
      name: 'JudgeApprovedBrief',
      shape: '{ brief, judge }',
    },
    outgoing: {
      name: 'ResearchBrief',
      shape: '{ sections, citations, provenance, judge }',
    },
    upstreams: [IDX.JUDGE],
    sidebands: [
      { to: IDX.EMIT, kind: 'telemetry', label: 'GuardrailDecision rows' },
    ],
    details: (
      <p>
        Every modification is appended to the brief's provenance block so the user
        can audit exactly what was redacted and why.
      </p>
    ),
  },

  // 15 — Emit / Persist / Stream
  {
    role: 'Emit · Persist · Stream',
    responsibility:
      'Writes the ResearchBrief across research_runs / research_brief_sections / research_provenance / research_judge_reports, refreshes the Snapshot, streams on research:<run_id>, and publishes a ResearchSignal for the Trade bridge if conviction ≥ threshold.',
    incoming: {
      name: 'ResearchBrief',
      shape: '{ sections, citations[] }',
    },
    outgoing: null,
    upstreams: [IDX.GUARD_OUT],
    details: (
      <p>
        Judge-approved briefs with conviction ≥ 0.5 emit a <code>ResearchSignal</code>
        on the algo Redis stream — that's the bridge into the Trade architecture.
        From the Trade side it appears as "Research signals filter (optional)".
      </p>
    ),
  },
];

export default function ResearchArchitecturePage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <header
        style={{
          paddingBottom: 20,
          borderBottom: '1px solid var(--line-3)',
          display: 'flex',
          gap: 20,
          alignItems: 'flex-start',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
            Edge · How it works
          </p>
          <h1 className="qr-headline" style={{ margin: '10px 0' }}>
            Architecture
          </h1>
          <p
            className="qr-body qr-body--lg"
            style={{ margin: 0, maxWidth: 760 }}
          >
            A multi-agent RAG DAG, not a one-way pipeline. Six Sub_Agents run in
            parallel under LangGraph. Memory and caches are peer sources, not
            children of the plan. The Judge is wired back into the Report
            Synthesiser with a bounded feedback loop. Each edge below carries its
            own data shape; the coloured cubes visualise what's moving.
          </p>
        </div>
        <div
          aria-hidden
          style={{
            flexShrink: 0,
            width: 96,
            height: 96 * 1.35,
            marginTop: -8,
          }}
        >
          <LohiAvatarResearch
            size="md"
            mood="focused"
            action="point"
            actionKey={1}
          />
        </div>
      </header>

      <WorkflowSimulator steps={STEPS} />

      <footer
        style={{
          paddingTop: 12,
          borderTop: '1px solid var(--line-2)',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 18,
          fontSize: 12,
          color: 'var(--fg-muted)',
        }}
      >
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Parallelism
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            Six Sub_Agents run under an asyncio semaphore (cap 6). Memory and the
            three-tier cache are peer sources, consulted concurrently with plan
            construction.
          </p>
        </div>
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Feedback loops
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            Judge → Synth is the only retry edge (bounded at 1). Every other
            edge is forward-only so the DAG never deadlocks.
          </p>
        </div>
        <div>
          <p
            style={{
              margin: '0 0 4px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-primary)',
            }}
          >
            Cross-surface bridge
          </p>
          <p style={{ margin: 0, lineHeight: 1.55 }}>
            News + Technicals consume Trade's Commander / Soldier streams.
            Emit publishes ResearchSignal back to Trade. The two products
            share one Redis backbone.
          </p>
        </div>
      </footer>
    </div>
  );
}
