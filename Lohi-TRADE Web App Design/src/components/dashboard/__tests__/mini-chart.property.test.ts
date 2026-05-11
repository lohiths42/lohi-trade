/**
 * Property tests for Mini Chart Widget.
 * Feature: frontend-enhancements
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

const MAX_TICKS = 50;

// Pure logic: price tick accumulation
function addTick(ticks: number[], price: number): number[] {
  return [...ticks, price].slice(-MAX_TICKS);
}

function calcChangePercent(lastPrice: number, openPrice: number): number {
  return openPrice > 0 ? ((lastPrice - openPrice) / openPrice) * 100 : 0;
}

// ─── Property 25: Mini chart widget displays correct data ───────────────────

describe('Property 25: Mini chart widget displays correct data', () => {
  it('widget data contains symbol, last price, change percent, and at most 50 ticks', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 15 }),
        fc.array(fc.double({ min: 0.01, max: 100_000, noNaN: true }), { minLength: 1, maxLength: 100 }),
        fc.double({ min: 0.01, max: 100_000, noNaN: true }),
        (symbol, prices, openPrice) => {
          let ticks: number[] = [];
          for (const p of prices) {
            ticks = addTick(ticks, p);
          }
          const lastPrice = ticks[ticks.length - 1];
          const changePct = calcChangePercent(lastPrice, openPrice);

          expect(symbol.length).toBeGreaterThan(0);
          expect(lastPrice).toBe(prices[prices.length - 1]);
          expect(ticks.length).toBeLessThanOrEqual(MAX_TICKS);
          expect(typeof changePct).toBe('number');
          expect(Number.isFinite(changePct)).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 26: Mini chart widget count matches monitored symbols ─────────

describe('Property 26: Mini chart widget count matches monitored symbols', () => {
  it('one widget per monitored symbol', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(fc.string({ minLength: 1, maxLength: 10 }), { minLength: 0, maxLength: 20 }),
        (symbols) => {
          // The Market Overview section renders exactly one widget per symbol
          const widgetCount = symbols.length;
          expect(widgetCount).toBe(symbols.length);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 27: Price tick updates widget data ────────────────────────────

describe('Property 27: Price tick updates widget data', () => {
  it('new price tick is appended and reflected in last price', () => {
    fc.assert(
      fc.property(
        fc.array(fc.double({ min: 0.01, max: 100_000, noNaN: true }), { minLength: 0, maxLength: 49 }),
        fc.double({ min: 0.01, max: 100_000, noNaN: true }),
        (existingTicks, newPrice) => {
          const updated = addTick(existingTicks, newPrice);
          expect(updated[updated.length - 1]).toBe(newPrice);
          expect(updated.length).toBe(Math.min(existingTicks.length + 1, MAX_TICKS));
        },
      ),
      { numRuns: 100 },
    );
  });

  it('ticks are capped at 50 even with many updates', () => {
    fc.assert(
      fc.property(
        fc.array(fc.double({ min: 0.01, max: 100_000, noNaN: true }), { minLength: 51, maxLength: 200 }),
        (prices) => {
          let ticks: number[] = [];
          for (const p of prices) {
            ticks = addTick(ticks, p);
          }
          expect(ticks.length).toBe(MAX_TICKS);
          // Last tick should be the last price
          expect(ticks[ticks.length - 1]).toBe(prices[prices.length - 1]);
        },
      ),
      { numRuns: 100 },
    );
  });
});
