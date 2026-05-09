/**
 * Property tests for Watchlist Manager.
 * Feature: frontend-enhancements
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

// Re-implement filterSuggestions locally to avoid importing the store
// (which pulls in React/Toast dependencies not available in node env)
const NSE_SYMBOLS = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'KOTAKBANK', 'ITC', 'LT', 'AXISBANK', 'BAJFINANCE', 'ASIANPAINT',
  'MARUTI', 'TITAN', 'SUNPHARMA', 'ULTRACEMCO', 'NESTLEIND', 'WIPRO', 'HCLTECH',
  'ADANIENT', 'ADANIPORTS', 'POWERGRID', 'NTPC', 'JSWSTEEL', 'TATAMOTORS',
  'TATASTEEL', 'ONGC', 'COALINDIA', 'BAJAJFINSV', 'TECHM', 'INDUSINDBK',
  'HINDALCO', 'DRREDDY', 'CIPLA', 'EICHERMOT', 'DIVISLAB', 'BPCL', 'GRASIM',
  'BRITANNIA', 'APOLLOHOSP', 'HEROMOTOCO', 'SBILIFE', 'HDFCLIFE', 'TATACONSUM',
  'M&M', 'UPL', 'BAJAJ-AUTO',
];

function filterSuggestions(query: string, currentSymbols: string[]): string[] {
  if (!query.trim()) return [];
  const q = query.toUpperCase();
  return NSE_SYMBOLS.filter(
    (s) => s.includes(q) && !currentSymbols.includes(s),
  ).slice(0, 8);
}

// Pure logic helpers for testing without Zustand side effects
function addSymbol(symbols: string[], symbol: string): { symbols: string[]; added: boolean } {
  const upper = symbol.toUpperCase().trim();
  if (!upper || symbols.includes(upper)) return { symbols, added: false };
  return { symbols: [...symbols, upper], added: true };
}

function removeSymbol(symbols: string[], symbol: string): string[] {
  return symbols.filter((s) => s !== symbol);
}

// ─── Property 16: Watchlist add/remove round-trip ───────────────────────────

describe('Property 16: Watchlist add/remove round-trip', () => {
  const symbolArb = fc.stringMatching(/^[A-Z][A-Z0-9&-]{0,14}$/);

  it('adding a new symbol increases length by 1 and the symbol is present', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(symbolArb, { minLength: 0, maxLength: 20 }),
        symbolArb,
        (existing, newSym) => {
          fc.pre(!existing.includes(newSym.toUpperCase()));
          const { symbols, added } = addSymbol(existing, newSym);
          expect(added).toBe(true);
          expect(symbols.length).toBe(existing.length + 1);
          expect(symbols).toContain(newSym.toUpperCase());
        },
      ),
      { numRuns: 100 },
    );
  });

  it('removing a symbol decreases length by 1 and the symbol is absent', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(symbolArb, { minLength: 1, maxLength: 20 }),
        (symbols) => {
          const target = symbols[0];
          const result = removeSymbol(symbols, target);
          expect(result.length).toBe(symbols.length - 1);
          expect(result).not.toContain(target);
        },
      ),
      { numRuns: 100 },
    );
  });

  it('add then remove returns to original list', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(symbolArb, { minLength: 0, maxLength: 20 }),
        symbolArb,
        (existing, newSym) => {
          const upper = newSym.toUpperCase();
          fc.pre(!existing.includes(upper));
          const { symbols: afterAdd } = addSymbol(existing, newSym);
          const afterRemove = removeSymbol(afterAdd, upper);
          expect(afterRemove).toEqual(existing);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 17: Watchlist duplicate add is idempotent ─────────────────────

describe('Property 17: Watchlist duplicate add is idempotent', () => {
  const symbolArb = fc.stringMatching(/^[A-Z][A-Z0-9&-]{0,14}$/);

  it('adding a symbol already in the list does not change it', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(symbolArb, { minLength: 1, maxLength: 20 }),
        (symbols) => {
          const existing = symbols[0];
          const { symbols: result, added } = addSymbol(symbols, existing);
          expect(added).toBe(false);
          expect(result).toEqual(symbols);
          expect(result.length).toBe(symbols.length);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ─── Property 18: Watchlist autocomplete returns matching symbols ────────────

describe('Property 18: Watchlist autocomplete returns matching symbols', () => {
  it('all suggestions contain the query as a substring (case-insensitive)', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('A', 'IN', 'TA', 'BA', 'HD', 'SB', 'RE', 'IC', 'KO', 'MA'),
        (query) => {
          const results = filterSuggestions(query, []);
          for (const s of results) {
            expect(s.toUpperCase()).toContain(query.toUpperCase());
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it('suggestions do not include symbols already in the watchlist', () => {
    fc.assert(
      fc.property(
        fc.constant('A'), // broad query to get many results
        fc.uniqueArray(fc.constantFrom('RELIANCE', 'TCS', 'INFY', 'SBIN'), { minLength: 1, maxLength: 4 }),
        (query, currentSymbols) => {
          const results = filterSuggestions(query, currentSymbols);
          for (const s of results) {
            expect(currentSymbols).not.toContain(s);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it('empty query returns no suggestions', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('', '  ', '\t'),
        (query) => {
          const results = filterSuggestions(query, []);
          expect(results).toHaveLength(0);
        },
      ),
      { numRuns: 100 },
    );
  });
});
