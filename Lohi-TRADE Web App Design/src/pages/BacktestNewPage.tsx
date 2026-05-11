import { useState } from 'react';
import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { FlaskConical, Play, Upload, Database, FileChartLine } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';

/**
 * BacktestNewPage — spec §2.8 /backtest/new.
 * Configures & launches a backtest. Submit enqueues a job and navigates
 * to /backtest/:run_id for live progress.
 */

const DATA_SOURCES = [
  { id: 'csv', label: 'CSV upload', icon: Upload, blurb: 'Bring your own OHLCV data (kite/dhan compatible)' },
  { id: 'bhav', label: 'NSE Bhavcopy', icon: Database, blurb: 'Auto-downloaded from official archive' },
  { id: 'yf', label: 'Yahoo Finance', icon: FileChartLine, blurb: 'Educational only · may rate-limit' },
];
const RESOLUTIONS = ['Tick', '1m', '5m', '15m', '1h', '1d'];
const FILL_POLICIES = ['Next bar open', 'Current bar close'];
const SLIPPAGE = ['Fixed bps', 'Percentage', 'Market impact'];
const COMMISSIONS = ['Zerodha', 'Dhan', 'Upstox', 'Custom (Indian)'];
const OPT_MODES = ['Single run', 'Grid search', 'Walk-forward'];

export default function BacktestNewPage() {
  const navigate = useNavigate();
  const [strategy, setStrategy] = useState('SMA Crossover');
  const [source, setSource] = useState('bhav');
  const [symbols, setSymbols] = useState('RELIANCE, TCS');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [resolution, setResolution] = useState('5m');
  const [capital, setCapital] = useState('200000');
  const [slippage, setSlippage] = useState(SLIPPAGE[0]);
  const [commission, setCommission] = useState(COMMISSIONS[0]);
  const [fill, setFill] = useState(FILL_POLICIES[0]);
  const [opt, setOpt] = useState('Single run');
  const [running, setRunning] = useState(false);

  const launch = () => {
    setRunning(true);
    // Real impl: POST /api/backtests → get runId → navigate.
    const runId = 'run_' + Date.now().toString(36);
    setTimeout(() => navigate(`/backtest/${runId}`), 400);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<FlaskConical size={16} />}
        title="New backtest"
        subtitle="Configure data, execution, and optimization · then launch"
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16 }}>
        {/* Left — config */}
        <BentoCard reveal>
          <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="Strategy">
              <select value={strategy} onChange={(e) => setStrategy(e.target.value)} style={input}>
                {['SMA Crossover', 'RSI Mean Reversion', 'VWAP Bounce', 'Opening Range Breakout'].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>

            <Field label="Data source">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                {DATA_SOURCES.map((s) => {
                  const active = source === s.id;
                  const Icon = s.icon;
                  return (
                    <button
                      key={s.id}
                      onClick={() => setSource(s.id)}
                      style={{
                        padding: '12px 10px', borderRadius: 'var(--r-sm)', textAlign: 'left',
                        background: active ? 'color-mix(in srgb, var(--accent) 10%, transparent)' : 'var(--surface-3)',
                        border: active ? '1px solid color-mix(in srgb, var(--accent) 32%, transparent)' : '1px solid var(--line-2)',
                        color: 'var(--fg-primary)', cursor: 'pointer',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600 }}>
                        <Icon size={12} /> {s.label}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 4 }}>{s.blurb}</div>
                    </button>
                  );
                })}
              </div>
            </Field>

            <Field label="Symbols (comma-separated)">
              <input value={symbols} onChange={(e) => setSymbols(e.target.value)} style={input} />
            </Field>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
              <Field label="From"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={input} /></Field>
              <Field label="To"><input type="date" value={to} onChange={(e) => setTo(e.target.value)} style={input} /></Field>
              <Field label="Resolution">
                <select value={resolution} onChange={(e) => setResolution(e.target.value)} style={input}>
                  {RESOLUTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </Field>
            </div>

            <div style={{ borderTop: '1px solid var(--line-2)', marginTop: 4, paddingTop: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Starting capital (₹)">
                  <input value={capital} onChange={(e) => setCapital(e.target.value.replace(/\D/g, ''))} style={input} />
                </Field>
                <Field label="Fill policy">
                  <select value={fill} onChange={(e) => setFill(e.target.value)} style={input}>
                    {FILL_POLICIES.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </Field>
                <Field label="Slippage">
                  <select value={slippage} onChange={(e) => setSlippage(e.target.value)} style={input}>
                    {SLIPPAGE.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
                <Field label="Commission model">
                  <select value={commission} onChange={(e) => setCommission(e.target.value)} style={input}>
                    {COMMISSIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </Field>
              </div>
            </div>

            <Field label="Optimization">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                {OPT_MODES.map((o) => {
                  const active = opt === o;
                  return (
                    <button key={o} onClick={() => setOpt(o)} style={{
                      padding: '8px 10px', borderRadius: 'var(--r-sm)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      background: active ? 'var(--surface-2)' : 'transparent',
                      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
                      color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
                    }}>{o}</button>
                  );
                })}
              </div>
            </Field>

            <button
              onClick={launch}
              disabled={running}
              style={{
                marginTop: 8, padding: '11px 16px', borderRadius: 'var(--r-sm)',
                background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
                border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
                color: '#fff', fontSize: 13, fontWeight: 700,
                cursor: running ? 'not-allowed' : 'pointer',
                opacity: running ? 0.6 : 1,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
              }}
            >
              <Play size={14} /> {running ? 'Launching…' : 'Run backtest'}
            </button>
          </div>
        </BentoCard>

        {/* Right — summary */}
        <BentoCard reveal accent="indigo">
          <div style={{ padding: 24 }}>
            <h3 style={sideTitle}>Summary</h3>
            <dl style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '8px 14px', fontSize: 12, margin: '12px 0 0' }}>
              <dt style={dt}>Strategy</dt><dd style={dd}>{strategy}</dd>
              <dt style={dt}>Source</dt><dd style={dd}>{DATA_SOURCES.find((d) => d.id === source)?.label}</dd>
              <dt style={dt}>Symbols</dt><dd style={dd}>{symbols.split(',').filter(Boolean).length || 0}</dd>
              <dt style={dt}>Resolution</dt><dd style={dd}>{resolution}</dd>
              <dt style={dt}>Range</dt><dd style={dd}>{from || '—'} → {to || '—'}</dd>
              <dt style={dt}>Capital</dt><dd style={dd}>₹{parseInt(capital || '0').toLocaleString('en-IN')}</dd>
              <dt style={dt}>Slippage</dt><dd style={dd}>{slippage}</dd>
              <dt style={dt}>Commission</dt><dd style={dd}>{commission}</dd>
              <dt style={dt}>Fill</dt><dd style={dd}>{fill}</dd>
              <dt style={dt}>Optimization</dt><dd style={dd}>{opt}</dd>
            </dl>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 16, lineHeight: 1.5 }}>
              Backtests are event-driven and match live-trading semantics. You can deploy a successful run directly to paper or live from the results page.
            </p>
          </div>
        </BentoCard>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

const input: React.CSSProperties = {
  width: '100%', padding: '9px 11px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
};
const sideTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
};
const dt: React.CSSProperties = { color: 'var(--fg-muted)', fontWeight: 500 };
const dd: React.CSSProperties = { color: 'var(--fg-primary)', margin: 0, textAlign: 'right', fontWeight: 600 };
