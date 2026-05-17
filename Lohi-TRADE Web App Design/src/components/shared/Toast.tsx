import { useState, useEffect, useCallback } from 'react';
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { useNotificationStore } from '../../stores/notification-store';
import { useThemeColors } from '../../hooks/use-theme-colors';
import type { Notification } from '../../lib/types';

export type ToastType = 'success' | 'warning' | 'error' | 'info';

interface ToastItem { id: number; type: ToastType; message: string; }

const ICONS = {
  success: <CheckCircle size={16} color="#34d399" />,
  warning: <AlertTriangle size={16} color="#fbbf24" />,
  error: <XCircle size={16} color="#f87171" />,
  info: <Info size={16} color="#60a5fa" />,
};

const BORDERS = {
  success: '1px solid rgba(52,211,153,0.3)',
  warning: '1px solid rgba(251,191,36,0.3)',
  error: '1px solid rgba(248,113,113,0.3)',
  info: '1px solid rgba(96,165,250,0.3)',
};

let toastId = 0;
let addToastFn: ((type: ToastType, message: string) => void) | null = null;

const TOAST_TO_NOTIFICATION_TYPE: Record<ToastType, Notification['type']> = {
  success: 'trade', error: 'system', warning: 'system', info: 'user',
};

export function showToast(type: ToastType, message: string) {
  addToastFn?.(type, message);
  useNotificationStore.getState().addNotification({
    type: TOAST_TO_NOTIFICATION_TYPE[type], message, timestamp: Date.now(),
  });
}

export default function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const t = useThemeColors();

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = ++toastId;
    setToasts((prev) => [...prev.slice(-4), { id, type, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((ti) => ti.id !== id)), 4000);
  }, []);

  useEffect(() => { addToastFn = addToast; return () => { addToastFn = null; }; }, [addToast]);

  const dismiss = (id: number) => setToasts((prev) => prev.filter((ti) => ti.id !== id));

  if (toasts.length === 0) return null;

  return (
    <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 200, display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 360 }}>
      {toasts.map((ti) => (
        <div key={ti.id} style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
          background: t.bgCard, border: BORDERS[ti.type], borderRadius: 10,
          boxShadow: t.cardShadow, animation: 'slideIn 0.2s ease-out',
        }}>
          {ICONS[ti.type]}
          <span style={{ flex: 1, fontSize: 12, color: t.textPrimary, lineHeight: 1.4 }}>{ti.message}</span>
          <button onClick={() => dismiss(ti.id)} style={{ padding: 2, background: 'none', border: 'none', cursor: 'pointer', color: t.textMuted }}><X size={12} /></button>
        </div>
      ))}
      <style>{`@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }`}</style>
    </div>
  );
}
