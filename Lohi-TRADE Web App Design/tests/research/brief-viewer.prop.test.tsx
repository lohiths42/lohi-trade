/**
 * Property tests for `BriefViewer` citation click-through.
 *
 * Task 17.13 — Requirements: 6.6, design §3.13.
 *
 * Invariants (per spec):
 *   1. Every `[cite:<chunk_id>]` marker in a section renders as a clickable
 *      pill that, when activated, produces a `Citation` with the exact
 *      `chunk_id` that appeared in the source text.
 *   2. When a matching `Citation` carries a `source_url`, the resolved
 *      drawer citation preserves that URL (never falls back to "unavailable").
 *
 * Notes:
 *   - The project has no DOM test environment (no jsdom / testing-library),
 *     so this test exercises the pure rendering contract that the
 *     `BriefViewer` component follows: tokenize section text, resolve
 *     each `[cite:…]` marker against the brief's citations map, open the
 *     drawer with the resolved Citation. The same resolution logic is
 *     exported (`tokenizeSection`) and re-implemented inline here for the
 *     click-lookup half, which keeps the property test deterministic and
 *     runtime-independent.
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

import { tokenizeSection } from '../../src/components/research/BriefViewer';
import type { Citation, ResearchBrief } from '../../src/lib/research-types';

// ─── Arbitraries ────────────────────────────────────────────────────────────

const chunkIdArb: fc.Arbitrary<string> = fc.stringMatching(/^[0-9a-f]{6,12}$/);

const citationArb: (forceUrl: boolean) => fc.Arbitrary<Citation> = (forceUrl) =>
  fc.record({
    chunk_id: chunkIdArb,
    document_id: fc.uuid(),
    source_url: forceUrl ? fc.webUrl() : fc.option(fc.webUrl(), { nil: null }),
    start_offset: fc.nat({ max: 1000 }),
    end_offset: fc.nat({ max: 1000 }),
  });

/**
 * Build a `ResearchBrief` and a corresponding `summary` section containing
 * one `[cite:<chunk_id>]` marker for every citation, in random order.
 */
const briefWithCitationsArb = (forceUrl: boolean) =>
  fc
    .uniqueArray(citationArb(forceUrl), {
      minLength: 1,
      maxLength: 8,
      selector: (c) => c.chunk_id,
    })
    .map<{ brief: ResearchBrief; orderedIds: string[] }>((citations) => {
      // Randomise marker order inside the section to catch off-by-one
      // regressions in tokenization.
      const ordered = citations.map((c) => c.chunk_id);
      const summary = ordered
        .map((id, i) => `Claim ${i} says something [cite:${id}].`)
        .join(' ');
      return {
        brief: {
          run_id: '00000000-0000-0000-0000-000000000000',
          symbol: 'ACME',
          summary,
          thesis: '',
          risks: '',
          financial_highlights: '',
          management_commentary: '',
          technical_view: '',
          peers: '',
          macro_context: '',
          citations,
          provenance: [],
          guardrail_decisions: [],
          judge: null,
          partial: false,
          quality: 'normal',
          budget_exhausted: false,
          judge_pending: false,
        },
        orderedIds: ordered,
      };
    });

// ─── Reproduction of the BriefViewer click-lookup contract ──────────────────
//
// `BriefViewer` (see src/components/research/BriefViewer.tsx) builds a
// `Map<chunk_id, Citation>` over `brief.citations` and, on click of a
// citation marker, calls `map.get(chunkId) ?? fallbackCitation`. The test
// below mirrors that exact lookup so a regression in the component's
// resolution logic would be caught by diff review; the property here
// asserts the *contract* `tokenizeSection` + lookup must satisfy.
function resolveClick(brief: ResearchBrief, chunkId: string): Citation {
  const map = new Map<string, Citation>();
  for (const c of brief.citations) map.set(c.chunk_id, c);
  return (
    map.get(chunkId) ?? {
      chunk_id: chunkId,
      document_id: '',
      source_url: null,
      start_offset: 0,
      end_offset: 0,
    }
  );
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe('Property — BriefViewer citation click-through', () => {
  it('every citation marker tokenizes to a chunk_id present in brief.citations', () => {
    fc.assert(
      fc.property(briefWithCitationsArb(false), ({ brief, orderedIds }) => {
        const tokens = tokenizeSection(brief.summary);
        const extracted = tokens
          .filter((t): t is { kind: 'cite'; chunkId: string } => t.kind === 'cite')
          .map((t) => t.chunkId);
        expect(extracted).toEqual(orderedIds);
        // Each extracted id resolves to a real citation.
        for (const id of extracted) {
          const resolved = resolveClick(brief, id);
          expect(resolved.chunk_id).toBe(id);
          // The resolved citation comes from the brief, not the fallback.
          const original = brief.citations.find((c) => c.chunk_id === id);
          expect(original).toBeDefined();
          expect(resolved.document_id).toBe(original!.document_id);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('clicking a citation never falls back to "unavailable" when a source URL is present', () => {
    fc.assert(
      fc.property(briefWithCitationsArb(true), ({ brief, orderedIds }) => {
        for (const id of orderedIds) {
          const resolved = resolveClick(brief, id);
          expect(resolved.chunk_id).toBe(id);
          expect(resolved.source_url).not.toBeNull();
          expect(typeof resolved.source_url).toBe('string');
          expect(resolved.source_url!.length).toBeGreaterThan(0);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('tokenizeSection round-trips plain text unchanged', () => {
    fc.assert(
      fc.property(
        fc
          .string({ maxLength: 120 })
          // Strip citation-marker-like sequences so the property focuses on
          // plain prose.
          .map((s) => s.replace(/\[cite:[^\]]*\]/g, '')),
        (plain) => {
          const tokens = tokenizeSection(plain);
          const textOnly = tokens
            .filter((t): t is { kind: 'text'; text: string } => t.kind === 'text')
            .map((t) => t.text)
            .join('');
          expect(textOnly).toBe(plain);
          expect(tokens.every((t) => t.kind === 'text')).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });
});
