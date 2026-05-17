import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  X, Play, Square, Loader2, Zap, Database, Clock, Gauge,
  TrendingUp, Shield, ChevronRight, CheckCircle2, Info,
} from 'lucide-react';
import { useThemeColors, type ThemeColors } from '../../hooks/use-theme-colors';
import type { PaperTradingStatus } from '../../lib/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onStart: (cfg: { capital: number; days: number; speed: number; useRealData: boolean }) => Promise<void>;
  onStop: () => void;
  status: PaperTradingStatus;
  loading: boolean;
}

const PRESETS = [
  { id: 'quick', label: 'Quick Test', desc: '1 day · 100x speed', icon: Zap, color: '#fbbf24', capital: 200000, days: 1, speed: 100, useRealData: true },
  { id: 'standard', label: 'Standard', desc: '5 days · 50x speed', icon: TrendingUp, color: '#34d399', capital: 200000, days: 5, speed: 50, useRealData: true },
  { id: 'deep', label: 'Deep Run', desc: '20 days · 20x speed', icon: Shield, color: '#60a5fa', capital: 500000, days: 20, speed: 20, useRealData: true },
];

function Slider({ label, value, min, max, step, onChange, format, t }: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; format: (v: number) => string; t: ThemeColors;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: t.textMuted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
        <span style={{ fontSize: 14, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: t.textPrimary }}>{format(value)}</span>
      </div>
      <div style={{ position: 'relative', height: 6, borderRadius: 3, background: t.isLight ? '#e2e8f0' : 'rgba(30,41,59,0.9)' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`, borderRadius: 3, background: 'linear-gradient(to right, #3b82f6, #6366f1)', transition: 'width 0.1s' }} />
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{ position: 'absolute', inset: 0, width: '100%', opacity: 0, cursor: 'pointer', height: '100%' }} />
        <div style={{ position: 'absolute', top: '50%', left: `${pct}%`, transform: 'translate(-50%, -50%)', width: 16, height: 16, borderRadius: '50%', background: '#6366f1', border: '2px solid #818cf8', boxShadow: '0 0 10px rgba(99,102,241,0.5)', pointerEvents: 'none' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        <span style={{ fontSize: 10, color: t.textMuted }}>{format(min)}</span>
        <span style={{ fontSize: 10, color: t.textMuted }}>{format(max)}</span>
      </div>
    </div>
  );
}

function RunningPanel({ status, onStop, loading, t }: { status: PaperTradingStatus; onStop: () => void; loading: boolean; t: ThemeColors }) {
  const elapsed = status.startedAt ? Math.floor((Date.now() - new Date(status.startedAt).getTime()) / 1000) : 0;
  const hh = Math.floor(elapsed / 3600).toString().padStart(2, '0');
  const mm = Math.floor((elapsed % 3600) / 60).toString().padStart(2, '0');
  const ss = (elapsed % 60).toString().padStart(2, '0');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '14px 0' }}>
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#34d399', boxShadow: '0 0 12px #34d399' }} className="animate-pulse" />
        <span style={{ fontSize: 13, fontWeight: 800, color: '#34d399', letterSpacing: '0.12em' }}>SIMULATION RUNNING</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {[
          { label: 'Capital', value: `₹${(status.capital ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, icon: Database, color: '#60a5fa' },
          { label: 'Duration', value: `${status.days ?? 0} days`, icon: Clock, color: '#a78bfa' },
          { label: 'Speed', value: `${status.speed ?? 0}x`, icon: Gauge, color: '#fbbf24' },
          { label: 'Elapsed', value: `${hh}:${mm}:${ss}`, icon: Zap, color: '#34d399' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} style={{ padding: '16px 18px', borderRadius: 12, background: t.bgMuted, border: `1px solid ${t.borderPrimary}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ padding: 6, borderRadius: 7, background: `${color}15` }}>
                <Icon size={14} color={color} />
              </div>
              <span style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
            </div>
            <p style={{ fontSize: 20, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color, margin: 0 }}>{value}</p>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderRadius: 10, background: 'rgba(52,211,153,0.06)', border: '1px solid rgba(52,211,153,0.15)' }}>
        <CheckCircle2 size={16} color="#34d399" />
        <span style={{ fontSize: 12, color: t.textSecondary }}>
          Using <span style={{ color: '#34d399', fontWeight: 600 }}>{status.useRealData ? 'real NSE historical data' : 'synthetic data'}</span> for price simulation
        </span>
      </div>

      <button onClick={onStop} disabled={loading}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
          padding: '14px', borderRadius: 12, border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
          background: 'linear-gradient(135deg, #dc2626, #b91c1c)', color: 'white', fontWeight: 700, fontSize: 14,
          boxShadow: '0 4px 20px rgba(220,38,38,0.3)', opacity: loading ? 0.7 : 1,
        }}>
        {loading ? <Loader2 size={18} className="animate-spin" /> : <Square size={18} strokeWidth={3} />}
        Stop Simulation
      </button>
    </div>
  );
}

function ConfigPanel({ onStart, loading, t }: { onStart: Props['onStart']; loading: boolean; t: ThemeColors }) {
  const [selectedPreset, setSelectedPreset] = useState<string | null>('standard');
  const [capital, setCapital] = useState(200000);
  const [days, setDays] = useState(5);
  const [speed, setSpeed] = useState(50);
  const [useRealData, setUseRealData] = useState(true);

  const applyPreset = (p: typeof PRESETS[0]) => { setSelectedPreset(p.id); setCapital(p.capital); setDays(p.days); setSpeed(p.speed); setUseRealData(p.useRealData); };
  const handleCustomChange = () => setSelectedPreset(null);

  const estimatedTime = Math.ceil((days * 375 * 60) / speed);
  const etMin = Math.floor(estimatedTime / 60);
  const etSec = estimatedTime % 60;
  const etLabel = etMin > 0 ? `~${etMin}m ${etSec}s` : `~${etSec}s`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div>
        <p style={{ fontSize: 11, color: t.textMuted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12 }}>Quick Presets</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {PRESETS.map((p) => {
            const Icon = p.icon;
            const active = selectedPreset === p.id;
            return (
              <button key={p.id} onClick={() => applyPreset(p)}
                style={{
                  padding: '14px 12px', borderRadius: 12, cursor: 'pointer', textAlign: 'left',
                  background: active ? `${p.color}12` : t.bgMuted,
                  border: `1px solid ${active ? p.color + '40' : t.borderPrimary}`,
                  transition: 'all 0.15s',
                  boxShadow: active ? `0 0 16px ${p.color}15` : 'none',
                }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <div style={{ padding: 6, borderRadius: 7, background: `${p.color}18` }}>
                    <Icon size={14} color={p.color} />
                  </div>
                  {active && <CheckCircle2 size={13} color={p.color} style={{ marginLeft: 'auto' }} />}
                </div>
                <p style={{ fontSize: 13, fontWeight: 700, color: active ? p.color : t.textPrimary, margin: '0 0 2px' }}>{p.label}</p>
                <p style={{ fontSize: 10, color: t.textMuted, margin: 0 }}>{p.desc}</p>
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ height: 1, background: t.borderPrimary }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
        <p style={{ fontSize: 11, color: t.textMuted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', margin: 0 }}>Custom Configuration</p>
        <Slider label="Capital" value={capital} min={50000} max={2000000} step={50000}
          onChange={(v) => { setCapital(v); handleCustomChange(); }} format={(v) => `₹${(v / 100000).toFixed(1)}L`} t={t} />
        <Slider label="Trading Days" value={days} min={1} max={30} step={1}
          onChange={(v) => { setDays(v); handleCustomChange(); }} format={(v) => `${v}d`} t={t} />
        <Slider label="Simulation Speed" value={speed} min={1} max={200} step={1}
          onChange={(v) => { setSpeed(v); handleCustomChange(); }} format={(v) => `${v}x`} t={t} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderRadius: 12, background: t.bgMuted, border: `1px solid ${t.borderPrimary}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ padding: 8, borderRadius: 9, background: useRealData ? 'rgba(52,211,153,0.12)' : t.bgMuted }}>
            <Database size={16} color={useRealData ? '#34d399' : t.textMuted} />
          </div>
          <div>
            <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>Real NSE Market Data</p>
            <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0' }}>Historical prices from Yahoo Finance</p>
          </div>
        </div>
        <button onClick={() => setUseRealData(!useRealData)}
          style={{ width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer', position: 'relative', flexShrink: 0,
            background: useRealData ? '#059669' : (t.isLight ? '#cbd5e1' : 'rgba(30,41,59,0.9)'), transition: 'background 0.2s' }}>
          <div style={{ position: 'absolute', top: 3, left: useRealData ? 23 : 3, width: 18, height: 18,
            borderRadius: '50%', background: 'white', transition: 'left 0.2s', boxShadow: '0 1px 4px rgba(0,0,0,0.3)' }} />
        </button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderRadius: 10, background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.15)' }}>
        <Info size={14} color="#818cf8" style={{ flexShrink: 0 }} />
        <span style={{ fontSize: 12, color: t.textSecondary }}>
          Simulating <span style={{ color: t.textPrimary, fontWeight: 600 }}>{days} trading day{days > 1 ? 's' : ''}</span> at <span style={{ color: t.textPrimary, fontWeight: 600 }}>{speed}x</span> speed — estimated real time: <span style={{ color: '#818cf8', fontWeight: 700 }}>{etLabel}</span>
        </span>
      </div>

      <button onClick={() => onStart({ capital, days, speed, useRealData })} disabled={loading}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
          padding: '15px', borderRadius: 12, border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
          background: 'linear-gradient(135deg, #059669 0%, #047857 100%)', color: 'white', fontWeight: 800, fontSize: 15, letterSpacing: '0.02em',
          boxShadow: '0 4px 24px rgba(5,150,105,0.35)', opacity: loading ? 0.7 : 1, transition: 'opacity 0.15s, transform 0.1s',
        }}>
        {loading ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} strokeWidth={3} />}
        {loading ? 'Starting Simulation…' : 'Launch Paper Trading'}
        {!loading && <ChevronRight size={16} style={{ opacity: 0.7 }} />}
      </button>
    </div>
  );
}

export default function PaperTradeModal({ open, onClose, onStart, onStop, status, loading }: Props) {
  const isRunning = status.running;
  const t = useThemeColors();

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay, backdropFilter: 'blur(6px)' }}
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.94, opacity: 0, y: 16 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.94, opacity: 0, y: 16 }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
            style={{
              width: '100%', maxWidth: 520, maxHeight: '90vh', overflowY: 'auto',
              borderRadius: 20,
              background: t.isLight ? t.bgCard : 'linear-gradient(160deg, #0d1526 0%, #080d1a 100%)',
              border: `1px solid ${t.borderPrimary}`,
              boxShadow: t.isLight
                ? '0 24px 80px rgba(0,0,0,0.1), 0 0 0 1px rgba(99,102,241,0.06)'
                : '0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(99,102,241,0.08)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '22px 24px 18px', borderBottom: `1px solid ${t.borderPrimary}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: isRunning
                    ? 'linear-gradient(135deg, rgba(52,211,153,0.2), rgba(16,185,129,0.1))'
                    : 'linear-gradient(135deg, rgba(99,102,241,0.2), rgba(59,130,246,0.1))',
                  border: `1px solid ${isRunning ? 'rgba(52,211,153,0.25)' : 'rgba(99,102,241,0.25)'}`,
                }}>
                  {isRunning ? <Zap size={20} color="#34d399" /> : <Play size={20} color="#818cf8" />}
                </div>
                <div>
                  <h2 style={{ fontSize: 17, fontWeight: 800, color: t.textPrimary, margin: 0, letterSpacing: '-0.01em' }}>
                    {isRunning ? 'Simulation Active' : 'Paper Trading'}
                  </h2>
                  <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0' }}>
                    {isRunning ? 'Running with real market patterns' : 'Test strategies with zero risk'}
                  </p>
                </div>
              </div>
              <button onClick={onClose}
                style={{ padding: 8, borderRadius: 9, background: t.bgMuted, border: `1px solid ${t.borderPrimary}`, cursor: 'pointer', color: t.textMuted, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: '24px' }}>
              {isRunning
                ? <RunningPanel status={status} onStop={onStop} loading={loading} t={t} />
                : <ConfigPanel onStart={onStart} loading={loading} t={t} />
              }
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
