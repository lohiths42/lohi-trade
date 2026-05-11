/**
 * Positions Zustand store.
 *
 * Holds the array of open positions and reacts to real-time position updates.
 *
 * Requirements: 3.3
 */

import { create } from 'zustand';
import type { Position, PositionUpdate } from '../lib/types';
import { on } from '../lib/websocket-client';

export interface PositionsState {
  positions: Position[];
}

export interface PositionsActions {
  setPositions: (positions: Position[]) => void;
  updatePosition: (update: PositionUpdate) => void;
  removePosition: (id: number) => void;
}

export type PositionsStore = PositionsState & PositionsActions;

export const usePositionsStore = create<PositionsStore>((set) => ({
  // ── State ───────────────────────────────────────────────────────────
  positions: [],

  // ── Actions ─────────────────────────────────────────────────────────
  setPositions: (positions: Position[]) => set({ positions }),

  updatePosition: (update: PositionUpdate) =>
    set((state) => ({
      positions: state.positions.map((p) =>
        p.id === update.id
          ? { ...p, currentPrice: update.currentPrice, pnl: update.pnl }
          : p,
      ),
    })),

  removePosition: (id: number) =>
    set((state) => ({
      positions: state.positions.filter((p) => p.id !== id),
    })),
}));

// ─── WebSocket Subscriptions ────────────────────────────────────────────────

/** Call once at app startup to wire WebSocket events into the store. */
export function initPositionSubscriptions(): void {
  on('position_update', (update) => {
    usePositionsStore.getState().updatePosition(update);
  });
}
