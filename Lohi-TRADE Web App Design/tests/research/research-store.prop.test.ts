/**
 * Property tests for `useResearchStore`.
 *
 * Task 17.12 — Requirements: 6.4, design §3.13.
 *
 * Invariants (per spec):
 *   1. No cross-run state bleed — merging into run A never mutates run B.
 *   2. Citations are monotonically accumulated per `run_id` and are
 *      deduplicated by `chunk_id`.
 *   3. `reset(runId)` fully clears state for that run.
 *   4. `reset()` (no arg, no active run set) clears the whole store.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';

import {
  useResearchStore,
  mergeCitations,
  createEmptyRunState,
} from '../../src/stores/research-store';
import type {
  AgentName,
  AgentResult,
  Citation,
  GuardrailDecision,
  JudgeReport,
} from '../../src/lib/research-types';

// ─── Helpers ────────────────────────────────────────────────────────────────

const AGENT_NAMES: AgentName[] = [
  'filings',
  'fundamentals',
  'news_sentiment',
  'technicals',
  'peer_sector',
  'macro',
  'synthesizer',
];

const agentArb: fc.Arbitrary<AgentName> = fc.constantFrom(...AGENT_NAMES);

const citationArb: fc.Arbitrary<Citation> = fc.record({
  chunk_id: fc.stringMatching(/^[0-9a-f]{6,12}$/),
  document_id: fc.uuid(),
  source_url: fc.option(fc.webUrl(), { nil: null }),
  start_offset: fc.nat({ max: 10_000 }),
  end_offset: fc.nat({ max: 10_000 }),
});

const agentResultArb: fc.Arbitrary<AgentResult> = fc.record({
  agent: agentArb,
  kind: fc.constantFrom('ok', 'no_data', 'error') as fc.Arbitrary<AgentResult['kind']>,
  content_md: fc.option(fc.string({ maxLength: 64 }), { nil: null }),
  citations: fc.array(citationArb, { maxLength: 4 }),
  wall_time_ms: fc.nat({ max: 5000 }),
  input_tokens: fc.nat({ max: 1000 }),
  output_tokens: fc.nat({ max: 1000 }),
  reason: fc.option(fc.string({ maxLength: 32 }), { nil: null }),
});

const guardrailArb: fc.Arbitrary<GuardrailDecision> = fc.record({
  phase: fc.constantFrom('input', 'output') as fc.Arbitrary<GuardrailDecision['phase']>,
  rule_id: fc.string({ minLength: 1, maxLength: 16 }),
  action: fc.constantFrom('allow', 'modify', 'refuse') as fc.Arbitrary<
    GuardrailDecision['action']
  >,
  reason: fc.string({ maxLength: 32 }),
});

function buildJudgeReport(runId: string, pass: boolean): JudgeReport {
  return {
    run_id: runId,
    groundedness_score: { summary: pass ? 0.9 : 0.4 },
    unsupported_claims: [],
    safe_to_display: pass,
    contradiction_pairs: [],
    off_policy_findings: [],
    retry_count: 0,
  };
}

// ─── Reset between tests ────────────────────────────────────────────────────

beforeEach(() => {
  useResearchStore.setState({ runs: {}, activeRunId: null });
});

// ─── Pure helper: mergeCitations ────────────────────────────────────────────

describe('mergeCitations', () => {
  it('deduplicates by chunk_id, preserves order, never removes existing', () => {
    fc.assert(
      fc.property(
        fc.array(citationArb, { maxLength: 10 }),
        fc.array(citationArb, { maxLength: 10 }),
        (a, b) => {
          const merged = mergeCitations(a, b);
          // Invariant A: every id in `a` is still present.
          for (const c of a) {
            expect(merged.some((m) => m.chunk_id === c.chunk_id)).toBe(true);
          }
          // Invariant B: first len(a) items remain as-is in order.
          for (let i = 0; i < a.length; i++) {
            expect(merged[i].chunk_id).toBe(a[i].chunk_id);
          }
          // Invariant C: all ids are unique.
          const ids = merged.map((m) => m.chunk_id);
          expect(new Set(ids).size).toBe(ids.length);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Invariant: No cross-run state bleed ────────────────────────────────────

describe('Property — no cross-run state bleed', () => {
  it('merging into run A never mutates run B', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.uuid(),
        fc.array(agentResultArb, { minLength: 1, maxLength: 12 }),
        (runA, runB, resultsForA) => {
          fc.pre(runA !== runB);

          useResearchStore.setState({ runs: {}, activeRunId: null });
          const s = useResearchStore.getState();
          s.startRun({ runId: runA, symbol: 'AAA', prompt: 'p' });
          s.startRun({ runId: runB, symbol: 'BBB', prompt: 'q' });

          const snapshotB = JSON.stringify(useResearchStore.getState().runs[runB]);

          for (const r of resultsForA) {
            useResearchStore.getState().mergeAgentPartial(runA, r);
          }
          useResearchStore
            .getState()
            .applyJudgeReport(runA, buildJudgeReport(runA, true));
          useResearchStore.getState().applyGuardrailDecision(runA, {
            phase: 'output',
            rule_id: 'x',
            action: 'allow',
            reason: 'ok',
          });

          const finalB = JSON.stringify(useResearchStore.getState().runs[runB]);
          expect(finalB).toBe(snapshotB);
        },
      ),
      { numRuns: 50 },
    );
  });
});

// ─── Invariant: Citations monotonically accumulated per run_id ──────────────

describe('Property — citations monotonically accumulated per run_id', () => {
  it('citations count is non-decreasing and every chunk_id is unique', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.array(agentResultArb, { minLength: 1, maxLength: 20 }),
        (runId, results) => {
          useResearchStore.setState({ runs: {}, activeRunId: null });
          const s = useResearchStore.getState();
          s.startRun({ runId, symbol: null, prompt: 'x' });

          let prevLen = 0;
          for (const r of results) {
            useResearchStore.getState().mergeAgentPartial(runId, r);
            const cits = useResearchStore.getState().runs[runId].citations;
            expect(cits.length).toBeGreaterThanOrEqual(prevLen);
            const ids = cits.map((c) => c.chunk_id);
            expect(new Set(ids).size).toBe(ids.length);
            prevLen = cits.length;
          }

          // Final set must contain every unique chunk_id that appeared in any
          // input result.
          const expectedIds = new Set<string>();
          for (const r of results) for (const c of r.citations) expectedIds.add(c.chunk_id);
          const actualIds = new Set(
            useResearchStore.getState().runs[runId].citations.map((c) => c.chunk_id),
          );
          expect(actualIds).toEqual(expectedIds);
        },
      ),
      { numRuns: 50 },
    );
  });
});

// ─── Invariant: reset fully clears state ────────────────────────────────────

describe('Property — reset fully clears state', () => {
  it('reset(runId) removes that run entirely', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.array(agentResultArb, { maxLength: 8 }),
        fc.array(guardrailArb, { maxLength: 4 }),
        (runId, results, decisions) => {
          useResearchStore.setState({ runs: {}, activeRunId: null });
          const s = useResearchStore.getState();
          s.startRun({ runId, symbol: null, prompt: 'p' });
          for (const r of results) useResearchStore.getState().mergeAgentPartial(runId, r);
          for (const d of decisions)
            useResearchStore.getState().applyGuardrailDecision(runId, d);
          useResearchStore
            .getState()
            .applyJudgeReport(runId, buildJudgeReport(runId, false));
          useResearchStore
            .getState()
            .setError(runId, { code: 'X', message: 'y' });

          useResearchStore.getState().reset(runId);
          const state = useResearchStore.getState();
          expect(state.runs[runId]).toBeUndefined();
          if (state.activeRunId === runId) {
            // Should have been cleared alongside the run.
            throw new Error('activeRunId still pointed to deleted run');
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it('reset() with no argument and no active run clears the whole store', () => {
    fc.assert(
      fc.property(
        fc.array(fc.uuid(), { minLength: 1, maxLength: 5 }),
        (runIds) => {
          useResearchStore.setState({ runs: {}, activeRunId: null });
          for (const id of runIds) {
            useResearchStore
              .getState()
              .startRun({ runId: id, symbol: null, prompt: 'p' });
          }
          useResearchStore.setState({ activeRunId: null });
          useResearchStore.getState().reset();
          expect(Object.keys(useResearchStore.getState().runs)).toHaveLength(0);
          expect(useResearchStore.getState().activeRunId).toBeNull();
        },
      ),
      { numRuns: 30 },
    );
  });
});

// ─── createEmptyRunState sanity ─────────────────────────────────────────────

describe('createEmptyRunState', () => {
  it('has empty citations and no-op accumulators', () => {
    const s = createEmptyRunState({ runId: 'r', symbol: null, prompt: 'p' });
    expect(s.citations).toHaveLength(0);
    expect(s.guardrailDecisions).toHaveLength(0);
    expect(s.judgeReport).toBeNull();
    expect(s.brief).toBeNull();
    expect(s.error).toBeNull();
    expect(s.streamingState).toBe('starting');
  });
});
