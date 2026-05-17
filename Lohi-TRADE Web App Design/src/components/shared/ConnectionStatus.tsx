/**
 * WebSocket connection status indicator for the header bar.
 * Validates: Requirements 2.5, 3.5
 */

import { useThemeColors } from '../../hooks/use-theme-colors';
import type { ConnectionStatus as Status } from '../../lib/websocket-client';

interface ConnectionStatusProps { status: Status; }

const STATUS_CONFIG: Record<Status, { dot: string; label: string }> = {
  connected: { dot: 'bg-emerald-500', label: 'Connected' },
  reconnecting: { dot: 'bg-amber-500', label: 'Reconnecting' },
  disconnected: { dot: 'bg-red-500', label: 'Disconnected' },
};

export default function ConnectionStatus({ status }: ConnectionStatusProps) {
  const { dot, label } = STATUS_CONFIG[status];
  const t = useThemeColors();

  return (
    <div
      className="flex items-center space-x-2 text-xs font-mono px-3 py-1.5 rounded"
      style={{ background: t.isLight ? '#f1f5f9' : '#1e293b', border: `1px solid ${t.borderPrimary}` }}
    >
      <div className={`w-2 h-2 rounded-full ${dot} animate-pulse`} />
      <span style={{ color: t.textSecondary }} className="uppercase">{label}</span>
    </div>
  );
}
