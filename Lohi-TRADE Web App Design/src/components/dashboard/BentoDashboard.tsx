import { motion } from 'motion/react';
import { TrendingUp, TrendingDown, Activity, Wallet, Target, Shield } from 'lucide-react';
import { BentoCard } from '../shared/BentoCard';
import { AnimatedNumber } from '../shared/AnimatedNumber';
import { bentoStagger, revealVariants } from '../../lib/motion';

/**
 * BentoDashboard — a drop-in demonstration of the modernized layout.
 * Plug in real store values in place of the `metrics` props. Matches the
 * hero row of the existing DashboardPage but with:
 *   • 12-col bento grid (Linear/Vercel style)
 *   • Animated numeric tickers (spring-interpolated)
 *   • Corner accent glows + hairline borders
 *   • Staggered reveal on mount
 */
export interface DashboardMetrics {
  portfolioValue: number;
  capital: number;
  realizedPnl: number;
  unrealizedPnl: number;
  winRate: number;
  tradesCount: number;
  openPositions: number;
  profitablePositions: number;
}

const INR = (n: number) =>
  `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export default function BentoDashboard({ metrics }: { metrics: DashboardMetrics }) {
  const dayPnl = metrics.realizedPnl + metrics.unrealizedPnl;
  const ret = metrics.capital > 0 ? ((metrics.portfolioValue - metrics.capital) / metrics.capital) * 100 : 0;

  return (
    <motion.div
      variants={bentoStagger}
      initial="hidden"
      animate="visible"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(12, 1fr)',
        gridAutoRows: 'minmax(120px, auto)',
        gap: 'var(--space-4)',
      }}
    >
      {/* ── HERO: Portfolio (spans 6 cols, 2 rows) ───────────────── */}
      <BentoCard colSpan={6} rowSpan={2} accent="indigo">
        <motion.div variants={revealVariants} style={{ padding: '28px 32px', display: 'flex', flexDirection: 'column', height: '100%', justifyContent: 'space-between' }}>
          <div>
            <p style={label}>Portfolio Value</p>
            <div style={{ fontSize: 48, fontWeight: 800, letterSpacing: '-0.035em', lineHeight: 1, marginTop: 12, color: 'var(--fg-primary)' }}>
              <AnimatedNumber value={metrics.portfolioValue} format={INR} durationMs={420} flash={false} />
            </div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 14, padding: '6px 12px', borderRadius: 8,
              background: ret >= 0 ? 'var(--bull-soft)' : 'var(--bear-soft)' }}>
              {ret >= 0 ? <TrendingUp size={14} color="var(--bull)" /> : <TrendingDown size={14} color="var(--bear)" />}
              <span className="lt-tabular" style={{ fontWeight: 700, fontSize: 13, color: ret >= 0 ? 'var(--bull)' : 'var(--bear)' }}>
                <AnimatedNumber value={ret} format={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`} durationMs={420} flash={false} color={ret >= 0 ? 'var(--bull)' : 'var(--bear)'} />
              </span>
              <span style={{ color: 'var(--fg-muted)', fontSize: 12 }}>from {INR(metrics.capital)}</span>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, paddingTop: 20, borderTop: '1px solid var(--line-2)' }}>
            <SubMetric label="Today's P&L" value={dayPnl} format={INR} semantic />
            <SubMetric label="Invested" value={metrics.capital} format={INR} />
          </div>
        </motion.div>
      </BentoCard>

      {/* ── Metric cards ──────────────────────────────────────────── */}
      <BentoCard colSpan={3} accent="emerald">
        <MetricBlock label="Realized P&L" value={metrics.realizedPnl} icon={<TrendingUp size={16} />} semantic />
      </BentoCard>

      <BentoCard colSpan={3} accent="rose">
        <MetricBlock label="Unrealized P&L" value={metrics.unrealizedPnl} icon={<Activity size={16} />} semantic />
      </BentoCard>

      <BentoCard colSpan={3}>
        <MetricBlock
          label="Win Rate"
          value={metrics.winRate}
          format={(v) => `${v.toFixed(1)}%`}
          sub={`${metrics.tradesCount} trades total`}
          icon={<Target size={16} />}
          color={metrics.winRate >= 50 ? 'var(--bull)' : 'var(--warn)'}
        />
      </BentoCard>

      <BentoCard colSpan={3} accent="cyan">
        <MetricBlock
          label="Open Positions"
          value={metrics.openPositions}
          format={(v) => String(Math.round(v))}
          sub={`${metrics.profitablePositions} in profit`}
          icon={<Shield size={16} />}
          color="var(--accent-2)"
        />
      </BentoCard>

      {/* ── Chart strip (spans 8) ─────────────────────────────────── */}
      <BentoCard colSpan={8} rowSpan={2} reveal>
        <div style={{ padding: 24, height: '100%', minHeight: 280 }}>
          <header style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-primary)', margin: 0 }}>Equity Curve</h3>
              <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 4 }}>Cumulative P&L · last 30 days</p>
            </div>
          </header>
          {/* slot your existing Recharts / Lightweight-Charts canvas here */}
          <div style={{ height: 'calc(100% - 48px)', display: 'grid', placeItems: 'center', color: 'var(--fg-muted)', fontSize: 12 }}>
            &lt;- wire existing &lt;AreaChart /&gt; here -&gt;
          </div>
        </div>
      </BentoCard>

      {/* ── Side column: Wallet + Strategies (spans 4) ───────────── */}
      <BentoCard colSpan={4} reveal>
        <div style={{ padding: 24 }}>
          <header style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ padding: 6, borderRadius: 8, background: 'var(--bull-soft)' }}>
              <Wallet size={14} color="var(--bull)" />
            </div>
            <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-primary)', margin: 0 }}>Wallet</h3>
          </header>
          <p style={{ fontSize: 32, fontWeight: 700, marginTop: 16, letterSpacing: '-0.02em', color: 'var(--fg-primary)' }} className="lt-tabular">
            <AnimatedNumber value={metrics.capital + dayPnl} format={INR} />
          </p>
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 4 }}>Available buying power</p>
        </div>
      </BentoCard>

      <BentoCard colSpan={4} reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg-primary)', margin: 0 }}>Active Strategies</h3>
          <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 4 }}>3 running · 1 paused</p>
          {/* slot strategy list here */}
        </div>
      </BentoCard>
    </motion.div>
  );
}

/* ── small atoms ─────────────────────────────────────────────────── */

const label: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--fg-muted)',
};

function SubMetric({ label: l, value, format, semantic = false }: { label: string; value: number; format: (v: number) => string; semantic?: boolean }) {
  return (
    <div>
      <p style={label}>{l}</p>
      <p className="lt-tabular" style={{ fontSize: 20, fontWeight: 700, marginTop: 6, color: semantic ? (value >= 0 ? 'var(--bull)' : 'var(--bear)') : 'var(--fg-secondary)' }}>
        <AnimatedNumber value={value} format={(v) => `${semantic && v >= 0 ? '+' : ''}${format(v)}`} semanticColor={semantic} />
      </p>
    </div>
  );
}

function MetricBlock({
  label: l, value, format = (v) => v.toFixed(0), sub, icon, color, semantic = false,
}: {
  label: string; value: number;
  format?: (v: number) => string;
  sub?: string; icon: React.ReactNode; color?: string; semantic?: boolean;
}) {
  const resolvedColor = semantic ? (value >= 0 ? 'var(--bull)' : 'var(--bear)') : (color ?? 'var(--fg-primary)');
  return (
    <motion.div variants={revealVariants} style={{ padding: 20, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={label}>{l}</span>
        <div style={{ padding: 6, borderRadius: 8, background: 'var(--line-1)', color: resolvedColor }}>{icon}</div>
      </header>
      <div>
        <p className="lt-tabular" style={{ fontSize: 26, fontWeight: 800, color: resolvedColor, letterSpacing: '-0.02em', marginTop: 12 }}>
          <AnimatedNumber value={value} format={(v) => `${semantic && v >= 0 ? '+' : ''}${format(v)}`} semanticColor={semantic} color={!semantic ? color : undefined} />
        </p>
        {sub && <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 6 }}>{sub}</p>}
      </div>
    </motion.div>
  );
}
