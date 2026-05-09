/**
 * Research Zustand store.
 *
 * Holds the per-run streaming state produced by the Lohi-Research
 * Orchestrator over the `research:<run_id>` Socket.IO channel.
 *
 * Task 17.1 — Requirements: 6.4, design §3.13.
 */

import { create } from 'zustand';
import type {
  AgentName,
  AgentResult,
  Citation,
  GuardrailDecision,
  JudgeReport,
  ResearchBrief,
  StreamingState,
} from '../lib/research-types';

// ─── Per-run snapshot ───────────────────────────────────────────────────────

/**
 * Per-run accumulator. Each field can be progressively filled as events
 * arrive on the `research:<run_id>` channel.
 */
export interface RunState {
  runId: string;
  symbol: string | null;
  prompt: string;
  streamingState: StreamingState;
  /** Partial results keyed by agent name for O(1) merge. */
  partials: Partial<Record<AgentName, AgentResult>>;
  /** Final accumulated citations (deduplicated by chunk_id, append-only). */
  citations: Citation[];
  /** All guardrail decisions observed for this run, in arrival order. */
  guardrailDecisions: GuardrailDecision[];
  /** Latest JudgeReport received (replaces earlier reports for same run). */
  judgeReport: JudgeReport | null;
  /** Final brief when `research:done` arrives. */
  brief: ResearchBrief | null;
  /** Structured error payload if `research:error` fires. */
  error: ResearchStoreError | null;
  /** Total observed streamed deltas (for UI "streaming" indicator). */
  tokenCount: number;
  /** Creation timestamp (epoch ms) for sort ordering on the home page. */
  createdAt: number;
}

export interface ResearchStoreError {
  code: string;
  message: string;
  provider?: string;
  model?: string;
}

// ─── Store shape ────────────────────────────────────────────────────────────

export interface ResearchState {
  /** All runs the user has started this session, keyed by run_id. */
  runs: Record<string, RunState>;
  /** Currently focused run (drives the chat / symbol page view). */
  activeRunId: string | null;
}

export interface ResearchActions {
  /** Register a new run and make it active. */
  startRun: (input: {
    runId: string;
    symbol: string | null;
    prompt: string;
  }) => void;

  /** Switch the active run without mutating its contents. */
  setActiveRun: (runId: string | null) => void;

  /**
   * Merge a streaming `research:agent_partial` or `research:agent_done`
   * payload into the matching run. New citations are appended monotonically,
   * deduplicated by chunk_id.
   */
  mergeAgentPartial: (runId: string, result: AgentResult) => void;

  /** Apply a `research:judge_report` arrival. */
  applyJudgeReport: (runId: string, report: JudgeReport) => void;

  /** Apply a `research:guardrail_decision` arrival. */
  applyGuardrailDecision: (runId: string, decision: GuardrailDecision) => void;

  /** Record a streamed token delta (increments `tokenCount`). */
  recordToken: (runId: string) => void;

  /** Mark the run finished and persist the final brief. */
  completeRun: (runId: string, brief: ResearchBrief) => void;

  /** Record a fatal stream error for the given run. */
  setError: (runId: string, error: ResearchStoreError) => void;

  /**
   * Fully clear state for a single run (defaults to `activeRunId`).
   * Satisfies the "`reset` fully clears state" property.
   */
  reset: (runId?: string | null) => void;
}

export type ResearchStore = ResearchState & ResearchActions;

// ─── Pure helpers (exported for property tests) ─────────────────────────────

/**
 * Merge `incoming` citations into `existing`, preserving arrival order and
 * deduplicating by `chunk_id`. Citations are monotonically accumulated —
 * existing entries are never removed.
 */
export function mergeCitations(
  existing: Citation[],
  incoming: Citation[],
): Citation[] {
  if (incoming.length === 0) return existing;
  const seen = new Set(existing.map((c) => c.chunk_id));
  const out = existing.slice();
  for (const c of incoming) {
    if (!c || typeof c.chunk_id !== 'string') continue;
    if (seen.has(c.chunk_id)) continue;
    seen.add(c.chunk_id);
    out.push(c);
  }
  return out;
}

/** Build a fresh, empty `RunState`. */
export function createEmptyRunState(input: {
  runId: string;
  symbol: string | null;
  prompt: string;
  createdAt?: number;
}): RunState {
  return {
    runId: input.runId,
    symbol: input.symbol,
    prompt: input.prompt,
    streamingState: 'starting',
    partials: {},
    citations: [],
    guardrailDecisions: [],
    judgeReport: null,
    brief: null,
    error: null,
    tokenCount: 0,
    createdAt: input.createdAt ?? Date.now(),
  };
}

// ─── Store ──────────────────────────────────────────────────────────────────

export const useResearchStore = create<ResearchStore>((set) => ({
  runs: {},
  activeRunId: null,

  startRun: ({ runId, symbol, prompt }) =>
    set((state) => ({
      runs: {
        ...state.runs,
        [runId]: createEmptyRunState({ runId, symbol, prompt }),
      },
      activeRunId: runId,
    })),

  setActiveRun: (runId) => set({ activeRunId: runId }),

  mergeAgentPartial: (runId, result) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      const nextCitations = mergeCitations(run.citations, result.citations ?? []);
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            streamingState:
              run.streamingState === 'starting' ? 'streaming' : run.streamingState,
            partials: { ...run.partials, [result.agent]: result },
            citations: nextCitations,
          },
        },
      };
    }),

  applyJudgeReport: (runId, report) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            judgeReport: report,
            // Only transition OUT of 'verifying' if we were there; otherwise
            // leave streamingState unchanged so 'done' can set it explicitly.
            streamingState:
              run.streamingState === 'verifying'
                ? (report.safe_to_display ? 'done' : 'error')
                : run.streamingState,
          },
        },
      };
    }),

  applyGuardrailDecision: (runId, decision) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            guardrailDecisions: [...run.guardrailDecisions, decision],
          },
        },
      };
    }),

  recordToken: (runId) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            streamingState:
              run.streamingState === 'starting' ? 'streaming' : run.streamingState,
            tokenCount: run.tokenCount + 1,
          },
        },
      };
    }),

  completeRun: (runId, brief) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      const nextCitations = mergeCitations(run.citations, brief.citations ?? []);
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            brief,
            citations: nextCitations,
            // If judge is pending, UI should show "verifying…" until the
            // judge_report event arrives.
            streamingState: brief.judge_pending ? 'verifying' : 'done',
          },
        },
      };
    }),

  setError: (runId, error) =>
    set((state) => {
      const run = state.runs[runId];
      if (!run) return state;
      return {
        runs: {
          ...state.runs,
          [runId]: {
            ...run,
            error,
            streamingState: 'error',
          },
        },
      };
    }),

  reset: (runId) =>
    set((state) => {
      const target = runId ?? state.activeRunId;
      if (!target) {
        // With no target, reset the whole store to its initial state.
        return { runs: {}, activeRunId: null };
      }
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [target]: _removed, ...rest } = state.runs;
      return {
        runs: rest,
        activeRunId: state.activeRunId === target ? null : state.activeRunId,
      };
    }),
}));

// ─── Convenience selectors ──────────────────────────────────────────────────

export const selectActiveRun = (state: ResearchStore): RunState | null =>
  state.activeRunId ? (state.runs[state.activeRunId] ?? null) : null;

export const selectRunCitations = (runId: string | null) =>
  (state: ResearchStore): Citation[] =>
    runId && state.runs[runId] ? state.runs[runId].citations : [];

export const selectRunPartials = (runId: string | null) =>
  (state: ResearchStore): AgentResult[] =>
    runId && state.runs[runId]
      ? (Object.values(state.runs[runId].partials).filter(Boolean) as AgentResult[])
      : [];
