/**
 * Trading mode store — single source of truth for PAPER vs LIVE.
 *
 * Per the build spec:
 *   • Always starts in PAPER mode
 *   • Switching to LIVE requires a 3-step activation modal
 *   • Kill-switch state is mirrored here for banner-level display
 *
 * The actual enable/disable flow calls the backend (which gates on
 * paper-session history + 2FA + typed confirmation phrase); the store
 * only reflects the server's authoritative state.
 */
import { create } from 'zustand';

export type TradingMode = 'PAPER' | 'LIVE';

interface TradingModeState {
  mode: TradingMode;
  killSwitchActive: boolean;
  paperSessionsCompleted: number;
  /** Set by backend in response to successful activation modal. */
  setMode: (mode: TradingMode) => void;
  setKillSwitch: (active: boolean) => void;
  setPaperSessionsCompleted: (n: number) => void;
}

export const useTradingModeStore = create<TradingModeState>((set) => ({
  mode: 'PAPER',
  killSwitchActive: false,
  paperSessionsCompleted: 0,
  setMode: (mode) => set({ mode }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setPaperSessionsCompleted: (paperSessionsCompleted) => set({ paperSessionsCompleted }),
}));
