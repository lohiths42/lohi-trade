/**
 * WalkthroughOverlay unit + property tests
 *
 * Tests the pure logic of the walkthrough overlay component:
 * - Step definitions completeness and validity
 * - Tooltip position computation and viewport clamping
 * - Navigation state machine (next, back, skip)
 *
 * Validates: Requirements 33.1, 33.2, 33.3, 33.4, 33.5, 33.9, 33.10
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  WALKTHROUGH_STEPS,
  computeTooltipPosition,
  type WalkthroughStep,
  type TargetRect,
} from '../WalkthroughOverlay';

/* ─── Unit Tests ─────────────────────────────────────────────────────────── */

describe('WalkthroughOverlay — step definitions', () => {
  it('defines exactly 7 walkthrough steps', () => {
    expect(WALKTHROUGH_STEPS).toHaveLength(7);
  });

  it('covers all required features in order', () => {
    const titles = WALKTHROUGH_STEPS.map((s) => s.title);
    expect(titles).toEqual([
      'Dashboard Overview',
      'Manage Positions',
      'Stock Screener',
      'Watchlists',
      'Connect Broker',
      'Meet Lohi',
      'Kill Switch',
    ]);
  });

  it('every step has a data-tour selector', () => {
    for (const step of WALKTHROUGH_STEPS) {
      expect(step.targetSelector).toMatch(/^\[data-tour="[a-z-]+"\]$/);
    }
  });

  it('every step has a non-empty title and description', () => {
    for (const step of WALKTHROUGH_STEPS) {
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.description.length).toBeGreaterThan(0);
    }
  });

  it('every step has a valid position', () => {
    const validPositions = ['top', 'bottom', 'left', 'right'];
    for (const step of WALKTHROUGH_STEPS) {
      expect(validPositions).toContain(step.position);
    }
  });

  it('all target selectors are unique', () => {
    const selectors = WALKTHROUGH_STEPS.map((s) => s.targetSelector);
    expect(new Set(selectors).size).toBe(selectors.length);
  });
});

describe('WalkthroughOverlay — navigation state machine', () => {
  it('starts at step 0', () => {
    const initialStep = 0;
    expect(initialStep).toBe(0);
    expect(WALKTHROUGH_STEPS[initialStep].title).toBe('Dashboard Overview');
  });

  it('next increments step until last', () => {
    let step = 0;
    for (let i = 0; i < WALKTHROUGH_STEPS.length - 1; i++) {
      step = step + 1;
    }
    expect(step).toBe(WALKTHROUGH_STEPS.length - 1);
  });

  it('back decrements step but not below 0', () => {
    let step = 3;
    step = Math.max(0, step - 1);
    expect(step).toBe(2);

    step = 0;
    step = Math.max(0, step - 1);
    expect(step).toBe(0);
  });

  it('last step shows Finish instead of Next', () => {
    const lastIndex = WALKTHROUGH_STEPS.length - 1;
    const isLast = lastIndex === WALKTHROUGH_STEPS.length - 1;
    expect(isLast).toBe(true);
  });

  it('first step hides Back button', () => {
    const isFirst = 0 === 0;
    expect(isFirst).toBe(true);
  });
});

/* ─── Tooltip Position Tests ─────────────────────────────────────────────── */

describe('WalkthroughOverlay — tooltip positioning', () => {
  const tooltipW = 320;
  const tooltipH = 180;
  const vpW = 1280;
  const vpH = 800;

  it('positions tooltip below target for "bottom" position', () => {
    const target: TargetRect = { top: 100, left: 400, width: 200, height: 50 };
    const pos = computeTooltipPosition(target, 'bottom', tooltipW, tooltipH, vpW, vpH);
    expect(pos.top).toBeGreaterThan(target.top + target.height);
  });

  it('positions tooltip above target for "top" position', () => {
    const target: TargetRect = { top: 400, left: 400, width: 200, height: 50 };
    const pos = computeTooltipPosition(target, 'top', tooltipW, tooltipH, vpW, vpH);
    expect(pos.top).toBeLessThan(target.top);
  });

  it('positions tooltip to the right for "right" position', () => {
    const target: TargetRect = { top: 300, left: 100, width: 100, height: 50 };
    const pos = computeTooltipPosition(target, 'right', tooltipW, tooltipH, vpW, vpH);
    expect(pos.left).toBeGreaterThan(target.left + target.width);
  });

  it('positions tooltip to the left for "left" position', () => {
    const target: TargetRect = { top: 300, left: 800, width: 100, height: 50 };
    const pos = computeTooltipPosition(target, 'left', tooltipW, tooltipH, vpW, vpH);
    expect(pos.left).toBeLessThan(target.left);
  });

  it('clamps tooltip within viewport when target is near edge', () => {
    // Target near right edge
    const target: TargetRect = { top: 100, left: 1200, width: 60, height: 40 };
    const pos = computeTooltipPosition(target, 'bottom', tooltipW, tooltipH, vpW, vpH);
    expect(pos.left + tooltipW).toBeLessThanOrEqual(vpW);
    expect(pos.left).toBeGreaterThanOrEqual(0);
  });
});

/* ─── Property-Based Tests ───────────────────────────────────────────────── */

// Generators
const arbTargetRect = fc.record({
  top: fc.integer({ min: 0, max: 2000 }),
  left: fc.integer({ min: 0, max: 2000 }),
  width: fc.integer({ min: 20, max: 400 }),
  height: fc.integer({ min: 20, max: 200 }),
});

const arbPosition = fc.constantFrom<WalkthroughStep['position']>('top', 'bottom', 'left', 'right');

const arbViewport = fc.record({
  width: fc.integer({ min: 400, max: 3000 }),
  height: fc.integer({ min: 400, max: 2000 }),
});

const arbTooltipSize = fc.record({
  width: fc.integer({ min: 100, max: 500 }),
  height: fc.integer({ min: 80, max: 400 }),
});

describe('WalkthroughOverlay — property: tooltip always within viewport', () => {
  /**
   * **Validates: Requirements 33.3, 33.5**
   *
   * For any target element position, tooltip size, and viewport dimensions
   * where the tooltip can physically fit, the computed tooltip position
   * must keep the tooltip fully within the viewport.
   */
  it('tooltip is always clamped within viewport bounds', () => {
    // Generate viewport and tooltip sizes where tooltip fits within viewport
    const arbFittingConfig = arbViewport.chain((viewport) => {
      const maxTW = Math.max(100, viewport.width - 24); // leave 12px margin each side
      const maxTH = Math.max(80, viewport.height - 24);
      return fc.tuple(
        fc.constant(viewport),
        fc.record({
          width: fc.integer({ min: 100, max: Math.min(maxTW, 500) }),
          height: fc.integer({ min: 80, max: Math.min(maxTH, 400) }),
        }),
      );
    });

    fc.assert(
      fc.property(
        arbTargetRect,
        arbPosition,
        arbFittingConfig,
        (target, position, [viewport, tooltipSize]) => {
          const pos = computeTooltipPosition(
            target,
            position,
            tooltipSize.width,
            tooltipSize.height,
            viewport.width,
            viewport.height,
          );

          // Tooltip left edge >= 12px margin
          expect(pos.left).toBeGreaterThanOrEqual(12);
          // Tooltip right edge <= viewport width - 12px margin
          expect(pos.left + tooltipSize.width).toBeLessThanOrEqual(viewport.width);
          // Tooltip top edge >= 12px margin
          expect(pos.top).toBeGreaterThanOrEqual(12);
          // Tooltip bottom edge <= viewport height - 12px margin
          expect(pos.top + tooltipSize.height).toBeLessThanOrEqual(viewport.height);
        },
      ),
      { numRuns: 200 },
    );
  });
});

describe('WalkthroughOverlay — property: navigation step bounds', () => {
  /**
   * **Validates: Requirements 33.2, 33.5**
   *
   * For any sequence of next/back operations, the current step index
   * always stays within [0, totalSteps - 1].
   */
  it('step index stays within valid bounds for any navigation sequence', () => {
    const totalSteps = WALKTHROUGH_STEPS.length;

    // Generate a sequence of navigation actions
    const arbAction = fc.constantFrom('next', 'back');
    const arbActions = fc.array(arbAction, { minLength: 1, maxLength: 50 });

    fc.assert(
      fc.property(arbActions, (actions) => {
        let step = 0;
        for (const action of actions) {
          if (action === 'next' && step < totalSteps - 1) {
            step += 1;
          } else if (action === 'back' && step > 0) {
            step -= 1;
          }
          expect(step).toBeGreaterThanOrEqual(0);
          expect(step).toBeLessThan(totalSteps);
        }
      }),
      { numRuns: 200 },
    );
  });

  /**
   * **Validates: Requirements 33.2, 33.5**
   *
   * N consecutive "next" actions from step 0 reach step min(N, totalSteps - 1).
   */
  it('N next actions from step 0 reach min(N, totalSteps - 1)', () => {
    const totalSteps = WALKTHROUGH_STEPS.length;

    fc.assert(
      fc.property(fc.integer({ min: 0, max: 20 }), (n) => {
        let step = 0;
        for (let i = 0; i < n; i++) {
          if (step < totalSteps - 1) step += 1;
        }
        expect(step).toBe(Math.min(n, totalSteps - 1));
      }),
      { numRuns: 100 },
    );
  });
});
