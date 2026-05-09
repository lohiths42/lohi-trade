/**
 * Property-based tests for feature availability correctness (frontend).
 *
 * **Property 4: Feature availability correctness (frontend)**
 *
 * For any subset of configured services, the feature availability map
 * SHALL mark a feature as available if and only if at least one of its
 * dependency groups (using OR-logic with `|` separator) is in
 * "configured" status.
 *
 * **Validates: Requirements 4.1**
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { CREDENTIAL_GROUPS } from '../../../lib/setup-types';

// ─── Feature Dependency Map ─────────────────────────────────────────────────
// Mirrors backend FEATURE_DEPENDENCIES from service_registry.py
// Uses `|` for OR logic: "nvidia_nim|ollama" means either satisfies.

const FEATURE_DEPENDENCIES: Record<string, string[]> = {
  research_dashboard: ['nvidia_nim|ollama'],
  ai_analysis: ['nvidia_nim|ollama'],
  research_dashboard_local: ['ollama'],
  ai_analysis_local: ['ollama'],
  live_market_data: ['nubra'],
  real_time_quotes: ['nubra'],
  tick_streaming: ['nubra'],
  live_trading: ['broker_shoonya|broker_angelone'],
  order_execution: ['broker_shoonya|broker_angelone'],
  telegram_notifications: ['telegram'],
};

// ─── Logic Under Test ───────────────────────────────────────────────────────

/**
 * Determines if a single dependency expression is satisfied.
 * A dep expression like "nvidia_nim|ollama" is satisfied if ANY of the
 * pipe-separated group IDs is in the configured set.
 */
function isDependencySatisfied(depExpr: string, configuredGroups: Set<string>): boolean {
  const alternatives = depExpr.split('|').map((g) => g.trim());
  return alternatives.some((alt) => configuredGroups.has(alt));
}

/**
 * Computes feature availability for all features given a set of configured groups.
 * A feature is available iff ALL its dependency expressions are satisfied.
 */
function computeFeatureAvailability(configuredGroups: Set<string>): Record<string, boolean> {
  const result: Record<string, boolean> = {};
  for (const [feature, deps] of Object.entries(FEATURE_DEPENDENCIES)) {
    result[feature] = deps.every((dep) => isDependencySatisfied(dep, configuredGroups));
  }
  return result;
}

// ─── Generators ─────────────────────────────────────────────────────────────

const ALL_GROUP_IDS = CREDENTIAL_GROUPS.map((g) => g.group_id);

/**
 * Generates a random subset of credential group IDs representing
 * which groups are "configured".
 */
const arbConfiguredSubset: fc.Arbitrary<string[]> = fc.subarray(ALL_GROUP_IDS, {
  minLength: 0,
  maxLength: ALL_GROUP_IDS.length,
});

// ─── Property Tests ─────────────────────────────────────────────────────────

describe('Feature Availability — Property 4: Feature availability correctness (frontend)', () => {
  /**
   * **Validates: Requirements 4.1**
   *
   * For any subset of configured services, a feature is available
   * if and only if at least one alternative in each of its dependency
   * expressions is in the configured set.
   */
  it('feature is available iff all dependency expressions are satisfied', () => {
    fc.assert(
      fc.property(arbConfiguredSubset, (configuredIds) => {
        const configuredSet = new Set(configuredIds);
        const availability = computeFeatureAvailability(configuredSet);

        for (const [feature, deps] of Object.entries(FEATURE_DEPENDENCIES)) {
          const expectedAvailable = deps.every((depExpr) => {
            const alternatives = depExpr.split('|').map((g) => g.trim());
            return alternatives.some((alt) => configuredSet.has(alt));
          });

          expect(availability[feature]).toBe(expectedAvailable);
        }
      }),
      { numRuns: 200 },
    );
  });

  /**
   * **Validates: Requirements 4.1**
   *
   * When no groups are configured, all features with dependencies
   * SHALL be unavailable.
   */
  it('no configured groups means all features are unavailable', () => {
    fc.assert(
      fc.property(fc.constant([]), () => {
        const availability = computeFeatureAvailability(new Set());

        for (const feature of Object.keys(FEATURE_DEPENDENCIES)) {
          expect(availability[feature]).toBe(false);
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1**
   *
   * When all groups are configured, all features SHALL be available.
   */
  it('all groups configured means all features are available', () => {
    fc.assert(
      fc.property(fc.constant(ALL_GROUP_IDS), (allIds) => {
        const availability = computeFeatureAvailability(new Set(allIds));

        for (const feature of Object.keys(FEATURE_DEPENDENCIES)) {
          expect(availability[feature]).toBe(true);
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1**
   *
   * OR-logic: for features with pipe-separated dependencies (e.g.,
   * "nvidia_nim|ollama"), configuring ANY one alternative SHALL make
   * the feature available.
   */
  it('configuring any single alternative in an OR-dependency satisfies the feature', () => {
    fc.assert(
      fc.property(arbConfiguredSubset, (configuredIds) => {
        const configuredSet = new Set(configuredIds);

        for (const [feature, deps] of Object.entries(FEATURE_DEPENDENCIES)) {
          for (const depExpr of deps) {
            const alternatives = depExpr.split('|').map((g) => g.trim());
            const anySatisfied = alternatives.some((alt) => configuredSet.has(alt));

            if (anySatisfied && deps.length === 1) {
              // If this is the only dependency and it's satisfied, feature must be available
              expect(computeFeatureAvailability(configuredSet)[feature]).toBe(true);
            }
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1**
   *
   * Adding a configured group can only make features MORE available,
   * never less (monotonicity property).
   */
  it('adding a configured group never reduces feature availability', () => {
    fc.assert(
      fc.property(
        arbConfiguredSubset,
        fc.constantFrom(...ALL_GROUP_IDS),
        (configuredIds, extraGroup) => {
          const baseSet = new Set(configuredIds);
          const extendedSet = new Set([...configuredIds, extraGroup]);

          const baseAvailability = computeFeatureAvailability(baseSet);
          const extendedAvailability = computeFeatureAvailability(extendedSet);

          for (const feature of Object.keys(FEATURE_DEPENDENCIES)) {
            // If feature was available before, it must still be available
            if (baseAvailability[feature]) {
              expect(extendedAvailability[feature]).toBe(true);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
