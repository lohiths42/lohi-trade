/**
 * Commander Zustand store.
 *
 * Holds bias data and news articles, reacts to real-time bias and signal updates.
 *
 * Requirements: 3.3
 */

import { create } from 'zustand';
import type { Bias, BiasUpdate, NewsArticle } from '../lib/types';
import { on } from '../lib/websocket-client';

export interface CommanderState {
  bias: Bias[];
  news: NewsArticle[];
}

export interface CommanderActions {
  setBias: (bias: Bias[]) => void;
  updateBias: (update: BiasUpdate) => void;
  setNews: (news: NewsArticle[]) => void;
}

export type CommanderStore = CommanderState & CommanderActions;

export const useCommanderStore = create<CommanderStore>((set) => ({
  // ── State ───────────────────────────────────────────────────────────
  bias: [],
  news: [],

  // ── Actions ─────────────────────────────────────────────────────────
  setBias: (bias: Bias[]) => set({ bias }),

  updateBias: (update: BiasUpdate) =>
    set((state) => ({
      bias: state.bias.map((b) =>
        b.ticker === update.ticker
          ? { ...b, bias: update.bias, score: update.score, confidence: update.confidence }
          : b,
      ),
    })),

  setNews: (news: NewsArticle[]) => set({ news }),
}));

// ─── WebSocket Subscriptions ────────────────────────────────────────────────

/** Call once at app startup to wire WebSocket events into the store. */
export function initCommanderSubscriptions(): void {
  on('bias_update', (update) => {
    useCommanderStore.getState().updateBias(update);
  });

  on('signal_generated', (_signal) => {
    // Signal events can be consumed here for commander-level state
    // (e.g. recent signals list). Currently a no-op — extend as needed.
  });
}
