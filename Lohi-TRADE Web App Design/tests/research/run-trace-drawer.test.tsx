/**
 * Unit tests for `RunTraceDrawer` pure helpers.
 *
 * The vitest environment is `node` (no jsdom) so we exercise the
 * exported helper functions that encode the drawer's contract:
 *
 *   - `formatWallTime` — readable ms / s formatting.
 *   - `minGroundednessScore` — per-report aggregate.
 *   - `chunkCountFor` — provenance chunk-count extraction.
 *
 * Rendering tests live in Storybook (already wired on this project)
 * and in the e2e Playwright suite (`/research` page flows).
 *
 * Task 20.3 — Requirements: 13.3, 13.4, design §15.
 */

import { describe, it, expect } from 'vitest';
import {
  formatWallTime,
  minGroundednessScore,
  chunkCountFor,
  type TraceJudgeReport,
  type TraceProvenanceEntry,
} from '../../src/components/research/RunTraceDrawer';

describe('RunTraceDrawer.formatWallTime', () => {
  it('renders sub-second values in milliseconds', () => {
    expect(formatWallTime(0)).toBe('0 ms');
    expect(formatWallTime(42)).toBe('42 ms');
    expect(formatWallTime(999)).toBe('999 ms');
  });

  it('renders one-second-and-up values in seconds with two decimals', () => {
    expect(formatWallTime(1000)).toBe('1.00 s');
    expect(formatWallTime(1234)).toBe('1.23 s');
    expect(formatWallTime(15000)).toBe('15.00 s');
  });

  it('renders missing or invalid input as em-dash', () => {
    expect(formatWallTime(undefined)).toBe('—');
    expect(formatWallTime(null)).toBe('—');
    expect(formatWallTime(Number.NaN)).toBe('—');
    expect(formatWallTime(Number.POSITIVE_INFINITY)).toBe('—');
  });

  it('floors fractional values so observed latency reads cleanly', () => {
    // Upstream code may pass floats when the orchestrator uses
    // `perf_counter()` deltas; the drawer should normalise to int ms.
    expect(formatWallTime(250.7)).toBe('250 ms');
  });
});

describe('RunTraceDrawer.minGroundednessScore', () => {
  it('returns null when the report has no score map', () => {
    expect(minGroundednessScore(undefined)).toBeNull();
    expect(minGroundednessScore({} as TraceJudgeReport)).toBeNull();
    expect(
      minGroundednessScore({ groundedness_score: {} } as TraceJudgeReport),
    ).toBeNull();
  });

  it('returns the minimum per-section score', () => {
    const report: TraceJudgeReport = {
      groundedness_score: { summary: 0.9, thesis: 0.65, risks: 0.82 },
    };
    expect(minGroundednessScore(report)).toBeCloseTo(0.65);
  });

  it('handles a single-section score', () => {
    const report: TraceJudgeReport = {
      groundedness_score: { summary: 0.77 },
    };
    expect(minGroundednessScore(report)).toBeCloseTo(0.77);
  });
});

describe('RunTraceDrawer.chunkCountFor', () => {
  it('returns the length of chunk_ids when present', () => {
    const entry: TraceProvenanceEntry = {
      agent_name: 'filings',
      kind: 'ok',
      chunk_ids: ['a', 'b', 'c'],
    };
    expect(chunkCountFor(entry)).toBe(3);
  });

  it('returns 0 when chunk_ids is missing', () => {
    const entry: TraceProvenanceEntry = { agent_name: 'macro', kind: 'no_data' };
    expect(chunkCountFor(entry)).toBe(0);
  });

  it('returns 0 when chunk_ids is an empty array', () => {
    const entry: TraceProvenanceEntry = {
      agent_name: 'technicals',
      kind: 'ok',
      chunk_ids: [],
    };
    expect(chunkCountFor(entry)).toBe(0);
  });
});

describe('RunTraceDrawer module surface', () => {
  it('exports the component and pure helpers from the barrel', async () => {
    // Dynamic import so the test doesn't tank at collection time if
    // the barrel adds a syntax error during refactoring.
    const mod = await import('../../src/components/research');
    expect(typeof mod.RunTraceDrawer).toBe('function');
    expect(typeof mod.formatWallTime).toBe('function');
    expect(typeof mod.minGroundednessScore).toBe('function');
    expect(typeof mod.chunkCountFor).toBe('function');
  });
});
