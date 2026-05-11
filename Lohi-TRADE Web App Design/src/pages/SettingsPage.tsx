import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Settings, Save, CheckCircle, XCircle, Link2, Unplug, Loader2,
  AlertTriangle, RotateCcw, Shield, Clock, Zap,
  ChevronRight, ChevronDown, DollarSign, Sliders, Volume2, VolumeX, Smartphone,
  Search, Wallet, Sparkles, Eye, EyeOff, SkipForward, Info, Bell,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { api } from '../lib/api-client';
import { useThemeColors } from '../hooks/use-theme-colors';
import type { Config } from '../lib/types';
import { useOnboarding } from '../hooks/use-onboarding';
import { useSound } from '../hooks/use-sound';
import { isMobileOrdersAllowed, setMobileOrdersAllowed } from '../components/shared/MobileOrderGuard';
import { useSetupStore } from '../stores/setup-store';
import { CREDENTIAL_GROUPS } from '../lib/setup-types';
import type { ServiceStatus, TestResult, CredentialGroupDef } from '../lib/setup-types';

type Toast = { type: 'success' | 'error'; message: string } | null;
type TabId = 'general' | 'risk' | 'strategies' | 'broker' | 'system';

interface ValidationErrors { [key: string]: string; }

function validate(config: Config): ValidationErrors {
  const errors: ValidationErrors = {};
  if (!config.broker?.primary) errors['broker.primary'] = 'Primary broker is required';
  if (config.capital?.total == null || config.capital.total <= 0)
    errors['capital.total'] = 'Total capital must be greater than 0';
  if (config.capital?.risk_per_trade_pct == null || config.capital.risk_per_trade_pct <= 0 || config.capital.risk_per_trade_pct > 100)
    errors['capital.risk_per_trade_pct'] = 'Risk per trade must be between 0 and 100';
  if (config.capital?.max_position_size_pct == null || config.capital.max_position_size_pct <= 0 || config.capital.max_position_size_pct > 100)
    errors['capital.max_position_size_pct'] = 'Max position size must be between 0 and 100';
  if (config.capital?.max_daily_loss_pct == null || config.capital.max_daily_loss_pct <= 0 || config.capital.max_daily_loss_pct > 100)
    errors['capital.max_daily_loss_pct'] = 'Max daily loss must be between 0 and 100';
  if (config.risk_limits?.max_open_positions == null || config.risk_limits.max_open_positions < 1)
    errors['risk_limits.max_open_positions'] = 'Must allow at least 1 open position';
  if (config.risk_limits?.max_orders_per_day == null || config.risk_limits.max_orders_per_day < 1)
    errors['risk_limits.max_orders_per_day'] = 'Must allow at least 1 order per day';
  return errors;
}

function FieldError({ error }: { error?: string }) {
  if (!error) return null;
  return (
    <p style={{
      fontSize: 11, color: 'var(--bear)', margin: '6px 0 0', fontWeight: 500,
      display: 'inline-flex', alignItems: 'center', gap: 4,
    }}>
      <AlertTriangle size={11} /> {error}
    </p>
  );
}

/* ─── Tab definitions ────────────────────────────────────────────────── */
const TABS: {
  id: TabId; label: string; icon: typeof Settings;
  description: string; accent: string;
}[] = [
  { id: 'general', label: 'General', icon: Settings, description: 'Brokers & hours', accent: 'var(--accent-2)' },
  { id: 'risk', label: 'Risk & Capital', icon: Shield, description: 'Capital & limits', accent: 'var(--bull)' },
  { id: 'strategies', label: 'Strategies', icon: Zap, description: 'Algo catalog', accent: 'var(--warn)' },
  { id: 'broker', label: 'Credentials', icon: Link2, description: 'API keys', accent: '#a78bfa' },
  { id: 'system', label: 'System', icon: Sliders, description: 'App preferences', accent: '#f472b6' },
];

/* ─── Strategy display metadata ─────────────────────────────────────── */
const STRATEGY_META: Record<string, { label: string; color: string; emoji: string }> = {
  mean_reversion:            { label: 'Mean Reversion',         color: '#60a5fa', emoji: '🎯' },
  trend_following:           { label: 'Trend Following',        color: '#a78bfa', emoji: '📈' },
  orb:                       { label: 'Opening Range Breakout', color: '#fbbf24', emoji: '🚀' },
  vwap_bounce:               { label: 'VWAP Bounce',            color: '#22d3ee', emoji: '🌊' },
  stochastic_rsi:            { label: 'Stochastic RSI',         color: '#f472b6', emoji: '📊' },
  adx_trend:                 { label: 'ADX Trend',              color: '#34d399', emoji: '💨' },
  bollinger_squeeze:         { label: 'Bollinger Squeeze',      color: '#fb923c', emoji: '🎈' },
  pivot_point:               { label: 'Pivot Point',            color: '#818cf8', emoji: '🎡' },
  ichimoku_cloud:            { label: 'Ichimoku Cloud',         color: '#c084fc', emoji: '☁️' },
  macd_divergence:           { label: 'MACD Divergence',        color: '#fb7185', emoji: '🔀' },
  parabolic_sar_trend:       { label: 'Parabolic SAR',          color: '#2dd4bf', emoji: '🎢' },
  volume_breakout:           { label: 'Volume Breakout',        color: '#a3e635', emoji: '💥' },
  multi_timeframe_momentum:  { label: 'Multi-TF Momentum',      color: '#38bdf8', emoji: '⏱️' },
};

/* ─── Shared style primitives ───────────────────────────────────────── */
const SETTINGS_INPUT: React.CSSProperties = {
  width: '100%',
  background: 'var(--surface-2)',
  border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-sm)',
  padding: '9px 12px',
  fontSize: 13,
  color: 'var(--fg-primary)',
  outline: 'none',
  transition: 'border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out)',
  fontFamily: 'inherit',
};

const SETTINGS_LABEL: React.CSSProperties = {
  display: 'block',
  fontSize: 10,
  color: 'var(--fg-muted)',
  margin: '0 0 6px',
  fontWeight: 700,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
};

function applyInputFocus(e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) {
  e.target.style.borderColor = 'color-mix(in srgb, var(--accent) 55%, var(--line-2))';
  e.target.style.boxShadow = '0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent)';
}
function applyInputBlur(e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) {
  e.target.style.borderColor = 'var(--line-2)';
  e.target.style.boxShadow = 'none';
}

const gridAuto: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
  gap: 14,
};

/* ═══════════════════════════════════════════════════════════════════════
   Page
   ═══════════════════════════════════════════════════════════════════════ */
export default function SettingsPage() {
  useThemeColors();
  const { resetOnboarding } = useOnboarding();
  const [tutorialToast, setTutorialToast] = useState(false);
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [activeTab, setActiveTab] = useState<TabId>('general');
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string; message: string; onConfirm: () => void;
  } | null>(null);
  const prevCapitalRef = useRef<number | null>(null);
  const prevRiskRef = useRef<number | null>(null);
  const [expandedStrategy, setExpandedStrategy] = useState<string | null>(null);
  const [strategyFilter, setStrategyFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [strategySearch, setStrategySearch] = useState('');

  useEffect(() => {
    api.getConfig().then((data) => {
      setConfig(data);
      prevCapitalRef.current = data.capital?.total ?? null;
      prevRiskRef.current = data.capital?.max_daily_loss_pct ?? null;
      setLoading(false);
    }).catch(() => {
      setToast({ type: 'error', message: 'Failed to load configuration' });
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  const doSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.updateConfig(config);
      prevCapitalRef.current = config.capital.total;
      prevRiskRef.current = config.capital.max_daily_loss_pct;
      setToast({ type: 'success', message: 'Configuration saved successfully' });
    } catch {
      setToast({ type: 'error', message: 'Failed to save configuration' });
    } finally { setSaving(false); }
  };

  const handleSave = async () => {
    if (!config) return;
    const validationErrors = validate(config);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    const capitalChanged = prevCapitalRef.current !== null && config.capital.total !== prevCapitalRef.current;
    const riskChanged = prevRiskRef.current !== null && config.capital.max_daily_loss_pct !== prevRiskRef.current;

    if (capitalChanged || riskChanged) {
      const changes: string[] = [];
      if (capitalChanged) changes.push(`Capital: ₹${prevCapitalRef.current?.toLocaleString()} → ₹${config.capital.total.toLocaleString()}`);
      if (riskChanged) changes.push(`Max Daily Loss: ${prevRiskRef.current}% → ${config.capital.max_daily_loss_pct}%`);
      setConfirmDialog({
        title: 'Critical Settings Change',
        message: `You are modifying risk-critical parameters:\n\n${changes.join('\n')}\n\nThis will take effect immediately. Are you sure?`,
        onConfirm: () => { setConfirmDialog(null); doSave(); },
      });
      return;
    }
    doSave();
  };

  const updateCapital = (field: string, value: number) => {
    if (!config) return;
    setConfig({ ...config, capital: { ...config.capital, [field]: value } });
  };
  const updateRiskLimits = (field: string, value: number) => {
    if (!config) return;
    setConfig({ ...config, risk_limits: { ...config.risk_limits, [field]: value } });
  };
  const updateBroker = (field: string, value: string) => {
    if (!config) return;
    setConfig({ ...config, broker: { ...config.broker, [field]: value } });
  };
  const updateTradingHours = (field: string, value: string) => {
    if (!config) return;
    setConfig({ ...config, trading_hours: { ...config.trading_hours, [field]: value } });
  };

  /* ─── Loading state ─────────────────────────────────────────── */
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="lt-skeleton" style={{ height: 120, borderRadius: 'var(--r-lg)' }} />
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24 }}>
          <div className="lt-skeleton" style={{ height: 380, borderRadius: 'var(--r-lg)' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="lt-skeleton" style={{ height: 140, borderRadius: 'var(--r-lg)' }} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="lt-bento" style={{
        padding: 40, textAlign: 'center',
        borderColor: 'color-mix(in srgb, var(--bear) 30%, transparent)',
      }}>
        <AlertTriangle size={28} color="var(--bear)" style={{ margin: '0 auto 12px', display: 'block' }} />
        <p style={{ color: 'var(--bear)', fontSize: 14, margin: 0, fontWeight: 700 }}>
          Failed to load configuration
        </p>
        <p style={{ color: 'var(--fg-muted)', fontSize: 12, margin: '6px 0 0' }}>
          Try refreshing the page, or check your backend connection.
        </p>
      </div>
    );
  }

  const inputStyle = SETTINGS_INPUT;
  const labelStyle = SETTINGS_LABEL;
  const cardStyle: React.CSSProperties = {
    background: 'var(--surface-2)',
    border: '1px solid var(--line-2)',
    borderRadius: 'var(--r-lg)',
    padding: 22,
    boxShadow: 'var(--elev-1)',
  };

  const enabledCount = config.strategies
    ? Object.values(config.strategies).filter((s) => s.enabled !== false).length
    : 0;
  const totalStrategies = config.strategies
    ? Object.keys(config.strategies).length
    : 0;

  // Count configured fields to populate the hero's "integrity" meter.
  const integrity = (() => {
    let pct = 0;
    if (config.broker?.primary) pct += 20;
    if (config.capital?.total && config.capital.total > 0) pct += 25;
    if (enabledCount > 0) pct += 25;
    if (config.risk_limits?.max_open_positions) pct += 15;
    if (config.trading_hours?.market_open) pct += 15;
    return Math.min(100, pct);
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>

      {/* ── Hero ────────────────────────────────────────────────── */}
      <ConfigHero
        integrity={integrity}
        brokerPrimary={config.broker?.primary ?? '—'}
        capital={config.capital?.total ?? 0}
        enabledStrategies={enabledCount}
        totalStrategies={totalStrategies}
      />

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(240px, 260px) 1fr',
        gap: 24,
        alignItems: 'flex-start',
      }} className="settings-grid">
        {/* ── Sidebar ───────────────────────────────────────────── */}
        <aside style={{ position: 'sticky', top: 0, minWidth: 0 }}>
          <div className="lt-bento" style={{ padding: 14, overflow: 'hidden' }}>
            <div style={{
              padding: '4px 8px 10px', display: 'flex',
              alignItems: 'center', gap: 8,
            }}>
              <Sparkles size={12} color="var(--accent-2)" />
              <span style={{
                fontSize: 10, fontWeight: 800, letterSpacing: '0.14em',
                color: 'var(--fg-muted)', textTransform: 'uppercase',
              }}>
                Settings
              </span>
            </div>
            <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    style={{
                      position: 'relative',
                      width: '100%', textAlign: 'left',
                      display: 'flex', alignItems: 'center', gap: 11,
                      padding: '10px 12px', borderRadius: 'var(--r-sm)',
                      background: isActive
                        ? 'color-mix(in srgb, var(--accent) 12%, transparent)'
                        : 'transparent',
                      border: '1px solid transparent',
                      borderColor: isActive
                        ? 'color-mix(in srgb, var(--accent) 28%, transparent)'
                        : 'transparent',
                      cursor: 'pointer',
                      transition: 'all var(--dur-2) var(--ease-out)',
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.background = 'var(--surface-3)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    {isActive && (
                      <motion.span
                        layoutId="settings-active-rail"
                        style={{
                          position: 'absolute', left: -15, top: 8, bottom: 8, width: 3,
                          borderRadius: 2, background: tab.accent,
                          boxShadow: `0 0 10px color-mix(in srgb, ${tab.accent} 50%, transparent)`,
                        }}
                      />
                    )}
                    <span style={{
                      width: 30, height: 30, borderRadius: 'var(--r-sm)',
                      display: 'grid', placeItems: 'center', flexShrink: 0,
                      background: isActive
                        ? `color-mix(in srgb, ${tab.accent} 18%, transparent)`
                        : 'var(--surface-3)',
                      border: `1px solid ${isActive
                        ? `color-mix(in srgb, ${tab.accent} 35%, transparent)`
                        : 'var(--line-1)'}`,
                      color: isActive ? tab.accent : 'var(--fg-muted)',
                      transition: 'all var(--dur-2) var(--ease-out)',
                    }}>
                      <Icon size={14} strokeWidth={2.2} />
                    </span>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <p style={{
                        fontSize: 13, margin: 0,
                        fontWeight: isActive ? 700 : 500,
                        color: isActive ? 'var(--fg-primary)' : 'var(--fg-secondary)',
                      }}>
                        {tab.label}
                      </p>
                      <p style={{
                        fontSize: 10, color: 'var(--fg-muted)',
                        margin: '2px 0 0',
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      }}>
                        {tab.description}
                      </p>
                    </div>
                    {isActive && (
                      <ChevronRight size={12} style={{ color: tab.accent, flexShrink: 0 }} />
                    )}
                  </button>
                );
              })}
            </nav>

            <div style={{ height: 1, background: 'var(--line-2)', margin: '12px 2px' }} />

            {/* Save button in sidebar */}
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                padding: '11px 16px',
                background: saving ? 'var(--surface-4)' : 'var(--accent-gradient)',
                color: '#fff',
                border: 'none',
                borderRadius: 'var(--r-sm)',
                fontSize: 13, fontWeight: 700, letterSpacing: '0.02em',
                boxShadow: saving ? 'none' : '0 6px 18px var(--accent-glow)',
                opacity: saving ? 0.6 : 1,
                cursor: saving ? 'not-allowed' : 'pointer',
                transition: 'all var(--dur-2) var(--ease-out)',
              }}
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              <span>{saving ? 'Saving…' : 'Save Changes'}</span>
            </button>
            {Object.keys(errors).length > 0 && (
              <p style={{
                fontSize: 11, color: 'var(--bear)', margin: '10px 0 0',
                textAlign: 'center', fontWeight: 600,
              }}>
                {Object.keys(errors).length} field{Object.keys(errors).length === 1 ? '' : 's'} need attention
              </p>
            )}
          </div>
        </aside>

        {/* ── Content Area ─────────────────────────────────────── */}
        <div style={{
          minWidth: 0, display: 'flex', flexDirection: 'column', gap: 18,
        }}>
          {/* Toast */}
          <AnimatePresence>
            {toast && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '11px 16px', borderRadius: 'var(--r-sm)',
                  fontSize: 13, fontWeight: 600,
                  color: toast.type === 'success' ? 'var(--bull)' : 'var(--bear)',
                  background: toast.type === 'success' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                  border: `1px solid color-mix(in srgb, ${toast.type === 'success' ? 'var(--bull)' : 'var(--bear)'} 30%, transparent)`,
                }}
              >
                {toast.type === 'success' ? <CheckCircle size={16} /> : <XCircle size={16} />}
                <span>{toast.message}</span>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              style={{ display: 'flex', flexDirection: 'column', gap: 18 }}
            >
              {/* ── GENERAL TAB ──────────────────────────────── */}
              {activeTab === 'general' && (
                <>
                  <div style={cardStyle}>
                    <SectionTitle
                      icon={<Link2 size={15} />}
                      iconColor="var(--accent-2)"
                      title="Broker Selection"
                      subtitle="Pick which broker routes your orders by default. The backup steps in when the primary is down."
                    />
                    <div style={gridAuto}>
                      <div>
                        <label style={labelStyle}>Primary Broker</label>
                        <select
                          value={config.broker.primary}
                          onChange={(e) => updateBroker('primary', e.target.value)}
                          style={inputStyle}
                          onFocus={applyInputFocus}
                          onBlur={applyInputBlur}
                        >
                          <option value="shoonya">Shoonya</option>
                          <option value="angelone">Angel One</option>
                        </select>
                        <FieldError error={errors['broker.primary']} />
                      </div>
                      <div>
                        <label style={labelStyle}>Backup Broker</label>
                        <select
                          value={config.broker.backup}
                          onChange={(e) => updateBroker('backup', e.target.value)}
                          style={inputStyle}
                          onFocus={applyInputFocus}
                          onBlur={applyInputBlur}
                        >
                          <option value="shoonya">Shoonya</option>
                          <option value="angelone">Angel One</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  <div style={cardStyle}>
                    <SectionTitle
                      icon={<Clock size={15} />}
                      iconColor="var(--warn)"
                      title="Trading Hours"
                      subtitle="Windows that gate when strategies may open and close positions. All times IST (HH:MM)."
                    />
                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                      gap: 14,
                    }}>
                      {(['market_open', 'trading_start', 'trading_end', 'square_off_time', 'market_close'] as const).map((field) => (
                        <div key={field}>
                          <label style={labelStyle}>{field.replace(/_/g, ' ')}</label>
                          <input
                            type="text"
                            value={config.trading_hours[field]}
                            onChange={(e) => updateTradingHours(field, e.target.value)}
                            style={{ ...inputStyle, fontFamily: 'ui-monospace, monospace' }}
                            placeholder="HH:MM"
                            onFocus={applyInputFocus}
                            onBlur={applyInputBlur}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* ── RISK & CAPITAL TAB ──────────────────────── */}
              {activeTab === 'risk' && (
                <>
                  <div style={cardStyle}>
                    <SectionTitle
                      icon={<DollarSign size={15} />}
                      iconColor="var(--bull)"
                      title="Capital Allocation"
                      subtitle="These inputs drive every position sizing calculation."
                    />

                    {/* Live capital visualizer */}
                    <CapitalVisualizer
                      total={config.capital.total}
                      riskPerTrade={config.capital.risk_per_trade_pct}
                      maxPosition={config.capital.max_position_size_pct}
                      maxDailyLoss={config.capital.max_daily_loss_pct}
                    />

                    <div style={{ ...gridAuto, marginTop: 18 }}>
                      <NumberField
                        label="Total Capital (₹)"
                        value={config.capital.total}
                        onChange={(v) => updateCapital('total', v)}
                        error={errors['capital.total']}
                        min={0}
                        prefix="₹"
                      />
                      <PercentField
                        label="Risk Per Trade"
                        value={config.capital.risk_per_trade_pct}
                        onChange={(v) => updateCapital('risk_per_trade_pct', v)}
                        error={errors['capital.risk_per_trade_pct']}
                      />
                      <PercentField
                        label="Max Position Size"
                        value={config.capital.max_position_size_pct}
                        onChange={(v) => updateCapital('max_position_size_pct', v)}
                        error={errors['capital.max_position_size_pct']}
                      />
                      <PercentField
                        label="Max Daily Loss"
                        value={config.capital.max_daily_loss_pct}
                        onChange={(v) => updateCapital('max_daily_loss_pct', v)}
                        error={errors['capital.max_daily_loss_pct']}
                        danger
                      />
                    </div>
                  </div>

                  <div style={cardStyle}>
                    <SectionTitle
                      icon={<Shield size={15} />}
                      iconColor="var(--bear)"
                      title="Risk Limits"
                      subtitle="Hard ceilings the execution engine will never cross."
                    />
                    <div style={gridAuto}>
                      <NumberField
                        label="Max Open Positions"
                        value={config.risk_limits.max_open_positions}
                        onChange={(v) => updateRiskLimits('max_open_positions', v)}
                        error={errors['risk_limits.max_open_positions']}
                        min={1}
                      />
                      <NumberField
                        label="Max Orders Per Day"
                        value={config.risk_limits.max_orders_per_day}
                        onChange={(v) => updateRiskLimits('max_orders_per_day', v)}
                        error={errors['risk_limits.max_orders_per_day']}
                        min={1}
                      />
                      <NumberField
                        label="Cooldown After Loss (min)"
                        value={config.risk_limits.cooldown_after_loss_minutes}
                        onChange={(v) => updateRiskLimits('cooldown_after_loss_minutes', v)}
                        min={0}
                      />
                      <PercentField
                        label="Volatility Guard Threshold"
                        value={config.risk_limits.volatility_guard_threshold_pct}
                        onChange={(v) => updateRiskLimits('volatility_guard_threshold_pct', v)}
                      />
                    </div>
                  </div>
                </>
              )}

              {/* ── STRATEGIES TAB ──────────────────────────── */}
              {activeTab === 'strategies' && config.strategies && (
                <StrategiesTab
                  config={config}
                  setConfig={setConfig}
                  enabledCount={enabledCount}
                  totalStrategies={totalStrategies}
                  expandedStrategy={expandedStrategy}
                  setExpandedStrategy={setExpandedStrategy}
                  strategyFilter={strategyFilter}
                  setStrategyFilter={setStrategyFilter}
                  strategySearch={strategySearch}
                  setStrategySearch={setStrategySearch}
                  inputStyle={inputStyle}
                />
              )}

              {/* ── BROKER CREDENTIALS TAB ──────────────────── */}
              {activeTab === 'broker' && (
                <BrokerConnectionSection
                  inputStyle={inputStyle}
                  labelStyle={labelStyle}
                  cardStyle={cardStyle}
                />
              )}

              {/* ── SYSTEM TAB ──────────────────────────────── */}
              {activeTab === 'system' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div style={cardStyle}>
                    <SectionTitle
                      icon={<RotateCcw size={15} />}
                      iconColor="#a78bfa"
                      title="Onboarding Tutorial"
                      subtitle="Replay the guided walkthrough to revisit key platform features."
                    />
                    <button
                      onClick={() => {
                        resetOnboarding();
                        setTutorialToast(true);
                        setTimeout(() => setTutorialToast(false), 3000);
                      }}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 8,
                        padding: '9px 16px', borderRadius: 'var(--r-sm)',
                        background: 'var(--accent-gradient)',
                        color: '#fff', border: 'none',
                        fontSize: 13, fontWeight: 700, cursor: 'pointer',
                        boxShadow: '0 4px 12px var(--accent-glow)',
                      }}
                    >
                      <RotateCcw size={14} />
                      <span>Replay Tutorial</span>
                    </button>
                    <AnimatePresence>
                      {tutorialToast && (
                        <motion.div
                          initial={{ opacity: 0, y: -6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -6 }}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 8,
                            padding: '9px 14px', borderRadius: 'var(--r-sm)',
                            fontSize: 12, marginTop: 14,
                            background: 'var(--bull-soft)',
                            border: '1px solid color-mix(in srgb, var(--bull) 30%, transparent)',
                            color: 'var(--bull)', fontWeight: 500,
                          }}
                        >
                          <CheckCircle size={14} />
                          <span>Tutorial reset — navigate to Dashboard to start the walkthrough</span>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>

                  <PreferencesCard cardStyle={cardStyle} />
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* ── Confirm Dialog ─────────────────────────────────────── */}
      <AnimatePresence>
        {confirmDialog && (
          <div
            style={{
              position: 'fixed', inset: 0, zIndex: 100,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--scrim)',
              backdropFilter: 'saturate(140%) blur(8px)',
              WebkitBackdropFilter: 'saturate(140%) blur(8px)',
            }}
            onClick={() => setConfirmDialog(null)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.94, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 6 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              className="lt-bento"
              style={{
                padding: 28, width: 440, maxWidth: '90vw',
                border: '1px solid color-mix(in srgb, var(--warn) 36%, transparent)',
                boxShadow: 'var(--elev-3), 0 0 40px color-mix(in srgb, var(--warn) 22%, transparent)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 'var(--r-sm)',
                  display: 'grid', placeItems: 'center',
                  background: 'var(--warn-soft)',
                  border: '1px solid color-mix(in srgb, var(--warn) 32%, transparent)',
                }}>
                  <AlertTriangle size={18} color="var(--warn)" />
                </div>
                <h3 style={{
                  fontSize: 15, fontWeight: 700,
                  color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.01em',
                }}>
                  {confirmDialog.title}
                </h3>
              </div>
              <p style={{
                fontSize: 13, color: 'var(--fg-secondary)', lineHeight: 1.6,
                whiteSpace: 'pre-line', margin: '0 0 22px',
              }}>
                {confirmDialog.message}
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  onClick={() => setConfirmDialog(null)}
                  style={{
                    padding: '9px 18px', fontSize: 13, fontWeight: 600,
                    color: 'var(--fg-secondary)',
                    background: 'var(--surface-3)',
                    border: '1px solid var(--line-2)', borderRadius: 'var(--r-sm)',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDialog.onConfirm}
                  style={{
                    padding: '9px 18px', fontSize: 13, fontWeight: 700, color: '#fff',
                    background: 'linear-gradient(135deg, var(--bear), #c03050)',
                    borderRadius: 'var(--r-sm)', border: 'none',
                    cursor: 'pointer',
                    boxShadow: '0 6px 16px var(--bear-glow)',
                  }}
                >
                  Confirm Changes
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Responsive collapse for narrow screens */}
      <style>{`
        @media (max-width: 820px) {
          .settings-grid { grid-template-columns: 1fr !important; }
          .settings-grid > aside { position: static !important; }
        }
      `}</style>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════
   ConfigHero — top status banner with 4 live chips
   ═══════════════════════════════════════════════════════════════════════ */
function ConfigHero({
  integrity, brokerPrimary, capital, enabledStrategies, totalStrategies,
}: {
  integrity: number;
  brokerPrimary: string;
  capital: number;
  enabledStrategies: number;
  totalStrategies: number;
}) {
  return (
    <div
      className="lt-bento"
      style={{
        position: 'relative', overflow: 'hidden',
        padding: 0,
      }}
    >
      {/* Ambient radial glow */}
      <div aria-hidden style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background:
          'radial-gradient(120% 80% at 0% 0%, color-mix(in srgb, var(--accent) 18%, transparent) 0%, transparent 50%), radial-gradient(80% 100% at 100% 100%, color-mix(in srgb, var(--accent-2) 14%, transparent) 0%, transparent 60%)',
      }} />
      <div style={{
        position: 'relative',
        padding: '22px 24px',
        display: 'grid',
        gridTemplateColumns: 'minmax(240px, 1.4fr) repeat(3, minmax(140px, 1fr))',
        gap: 20,
        alignItems: 'center',
      }} className="hero-grid">
        {/* Title + integrity */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Settings size={14} color="var(--accent-2)" />
            <span style={{
              fontSize: 10, fontWeight: 800, letterSpacing: '0.18em',
              color: 'var(--accent-2)', textTransform: 'uppercase',
            }}>
              Configuration
            </span>
          </div>
          <h1 style={{
            fontSize: 22, fontWeight: 800, color: 'var(--fg-primary)',
            margin: 0, letterSpacing: '-0.02em', lineHeight: 1.2,
          }}>
            Your trading system, your rules
          </h1>
          <p style={{
            fontSize: 12, color: 'var(--fg-muted)',
            margin: '6px 0 12px', lineHeight: 1.55,
          }}>
            Tune brokers, capital, risk rails, and strategies. Everything saves together.
          </p>
          <IntegrityBar pct={integrity} />
        </div>

        {/* Live chips */}
        <HeroChip
          icon={<Link2 size={13} />}
          iconColor="var(--accent-2)"
          label="Primary broker"
          value={brokerPrimary ? brokerPrimary[0].toUpperCase() + brokerPrimary.slice(1) : '—'}
        />
        <HeroChip
          icon={<Wallet size={13} />}
          iconColor="var(--bull)"
          label="Capital at work"
          value={`₹${capital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          mono
        />
        <HeroChip
          icon={<Zap size={13} />}
          iconColor="var(--warn)"
          label="Strategies online"
          value={`${enabledStrategies} / ${totalStrategies}`}
          mono
        />
      </div>

      <style>{`
        @media (max-width: 900px) {
          .hero-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function IntegrityBar({ pct }: { pct: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.14em',
          color: 'var(--fg-muted)', textTransform: 'uppercase',
        }}>
          Setup Completion
        </span>
        <span
          className="lt-tabular"
          style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent-2)' }}
        >
          {pct}%
        </span>
      </div>
      <div style={{
        position: 'relative', height: 4, borderRadius: 2,
        background: 'var(--line-2)', overflow: 'hidden',
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          style={{
            height: '100%',
            background: 'var(--accent-gradient)',
            boxShadow: '0 0 10px var(--accent-glow)',
          }}
        />
      </div>
    </div>
  );
}

function HeroChip({
  icon, iconColor, label, value, mono,
}: {
  icon: React.ReactNode;
  iconColor: string;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div style={{
      padding: 14,
      borderRadius: 'var(--r-md)',
      background: 'color-mix(in srgb, var(--surface-3) 62%, transparent)',
      border: '1px solid var(--line-2)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span style={{
          width: 22, height: 22, borderRadius: 6,
          display: 'grid', placeItems: 'center',
          background: `color-mix(in srgb, ${iconColor} 18%, transparent)`,
          color: iconColor,
        }}>
          {icon}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
          color: 'var(--fg-muted)', textTransform: 'uppercase',
        }}>
          {label}
        </span>
      </div>
      <p
        className={mono ? 'lt-tabular' : undefined}
        style={{
          fontSize: 16, fontWeight: 800,
          color: 'var(--fg-primary)', margin: 0,
          letterSpacing: '-0.02em',
          whiteSpace: 'nowrap',
          overflow: 'hidden', textOverflow: 'ellipsis',
        }}
      >
        {value}
      </p>
    </div>
  );
}

/* ─── Section title with subtitle ─────────────────────────────── */
function SectionTitle({
  icon, iconColor, title, subtitle,
}: {
  icon: React.ReactNode; iconColor: string; title: string; subtitle?: string;
}) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: subtitle ? 6 : 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 'var(--r-sm)',
          display: 'grid', placeItems: 'center',
          background: `color-mix(in srgb, ${iconColor} 14%, transparent)`,
          border: `1px solid color-mix(in srgb, ${iconColor} 28%, transparent)`,
          color: iconColor,
        }}>
          {icon}
        </div>
        <h3 style={{
          fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)',
          margin: 0, letterSpacing: '-0.01em',
        }}>
          {title}
        </h3>
      </div>
      {subtitle && (
        <p style={{
          fontSize: 12, color: 'var(--fg-muted)',
          margin: '0 0 0 42px', lineHeight: 1.55,
        }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}

/* ─── Smart number input with prefix ──────────────────────────── */
function NumberField({
  label, value, onChange, error, min, prefix,
}: {
  label: string; value: number; onChange: (v: number) => void;
  error?: string; min?: number; prefix?: string;
}) {
  return (
    <div>
      <label style={SETTINGS_LABEL}>{label}</label>
      <div style={{ position: 'relative' }}>
        {prefix && (
          <span style={{
            position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
            fontSize: 13, color: 'var(--fg-muted)', fontWeight: 600,
            pointerEvents: 'none',
          }}>
            {prefix}
          </span>
        )}
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          min={min}
          style={{
            ...SETTINGS_INPUT,
            paddingLeft: prefix ? 28 : 12,
            fontFamily: 'ui-monospace, monospace',
            fontWeight: 600,
          }}
          onFocus={applyInputFocus}
          onBlur={applyInputBlur}
        />
      </div>
      <FieldError error={error} />
    </div>
  );
}

/* ─── Percent input with live bar preview ─────────────────────── */
function PercentField({
  label, value, onChange, error, danger,
}: {
  label: string; value: number; onChange: (v: number) => void;
  error?: string; danger?: boolean;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const barColor = danger ? 'var(--bear)' : 'var(--bull)';
  return (
    <div>
      <label style={SETTINGS_LABEL}>{label}</label>
      <div style={{ position: 'relative' }}>
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          min={0}
          max={100}
          step={0.1}
          style={{
            ...SETTINGS_INPUT,
            paddingRight: 34,
            fontFamily: 'ui-monospace, monospace',
            fontWeight: 600,
          }}
          onFocus={applyInputFocus}
          onBlur={applyInputBlur}
        />
        <span style={{
          position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
          fontSize: 12, color: 'var(--fg-muted)', fontWeight: 700,
          pointerEvents: 'none',
        }}>
          %
        </span>
      </div>
      {/* Live visual bar */}
      <div style={{
        height: 3, borderRadius: 2, background: 'var(--line-2)',
        overflow: 'hidden', marginTop: 8,
      }}>
        <motion.div
          initial={false}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.3 }}
          style={{
            height: '100%',
            background: barColor,
            boxShadow: `0 0 8px color-mix(in srgb, ${barColor} 60%, transparent)`,
          }}
        />
      </div>
      <FieldError error={error} />
    </div>
  );
}

/* ─── Capital visualizer: shows how risk/position caps split the total ─── */
function CapitalVisualizer({
  total, riskPerTrade, maxPosition, maxDailyLoss,
}: {
  total: number;
  riskPerTrade: number;
  maxPosition: number;
  maxDailyLoss: number;
}) {
  const perTrade = (total * riskPerTrade) / 100;
  const perPosition = (total * maxPosition) / 100;
  const dailyLossCap = (total * maxDailyLoss) / 100;

  const stat = (label: string, value: string, color: string) => (
    <div style={{ minWidth: 0, flex: 1 }}>
      <p style={{
        fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
        color: 'var(--fg-muted)', margin: 0, textTransform: 'uppercase',
      }}>
        {label}
      </p>
      <p
        className="lt-tabular"
        style={{
          fontSize: 15, fontWeight: 800, color,
          margin: '4px 0 0', letterSpacing: '-0.01em',
        }}
      >
        {value}
      </p>
    </div>
  );

  return (
    <div style={{
      position: 'relative',
      padding: 16,
      borderRadius: 'var(--r-md)',
      background:
        'linear-gradient(135deg, color-mix(in srgb, var(--accent) 6%, transparent) 0%, color-mix(in srgb, var(--accent-2) 4%, transparent) 100%)',
      border: '1px solid var(--line-2)',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
      }}>
        {stat('Per trade', `₹${perTrade.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, 'var(--accent-2)')}
        {stat('Per position', `₹${perPosition.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, 'var(--bull)')}
        {stat('Daily loss cap', `₹${dailyLossCap.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, 'var(--bear)')}
      </div>

      {/* Stacked horizontal bars */}
      <div style={{
        display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden',
        marginTop: 14, background: 'var(--line-2)',
      }}>
        <motion.div
          initial={false}
          animate={{ width: `${Math.min(100, maxPosition)}%` }}
          transition={{ duration: 0.4 }}
          style={{
            background: 'linear-gradient(90deg, var(--accent), var(--bull))',
            boxShadow: '0 0 8px var(--bull-glow)',
          }}
        />
      </div>
      <p style={{
        fontSize: 10, color: 'var(--fg-muted)',
        margin: '8px 0 0', fontWeight: 500, lineHeight: 1.5,
      }}>
        Max position uses up to <b style={{ color: 'var(--fg-secondary)' }}>{maxPosition}%</b> of capital.
        Per-trade risk caps loss at <b style={{ color: 'var(--fg-secondary)' }}>{riskPerTrade}%</b>.
        Daily loss trigger halts trading at <b style={{ color: 'var(--bear)' }}>{maxDailyLoss}%</b>.
      </p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   Strategies Tab
   ═══════════════════════════════════════════════════════════════════════ */
function StrategiesTab({
  config, setConfig, enabledCount, totalStrategies,
  expandedStrategy, setExpandedStrategy,
  strategyFilter, setStrategyFilter,
  strategySearch, setStrategySearch,
  inputStyle,
}: {
  config: Config;
  setConfig: (c: Config) => void;
  enabledCount: number;
  totalStrategies: number;
  expandedStrategy: string | null;
  setExpandedStrategy: (s: string | null) => void;
  strategyFilter: 'all' | 'enabled' | 'disabled';
  setStrategyFilter: (f: 'all' | 'enabled' | 'disabled') => void;
  strategySearch: string;
  setStrategySearch: (s: string) => void;
  inputStyle: React.CSSProperties;
}) {
  const filtered = useMemo(() => {
    if (!config.strategies) return [] as [string, any][];
    const q = strategySearch.trim().toLowerCase();
    return Object.entries(config.strategies).filter(([name, strat]) => {
      const meta = STRATEGY_META[name];
      const label = (meta?.label || name).toLowerCase();
      if (q && !label.includes(q) && !name.toLowerCase().includes(q)) return false;
      const isEnabled = strat.enabled !== false;
      if (strategyFilter === 'enabled' && !isEnabled) return false;
      if (strategyFilter === 'disabled' && isEnabled) return false;
      return true;
    });
  }, [config.strategies, strategyFilter, strategySearch]);

  const toggleAll = (enable: boolean) => {
    if (!config.strategies) return;
    const next: any = {};
    Object.entries(config.strategies).forEach(([name, s]) => {
      next[name] = { ...s, enabled: enable };
    });
    setConfig({ ...config, strategies: next });
  };

  return (
    <>
      {/* Summary hero */}
      <StrategyCatalogHero
        enabledCount={enabledCount}
        totalStrategies={totalStrategies}
        onEnableAll={() => toggleAll(true)}
        onDisableAll={() => toggleAll(false)}
      />

      {/* Controls row */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      }}>
        {/* Search */}
        <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
          <Search size={13} style={{
            position: 'absolute', left: 12, top: '50%',
            transform: 'translateY(-50%)', color: 'var(--fg-muted)',
            pointerEvents: 'none',
          }} />
          <input
            type="text"
            placeholder="Search strategies…"
            value={strategySearch}
            onChange={(e) => setStrategySearch(e.target.value)}
            style={{
              ...inputStyle,
              paddingLeft: 34,
            }}
            onFocus={applyInputFocus}
            onBlur={applyInputBlur}
          />
        </div>

        {/* Filter pills */}
        <div style={{
          display: 'inline-flex', gap: 3, padding: 3,
          background: 'var(--surface-2)', border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-sm)',
        }}>
          {(['all', 'enabled', 'disabled'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setStrategyFilter(f)}
              style={{
                padding: '6px 12px', fontSize: 11, fontWeight: 700,
                borderRadius: 6, border: 'none', cursor: 'pointer',
                background: strategyFilter === f ? 'var(--surface-4)' : 'transparent',
                color: strategyFilter === f ? 'var(--fg-primary)' : 'var(--fg-muted)',
                boxShadow: strategyFilter === f ? 'var(--elev-1)' : 'none',
                textTransform: 'capitalize',
                transition: 'all var(--dur-2) var(--ease-out)',
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Strategy cards grid */}
      {filtered.length === 0 ? (
        <div className="lt-bento" style={{ padding: 40, textAlign: 'center' }}>
          <Search size={24} color="var(--fg-muted)" style={{ margin: '0 auto 10px', opacity: 0.5 }} />
          <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: 0 }}>
            No strategies match your filters
          </p>
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 12,
        }}>
          {filtered.map(([name, strat]) => {
            const meta = STRATEGY_META[name] || {
              label: name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
              color: 'var(--fg-muted)',
              emoji: '⚙️',
            };
            const params = Object.entries(strat).filter(([k]) => k !== 'enabled');
            const isExpanded = expandedStrategy === name;
            const isEnabled = strat.enabled !== false;

            return (
              <motion.div
                key={name}
                layout
                style={{
                  borderRadius: 'var(--r-md)', overflow: 'hidden',
                  background: isExpanded ? 'var(--surface-3)' : 'var(--surface-2)',
                  border: `1px solid ${isExpanded
                    ? 'color-mix(in srgb, var(--accent) 30%, transparent)'
                    : 'var(--line-2)'}`,
                  borderLeftWidth: 3,
                  borderLeftColor: isEnabled ? meta.color : 'var(--line-3)',
                  boxShadow: isExpanded
                    ? '0 8px 24px color-mix(in srgb, var(--accent) 12%, transparent)'
                    : 'var(--elev-1)',
                  transition: 'all var(--dur-2) var(--ease-out)',
                }}
              >
                <div
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '12px 14px', cursor: 'pointer',
                    transition: 'background var(--dur-2) var(--ease-out)',
                  }}
                  onClick={() => setExpandedStrategy(isExpanded ? null : name)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: 1 }}>
                    <span style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>
                      {meta.emoji}
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <p style={{
                        fontSize: 13, fontWeight: 600,
                        color: isEnabled ? 'var(--fg-primary)' : 'var(--fg-muted)',
                        margin: 0, letterSpacing: '-0.01em',
                      }}>
                        {meta.label}
                      </p>
                      <p style={{
                        fontSize: 10, color: 'var(--fg-muted)', margin: '2px 0 0',
                        display: 'flex', alignItems: 'center', gap: 6,
                      }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: '50%',
                          background: meta.color, opacity: isEnabled ? 1 : 0.3,
                          boxShadow: isEnabled ? `0 0 6px ${meta.color}` : 'none',
                        }} />
                        {params.length > 0
                          ? `${params.length} parameter${params.length === 1 ? '' : 's'}`
                          : 'No parameters'}
                      </p>
                    </div>
                  </div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
                  }}>
                    <div onClick={(e) => e.stopPropagation()}>
                      <Toggle
                        checked={isEnabled}
                        onChange={(checked) => {
                          setConfig({
                            ...config,
                            strategies: { ...config.strategies, [name]: { ...strat, enabled: checked } },
                          });
                        }}
                      />
                    </div>
                    <ChevronRight
                      size={13}
                      style={{
                        color: 'var(--fg-muted)',
                        transition: 'transform var(--dur-2) var(--ease-out)',
                        transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                      }}
                    />
                  </div>
                </div>

                <AnimatePresence initial={false}>
                  {isExpanded && params.length > 0 && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                      style={{ overflow: 'hidden', borderTop: '1px solid var(--line-2)' }}
                    >
                      <div style={{
                        padding: '14px 14px 16px',
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                        gap: 12,
                      }}>
                        {params.map(([key, val]) => (
                          <div key={key}>
                            <label style={{
                              ...SETTINGS_LABEL,
                              fontSize: 9, letterSpacing: '0.08em',
                            }}>
                              {key.replace(/_/g, ' ')}
                            </label>
                            <input
                              type="number"
                              value={typeof val === 'number' ? val : 0}
                              onChange={(e) => {
                                setConfig({
                                  ...config,
                                  strategies: {
                                    ...config.strategies,
                                    [name]: { ...strat, [key]: Number(e.target.value) },
                                  },
                                });
                              }}
                              style={{
                                ...inputStyle,
                                padding: '6px 10px',
                                fontSize: 12,
                                fontFamily: 'ui-monospace, monospace',
                                fontWeight: 600,
                              }}
                              step={typeof val === 'number' && val < 1 ? 0.01 : 1}
                              onFocus={applyInputFocus}
                              onBlur={applyInputBlur}
                            />
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      )}
    </>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={(e) => { e.stopPropagation(); onChange(!checked); }}
      style={{
        position: 'relative',
        width: 34, height: 20, borderRadius: 999,
        border: `1px solid ${checked ? 'color-mix(in srgb, var(--bull) 55%, transparent)' : 'var(--line-2)'}`,
        background: checked ? 'color-mix(in srgb, var(--bull) 45%, transparent)' : 'var(--surface-4)',
        cursor: 'pointer', flexShrink: 0,
        transition: 'background var(--dur-2) var(--ease-out), border-color var(--dur-2) var(--ease-out)',
      }}
    >
      <span style={{
        position: 'absolute',
        top: 1, left: checked ? 15 : 1,
        width: 16, height: 16, borderRadius: '50%',
        background: '#fff',
        boxShadow: '0 1px 3px rgba(0,0,0,0.35)',
        transition: 'left var(--dur-2) var(--ease-out)',
      }} />
    </button>
  );
}


/* ═══════════════════════════════════════════════════════════════════════
   Broker Credentials — Preferences-style section
   ═══════════════════════════════════════════════════════════════════════ */


const ALL_SERVICES = [
  { id: 'shoonya', name: 'Shoonya (Finvasia)', description: 'Primary broker for order execution', icon: <Wallet size={16} />, type: 'broker' as const },
  { id: 'angelone', name: 'Angel One (SmartAPI)', description: 'Backup broker for order execution', icon: <Wallet size={16} />, type: 'broker' as const },
  { id: 'nubra', name: 'Nubra.io Market Data', description: 'Exchange-sourced NSE/BSE market data feed', icon: <Zap size={16} />, type: 'integration' as const },
  { id: 'nvidia_nim', name: 'NVIDIA NIM', description: 'Cloud AI inference for research analysis', icon: <Sparkles size={16} />, type: 'integration' as const },
  { id: 'ollama', name: 'Ollama (Local AI)', description: 'Run AI models locally on your machine', icon: <Sparkles size={16} />, type: 'integration' as const },
  { id: 'telegram', name: 'Telegram Bot', description: 'Trade notifications and alerts', icon: <Bell size={16} />, type: 'integration' as const },
];

type BrokerField = {
  label: string;
  type: 'text' | 'password';
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  half?: boolean;
};

function BrokerConnectionSection({
  inputStyle, labelStyle, cardStyle,
}: {
  inputStyle: React.CSSProperties;
  labelStyle: React.CSSProperties;
  cardStyle: React.CSSProperties;
}) {
  /* ── Accordion state: only one open at a time ── */
  const [open, setOpen] = useState<string | null>(null);
  const toggle = (id: string) => setOpen(prev => prev === id ? null : id);

  /* ── Broker credential state (Shoonya + Angel One) ── */
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ broker: string; ok: boolean; msg: string } | null>(null);

  const [shApiKey, setShApiKey] = useState('');
  const [shClientId, setShClientId] = useState('');
  const [shPassword, setShPassword] = useState('');
  const [shTotp, setShTotp] = useState('');
  const [shImei, setShImei] = useState('');

  const [aoApiKey, setAoApiKey] = useState('');
  const [aoClientId, setAoClientId] = useState('');
  const [aoPassword, setAoPassword] = useState('');
  const [aoTotp, setAoTotp] = useState('');

  const [savingBroker, setSavingBroker] = useState<string | null>(null);

  /* ── Integration state (setup-store) ── */
  const {
    services,
    loading: integrationLoading,
    fetchStatus,
    submitCredentials,
    testConnection,
    skipGroup,
  } = useSetupStore();

  useEffect(() => {
    api.getBrokerStatus().then(setBrokerStatus).catch(() => {});
    fetchStatus();
  }, [fetchStatus]);

  const getServiceStatus = useCallback(
    (groupId: string): ServiceStatus => {
      const found = services.find((s) => s.group_id === groupId);
      return found ?? {
        group_id: groupId,
        name: CREDENTIAL_GROUPS.find((g) => g.group_id === groupId)?.name ?? groupId,
        status: 'unconfigured',
        required: false,
        features_affected: [],
      };
    },
    [services],
  );

  /* ── Broker handlers ── */
  const handleSaveShoonya = async () => {
    setSavingBroker('shoonya');
    try {
      await api.updateShoonya({ api_key: shApiKey, client_id: shClientId, password: shPassword, totp_secret: shTotp, imei: shImei });
      api.getBrokerStatus().then(setBrokerStatus).catch(() => {});
    } catch { /* ignore */ }
    setSavingBroker(null);
  };

  const handleSaveAngelone = async () => {
    setSavingBroker('angelone');
    try {
      await api.updateAngelone({ api_key: aoApiKey, client_id: aoClientId, password: aoPassword, totp_secret: aoTotp });
      api.getBrokerStatus().then(setBrokerStatus).catch(() => {});
    } catch { /* ignore */ }
    setSavingBroker(null);
  };

  const handleTestBroker = async (broker: string) => {
    setTesting(broker);
    setTestResult(null);
    try {
      const res = await api.testBrokerConnection(broker);
      setTestResult({ broker, ok: true, msg: res.message });
    } catch (e: any) {
      setTestResult({ broker, ok: false, msg: e?.detail || 'Connection failed' });
    }
    setTesting(null);
  };

  /* ── Determine status for each service ── */
  const getStatus = (id: string): 'configured' | 'skipped' | 'pending' => {
    if (id === 'shoonya') return brokerStatus?.shoonya?.configured ? 'configured' : 'pending';
    if (id === 'angelone') return brokerStatus?.angelone?.configured ? 'configured' : 'pending';
    const svc = getServiceStatus(id);
    if (svc.status === 'configured') return 'configured';
    if (svc.status === 'skipped') return 'skipped';
    return 'pending';
  };

  const statusDotColor = (id: string) => {
    const s = getStatus(id);
    if (s === 'configured') return 'var(--bull)';
    if (s === 'skipped') return 'var(--warn)';
    return 'var(--surface-4)';
  };

  return (
    <div style={{
      background: 'var(--surface-2)',
      border: '1px solid var(--line-1)',
      borderRadius: 'var(--r-lg)',
      padding: 24,
    }}>
      {/* Section header — matches Preferences style */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <div style={{
            width: 40, height: 40, borderRadius: '50%',
            display: 'grid', placeItems: 'center',
            background: 'color-mix(in srgb, var(--accent) 15%, transparent)',
            color: 'var(--accent)',
          }}>
            <Link2 size={18} />
          </div>
          <div>
            <h3 style={{
              fontSize: 16, fontWeight: 700, color: 'var(--fg-primary)',
              margin: 0, letterSpacing: '-0.01em',
            }}>
              Credentials &amp; Integrations
            </h3>
            <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '2px 0 0' }}>
              Manage API keys for brokers, data feeds, and services.
            </p>
          </div>
        </div>
      </div>

      {/* Global test result banner */}
      <AnimatePresence>
        {testResult && (
          <motion.div
            initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px', borderRadius: 'var(--r-sm)', fontSize: 12, fontWeight: 500,
              marginBottom: 16,
              color: testResult.ok ? 'var(--bull)' : 'var(--bear)',
              background: testResult.ok ? 'var(--bull-soft)' : 'var(--bear-soft)',
              border: `1px solid color-mix(in srgb, ${testResult.ok ? 'var(--bull)' : 'var(--bear)'} 28%, transparent)`,
            }}
          >
            {testResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
            <span>{testResult.msg}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Service items */}
      {ALL_SERVICES.map((service, idx) => (
        <ServiceRow
          key={service.id}
          service={service}
          isLast={idx === ALL_SERVICES.length - 1}
          expanded={open === service.id}
          onToggle={() => toggle(service.id)}
          status={getStatus(service.id)}
          statusDotColor={statusDotColor(service.id)}
          inputStyle={inputStyle}
          labelStyle={labelStyle}
          /* Broker-specific props */
          brokerStatus={brokerStatus}
          savingBroker={savingBroker}
          testingBroker={testing}
          onSaveShoonya={handleSaveShoonya}
          onSaveAngelone={handleSaveAngelone}
          onTestBroker={handleTestBroker}
          shFields={{ shApiKey, setShApiKey, shClientId, setShClientId, shPassword, setShPassword, shTotp, setShTotp, shImei, setShImei }}
          aoFields={{ aoApiKey, setAoApiKey, aoClientId, setAoClientId, aoPassword, setAoPassword, aoTotp, setAoTotp }}
          /* Integration-specific props */
          getServiceStatus={getServiceStatus}
          integrationLoading={integrationLoading}
          submitCredentials={submitCredentials}
          testConnection={testConnection}
          skipGroup={skipGroup}
        />
      ))}
    </div>
  );
}

/* ── Service Row (single accordion item — Preferences style) ── */
function ServiceRow({
  service, isLast, expanded, onToggle, status, statusDotColor, inputStyle, labelStyle,
  brokerStatus, savingBroker, testingBroker, onSaveShoonya, onSaveAngelone, onTestBroker,
  shFields, aoFields,
  getServiceStatus, integrationLoading, submitCredentials, testConnection, skipGroup,
}: {
  service: typeof ALL_SERVICES[number];
  isLast: boolean;
  expanded: boolean;
  onToggle: () => void;
  status: 'configured' | 'skipped' | 'pending';
  statusDotColor: string;
  inputStyle: React.CSSProperties;
  labelStyle: React.CSSProperties;
  brokerStatus: any;
  savingBroker: string | null;
  testingBroker: string | null;
  onSaveShoonya: () => void;
  onSaveAngelone: () => void;
  onTestBroker: (broker: string) => void;
  shFields: any;
  aoFields: any;
  getServiceStatus: (id: string) => ServiceStatus;
  integrationLoading: boolean;
  submitCredentials: (groupId: string, creds: Record<string, string>) => Promise<void>;
  testConnection: (groupId: string) => Promise<TestResult>;
  skipGroup: (groupId: string) => Promise<void>;
}) {
  const statusLabel = status === 'configured' ? 'Connected' : status === 'skipped' ? 'Skipped' : 'Pending';

  return (
    <div style={{ borderBottom: isLast ? 'none' : '1px solid var(--line-1)' }}>
      {/* Clickable row */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        style={{
          display: 'flex', alignItems: 'center', gap: 14,
          width: '100%', padding: '16px 0',
          background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
        }}
      >
        {/* Service icon */}
        <div style={{
          width: 36, height: 36, borderRadius: 10, flexShrink: 0,
          display: 'grid', placeItems: 'center',
          background: 'var(--surface-3)',
          color: 'var(--fg-muted)',
        }}>
          {service.icon}
        </div>

        {/* Name + description */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            fontSize: 14, fontWeight: 600, color: 'var(--fg-primary)',
            margin: 0, letterSpacing: '-0.01em',
          }}>
            {service.name}
          </p>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '2px 0 0' }}>
            {service.description}
          </p>
        </div>

        {/* Status indicator */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: statusDotColor,
            boxShadow: status === 'configured' ? '0 0 6px var(--bull)' : 'none',
          }} />
          <span style={{
            fontSize: 11, fontWeight: 600,
            color: status === 'configured' ? 'var(--bull)' : 'var(--fg-muted)',
          }}>
            {statusLabel}
          </span>
        </div>
      </button>

      {/* Expanded content */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '16px 0 8px 50px' }}>
              {service.type === 'broker' ? (
                <BrokerExpandedContent
                  brokerId={service.id}
                  brokerStatus={brokerStatus}
                  savingBroker={savingBroker}
                  testingBroker={testingBroker}
                  onSaveShoonya={onSaveShoonya}
                  onSaveAngelone={onSaveAngelone}
                  onTestBroker={onTestBroker}
                  shFields={shFields}
                  aoFields={aoFields}
                  inputStyle={inputStyle}
                  labelStyle={labelStyle}
                />
              ) : (
                <IntegrationExpandedContent
                  groupId={service.id}
                  getServiceStatus={getServiceStatus}
                  integrationLoading={integrationLoading}
                  submitCredentials={submitCredentials}
                  testConnection={testConnection}
                  skipGroup={skipGroup}
                  inputStyle={inputStyle}
                  labelStyle={labelStyle}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Broker Expanded Content ── */
function BrokerExpandedContent({
  brokerId, brokerStatus, savingBroker, testingBroker,
  onSaveShoonya, onSaveAngelone, onTestBroker,
  shFields, aoFields, inputStyle, labelStyle,
}: {
  brokerId: string;
  brokerStatus: any;
  savingBroker: string | null;
  testingBroker: string | null;
  onSaveShoonya: () => void;
  onSaveAngelone: () => void;
  onTestBroker: (broker: string) => void;
  shFields: any;
  aoFields: any;
  inputStyle: React.CSSProperties;
  labelStyle: React.CSSProperties;
}) {
  const saving = savingBroker === brokerId;
  const isTesting = testingBroker === brokerId;

  const fields: BrokerField[] = brokerId === 'shoonya'
    ? [
        { label: 'API Key', type: 'text', value: shFields.shApiKey, onChange: shFields.setShApiKey, placeholder: brokerStatus?.shoonya?.api_key || 'Enter API key' },
        { label: 'Client ID', type: 'text', value: shFields.shClientId, onChange: shFields.setShClientId, placeholder: brokerStatus?.shoonya?.client_id || 'Enter client ID' },
        { label: 'Password', type: 'password', value: shFields.shPassword, onChange: shFields.setShPassword, placeholder: '••••••••' },
        { label: 'TOTP Secret', type: 'password', value: shFields.shTotp, onChange: shFields.setShTotp, placeholder: '••••••••', half: true },
        { label: 'IMEI', type: 'text', value: shFields.shImei, onChange: shFields.setShImei, placeholder: 'Device IMEI', half: true },
      ]
    : [
        { label: 'API Key', type: 'text', value: aoFields.aoApiKey, onChange: aoFields.setAoApiKey, placeholder: brokerStatus?.angelone?.api_key || 'Enter API key' },
        { label: 'Client ID', type: 'text', value: aoFields.aoClientId, onChange: aoFields.setAoClientId, placeholder: brokerStatus?.angelone?.client_id || 'Enter client ID' },
        { label: 'Password', type: 'password', value: aoFields.aoPassword, onChange: aoFields.setAoPassword, placeholder: '••••••••' },
        { label: 'TOTP Secret', type: 'password', value: aoFields.aoTotp, onChange: aoFields.setAoTotp, placeholder: '••••••••' },
      ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Render fields — pair half-width fields side by side */}
      {renderBrokerFields(fields, inputStyle, labelStyle)}

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 4 }}>
        <button
          onClick={brokerId === 'shoonya' ? onSaveShoonya : onSaveAngelone}
          disabled={saving}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 'var(--r-sm)',
            background: 'var(--accent-gradient)', color: '#fff', border: 'none',
            fontSize: 12, fontWeight: 700,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.5 : 1,
          }}
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          <span>Save</span>
        </button>
        <button
          onClick={() => onTestBroker(brokerId)}
          disabled={isTesting}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 'var(--r-sm)',
            background: 'var(--surface-3)', color: 'var(--fg-secondary)',
            border: '1px solid var(--line-1)',
            fontSize: 12, fontWeight: 700,
            cursor: isTesting ? 'not-allowed' : 'pointer',
            opacity: isTesting ? 0.5 : 1,
          }}
        >
          {isTesting ? <Loader2 size={12} className="animate-spin" /> : <Unplug size={12} />}
          <span>Test Connection</span>
        </button>
      </div>
    </div>
  );
}

function renderBrokerFields(fields: BrokerField[], inputStyle: React.CSSProperties, labelStyle: React.CSSProperties) {
  const rows: React.ReactNode[] = [];
  let i = 0;
  while (i < fields.length) {
    const f = fields[i];
    if (f.half && fields[i + 1]?.half) {
      rows.push(
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <FieldInput field={f} inputStyle={inputStyle} labelStyle={labelStyle} />
          <FieldInput field={fields[i + 1]} inputStyle={inputStyle} labelStyle={labelStyle} />
        </div>
      );
      i += 2;
    } else {
      rows.push(<FieldInput key={i} field={f} inputStyle={inputStyle} labelStyle={labelStyle} />);
      i++;
    }
  }
  return rows;
}

/* ── Integration Expanded Content ── */
function IntegrationExpandedContent({
  groupId, getServiceStatus, integrationLoading,
  submitCredentials, testConnection, skipGroup,
  inputStyle, labelStyle,
}: {
  groupId: string;
  getServiceStatus: (id: string) => ServiceStatus;
  integrationLoading: boolean;
  submitCredentials: (groupId: string, creds: Record<string, string>) => Promise<void>;
  testConnection: (groupId: string) => Promise<TestResult>;
  skipGroup: (groupId: string) => Promise<void>;
  inputStyle: React.CSSProperties;
  labelStyle: React.CSSProperties;
}) {
  const group = CREDENTIAL_GROUPS.find((g) => g.group_id === groupId);
  const status = getServiceStatus(groupId);

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((group?.credential_keys ?? []).map((key) => [key, ''])),
  );
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  if (!group) return null;

  const hasCredentialKeys = group.credential_keys.length > 0;

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    for (const key of group.credential_keys) {
      const value = values[key] ?? '';
      const pattern = group.validation_patterns[key];
      if (!value.trim()) {
        newErrors[key] = `${key.replace(/_/g, ' ')} is required`;
      } else if (pattern) {
        try {
          if (!new RegExp(pattern).test(value)) {
            newErrors[key] = 'Does not match expected format';
          }
        } catch { /* skip invalid pattern */ }
      }
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try { await submitCredentials(groupId, values); } finally { setSaving(false); }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testConnection(groupId);
      setTestResult(result);
    } catch {
      setTestResult({ success: false, response_time_ms: null, error: 'Connection test failed', suggestion: 'Check network and try again' });
    } finally { setTesting(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Credential fields */}
      {hasCredentialKeys && group.credential_keys.map((key) => {
        const isRevealed = revealed[key] ?? false;
        const hint = group.tooltip_hints[key];
        return (
          <div key={key}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
              <label style={labelStyle}>{key.replace(/_/g, ' ')}</label>
              {hint && (
                <span title={hint} style={{ cursor: 'help', color: 'var(--fg-muted)' }}>
                  <Info size={10} />
                </span>
              )}
            </div>
            <div style={{ position: 'relative' }}>
              <input
                type={isRevealed ? 'text' : 'password'}
                value={values[key] ?? ''}
                onChange={(e) => {
                  setValues((prev) => ({ ...prev, [key]: e.target.value }));
                  setErrors((prev) => { const n = { ...prev }; delete n[key]; return n; });
                }}
                placeholder={hint || `Enter ${key.replace(/_/g, ' ').toLowerCase()}`}
                autoComplete="off"
                style={{ ...inputStyle, paddingRight: 36, borderColor: errors[key] ? 'var(--bear)' : undefined }}
                onFocus={applyInputFocus}
                onBlur={applyInputBlur}
              />
              <button
                type="button"
                onClick={() => setRevealed((prev) => ({ ...prev, [key]: !prev[key] }))}
                style={{
                  position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fg-muted)', padding: 4,
                }}
                aria-label={isRevealed ? 'Hide value' : 'Reveal value'}
              >
                {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            {errors[key] && (
              <p style={{ fontSize: 11, color: 'var(--bear)', margin: '4px 0 0', fontWeight: 500 }}>{errors[key]}</p>
            )}
          </div>
        );
      })}

      {/* No credentials needed (Ollama) */}
      {!hasCredentialKeys && (
        <div style={{
          padding: '12px 14px', borderRadius: 'var(--r-sm)',
          background: 'var(--surface-3)', border: '1px solid var(--line-1)',
        }}>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: 0 }}>
            No API credentials needed. This service runs locally on your machine.
          </p>
        </div>
      )}

      {/* Test result feedback */}
      {testResult && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 'var(--r-sm)',
          background: testResult.success ? 'var(--bull-soft)' : 'var(--bear-soft)',
          border: `1px solid color-mix(in srgb, ${testResult.success ? 'var(--bull)' : 'var(--bear)'} 28%, transparent)`,
          fontSize: 12, fontWeight: 500,
          color: testResult.success ? 'var(--bull)' : 'var(--bear)',
        }}>
          {testResult.success ? <CheckCircle size={14} /> : <XCircle size={14} />}
          <span>
            {testResult.success
              ? `Connected${testResult.response_time_ms ? ` (${testResult.response_time_ms}ms)` : ''}`
              : testResult.error ?? 'Connection failed'}
          </span>
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 4 }}>
        {hasCredentialKeys && (
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 14px', borderRadius: 'var(--r-sm)',
              background: 'var(--accent-gradient)', color: '#fff', border: 'none',
              fontSize: 12, fontWeight: 700,
              cursor: saving ? 'not-allowed' : 'pointer',
              opacity: saving ? 0.5 : 1,
            }}
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            <span>Save</span>
          </button>
        )}
        <button
          onClick={handleTest}
          disabled={testing}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 'var(--r-sm)',
            background: 'var(--surface-3)', color: 'var(--fg-secondary)',
            border: '1px solid var(--line-1)',
            fontSize: 12, fontWeight: 700,
            cursor: testing ? 'not-allowed' : 'pointer',
            opacity: testing ? 0.5 : 1,
          }}
        >
          {testing ? <Loader2 size={12} className="animate-spin" /> : <Unplug size={12} />}
          <span>Test Connection</span>
        </button>
        {!group.required && status.status !== 'skipped' && status.status !== 'configured' && (
          <button
            onClick={() => skipGroup(groupId)}
            disabled={integrationLoading}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              padding: '8px 14px', borderRadius: 'var(--r-sm)',
              background: 'transparent', border: '1px solid var(--line-1)',
              color: 'var(--fg-muted)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}
          >
            <SkipForward size={12} /> Skip
          </button>
        )}
      </div>
    </div>
  );
}

/* ── FieldInput helper ── */
function FieldInput({
  field, inputStyle, labelStyle,
}: { field: BrokerField; inputStyle: React.CSSProperties; labelStyle: React.CSSProperties }) {
  return (
    <div>
      <label style={labelStyle}>{field.label}</label>
      <input
        type={field.type}
        value={field.value}
        onChange={(e) => field.onChange(e.target.value)}
        style={inputStyle}
        placeholder={field.placeholder}
        onFocus={applyInputFocus}
        onBlur={applyInputBlur}
      />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   Preferences
   ═══════════════════════════════════════════════════════════════════════ */
function PreferencesCard({ cardStyle }: { cardStyle: React.CSSProperties }) {
  const { setEnabled, isEnabled, play } = useSound();
  const [soundOn, setSoundOn] = useState<boolean>(() => isEnabled());
  const [mobileOn, setMobileOn] = useState<boolean>(() => isMobileOrdersAllowed());

  const toggleSound = (next: boolean) => {
    setEnabled(next);
    setSoundOn(next);
    if (next) setTimeout(() => play('fill'), 50);
  };

  const toggleMobile = (next: boolean) => {
    setMobileOrdersAllowed(next);
    setMobileOn(next);
  };

  return (
    <div style={cardStyle}>
      <SectionTitle
        icon={<Sliders size={15} />}
        iconColor="#f472b6"
        title="Preferences"
        subtitle="Fine-tune ambient behavior. These apply locally to this browser."
      />

      <PrefRow
        icon={soundOn ? <Volume2 size={16} /> : <VolumeX size={16} />}
        iconColor="var(--bull)"
        title="Sound cues"
        description="Play a short tone when orders fill or reject."
        checked={soundOn}
        onChange={toggleSound}
      />

      <div style={{ height: 1, background: 'var(--line-2)' }} />

      <PrefRow
        icon={<Smartphone size={16} />}
        iconColor="var(--warn)"
        title="Allow order placement on mobile"
        description="By default, orders are disabled below 640px width for safety."
        checked={mobileOn}
        onChange={toggleMobile}
      />
    </div>
  );
}

function PrefRow({
  icon, iconColor, title, description, checked, onChange,
}: {
  icon: React.ReactNode;
  iconColor: string;
  title: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 0', gap: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 'var(--r-sm)',
          display: 'grid', placeItems: 'center', flexShrink: 0,
          background: checked
            ? `color-mix(in srgb, ${iconColor} 14%, transparent)`
            : 'var(--surface-4)',
          border: `1px solid color-mix(in srgb, ${iconColor} ${checked ? 28 : 12}%, transparent)`,
          color: checked ? iconColor : 'var(--fg-muted)',
          transition: 'all var(--dur-2) var(--ease-out)',
        }}>
          {icon}
        </div>
        <div style={{ minWidth: 0 }}>
          <p style={{
            fontSize: 13, fontWeight: 600, color: 'var(--fg-primary)',
            margin: 0, letterSpacing: '-0.01em',
          }}>
            {title}
          </p>
          <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '3px 0 0', lineHeight: 1.5 }}>
            {description}
          </p>
        </div>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════
   Strategy Catalog Hero — animated ring + quick stats + bulk controls
   ═══════════════════════════════════════════════════════════════════════ */
function StrategyCatalogHero({
  enabledCount, totalStrategies, onEnableAll, onDisableAll,
}: {
  enabledCount: number;
  totalStrategies: number;
  onEnableAll: () => void;
  onDisableAll: () => void;
}) {
  const pct = totalStrategies === 0 ? 0 : (enabledCount / totalStrategies) * 100;

  // Ring geometry
  const size = 104;
  const stroke = 9;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = (pct / 100) * c;

  // Status label driven by ratio
  const status =
    pct >= 80 ? { text: 'Fully Armed', color: 'var(--bull)' } :
    pct >= 40 ? { text: 'Live',        color: 'var(--accent-2)' } :
    pct > 0   ? { text: 'Partial',     color: 'var(--warn)' } :
                { text: 'Idle',        color: 'var(--fg-muted)' };

  return (
    <div
      className="lt-bento"
      style={{
        position: 'relative', overflow: 'hidden',
        padding: 0,
      }}
    >
      {/* Ambient dual-tone gradient backdrop */}
      <div aria-hidden style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background:
          'radial-gradient(100% 80% at 0% 0%, color-mix(in srgb, var(--warn) 14%, transparent) 0%, transparent 50%), radial-gradient(90% 100% at 100% 100%, color-mix(in srgb, var(--accent) 12%, transparent) 0%, transparent 55%)',
      }} />

      <div style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: 'auto 1fr auto',
        gap: 24, alignItems: 'center',
        padding: '20px 24px',
      }} className="strategy-hero-grid">
        {/* ── Ring ────────────────────────────────────────── */}
        <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
          <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block' }}>
            <defs>
              <linearGradient id="strategy-ring" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="var(--accent)" />
                <stop offset="100%" stopColor="var(--accent-2)" />
              </linearGradient>
            </defs>
            {/* Track */}
            <circle
              cx={size / 2} cy={size / 2} r={r}
              fill="none" stroke="var(--line-2)" strokeWidth={stroke}
            />
            {/* Progress */}
            <motion.circle
              cx={size / 2} cy={size / 2} r={r}
              fill="none"
              stroke="url(#strategy-ring)"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={c}
              initial={{ strokeDashoffset: c }}
              animate={{ strokeDashoffset: c - dash }}
              transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
              style={{
                transform: `rotate(-90deg)`,
                transformOrigin: 'center',
                filter: 'drop-shadow(0 0 6px var(--accent-glow))',
              }}
            />
          </svg>
          {/* Center label */}
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
          }}>
            <span
              className="lt-tabular"
              style={{
                fontSize: 22, fontWeight: 800, color: 'var(--fg-primary)',
                letterSpacing: '-0.03em', lineHeight: 1,
              }}
            >
              {enabledCount}
              <span style={{ fontSize: 12, color: 'var(--fg-muted)', fontWeight: 700 }}>
                /{totalStrategies}
              </span>
            </span>
            <span style={{
              fontSize: 8, fontWeight: 800, letterSpacing: '0.16em',
              color: 'var(--fg-muted)', textTransform: 'uppercase',
              marginTop: 3,
            }}>
              Live
            </span>
          </div>
        </div>

        {/* ── Copy + status pill ────────────────────────── */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <div style={{
              width: 28, height: 28, borderRadius: 'var(--r-sm)',
              display: 'grid', placeItems: 'center',
              background: 'var(--warn-soft)',
              border: '1px solid color-mix(in srgb, var(--warn) 28%, transparent)',
              color: 'var(--warn)',
            }}>
              <Zap size={14} />
            </div>
            <h3 style={{
              fontSize: 16, fontWeight: 800, color: 'var(--fg-primary)',
              margin: 0, letterSpacing: '-0.02em',
            }}>
              Strategy Catalog
            </h3>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              fontSize: 9, fontWeight: 800, letterSpacing: '0.12em',
              padding: '3px 9px', borderRadius: 'var(--r-pill)',
              background: `color-mix(in srgb, ${status.color} 14%, transparent)`,
              color: status.color,
              border: `1px solid color-mix(in srgb, ${status.color} 30%, transparent)`,
              textTransform: 'uppercase',
            }}>
              <span style={{
                width: 5, height: 5, borderRadius: '50%',
                background: status.color,
                boxShadow: `0 0 6px ${status.color}`,
              }} />
              {status.text}
            </span>
          </div>
          <p style={{
            fontSize: 13, color: 'var(--fg-secondary)',
            margin: '0 0 14px', lineHeight: 1.55, maxWidth: 520,
          }}>
            Toggle algos on or off and fine-tune their parameters. Changes apply live the next time
            the engine ticks — no restart required.
          </p>

          {/* Quick stats row */}
          <div style={{
            display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center',
          }}>
            <QuickStat
              color="var(--bull)"
              label="Enabled"
              value={enabledCount}
            />
            <span style={{ width: 1, height: 22, background: 'var(--line-2)' }} />
            <QuickStat
              color="var(--fg-muted)"
              label="Disabled"
              value={totalStrategies - enabledCount}
            />
            <span style={{ width: 1, height: 22, background: 'var(--line-2)' }} />
            <QuickStat
              color="var(--accent-2)"
              label="Coverage"
              value={`${Math.round(pct)}%`}
              mono
            />
          </div>
        </div>

        {/* ── Bulk actions ─────────────────────────────── */}
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0,
        }} className="strategy-hero-actions">
          <button
            onClick={onEnableAll}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7,
              padding: '10px 16px', borderRadius: 'var(--r-sm)',
              background: 'linear-gradient(135deg, var(--bull), #00a76a)',
              color: '#001f14', border: 'none',
              fontSize: 12, fontWeight: 800, letterSpacing: '0.02em',
              cursor: 'pointer',
              boxShadow: '0 6px 16px var(--bull-glow)',
              minWidth: 140,
            }}
          >
            <CheckCircle size={13} strokeWidth={2.6} />
            <span>Enable all</span>
          </button>
          <button
            onClick={onDisableAll}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7,
              padding: '10px 16px', borderRadius: 'var(--r-sm)',
              background: 'var(--surface-3)',
              color: 'var(--fg-secondary)',
              border: '1px solid var(--line-2)',
              fontSize: 12, fontWeight: 700,
              cursor: 'pointer',
              minWidth: 140,
            }}
          >
            <XCircle size={13} strokeWidth={2.4} />
            <span>Disable all</span>
          </button>
        </div>
      </div>

      {/* Responsive stack for narrow screens */}
      <style>{`
        @media (max-width: 720px) {
          .strategy-hero-grid { grid-template-columns: 1fr !important; gap: 18px !important; }
          .strategy-hero-actions { flex-direction: row !important; }
          .strategy-hero-actions > button { flex: 1; }
        }
      `}</style>
    </div>
  );
}

function QuickStat({
  color, label, value, mono,
}: { color: string; label: string; value: number | string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: color,
        boxShadow: `0 0 8px color-mix(in srgb, ${color} 60%, transparent)`,
      }} />
      <div>
        <p
          className={mono ? 'lt-tabular' : undefined}
          style={{
            fontSize: 18, fontWeight: 800, color: 'var(--fg-primary)',
            margin: 0, letterSpacing: '-0.02em', lineHeight: 1,
          }}
        >
          {value}
        </p>
        <p style={{
          fontSize: 9, fontWeight: 800, letterSpacing: '0.12em',
          color: 'var(--fg-muted)', margin: '3px 0 0',
          textTransform: 'uppercase',
        }}>
          {label}
        </p>
      </div>
    </div>
  );
}
