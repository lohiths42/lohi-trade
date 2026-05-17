/**
 * Reusable error state component with optional retry button.
 * Validates: Requirements 3.6
 */

import { AlertCircle, RefreshCw } from 'lucide-react';
import { useThemeColors } from '../../hooks/use-theme-colors';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  detail?: string;
}

export default function ErrorState({ message, onRetry, detail }: ErrorStateProps) {
  const t = useThemeColors();
  return (
    <div style={{
      background: t.bgCard, border: '1px solid rgba(220,38,38,0.3)',
      borderRadius: 12, padding: 32, display: 'flex', flexDirection: 'column',
      alignItems: 'center', textAlign: 'center',
    }}>
      <AlertCircle size={36} color="#f87171" style={{ marginBottom: 12 }} />
      <p style={{ color: '#f87171', fontSize: 14, fontWeight: 500 }}>{message}</p>
      {detail && <p style={{ fontSize: 12, color: t.textMuted, marginTop: 4 }}>{detail}</p>}
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginTop: 16, display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 16px', background: t.isLight ? '#f1f5f9' : '#1e293b',
            border: `1px solid ${t.borderSecondary}`, borderRadius: 8,
            fontSize: 13, color: t.textSecondary, cursor: 'pointer',
            transition: 'background 0.15s',
          }}
        >
          <RefreshCw size={14} />
          <span>Retry</span>
        </button>
      )}
    </div>
  );
}
