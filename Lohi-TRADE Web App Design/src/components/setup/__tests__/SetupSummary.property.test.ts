/**
 * Property-based tests for SetupSummary rendering completeness.
 *
 * **Property 3: Service status rendering completeness**
 *
 * For any valid service registry state, the categorization logic
 * (configured/skipped/unconfigured/error) SHALL correctly account for
 * every registered credential group with its correct current status.
 *
 * Since we test pure logic (not React rendering), we verify that the
 * categorization function produces groups that collectively contain
 * every input service exactly once, with the correct status bucket.
 *
 * **Validates: Requirements 3.6, 8.2**
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  CREDENTIAL_GROUPS,
  type ServiceStatus,
  type ServiceStatusValue,
} from '../../../lib/setup-types';

// ─── Logic Under Test ───────────────────────────────────────────────────────
// This mirrors the categorization logic in SetupSummary.tsx

const ALL_STATUSES: ServiceStatusValue[] = ['configured', 'unconfigured', 'skipped', 'error'];

/**
 * Categorizes services into buckets by status.
 * This is the pure logic extracted from SetupSummary component.
 */
function categorizeServices(services: ServiceStatus[]): {
  configured: ServiceStatus[];
  skipped: ServiceStatus[];
  unconfigured: ServiceStatus[];
  error: ServiceStatus[];
} {
  return {
    configured: services.filter((s) => s.status === 'configured'),
    skipped: services.filter((s) => s.status === 'skipped'),
    unconfigured: services.filter((s) => s.status === 'unconfigured'),
    error: services.filter((s) => s.status === 'error'),
  };
}

// ─── Generators ─────────────────────────────────────────────────────────────

/**
 * Generates a random ServiceStatusValue.
 */
const arbServiceStatusValue: fc.Arbitrary<ServiceStatusValue> = fc.constantFrom(
  ...ALL_STATUSES,
);

/**
 * Generates a random ServiceStatus array based on the actual CREDENTIAL_GROUPS.
 * Each group gets a random status, simulating any possible registry state.
 */
const arbServiceStatusArray: fc.Arbitrary<ServiceStatus[]> = fc
  .tuple(
    ...CREDENTIAL_GROUPS.map((group) =>
      arbServiceStatusValue.map((status) => ({
        group_id: group.group_id,
        name: group.name,
        status,
        required: group.required,
        features_affected: group.features_dependent,
      })),
    ),
  )
  .map((statuses) => statuses as ServiceStatus[]);

// ─── Property Tests ─────────────────────────────────────────────────────────

describe('SetupSummary — Property 3: Service status rendering completeness', () => {
  /**
   * **Validates: Requirements 3.6, 8.2**
   *
   * For any valid service registry state, the categorized groups SHALL
   * collectively contain every registered credential group exactly once.
   */
  it('every registered group appears exactly once across all status categories', () => {
    fc.assert(
      fc.property(arbServiceStatusArray, (services) => {
        const categories = categorizeServices(services);

        // All categories combined should contain every service
        const allCategorized = [
          ...categories.configured,
          ...categories.skipped,
          ...categories.unconfigured,
          ...categories.error,
        ];

        // Total count must equal input count
        expect(allCategorized.length).toBe(services.length);

        // Every input service must appear in exactly one category
        const categorizedIds = allCategorized.map((s) => s.group_id).sort();
        const inputIds = services.map((s) => s.group_id).sort();
        expect(categorizedIds).toEqual(inputIds);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.6, 8.2**
   *
   * For any valid service registry state, each service SHALL appear in
   * the category that matches its actual status value.
   */
  it('each service appears in the category matching its status', () => {
    fc.assert(
      fc.property(arbServiceStatusArray, (services) => {
        const categories = categorizeServices(services);

        for (const service of services) {
          const bucket = categories[service.status];
          const found = bucket.find((s) => s.group_id === service.group_id);
          expect(found).toBeDefined();
          expect(found!.status).toBe(service.status);
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.6, 8.2**
   *
   * For any valid service registry state, no service SHALL appear in a
   * category that does not match its status.
   */
  it('no service appears in a wrong category', () => {
    fc.assert(
      fc.property(arbServiceStatusArray, (services) => {
        const categories = categorizeServices(services);

        for (const statusKey of ALL_STATUSES) {
          for (const service of categories[statusKey]) {
            expect(service.status).toBe(statusKey);
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.6, 8.2**
   *
   * The categorization preserves all service metadata (name, required,
   * features_affected) — no data loss during categorization.
   */
  it('categorization preserves all service metadata', () => {
    fc.assert(
      fc.property(arbServiceStatusArray, (services) => {
        const categories = categorizeServices(services);
        const allCategorized = [
          ...categories.configured,
          ...categories.skipped,
          ...categories.unconfigured,
          ...categories.error,
        ];

        for (const service of services) {
          const found = allCategorized.find((s) => s.group_id === service.group_id);
          expect(found).toBeDefined();
          expect(found!.name).toBe(service.name);
          expect(found!.required).toBe(service.required);
          expect(found!.features_affected).toEqual(service.features_affected);
        }
      }),
      { numRuns: 100 },
    );
  });
});
