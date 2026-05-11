/**
 * React hook for managing the Socket.IO WebSocket lifecycle.
 *
 * On mount: connects the socket and initializes all store subscriptions.
 * On unmount: disconnects the socket.
 * Tracks and returns the current connection status.
 *
 * Uses a module-level flag to ensure subscriptions are only initialized once,
 * even if multiple components use this hook.
 *
 * Validates: Requirements 3.4
 */

import { useEffect, useState } from 'react';
import { ws } from '../lib/websocket-client';
import type { ConnectionStatus } from '../lib/websocket-client';
import { initDashboardSubscriptions } from '../stores/dashboard-store';
import { initPositionSubscriptions } from '../stores/positions-store';
import { initOrderSubscriptions } from '../stores/orders-store';
import { initCommanderSubscriptions } from '../stores/commander-store';
import { showToast } from '../components/shared/Toast';

let subscriptionsInitialized = false;

function initToastSubscriptions(): void {
  ws.on('order_update', (update) => {
    if (update.status === 'FILLED') {
      showToast('success', `Order ${update.orderId.slice(0, 8)}… filled (${update.filledQty} qty)`);
    } else if (update.status === 'REJECTED') {
      showToast('error', `Order ${update.orderId.slice(0, 8)}… rejected`);
    } else if (update.status === 'CANCELLED') {
      showToast('info', `Order ${update.orderId.slice(0, 8)}… cancelled`);
    }
  });

  ws.on('kill_switch_toggle', (payload) => {
    if (payload.active) {
      showToast('error', 'KILL SWITCH ACTIVATED — all trading halted');
    } else {
      showToast('success', 'Kill switch deactivated — trading resumed');
    }
  });

  ws.on('signal_generated', (signal) => {
    showToast('info', `Signal: ${signal.side} ${signal.symbol} @ ₹${signal.price.toFixed(2)} (${signal.strategy.replace(/_/g, ' ')})`);
  });
}

export function useWebSocket() {
  const [status, setStatus] = useState<ConnectionStatus>(ws.getStatus());

  useEffect(() => {
    // Initialize store subscriptions exactly once
    if (!subscriptionsInitialized) {
      initDashboardSubscriptions();
      initPositionSubscriptions();
      initOrderSubscriptions();
      initCommanderSubscriptions();
      initToastSubscriptions();
      subscriptionsInitialized = true;
    }

    ws.connect();

    const unsubscribe = ws.onStatusChange(setStatus);

    return () => {
      unsubscribe();
      ws.disconnect();
    };
  }, []);

  return { status };
}
