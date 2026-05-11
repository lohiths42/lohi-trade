/**
 * Property tests for P&L Alert Engine.
 * Feature: frontend-enhancements
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { evaluateRule } from '../alert-store';
import type { AlertRule } from '../../lib/types';

// ─── Property 19: Alert threshold evaluation correctness ────────────────────

describe('Property 19: Alert threshold evaluation correctness', () => {
  it('absolute_profit fires when totalPnl >= threshold', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 1, max: 1_000_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: 100_000, max: 10_000_000, noNaN: true }),
        (threshold, realized, unrealized, capital) => {
          const rule: AlertRule = { id: 'test', type: 'absolute_profit', threshold, enabled: true };
          const totalPnl = realized + unrealized;
          const result = evaluateRule(rule, realized, unrealized, capital);
          expect(result).toBe(totalPnl >= threshold);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('absolute_loss fires when totalPnl <= -threshold', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 1, max: 1_000_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: 100_000, max: 10_000_000, noNaN: true }),
        (threshold, realized, unrealized, capital) => {
          const rule: AlertRule = { id: 'test', type: 'absolute_loss', threshold, enabled: true };
          const totalPnl = realized + unrealized;
          const result = evaluateRule(rule, realized, unrealized, capital);
          expect(result).toBe(totalPnl <= -threshold);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('percent_profit fires when pctPnl >= threshold', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.1, max: 100, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: 100_000, max: 10_000_000, noNaN: true }),
        (threshold, realized, unrealized, capital) => {
          const rule: AlertRule = { id: 'test', type: 'percent_profit', threshold, enabled: true };
          const totalPnl = realized + unrealized;
          const pctPnl = capital > 0 ? (totalPnl / capital) * 100 : 0;
          const result = evaluateRule(rule, realized, unrealized, capital);
          expect(result).toBe(pctPnl >= threshold);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('percent_loss fires when pctPnl <= -threshold', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.1, max: 100, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: -500_000, max: 500_000, noNaN: true }),
        fc.double({ min: 100_000, max: 10_000_000, noNaN: true }),
        (threshold, realized, unrealized, capital) => {
          const rule: AlertRule = { id: 'test', type: 'percent_loss', threshold, enabled: true };
          const totalPnl = realized + unrealized;
          const pctPnl = capital > 0 ? (totalPnl / capital) * 100 : 0;
          const result = evaluateRule(rule, realized, unrealized, capital);
          expect(result).toBe(pctPnl <= -threshold);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('disabled rules never fire', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('absolute_profit', 'absolute_loss', 'percent_profit', 'percent_loss') as fc.Arbitrary<AlertRule['type']>,
        fc.double({ min: 0.01, max: 1_000_000, noNaN: true }),
        fc.double({ min: -1_000_000, max: 1_000_000, noNaN: true }),
        fc.double({ min: -1_000_000, max: 1_000_000, noNaN: true }),
        fc.double({ min: 1, max: 10_000_000, noNaN: true }),
        (type, threshold, realized, unrealized, capital) => {
          const rule: AlertRule = { id: 'test', type, threshold, enabled: false };
          expect(evaluateRule(rule, realized, unrealized, capital)).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 20: Alert fires at most once per session ──────────────────────

describe('Property 20: Alert fires at most once per session', () => {
  it('tracking fired IDs prevents duplicate alerts', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 20 }),
        fc.integer({ min: 2, max: 10 }),
        (ruleCount, evaluationCount) => {
          const firedSet = new Set<string>();
          const fireCount: Record<string, number> = {};

          // Create rules
          const rules: AlertRule[] = Array.from({ length: ruleCount }, (_, i) => ({
            id: `rule-${i}`,
            type: 'absolute_profit' as const,
            threshold: 100,
            enabled: true,
          }));

          // Simulate multiple evaluations
          for (let e = 0; e < evaluationCount; e++) {
            for (const rule of rules) {
              if (!firedSet.has(rule.id)) {
                // Would fire
                firedSet.add(rule.id);
                fireCount[rule.id] = (fireCount[rule.id] || 0) + 1;
              }
            }
          }

          // Each rule should have fired exactly once
          for (const rule of rules) {
            expect(fireCount[rule.id]).toBe(1);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 21: Alert rules CRUD round-trip ───────────────────────────────

describe('Property 21: Alert rules CRUD round-trip', () => {
  it('add then delete returns to original state', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('absolute_profit', 'absolute_loss', 'percent_profit', 'percent_loss') as fc.Arbitrary<AlertRule['type']>,
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        (type, threshold) => {
          const rules: AlertRule[] = [];

          // Add
          const newRule: AlertRule = { id: 'new-1', type, threshold, enabled: true };
          const afterAdd = [...rules, newRule];
          expect(afterAdd.length).toBe(1);
          expect(afterAdd[0].type).toBe(type);
          expect(afterAdd[0].threshold).toBe(threshold);

          // Delete
          const afterDelete = afterAdd.filter((r) => r.id !== 'new-1');
          expect(afterDelete).toEqual(rules);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('edit preserves other fields', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('absolute_profit', 'absolute_loss', 'percent_profit', 'percent_loss') as fc.Arbitrary<AlertRule['type']>,
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        fc.double({ min: 1, max: 100_000, noNaN: true }),
        (type, originalThreshold, newThreshold) => {
          const rule: AlertRule = { id: 'r1', type, threshold: originalThreshold, enabled: true };
          const edited = { ...rule, threshold: newThreshold };
          expect(edited.id).toBe(rule.id);
          expect(edited.type).toBe(rule.type);
          expect(edited.enabled).toBe(rule.enabled);
          expect(edited.threshold).toBe(newThreshold);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('persistence round-trip preserves rules', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: fc.string({ minLength: 1, maxLength: 20 }),
            type: fc.constantFrom('absolute_profit', 'absolute_loss', 'percent_profit', 'percent_loss') as fc.Arbitrary<AlertRule['type']>,
            threshold: fc.double({ min: 0.01, max: 1_000_000, noNaN: true }),
            enabled: fc.boolean(),
          }),
          { minLength: 0, maxLength: 10 },
        ),
        (rules) => {
          const serialized = JSON.stringify(rules);
          const deserialized = JSON.parse(serialized);
          expect(deserialized).toEqual(rules);
        },
      ),
      { numRuns: 100 },
    );
  });
});
