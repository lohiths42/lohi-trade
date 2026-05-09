import { useEffect, useRef } from 'react';
import { useOrdersStore } from '../stores/orders-store';
import { useSound } from './use-sound';
import type { Order } from '../lib/types';

/**
 * useOrderSoundCues — plays audio cues on order status transitions.
 *
 * Subscribes to the orders store and plays:
 *   • 'fill'   when an order transitions into FILLED
 *   • 'reject' when an order transitions into REJECTED or CANCELLED
 *
 * The user must opt in via Settings (writes `lohi.sound` in localStorage),
 * otherwise useSound's `play()` is a no-op. Safe to mount in App.
 */
export function useOrderSoundCues(): void {
  const { play } = useSound();
  const prevRef = useRef<Record<string, Order['status']>>({});

  useEffect(() => {
    // Subscribe directly to the store so updates don't force App to re-render.
    return useOrdersStore.subscribe((state) => {
      const prev = prevRef.current;
      const next: Record<string, Order['status']> = {};

      for (const order of state.orders) {
        next[order.orderId] = order.status;
        const was = prev[order.orderId];
        if (!was || was === order.status) continue;

        if (order.status === 'FILLED') play('fill');
        else if (order.status === 'REJECTED' || order.status === 'CANCELLED') play('reject');
      }
      prevRef.current = next;
    });
  }, [play]);
}
