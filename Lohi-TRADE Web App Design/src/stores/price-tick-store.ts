/**
 * Price tick store — accumulates last 50 price ticks per symbol.
 */

import { create } from 'zustand';

const MAX_TICKS = 50;

export interface PriceTickState {
  ticks: Record<string, number[]>;
  lastPrices: Record<string, number>;
  openPrices: Record<string, number>;
}

export interface PriceTickActions {
  addTick: (symbol: string, price: number) => void;
  setOpenPrice: (symbol: string, price: number) => void;
}

export type PriceTickStore = PriceTickState & PriceTickActions;

export const usePriceTickStore = create<PriceTickStore>((set) => ({
  ticks: {},
  lastPrices: {},
  openPrices: {},

  addTick: (symbol, price) => {
    set((state) => {
      const existing = state.ticks[symbol] || [];
      const updated = [...existing, price].slice(-MAX_TICKS);
      return {
        ticks: { ...state.ticks, [symbol]: updated },
        lastPrices: { ...state.lastPrices, [symbol]: price },
      };
    });
  },

  setOpenPrice: (symbol, price) => {
    set((state) => ({
      openPrices: { ...state.openPrices, [symbol]: price },
    }));
  },
}));
