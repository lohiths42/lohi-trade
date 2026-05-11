/**
 * IntegrationsWizardPage — Unit Tests
 *
 * Tests the pure logic of the IntegrationsWizardPage component:
 * - Step navigation (next/back) with bounds checking
 * - Skip flow advances to next step in first-run mode
 * - Summary page correctly categorizes configured/skipped services
 * - Settings mode renders all 6 credential groups with status
 *
 * Validates: Requirements 2.1, 3.1, 3.6, 8.2
 */
import { describe, it, expect } from 'vitest';
import { CREDENTIAL_GROUPS } from '../../lib/setup-types';
import type { ServiceStatus, ServiceStatusValue } from '../../lib/setup-types';

// ─── Constants (mirrors IntegrationsWizardPage logic) ────────────────────────

const TOTAL_STEPS = CREDENTIAL_GROUPS.length + 1; // 6 groups + 1 summary = 7

// ─── Navigation Logic (extracted from component) ─────────────────────────────

/**
 * Simulates the goNext callback from IntegrationsWizardPage.
 * Advances step by 1, clamped to totalSteps - 1.
 */
function goNext(currentStep: number): number {
  return Math.min(currentStep + 1, TOTAL_STEPS - 1);
}

/**
 * Simulates the goBack callback from IntegrationsWizardPage.
 * Decrements step by 1, clamped to 0.
 */
function goBack(currentStep: number): number {
  return Math.max(currentStep - 1, 0);
}

/**
 * Simulates the handleSkip callback in first-run mode.
 * Advances to next step (same as goNext).
 */
function handleSkipFirstRun(currentStep: number): number {
  return Math.min(currentStep + 1, TOTAL_STEPS - 1);
}

/**
 * Determines if the current step is the summary step.
 */
function isSummaryStep(currentStep: number): boolean {
  return currentStep === CREDENTIAL_GROUPS.length;
}

/**
 * Computes progress percentage for the stepper.
 */
function computeProgress(currentStep: number): number {
  return ((currentStep + 1) / TOTAL_STEPS) * 100;
}

// ─── Summary Logic (mirrors SetupSummary categorization) ─────────────────────

function categorizeServices(services: ServiceStatus[]) {
  return {
    configured: services.filter((s) => s.status === 'configured'),
    skipped: services.filter((s) => s.status === 'skipped'),
    unconfigured: services.filter((s) => s.status === 'unconfigured'),
    error: services.filter((s) => s.status === 'error'),
  };
}

/**
 * Simulates getServiceStatus from IntegrationsWizardPage.
 * Returns the service status for a given group_id, or a default unconfigured status.
 */
function getServiceStatus(services: ServiceStatus[], groupId: string): ServiceStatus {
  const found = services.find((s) => s.group_id === groupId);
  return (
    found ?? {
      group_id: groupId,
      name: CREDENTIAL_GROUPS.find((g) => g.group_id === groupId)?.name ?? groupId,
      status: 'unconfigured' as ServiceStatusValue,
      required: false,
      features_affected: [],
    }
  );
}

// ─── Helper: create a ServiceStatus entry ────────────────────────────────────

function makeService(
  groupId: string,
  status: ServiceStatusValue,
  features: string[] = [],
): ServiceStatus {
  const group = CREDENTIAL_GROUPS.find((g) => g.group_id === groupId);
  return {
    group_id: groupId,
    name: group?.name ?? groupId,
    status,
    required: group?.required ?? false,
    features_affected: features.length > 0 ? features : group?.features_dependent ?? [],
  };
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/* Unit Tests                                                                 */
/* ═══════════════════════════════════════════════════════════════════════════ */

describe('IntegrationsWizardPage — step navigation', () => {
  it('totalSteps equals 7 (6 credential groups + 1 summary)', () => {
    expect(CREDENTIAL_GROUPS).toHaveLength(6);
    expect(TOTAL_STEPS).toBe(7);
  });

  it('goNext increments step from 0 to 1', () => {
    expect(goNext(0)).toBe(1);
  });

  it('goNext increments step from middle to next', () => {
    expect(goNext(3)).toBe(4);
  });

  it('goNext does not exceed totalSteps - 1 (clamped at summary)', () => {
    expect(goNext(TOTAL_STEPS - 1)).toBe(TOTAL_STEPS - 1);
    expect(goNext(6)).toBe(6);
  });

  it('goBack decrements step from 3 to 2', () => {
    expect(goBack(3)).toBe(2);
  });

  it('goBack does not go below 0', () => {
    expect(goBack(0)).toBe(0);
  });

  it('goBack from step 1 returns to step 0', () => {
    expect(goBack(1)).toBe(0);
  });

  it('sequential next calls reach summary step', () => {
    let step = 0;
    for (let i = 0; i < CREDENTIAL_GROUPS.length; i++) {
      step = goNext(step);
    }
    expect(step).toBe(CREDENTIAL_GROUPS.length);
    expect(isSummaryStep(step)).toBe(true);
  });

  it('next then back returns to original step', () => {
    const original = 2;
    const afterNext = goNext(original);
    const afterBack = goBack(afterNext);
    expect(afterBack).toBe(original);
  });

  it('isSummaryStep is true only at step 6', () => {
    expect(isSummaryStep(0)).toBe(false);
    expect(isSummaryStep(3)).toBe(false);
    expect(isSummaryStep(5)).toBe(false);
    expect(isSummaryStep(6)).toBe(true);
  });

  it('progress percentage increases with each step', () => {
    const p0 = computeProgress(0);
    const p3 = computeProgress(3);
    const p6 = computeProgress(6);
    expect(p0).toBeCloseTo((1 / 7) * 100);
    expect(p3).toBeCloseTo((4 / 7) * 100);
    expect(p6).toBe(100);
    expect(p3).toBeGreaterThan(p0);
    expect(p6).toBeGreaterThan(p3);
  });
});

describe('IntegrationsWizardPage — skip flow', () => {
  it('skipping a group in first-run mode advances to next step', () => {
    const step = 0; // NVIDIA NIM step
    const nextStep = handleSkipFirstRun(step);
    expect(nextStep).toBe(1);
  });

  it('skipping at step 2 advances to step 3', () => {
    expect(handleSkipFirstRun(2)).toBe(3);
  });

  it('skipping at the last group step advances to summary', () => {
    const lastGroupStep = CREDENTIAL_GROUPS.length - 1; // step 5
    const nextStep = handleSkipFirstRun(lastGroupStep);
    expect(nextStep).toBe(CREDENTIAL_GROUPS.length); // summary step
    expect(isSummaryStep(nextStep)).toBe(true);
  });

  it('skipping at summary step does not advance further', () => {
    const summaryStep = CREDENTIAL_GROUPS.length;
    const nextStep = handleSkipFirstRun(summaryStep);
    expect(nextStep).toBe(summaryStep); // clamped
  });

  it('skipping all groups sequentially reaches summary', () => {
    let step = 0;
    for (let i = 0; i < CREDENTIAL_GROUPS.length; i++) {
      step = handleSkipFirstRun(step);
    }
    expect(step).toBe(CREDENTIAL_GROUPS.length);
    expect(isSummaryStep(step)).toBe(true);
  });
});

describe('IntegrationsWizardPage — summary categorization', () => {
  it('correctly counts configured services', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'configured'),
      makeService('nubra', 'configured'),
      makeService('broker_shoonya', 'skipped'),
      makeService('broker_angelone', 'skipped'),
      makeService('telegram', 'unconfigured'),
      makeService('ollama', 'unconfigured'),
    ];

    const categories = categorizeServices(services);
    expect(categories.configured).toHaveLength(2);
    expect(categories.skipped).toHaveLength(2);
    expect(categories.unconfigured).toHaveLength(2);
    expect(categories.error).toHaveLength(0);
  });

  it('correctly counts when all services are configured', () => {
    const services: ServiceStatus[] = CREDENTIAL_GROUPS.map((g) =>
      makeService(g.group_id, 'configured'),
    );

    const categories = categorizeServices(services);
    expect(categories.configured).toHaveLength(6);
    expect(categories.skipped).toHaveLength(0);
    expect(categories.unconfigured).toHaveLength(0);
  });

  it('correctly counts when all services are skipped', () => {
    const services: ServiceStatus[] = CREDENTIAL_GROUPS.map((g) =>
      makeService(g.group_id, 'skipped'),
    );

    const categories = categorizeServices(services);
    expect(categories.configured).toHaveLength(0);
    expect(categories.skipped).toHaveLength(6);
  });

  it('handles mixed statuses including errors', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'configured'),
      makeService('nubra', 'error'),
      makeService('broker_shoonya', 'skipped'),
      makeService('broker_angelone', 'unconfigured'),
      makeService('telegram', 'configured'),
      makeService('ollama', 'error'),
    ];

    const categories = categorizeServices(services);
    expect(categories.configured).toHaveLength(2);
    expect(categories.skipped).toHaveLength(1);
    expect(categories.unconfigured).toHaveLength(1);
    expect(categories.error).toHaveLength(2);
  });

  it('total categorized services equals input length', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'configured'),
      makeService('nubra', 'skipped'),
      makeService('broker_shoonya', 'unconfigured'),
      makeService('broker_angelone', 'error'),
      makeService('telegram', 'configured'),
      makeService('ollama', 'skipped'),
    ];

    const categories = categorizeServices(services);
    const total =
      categories.configured.length +
      categories.skipped.length +
      categories.unconfigured.length +
      categories.error.length;
    expect(total).toBe(services.length);
  });

  it('skipped services retain their features_affected list', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'skipped', ['research_dashboard', 'ai_analysis']),
      makeService('telegram', 'skipped', ['telegram_notifications']),
    ];

    const categories = categorizeServices(services);
    expect(categories.skipped[0].features_affected).toEqual([
      'research_dashboard',
      'ai_analysis',
    ]);
    expect(categories.skipped[1].features_affected).toEqual(['telegram_notifications']);
  });
});

describe('IntegrationsWizardPage — settings mode (all groups with status)', () => {
  it('all 6 credential groups are available for rendering', () => {
    expect(CREDENTIAL_GROUPS).toHaveLength(6);
    const groupIds = CREDENTIAL_GROUPS.map((g) => g.group_id);
    expect(groupIds).toEqual([
      'nvidia_nim',
      'nubra',
      'broker_shoonya',
      'broker_angelone',
      'telegram',
      'ollama',
    ]);
  });

  it('getServiceStatus returns correct status for known group', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'configured'),
      makeService('nubra', 'skipped'),
    ];

    const nimStatus = getServiceStatus(services, 'nvidia_nim');
    expect(nimStatus.status).toBe('configured');
    expect(nimStatus.name).toBe('NVIDIA NIM');

    const nubraStatus = getServiceStatus(services, 'nubra');
    expect(nubraStatus.status).toBe('skipped');
    expect(nubraStatus.name).toBe('Nubra.io Market Data');
  });

  it('getServiceStatus returns unconfigured default for missing group', () => {
    const services: ServiceStatus[] = [makeService('nvidia_nim', 'configured')];

    const telegramStatus = getServiceStatus(services, 'telegram');
    expect(telegramStatus.status).toBe('unconfigured');
    expect(telegramStatus.group_id).toBe('telegram');
    expect(telegramStatus.name).toBe('Telegram Bot');
  });

  it('every credential group has a name and description', () => {
    for (const group of CREDENTIAL_GROUPS) {
      expect(group.name.length).toBeGreaterThan(0);
      expect(group.description.length).toBeGreaterThan(0);
    }
  });

  it('every credential group has a documentation URL', () => {
    for (const group of CREDENTIAL_GROUPS) {
      expect(group.documentation_url).toMatch(/^https?:\/\//);
    }
  });

  it('settings mode can resolve status for all 6 groups', () => {
    const services: ServiceStatus[] = [
      makeService('nvidia_nim', 'configured'),
      makeService('nubra', 'configured'),
      makeService('broker_shoonya', 'skipped'),
      makeService('broker_angelone', 'unconfigured'),
      makeService('telegram', 'error'),
      makeService('ollama', 'unconfigured'),
    ];

    // In settings mode, the page iterates over CREDENTIAL_GROUPS and resolves status
    const resolvedStatuses = CREDENTIAL_GROUPS.map((group) =>
      getServiceStatus(services, group.group_id),
    );

    expect(resolvedStatuses).toHaveLength(6);
    expect(resolvedStatuses[0].status).toBe('configured'); // nvidia_nim
    expect(resolvedStatuses[1].status).toBe('configured'); // nubra
    expect(resolvedStatuses[2].status).toBe('skipped'); // broker_shoonya
    expect(resolvedStatuses[3].status).toBe('unconfigured'); // broker_angelone
    expect(resolvedStatuses[4].status).toBe('error'); // telegram
    expect(resolvedStatuses[5].status).toBe('unconfigured'); // ollama
  });

  it('settings mode with empty services array defaults all to unconfigured', () => {
    const services: ServiceStatus[] = [];

    const resolvedStatuses = CREDENTIAL_GROUPS.map((group) =>
      getServiceStatus(services, group.group_id),
    );

    for (const status of resolvedStatuses) {
      expect(status.status).toBe('unconfigured');
    }
  });
});
