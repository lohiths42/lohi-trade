/**
 * P&L Alert Engine hook.
 * Evaluates alert rules against current P&L and fires notifications.
 */

import { useEffect, useCallback } from 'react';
import { useAlertStore, evaluateRule } from '../stores/alert-store';
import { useNotificationStore } from '../stores/notification-store';
import { showToast } from '../components/shared/Toast';

export function usePnlAlerts(
  realizedPnl: number,
  unrealizedPnl: number,
  capital: number,
  wsConnected: boolean,
) {
  const rules = useAlertStore((s) => s.rules);
  const firedThisSession = useAlertStore((s) => s.firedThisSession);
  const markFired = useAlertStore((s) => s.markFired);

  const evaluate = useCallback(() => {
    if (!wsConnected) return; // Pause during disconnection

    for (const rule of rules) {
      if (firedThisSession.has(rule.id)) continue;
      if (evaluateRule(rule, realizedPnl, unrealizedPnl, capital)) {
        markFired(rule.id);
        const msg = `P&L Alert: ${rule.type.replace(/_/g, ' ')} threshold (${rule.threshold}) crossed`;
        showToast(msg, 'warning');
      }
    }
  }, [rules, firedThisSession, realizedPnl, unrealizedPnl, capital, wsConnected, markFired]);

  useEffect(() => {
    evaluate();
  }, [evaluate]);
}
