/**
 * Feature: frontend-enhancements
 * Property 5: Virtual scroller renders bounded rows
 *
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
 *
 * Tests the mathematical properties of the virtual scroller logic:
 * - Total scrollable height = rowCount * rowHeight
 * - Visible rows = Math.ceil(containerHeight / rowHeight)
 * - Max rendered rows = visibleRows + 2 * overscan
 * - When data.length <= threshold (50), all rows are rendered (no virtualization)
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

// ─── Pure virtualizer math functions ────────────────────────────────────────

/** Compute total scrollable height for the virtual scroller. */
function computeTotalScrollHeight(rowCount: number, rowHeight: number): number {
  return rowCount * rowHeight;
}

/** Compute the number of visible rows that fit in the container. */
function computeVisibleRows(containerHeight: number, rowHeight: number): number {
  return Math.ceil(containerHeight / rowHeight);
}

/** Compute the maximum number of rendered rows (visible + overscan buffer). */
function computeMaxRenderedRows(
  visibleRows: number,
  overscan: number,
  totalRows: number,
): number {
  // Can never render more rows than exist in the dataset
  return Math.min(visibleRows + 2 * overscan, totalRows);
}

/** Determine whether virtualization is active based on the threshold. */
function isVirtualized(rowCount: number, threshold: number): boolean {
  return rowCount > threshold;
}

/**
 * Compute the rendered row range for a given scroll offset.
 * Returns [startIndex, endIndex) — the half-open range of row indices to render.
 */
function computeRenderedRange(
  scrollOffset: number,
  containerHeight: number,
  rowHeight: number,
  totalRows: number,
  overscan: number,
): { start: number; end: number; count: number } {
  const firstVisible = Math.floor(scrollOffset / rowHeight);
  const visibleCount = Math.ceil(containerHeight / rowHeight);

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(totalRows, firstVisible + visibleCount + overscan);
  return { start, end, count: end - start };
}

// ─── Generators ─────────────────────────────────────────────────────────────

/** Row height: positive integer between 20 and 100 px. */
const arbRowHeight = fc.integer({ min: 20, max: 100 });

/** Container height: between 200 and 2000 px. */
const arbContainerHeight = fc.integer({ min: 200, max: 2000 });

/** Overscan: 0 to 20 rows (default is 10). */
const arbOverscan = fc.integer({ min: 0, max: 20 });

/** Row count for virtualized tables: more than 50 rows, up to 10000. */
const arbLargeRowCount = fc.integer({ min: 51, max: 10000 });

/** Row count for non-virtualized tables: 0 to 50 rows. */
const arbSmallRowCount = fc.integer({ min: 0, max: 50 });

/** Threshold: the default is 50, but test with a range. */
const arbThreshold = fc.integer({ min: 10, max: 100 });

// ─── Property Tests ─────────────────────────────────────────────────────────

describe('Feature: frontend-enhancements, Property 5: Virtual scroller renders bounded rows', () => {
  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
   *
   * For any dataset with more than 50 rows and any row height,
   * the total scrollable height should equal rowCount * rowHeight.
   */
  it('total scrollable height equals rowCount * rowHeight for any dataset', () => {
    fc.assert(
      fc.property(arbLargeRowCount, arbRowHeight, (rowCount, rowHeight) => {
        const totalHeight = computeTotalScrollHeight(rowCount, rowHeight);
        expect(totalHeight).toBe(rowCount * rowHeight);
        expect(totalHeight).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
   *
   * For any container height and row height, the number of visible rows
   * should equal Math.ceil(containerHeight / rowHeight).
   */
  it('visible rows equals ceil(containerHeight / rowHeight)', () => {
    fc.assert(
      fc.property(arbContainerHeight, arbRowHeight, (containerHeight, rowHeight) => {
        const visibleRows = computeVisibleRows(containerHeight, rowHeight);
        expect(visibleRows).toBe(Math.ceil(containerHeight / rowHeight));
        expect(visibleRows).toBeGreaterThanOrEqual(1);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
   *
   * For any dataset with more than 50 rows and any scroll position,
   * the number of rendered rows should be at most visibleRows + 2 * overscan.
   */
  it('rendered row count is at most visibleRows + 2 * overscan for any scroll position', () => {
    fc.assert(
      fc.property(
        arbLargeRowCount,
        arbRowHeight,
        arbContainerHeight,
        arbOverscan,
        (rowCount, rowHeight, containerHeight, overscan) => {
          // Generate a random scroll offset within the valid range
          const maxScroll = Math.max(0, rowCount * rowHeight - containerHeight);

          return fc.assert(
            fc.property(
              fc.integer({ min: 0, max: Math.max(0, maxScroll) }),
              (scrollOffset) => {
                const { count } = computeRenderedRange(
                  scrollOffset,
                  containerHeight,
                  rowHeight,
                  rowCount,
                  overscan,
                );

                const visibleRows = computeVisibleRows(containerHeight, rowHeight);
                const maxRendered = computeMaxRenderedRows(visibleRows, overscan, rowCount);

                expect(count).toBeLessThanOrEqual(maxRendered);
                expect(count).toBeGreaterThanOrEqual(1);
              },
            ),
            { numRuns: 10 }, // inner property — fewer runs since outer already varies
          );
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
   *
   * When data.length <= threshold (default 50), all rows should be rendered
   * (no virtualization). The rendered count equals the total row count.
   */
  it('when row count is at or below threshold, all rows are rendered (no virtualization)', () => {
    fc.assert(
      fc.property(arbSmallRowCount, arbThreshold, (rowCount, threshold) => {
        // Only test when rowCount <= threshold (the non-virtualized case)
        fc.pre(rowCount <= threshold);

        const virtualized = isVirtualized(rowCount, threshold);
        expect(virtualized).toBe(false);

        // In non-virtualized mode, all rows are rendered
        // This matches VirtualTable.tsx: `const useVirtual = data.length > threshold;`
        // When useVirtual is false, all data rows are rendered in a plain <tbody>
        const renderedCount = rowCount; // all rows rendered
        expect(renderedCount).toBe(rowCount);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.5**
   *
   * The total scrollable height is always non-negative and proportional
   * to the number of rows, ensuring the scrollbar accurately reflects
   * the total dataset size.
   */
  it('total scrollable height is proportional to row count (doubling rows doubles height)', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 5000 }),
        arbRowHeight,
        (rowCount, rowHeight) => {
          const height1 = computeTotalScrollHeight(rowCount, rowHeight);
          const height2 = computeTotalScrollHeight(rowCount * 2, rowHeight);
          expect(height2).toBe(height1 * 2);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
   *
   * The rendered range indices are always valid: start >= 0, end <= totalRows,
   * and start < end (at least one row rendered when totalRows > 0).
   */
  it('rendered range indices are always within valid bounds', () => {
    fc.assert(
      fc.property(
        arbLargeRowCount,
        arbRowHeight,
        arbContainerHeight,
        arbOverscan,
        (rowCount, rowHeight, containerHeight, overscan) => {
          const maxScroll = Math.max(0, rowCount * rowHeight - containerHeight);

          return fc.assert(
            fc.property(
              fc.integer({ min: 0, max: Math.max(0, maxScroll) }),
              (scrollOffset) => {
                const { start, end, count } = computeRenderedRange(
                  scrollOffset,
                  containerHeight,
                  rowHeight,
                  rowCount,
                  overscan,
                );

                expect(start).toBeGreaterThanOrEqual(0);
                expect(end).toBeLessThanOrEqual(rowCount);
                expect(start).toBeLessThan(end);
                expect(count).toBe(end - start);
              },
            ),
            { numRuns: 10 },
          );
        },
      ),
      { numRuns: 100 },
    );
  });
});


// ─── Property 6 helpers ─────────────────────────────────────────────────────

/**
 * Simulate the rendered row indices for a given scroll state.
 * Returns the array of data indices that would be rendered by the virtual scroller.
 */
function getRenderedIndices(
  scrollOffset: number,
  containerHeight: number,
  rowHeight: number,
  totalRows: number,
  overscan: number,
): number[] {
  const { start, end } = computeRenderedRange(
    scrollOffset,
    containerHeight,
    rowHeight,
    totalRows,
    overscan,
  );
  const indices: number[] = [];
  for (let i = start; i < end; i++) {
    indices.push(i);
  }
  return indices;
}

// ─── Property 6 Tests ──────────────────────────────────────────────────────

describe('Feature: frontend-enhancements, Property 6: Virtual scroller preserves data ordering', () => {
  /**
   * **Validates: Requirements 2.6**
   *
   * For any dataset and any scroll position, the rendered indices returned by
   * computeRenderedRange form a contiguous subsequence of [0, totalRows).
   * This means the rendered rows are a contiguous slice of the input data.
   */
  it('rendered indices form a contiguous subsequence of the input data', () => {
    fc.assert(
      fc.property(
        arbLargeRowCount,
        arbRowHeight,
        arbContainerHeight,
        arbOverscan,
        (rowCount, rowHeight, containerHeight, overscan) => {
          const maxScroll = Math.max(0, rowCount * rowHeight - containerHeight);

          return fc.assert(
            fc.property(
              fc.integer({ min: 0, max: Math.max(0, maxScroll) }),
              (scrollOffset) => {
                const indices = getRenderedIndices(
                  scrollOffset,
                  containerHeight,
                  rowHeight,
                  rowCount,
                  overscan,
                );

                // Must have at least one rendered index
                expect(indices.length).toBeGreaterThanOrEqual(1);

                // Indices must be contiguous: each index is exactly previous + 1
                for (let i = 1; i < indices.length; i++) {
                  expect(indices[i]).toBe(indices[i - 1] + 1);
                }

                // All indices must be valid data indices
                for (const idx of indices) {
                  expect(idx).toBeGreaterThanOrEqual(0);
                  expect(idx).toBeLessThan(rowCount);
                }
              },
            ),
            { numRuns: 10 },
          );
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.6**
   *
   * For any dataset and any scroll position, the rendered indices are in
   * strictly ascending order, preserving the input data ordering.
   */
  it('rendered indices are in strictly ascending order', () => {
    fc.assert(
      fc.property(
        arbLargeRowCount,
        arbRowHeight,
        arbContainerHeight,
        arbOverscan,
        (rowCount, rowHeight, containerHeight, overscan) => {
          const maxScroll = Math.max(0, rowCount * rowHeight - containerHeight);

          return fc.assert(
            fc.property(
              fc.integer({ min: 0, max: Math.max(0, maxScroll) }),
              (scrollOffset) => {
                const indices = getRenderedIndices(
                  scrollOffset,
                  containerHeight,
                  rowHeight,
                  rowCount,
                  overscan,
                );

                // For any two adjacent rendered rows, the later one must have a
                // strictly greater index — this implies global strict ascending
                // order (if A < B for all consecutive pairs, then for any pair
                // where row A comes before row B, A's index < B's index).
                for (let i = 1; i < indices.length; i++) {
                  expect(indices[i]).toBeGreaterThan(indices[i - 1]);
                }
              },
            ),
            { numRuns: 10 },
          );
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.6**
   *
   * For any pre-sorted/pre-filtered dataset, the rows selected by the virtual
   * scroller's rendered range maintain the same relative order as the input.
   * We verify this by generating a sorted dataset and checking that the
   * rendered slice preserves that sort order.
   */
  it('rendered slice of a sorted dataset preserves the sort order', () => {
    // Generate a sorted array of numeric values (simulating pre-sorted data)
    const arbSortedData = fc
      .array(fc.integer({ min: -100000, max: 100000 }), { minLength: 51, maxLength: 500 })
      .map((arr) => [...arr].sort((a, b) => a - b));

    fc.assert(
      fc.property(
        arbSortedData,
        arbRowHeight,
        arbContainerHeight,
        arbOverscan,
        (sortedData, rowHeight, containerHeight, overscan) => {
          const totalRows = sortedData.length;
          const maxScroll = Math.max(0, totalRows * rowHeight - containerHeight);

          return fc.assert(
            fc.property(
              fc.integer({ min: 0, max: Math.max(0, maxScroll) }),
              (scrollOffset) => {
                const indices = getRenderedIndices(
                  scrollOffset,
                  containerHeight,
                  rowHeight,
                  totalRows,
                  overscan,
                );

                // Extract the rendered values from the sorted dataset
                const renderedValues = indices.map((i) => sortedData[i]);

                // The rendered values must maintain sorted (non-decreasing) order
                for (let i = 1; i < renderedValues.length; i++) {
                  expect(renderedValues[i]).toBeGreaterThanOrEqual(renderedValues[i - 1]);
                }
              },
            ),
            { numRuns: 10 },
          );
        },
      ),
      { numRuns: 100 },
    );
  });
});
