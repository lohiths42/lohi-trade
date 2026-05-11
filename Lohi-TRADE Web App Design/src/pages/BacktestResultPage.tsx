import { useParams, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { ArrowLeft, Download, Rocket, Copy, FlaskConical } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import ChartSwitcher from '../components/shared/ChartSwitcher';
import { bentoStagger, revealVariants } from '../lib/motion';

/**
 * BacktestResultPage — spec §2.9 /backtest/:run_id
 * Summary metrics, equity curve, trade list, deploy/save/clone actions.
 */
export default function BacktestResultPage() {
  const { run_id } = useParams();
  const navigate = useNavigate();
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const id = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) { setDone(true); clearInterval(id); return 100; }
        return Math.min(100, p + 9);
      });
    }, 200);
    return () => clearInterval(id);
  }, []);

  const equity = Array.from({ length: 40 }, (_, i) => ({
    x: `Day ${i + 1}`,
    y: 200_000 + i * 300 + Math.random() * 200,
  }));

  const metrics = {
    totalReturn: 21450, cagr: 14.6, sharpe: 1.48, sortino: 1.92,
    maxDD: 7.3, winRate: 58.4, profitFactor: 1.62, trades: 142, avgDuration: '18m',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<FlaskConical size={16} />}
        title={`Backtest · ${run_id}`}
        subtitle={done ? 'Complete · deploy to paper or live' : `Running · ${progress}%`}
        actions={
          <>
            <button onClick={() => navigate('/backtest/new')} style={chipBtn}><ArrowLeft size={12} /> New</button>
            <button style={chipBtn}><Download size={12} /> Save PDF</button>
            <button style={chipBtn}><Copy size={12} /> Clone run</button>
            {done && (
              <button style={primaryBtn}>
                <Rocket size={12} /> Deploy
              </button>
            )}
          </>
        }
      />

      {!done && (
        <BentoCard>
          <div style={{ padding: 24 }}>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, margin: 0 }}>Execution progress</p>
            <div style={{ marginTop: 12, height: 8, borderRadius: 999, background: 'var(--surface-4)', overflow: 'hidden' }}>
              <motion.div
                animate={{ width: `${progress}%` }}
                transition={{ ease: 'easeOut', duration: 0.2 }}
                style={{ height: '100%', background: 'linear-gradient(90deg, var(--accent), var(--accent-2))' }}
              />
            </div>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 8, fontFamily: 'ui-monospace, monospace' }}>{progress}% · ETA 2s</p>
          </div>
        </BentoCard>
      )}

      {done && (
        <>
          <motion.div variants={bentoStagger} initial="hidden" animate="visible" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 14 }}>
            <MetricPill label="Total Return" value={metrics.totalReturn} format={(v) => `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} color="var(--bull)" />
            <MetricPill label="CAGR" value={metrics.cagr} format={(v) => `${v.toFixed(2)}%`} color="var(--bull)" />
            <MetricPill label="Sharpe" value={metrics.sharpe} format={(v) => v.toFixed(2)} color={metrics.sharpe >= 1 ? 'var(--bull)' : 'var(--warn)'} />
            <MetricPill label="Max Drawdown" value={metrics.maxDD} format={(v) => `-${v.toFixed(1)}%`} color="var(--bear)" />
            <MetricPill label="Win Rate" value={metrics.winRate} format={(v) => `${v.toFixed(1)}%`} color={metrics.winRate >= 50 ? 'var(--bull)' : 'var(--warn)'} />
          </motion.div>

          <BentoCard reveal>
            <div style={{ padding: 24 }}>
              <h3 style={sideTitle}>Equity curve</h3>
              <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '4px 0 14px' }}>Drawdown filled area + trade markers available on full detail view</p>
              <ChartSwitcher
                id={`backtest-result-${run_id}`}
                height={260}
                defaultKind="area"
                allowedKinds={['area', 'line', 'bar']}
                seriesLabel="Equity"
                color="var(--bull)"
                valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
                linearData={equity}
              />
            </div>
          </BentoCard>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <BentoCard reveal>
              <div style={{ padding: 24 }}>
                <h3 style={sideTitle}>Additional metrics</h3>
                <dl style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '8px 12px', fontSize: 12, margin: '12px 0 0' }}>
                  <dt style={dt}>Sortino</dt><dd style={dd}>{metrics.sortino.toFixed(2)}</dd>
                  <dt style={dt}>Profit factor</dt><dd style={dd}>{metrics.profitFactor.toFixed(2)}</dd>
                  <dt style={dt}>Total trades</dt><dd style={dd}>{metrics.trades}</dd>
                  <dt style={dt}>Avg duration</dt><dd style={dd}>{metrics.avgDuration}</dd>
                </dl>
              </div>
            </BentoCard>
            <BentoCard reveal accent="indigo">
              <div style={{ padding: 24 }}>
                <h3 style={sideTitle}>Deploy</h3>
                <p style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 6, lineHeight: 1.5 }}>
                  Deploying creates a pre-configured Soldier you can start in paper or live mode. LIVE deploys require mode activation first.
                </p>
                <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                  <button style={primaryBtn}>Deploy to Paper</button>
                  <button style={{ ...chipBtn, borderColor: 'color-mix(in srgb, var(--bear) 30%, transparent)', color: 'var(--bear)' }}>Deploy to Live</button>
                </div>
              </div>
            </BentoCard>
          </div>
        </>
      )}
    </div>
  );
}

function MetricPill({ label, value, format, color }: { label: string; value: number; format: (v: number) => string; color: string }) {
  return (
    <BentoCard accent="none">
      <motion.div variants={revealVariants} style={{ padding: 18, minHeight: 96 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
        <p className="lt-tabular" style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: '-0.02em', marginTop: 10 }}>
          <AnimatedNumber value={value} format={format} color={color} />
        </p>
      </motion.div>
    </BentoCard>
  );
}

const sideTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
};
const chipBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 10px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 14px',
  borderRadius: 'var(--r-sm)',
  background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent) 95%, white 5%), var(--accent))',
  border: '1px solid color-mix(in srgb, var(--accent) 60%, transparent)',
  color: '#fff', fontSize: 11, fontWeight: 700, cursor: 'pointer',
  boxShadow: '0 1px 0 rgba(255,255,255,0.15) inset, 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent)',
};
const dt: React.CSSProperties = { color: 'var(--fg-muted)', fontWeight: 500 };
const dd: React.CSSProperties = { color: 'var(--fg-primary)', margin: 0, textAlign: 'right', fontWeight: 600 };
