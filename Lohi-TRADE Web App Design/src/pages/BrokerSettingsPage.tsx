import { useState, useEffect } from 'react';
import {
  Wifi, WifiOff, AlertTriangle, Loader2, Star, StarOff,
  Link2, Unplug, Shield, RefreshCw,
} from 'lucide-react';
import { useThemeColors } from '../hooks/use-theme-colors';
import { api } from '../lib/api-client';
import PageHeader from '../components/shared/PageHeader';
import type { BrokerStatusItem, BrokerConnectionStatus } from '../lib/types';

/* ─── Broker metadata ────────────────────────────────────────────────────── */

interface BrokerMeta {
  name: string;
  displayName: string;
  description: string;
  color: string;
}

const BROKERS: BrokerMeta[] = [
  { name: 'shoonya', displayName: 'Shoonya', description: 'Finvasia / Shoonya — zero brokerage', color: '#10b981' },
  { name: 'angelone', displayName: 'Angel One', description: 'Angel One — SmartAPI integration', color: '#f59e0b' },
  { name: 'kite', displayName: 'Kite', description: 'Zerodha Kite Connect v3', color: '#ef4444' },
  { name: 'groww', displayName: 'Groww', description: 'Groww trading API', color: '#6366f1' },
];

/* ─── Status helpers ─────────────────────────────────────────────────────── */

function statusLabel(s: BrokerConnectionStatus): string {
  if (s === 'connected') return 'Connected';
  if (s === 'token_expired') return 'Token Expired';
  return 'Disconnected';
}

function statusColor(s: BrokerConnectionStatus): string {
  if (s === 'connected') return 'var(--bull)';
  if (s === 'token_expired') return 'var(--warn)';
  return 'var(--fg-muted)';
}

function StatusIcon({ status }: { status: BrokerConnectionStatus }) {
  if (status === 'connected') return <Wifi size={14} color="var(--bull)" />;
  if (status === 'token_expired') return <AlertTriangle size={14} color="var(--warn)" />;
  return <WifiOff size={14} color="var(--fg-muted)" />;
}

/* ─── Page ───────────────────────────────────────────────────────────────── */

export default function BrokerSettingsPage() {
  const t = useThemeColors();
  const [statuses, setStatuses] = useState<Record<string, BrokerConnectionStatus>>({});
  const [primaryBroker, setPrimaryBroker] = useState<string | null>(null);
  const [backupBroker, setBackupBroker] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');

  const card: React.CSSProperties = {
    background: t.bgCardGradient,
    border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16,
  };

  useEffect(() => { loadStatuses(); }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  async function loadStatuses() {
    setLoading(true);
    setError('');
    try {
      const res = await api.getBrokersStatus();
      const map: Record<string, BrokerConnectionStatus> = {};
      res.brokers.forEach((b: BrokerStatusItem) => { map[b.name] = b.status; });
      setStatuses(map);

      // Infer primary/backup from connected brokers (the API doesn't return preference in status)
      // We'll keep local state; setPrimary/setBackup calls update it
    } catch (e: any) {
      setError(e?.detail || e?.message || 'Failed to load broker status');
    } finally {
      setLoading(false);
    }
  }

  async function handleConnect(brokerName: string) {
    setActionLoading(brokerName);
    try {
      await api.connectBroker(brokerName);
      setToast(`${brokerName} connected successfully`);
      await loadStatuses();
    } catch (e: any) {
      setToast(e?.detail || e?.message || `Failed to connect ${brokerName}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDisconnect(brokerName: string) {
    setActionLoading(brokerName);
    try {
      await api.disconnectBroker(brokerName);
      setToast(`${brokerName} disconnected`);
      if (primaryBroker === brokerName) setPrimaryBroker(null);
      if (backupBroker === brokerName) setBackupBroker(null);
      await loadStatuses();
    } catch (e: any) {
      setToast(e?.detail || e?.message || `Failed to disconnect ${brokerName}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSetPrimary(brokerName: string) {
    setActionLoading(`primary-${brokerName}`);
    try {
      const res = await api.setPrimaryBroker(brokerName);
      setPrimaryBroker(res.primary_broker);
      setBackupBroker(res.backup_broker);
      setToast(`${brokerName} set as primary broker`);
    } catch (e: any) {
      setToast(e?.detail || e?.message || 'Failed to set primary broker');
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSetBackup(brokerName: string) {
    setActionLoading(`backup-${brokerName}`);
    try {
      const res = await api.setBackupBroker(brokerName);
      setPrimaryBroker(res.primary_broker);
      setBackupBroker(res.backup_broker);
      setToast(`${brokerName} set as backup broker`);
    } catch (e: any) {
      setToast(e?.detail || e?.message || 'Failed to set backup broker');
    } finally {
      setActionLoading(null);
    }
  }

  const isConnected = (name: string) => statuses[name] === 'connected';

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <PageHeader
        icon={<Link2 size={16} />}
        title="Broker Management"
        subtitle="Connect and manage your broker accounts"
        actions={
          <button
            onClick={loadStatuses}
            disabled={loading}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 'var(--r-sm)',
              background: 'var(--surface-3)', border: '1px solid var(--line-2)', color: 'var(--fg-secondary)',
              fontSize: 11, fontWeight: 600, cursor: 'pointer',
            }}
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        }
      />

      <div style={{ height: 20 }} />

      {/* Error */}
      {error && (
        <div style={{
          ...card, padding: '12px 16px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
          borderColor: 'rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.06)',
        }}>
          <AlertTriangle size={16} color="#ef4444" />
          <span style={{ fontSize: 13, color: '#ef4444' }}>{error}</span>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !Object.keys(statuses).length ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 60 }}>
          <Loader2 size={24} className="animate-spin" color={t.textMuted} />
        </div>
      ) : (
        /* Broker cards */
        <div style={{ display: 'grid', gap: 16 }}>
          {BROKERS.map((broker) => {
            const status = statuses[broker.name] || 'disconnected';
            const connected = isConnected(broker.name);
            const isPrimary = primaryBroker === broker.name;
            const isBackup = backupBroker === broker.name;
            const isActioning = actionLoading === broker.name
              || actionLoading === `primary-${broker.name}`
              || actionLoading === `backup-${broker.name}`;

            return (
              <div key={broker.name} style={{ ...card, padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                  {/* Left: broker info */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                    <div style={{
                      width: 44, height: 44, borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: `${broker.color}18`, border: `1px solid ${broker.color}30`,
                    }}>
                      <Shield size={20} color={broker.color} />
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary }}>{broker.displayName}</span>
                        {isPrimary && (
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
                            background: 'rgba(59,130,246,0.12)', color: '#60a5fa', letterSpacing: '0.05em',
                          }}>PRIMARY</span>
                        )}
                        {isBackup && (
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
                            background: 'rgba(251,191,36,0.12)', color: '#fbbf24', letterSpacing: '0.05em',
                          }}>BACKUP</span>
                        )}
                      </div>
                      <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0' }}>{broker.description}</p>
                    </div>
                  </div>

                  {/* Right: status + actions */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    {/* Status pill */}
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 8,
                      background: `${statusColor(status)}10`, border: `1px solid ${statusColor(status)}25`,
                    }}>
                      <StatusIcon status={status} />
                      <span style={{ fontSize: 11, fontWeight: 700, color: statusColor(status), letterSpacing: '0.04em' }}>
                        {statusLabel(status)}
                      </span>
                    </div>

                    {/* Connect / Disconnect */}
                    {connected || status === 'token_expired' ? (
                      <button
                        onClick={() => handleDisconnect(broker.name)}
                        disabled={isActioning}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px', borderRadius: 8,
                          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                          color: '#f87171', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        }}
                      >
                        {isActioning && actionLoading === broker.name ? <Loader2 size={13} className="animate-spin" /> : <Unplug size={13} />}
                        Disconnect
                      </button>
                    ) : (
                      <button
                        onClick={() => handleConnect(broker.name)}
                        disabled={isActioning}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px', borderRadius: 8,
                          background: `${broker.color}14`, border: `1px solid ${broker.color}30`,
                          color: broker.color, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        }}
                      >
                        {isActioning && actionLoading === broker.name ? <Loader2 size={13} className="animate-spin" /> : <Link2 size={13} />}
                        Connect
                      </button>
                    )}

                    {/* Set Primary */}
                    {connected && !isPrimary && (
                      <button
                        onClick={() => handleSetPrimary(broker.name)}
                        disabled={isActioning}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 8,
                          background: t.accentBg, border: `1px solid ${t.borderPrimary}`,
                          color: t.accentText, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        }}
                        title="Set as primary broker"
                      >
                        {isActioning && actionLoading === `primary-${broker.name}` ? <Loader2 size={13} className="animate-spin" /> : <Star size={13} />}
                        Primary
                      </button>
                    )}

                    {/* Set Backup */}
                    {connected && !isBackup && primaryBroker !== broker.name && (
                      <button
                        onClick={() => handleSetBackup(broker.name)}
                        disabled={isActioning}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 8,
                          background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)',
                          color: '#fbbf24', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        }}
                        title="Set as backup broker"
                      >
                        {isActioning && actionLoading === `backup-${broker.name}` ? <Loader2 size={13} className="animate-spin" /> : <StarOff size={13} />}
                        Backup
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="lt-glass" style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 100,
          padding: '12px 20px', borderRadius: 'var(--r-md)',
          color: 'var(--fg-primary)',
          fontSize: 13, fontWeight: 600,
          boxShadow: 'var(--elev-3), 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent)',
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}
