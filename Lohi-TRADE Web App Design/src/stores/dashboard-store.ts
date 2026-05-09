/**
 * Dashboard Zustand store.
 *
 * Holds aggregate P&L, trade stats, health status, and kill-switch state.
 * Subscribes to price_tick and kill_switch_toggle WebSocket events.
 *
 * Requirements: 3.3
 */

import { create } from 'zustand';
import type { HealthStatus, PriceTick } from '../lib/types';
import { on } from '../lib/websocket-client';

export interface DashboardState {
  totalPnl: number;
  realizedPnl: number;
  unrealizedPnl: number;
  tradesCount: number;
  winRate: number;
  health: HealthStatus | null;
  killSwitchActive: boolean;
}

export interface DashboardActions {
  updateFromTick: (tick: PriceTick) => void;
  toggleKillSwitch: () => void;
  setHealth: (health: HealthStatus) => void;
  setKillSwitchActive: (active: boolean) => void;
}

export type DashboardStore = DashboardState & DashboardActions;

export const useDashboardStore = create<DashboardStore>((set) => ({
  // ── State ───────────────────────────────────────────────────────────
  totalPnl: 0,
  realizedPnl: 0,
  unrealizedPnl: 0,
  tradesCount: 0,
  winRate: 0,
  health: null,
  killSwitchActive: false,

  // ── Actions ─────────────────────────────────────────────────────────
  updateFromTick: (_tick: PriceTick) => {
    // Tick-driven P&L recalculation is handled at the positions level;
    // the dashboard simply recomputes totals when positions change.
    // This action is a placeholder for any dashboard-specific tick logic.
  },

  toggleKillSwitch: () =>
    set((state) => ({ killSwitchActive: !state.killSwitchActive })),

  setHealth: (health: HealthStatus) => set({ health }),

  setKillSwitchActive: (active: boolean) => set({ killSwitchActive: active }),
}));

// ─── WebSocket Subscriptions ────────────────────────────────────────────────

/** Call once at app startup to wire WebSocket events into the store. */
export function initDashboardSubscriptions(): void {
  on('price_tick', (tick) => {
    useDashboardStore.getState().updateFromTick(tick);
  });

  on('kill_switch_toggle', (payload) => {
    useDashboardStore.getState().setKillSwitchActive(payload.active);
  });
}
