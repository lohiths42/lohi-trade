/**
 * Orders Zustand store.
 *
 * Holds the orders array and filter state, reacts to real-time order updates.
 *
 * Requirements: 3.3
 */

import { create } from 'zustand';
import type { Order, OrderUpdate } from '../lib/types';
import { on } from '../lib/websocket-client';

export interface OrderFilters {
  status?: string;
  symbol?: string;
}

export interface OrdersState {
  orders: Order[];
  filters: OrderFilters;
}

export interface OrdersActions {
  setOrders: (orders: Order[]) => void;
  updateOrder: (update: OrderUpdate) => void;
  setFilters: (filters: OrderFilters) => void;
}

export type OrdersStore = OrdersState & OrdersActions;

export const useOrdersStore = create<OrdersStore>((set) => ({
  // ── State ───────────────────────────────────────────────────────────
  orders: [],
  filters: {},

  // ── Actions ─────────────────────────────────────────────────────────
  setOrders: (orders: Order[]) => set({ orders }),

  updateOrder: (update: OrderUpdate) =>
    set((state) => ({
      orders: state.orders.map((o) =>
        o.orderId === update.orderId
          ? { ...o, status: update.status, filledQty: update.filledQty }
          : o,
      ),
    })),

  setFilters: (filters: OrderFilters) => set({ filters }),
}));

// ─── WebSocket Subscriptions ────────────────────────────────────────────────

/** Call once at app startup to wire WebSocket events into the store. */
export function initOrderSubscriptions(): void {
  on('order_update', (update) => {
    useOrdersStore.getState().updateOrder(update);
  });
}
