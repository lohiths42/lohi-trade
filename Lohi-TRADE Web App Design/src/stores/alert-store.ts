/**
 * P&L Alert Engine Zustand store.
 * Manages threshold rules with localStorage persistence.
 * Fires each alert at most once per session.
 */

import { create } from 'zustand';
import type { AlertRule } from '../lib/types';

const RULES_KEY = 'lohi_alert_rules';
const FIRED_KEY = 'lohi_alert_fired';

function loadRules(): AlertRule[] {
  try {
    const raw = localStorage.getItem(RULES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function loadFired(): Set<string> {
  try {
    const raw = localStorage.getItem(FIRED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function persistRules(rules: AlertRule[]): void {
  try { localStorage.setItem(RULES_KEY, JSON.stringify(rules)); } catch { /* ignore */ }
}

function persistFired(fired: Set<string>): void {
  try { localStorage.setItem(FIRED_KEY, JSON.stringify([...fired])); } catch { /* ignore */ }
}

export interface AlertState {
  rules: AlertRule[];
  firedThisSession: Set<string>;
}

export interface AlertActions {
  addRule: (rule: Omit<AlertRule, 'id'>) => void;
  editRule: (id: string, updates: Partial<AlertRule>) => void;
  deleteRule: (id: string) => void;
  resetSession: () => void;
  markFired: (id: string) => void;
}

export type AlertStore = AlertState & AlertActions;

/**
 * Evaluate whether a rule's threshold has been crossed.
 * Pure function — no side effects.
 */
export function evaluateRule(
  rule: AlertRule,
  realizedPnl: number,
  unrealizedPnl: number,
  capital: number,
): boolean {
  if (!rule.enabled) return false;
  const totalPnl = realizedPnl + unrealizedPnl;
  const pctPnl = capital > 0 ? (totalPnl / capital) * 100 : 0;

  switch (rule.type) {
    case 'absolute_profit':
      return totalPnl >= rule.threshold;
    case 'absolute_loss':
      return totalPnl <= -rule.threshold;
    case 'percent_profit':
      return pctPnl >= rule.threshold;
    case 'percent_loss':
      return pctPnl <= -rule.threshold;
    default:
      return false;
  }
}

const initialRules = loadRules();
const initialFired = loadFired();

export const useAlertStore = create<AlertStore>((set, get) => ({
  rules: initialRules,
  firedThisSession: initialFired,

  addRule: (rule) => {
    const newRule: AlertRule = { ...rule, id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}` };
    set((state) => {
      const updated = [...state.rules, newRule];
      persistRules(updated);
      return { rules: updated };
    });
  },

  editRule: (id, updates) => {
    set((state) => {
      const updated = state.rules.map((r) => (r.id === id ? { ...r, ...updates } : r));
      persistRules(updated);
      return { rules: updated };
    });
  },

  deleteRule: (id) => {
    set((state) => {
      const updated = state.rules.filter((r) => r.id !== id);
      persistRules(updated);
      return { rules: updated };
    });
  },

  resetSession: () => {
    const fired = new Set<string>();
    persistFired(fired);
    set({ firedThisSession: fired });
  },

  markFired: (id) => {
    set((state) => {
      const fired = new Set(state.firedThisSession);
      fired.add(id);
      persistFired(fired);
      return { firedThisSession: fired };
    });
  },
}));
