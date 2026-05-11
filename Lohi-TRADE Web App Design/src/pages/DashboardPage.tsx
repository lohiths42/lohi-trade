import { useEffect, useState } from 'react';
import {
  TrendingUp, TrendingDown, Shield, Loader2, Wallet, Target,
  ArrowUpRight, ArrowDownRight, Activity, Newspaper, Zap,
} from 'lucide-react';
import { motion } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { useEquityCurve } from '../hooks/use-analytics';
import { usePositions } from '../hooks/use-positions';
import { useDashboardStore } from '../stores/dashboard-store';
import { useCommanderStore } from '../stores/commander-store';
import { usePriceTickStore } from '../stores/price-tick-store';
import { usePnlAlerts } from '../hooks/use-pnl-alerts';
import { api } from '../lib/api-client';
import { useThemeColors } from '../hooks/use-theme-colors';
import MiniChartWidget from '../components/dashboard/MiniChartWidget';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import { BentoCard } from '../components/shared/BentoCard';
import ChartSwitcher from '../components/shared/ChartSwitcher';
import { bentoStagger, revealVariants } from '../lib/motion';
import type { PaperTradingStatus, StrategyMetrics } from '../lib/types';

/* ─── Helpers ────────────────────────────────────────────────────────────── */
const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const fmtSigned = (n: number) => `${n >= 0 ? '+' : ''}${fmt(n)}`;
const clr = (n: number) => (n > 0 ? 'var(--bull)' : n < 0 ? 'var(--bear)' : 'var(--fg-muted)');

/* ─── Bento Metric Card (2026 redesign) ─────────────────────────────────── */
function BentoMetric({
  label, value, sub, icon, accent, semantic, format,
}: {
  label: string;
  value: number;
  sub?: string;
  icon: React.ReactNode;
  accent: 'indigo' | 'emerald' | 'rose' | 'cyan' | 'none';
  semantic?: boolean;
  format?: (v: number) => string;
}) {
  const color = semantic ? clr(value) : (accent === 'emerald' ? 'var(--bull)' : accent === 'rose' ? 'var(--bear)' : accent === 'cyan' ? 'var(--accent-2)' : 'var(--fg-primary)');
  return (
    <BentoCard accent={accent}>
      <motion.div variants={revealVariants} style={{ padding: 22, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: 132 }}>
        <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
          <div style={{ padding: 7, borderRadius: 8, background: 'var(--line-1)', color, display: 'flex' }}>{icon}</div>
        </header>
        <div style={{ marginTop: 12 }}>
          <p className="lt-tabular" style={{ fontSize: 26, fontWeight: 800, color, letterSpacing: '-0.02em', margin: 0, lineHeight: 1.1 }}>
            <AnimatedNumber
              value={value}
              format={format ?? ((v) => (semantic ? fmtSigned(v) : fmt(v)))}
              semanticColor={semantic}
              color={!semantic ? color : undefined}
            />
          </p>
          {sub && <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 6 }}>{sub}</p>}
        </div>
      </motion.div>
    </BentoCard>
  );
}

/* ─── Main Component ─────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const { data: equityData, isLoading: eqLoading, refetch: refetchEq } = useEquityCurve();
  const { positions, isLoading: posLoading } = usePositions();
  const totalPnl = useDashboardStore((s) => s.totalPnl);
  const tradesCount = useDashboardStore((s) => s.tradesCount);
  const winRate = useDashboardStore((s) => s.winRate);
  const bias = useCommanderStore((s) => s.bias);
  const news = useCommanderStore((s) => s.news);
  const setBias = useCommanderStore((s) => s.setBias);
  const setNews = useCommanderStore((s) => s.setNews);
  const [sim, setSim] = useState<PaperTradingStatus | null>(null);
  const [strats, setStrats] = useState<StrategyMetrics[]>([]);
  const [capital, setCap] = useState(200000);
  const [monitoredSymbols, setMonitoredSymbols] = useState<string[]>([]);
  const navigate = useNavigate();
  const ticks = usePriceTickStore((s) => s.ticks);
  const lastPrices = usePriceTickStore((s) => s.lastPrices);
  const openPrices = usePriceTickStore((s) => s.openPrices);
  const t = useThemeColors();

  const card: React.CSSProperties = {
    background: t.bgCardGradient,
    border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16,
    boxShadow: t.cardShadow,
  };

  const refresh = () => {
    api.getBias().then(setBias).catch(() => {});
    api.getNews().then(setNews).catch(() => {});
    api.getStrategyPerformance().then((s) => {
      setStrats(s);
      const tp = s.reduce((a, x) => a + x.totalPnl, 0);
      const tt = s.reduce((a, x) => a + x.tradesCount, 0);
      const tw = s.reduce((a, x) => a + Math.round((x.winRate * x.tradesCount) / 100), 0);
      useDashboardStore.setState({ totalPnl: Math.round(tp * 100) / 100, tradesCount: tt, winRate: tt > 0 ? Math.round((tw / tt) * 1000) / 10 : 0 });
    }).catch(() => {});
    api.getConfig().then((c) => {
      if (c?.capital?.total) setCap(c.capital.total);
      if (c?.symbols) setMonitoredSymbols(c.symbols);
    }).catch(() => {});
  };

  useEffect(() => { refresh(); }, [setBias, setNews]);
  useEffect(() => {
    const poll = () => api.getPaperTradingStatus().then((s) => {
      setSim(s);
      if (s.running) { if (s.capital) setCap(s.capital); refresh(); refetchEq(); }
    }).catch(() => {});
    poll();
    const id = setInterval(poll, 4000);
    return () => clearInterval(id);
  }, [refetchEq]);

  const uPnl = positions.reduce((a, p) => a + (p.pnl ?? 0), 0);
  const invested = positions.reduce((a, p) => a + p.entryPrice * p.qty, 0);
  const curVal = capital + totalPnl + uPnl;
  const ret = capital > 0 ? ((curVal - capital) / capital) * 100 : 0;
  const profPos = positions.filter((p) => (p.pnl ?? 0) > 0).length;
  const totalDayPnl = totalPnl + uPnl;

  usePnlAlerts(totalPnl, uPnl, capital, true);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>

      {/* ── Sim Banner ──────────────────────────────────────────────── */}
      {sim?.running && (
        <div style={{
          ...card, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 28px', borderColor: 'rgba(52,211,153,0.25)',
          background: 'linear-gradient(135deg, rgba(16,185,129,0.06) 0%, rgba(15,23,42,0.95) 100%)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ padding: 8, borderRadius: 10, background: 'rgba(52,211,153,0.12)' }}>
              <Loader2 size={18} color="#34d399" className="animate-spin" />
            </div>
            <div>
              <p style={{ fontSize: 14, fontWeight: 700, color: '#34d399', margin: 0 }}>Paper Trading Active</p>
              <p style={{ fontSize: 11, color: 'rgba(52,211,153,0.5)', margin: '2px 0 0' }}>
                {fmt(sim.capital ?? 0)} · {sim.days}d · {sim.speed}x{sim.useRealData ? ' · Real Data' : ''}
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Zap size={14} color="#34d399" />
            <span style={{ fontSize: 11, padding: '4px 12px', borderRadius: 6, fontWeight: 700, color: '#34d399', background: 'rgba(52,211,153,0.12)', letterSpacing: '0.08em' }} className="animate-pulse">LIVE</span>
          </div>
        </div>
      )}

      {/* ── Hero Row: Portfolio Bento + 4 Metrics ────────────────────── */}
      <motion.div
        variants={bentoStagger}
        initial="hidden"
        animate="visible"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 16, alignItems: 'stretch' }}
      >
        {/* Portfolio Hero Card — spans 6 cols */}
        <BentoCard colSpan={6} accent="indigo">
          <motion.div
            variants={revealVariants}
            data-tour="dashboard-pnl"
            style={{ padding: '32px 36px', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%', justifyContent: 'space-between', minHeight: 272 }}
          >
            {/* Corner glow */}
            <div style={{ position: 'absolute', bottom: -20, left: 20, width: 160, height: 160, borderRadius: '50%', background: ret >= 0 ? 'rgba(0,227,140,0.10)' : 'rgba(255,77,109,0.10)', filter: 'blur(60px)', pointerEvents: 'none' }} />

            <div style={{ position: 'relative' }}>
              <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.14em', fontWeight: 700, margin: 0 }}>Portfolio Value</p>
              <p className="lt-tabular" style={{ fontSize: 46, fontWeight: 800, color: 'var(--fg-primary)', lineHeight: 1, letterSpacing: '-0.035em', margin: '12px 0 0' }}>
                <AnimatedNumber value={curVal} format={fmt} durationMs={420} flash={false} />
              </p>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16 }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14, fontWeight: 800,
                  padding: '6px 12px', borderRadius: 8,
                  color: clr(ret),
                  background: ret >= 0 ? 'var(--bull-soft)' : 'var(--bear-soft)',
                }}>
                  {ret >= 0 ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}
                  <AnimatedNumber value={ret} format={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`} durationMs={420} flash={false} color={clr(ret)} />
                </span>
                <span style={{ fontSize: 12, color: 'var(--fg-muted)' }}>from {fmt(capital)} capital</span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, paddingTop: 20, marginTop: 20, borderTop: '1px solid var(--line-2)', position: 'relative' }}>
              <div>
                <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, margin: '0 0 6px' }}>Today's P&L</p>
                <p className="lt-tabular" style={{ fontSize: 20, fontWeight: 700, color: clr(totalDayPnl), margin: 0 }}>
                  <AnimatedNumber value={totalDayPnl} format={fmtSigned} semanticColor />
                </p>
              </div>
              <div>
                <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, margin: '0 0 6px' }}>Invested</p>
                <p className="lt-tabular" style={{ fontSize: 20, fontWeight: 700, color: 'var(--fg-secondary)', margin: 0 }}>
                  <AnimatedNumber value={invested} format={fmt} />
                </p>
              </div>
            </div>
          </motion.div>
        </BentoCard>

        {/* 4 Bento Metrics (1.5 cols each on 12-grid → 6 cols total) */}
        <div style={{ gridColumn: 'span 6', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
          <BentoMetric
            label="Realized P&L"
            value={totalPnl}
            icon={totalPnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
            accent={totalPnl >= 0 ? 'emerald' : 'rose'}
            semantic
          />
          <BentoMetric
            label="Unrealized P&L"
            value={uPnl}
            icon={<Activity size={16} />}
            accent={uPnl >= 0 ? 'emerald' : 'rose'}
            semantic
          />
          <BentoMetric
            label="Win Rate"
            value={winRate}
            sub={`${tradesCount} trades total`}
            icon={<Target size={16} />}
            accent={winRate >= 50 ? 'emerald' : 'none'}
            format={(v) => `${v.toFixed(1)}%`}
          />
          <BentoMetric
            label="Open Positions"
            value={positions.length}
            sub={`${profPos} in profit`}
            icon={<Shield size={16} />}
            accent="cyan"
            format={(v) => String(Math.round(v))}
          />
        </div>
      </motion.div>

      {/* ── Row 2: Equity Curve + Strategy Performance ──────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '5fr 3fr', gap: 16 }}>

        {/* Equity Curve */}
        <div className="card-hover" style={{ ...card, padding: '28px 28px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Equity Curve</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>Cumulative P&L over time</p>
            </div>
            <div style={{ padding: 8, borderRadius: 10, background: 'rgba(16,185,129,0.1)' }}>
              <TrendingUp size={20} color="#34d399" />
            </div>
          </div>
          {eqLoading ? (
            <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: t.textMuted, fontSize: 13 }}>Loading…</div>
          ) : (
            <ChartSwitcher
              id="dashboard-equity"
              height={260}
              defaultKind="area"
              allowedKinds={['area', 'line', 'bar']}
              seriesLabel="P&L"
              color="var(--bull)"
              valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
              linearData={equityData.map((p) => ({ x: p.date, y: p.cumulativePnl }))}
            />
          )}
        </div>

        {/* Strategy Performance */}
        <div className="card-hover" style={{ ...card, padding: '28px 24px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Strategy Performance</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>P&L breakdown by strategy</p>
          </div>
          {strats.length === 0 ? (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
              <Activity size={32} color={t.borderPrimary} />
              <p style={{ color: t.textMuted, fontSize: 13, margin: 0 }}>No data yet</p>
            </div>
          ) : (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 0 }}>
              {strats.map((s, i) => {
                const pct = strats.length > 0 ? Math.abs(s.totalPnl) / Math.max(...strats.map(x => Math.abs(x.totalPnl))) * 100 : 0;
                return (
                  <div key={s.strategy} style={{ padding: '16px 0', borderBottom: i < strats.length - 1 ? `1px solid ${t.isLight ? '#f1f5f9' : 'rgba(30,41,59,0.5)'}` : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: s.totalPnl >= 0 ? '#34d399' : '#f87171', boxShadow: `0 0 6px ${s.totalPnl >= 0 ? '#34d399' : '#f87171'}` }} />
                        <div>
                          <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>{s.strategy.replace(/([A-Z])/g, ' $1').trim()}</p>
                          <p style={{ fontSize: 10, color: t.textMuted, margin: '2px 0 0' }}>{s.tradesCount} trades · {s.winRate.toFixed(1)}% win</p>
                        </div>
                      </div>
                      <span style={{ fontSize: 14, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: s.totalPnl >= 0 ? '#34d399' : '#f87171' }}>
                        {s.totalPnl >= 0 ? '+' : ''}{fmt(s.totalPnl)}
                      </span>
                    </div>
                    <div style={{ height: 3, borderRadius: 2, background: t.isLight ? '#e2e8f0' : 'rgba(30,41,59,0.8)', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${pct}%`, borderRadius: 2, background: s.totalPnl >= 0 ? 'linear-gradient(to right, #10b981, #34d399)' : 'linear-gradient(to right, #dc2626, #f87171)', transition: 'width 0.6s ease' }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Row 3: Active Positions ─────────────────────────────────── */}
      <div data-tour="positions" className="card-hover" style={{ ...card, padding: '28px 28px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Active Positions</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>{positions.length} open · {fmt(invested)} invested</p>
          </div>
          <div style={{ padding: 8, borderRadius: 10, background: 'rgba(96,165,250,0.1)' }}>
            <Wallet size={20} color="#60a5fa" />
          </div>
        </div>
        {posLoading ? (
          <div style={{ padding: 40, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>Loading…</div>
        ) : positions.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No open positions</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${t.borderPrimary}` }}>
                  {['Symbol', 'Qty', 'Entry', 'CMP', 'Invested', 'Current', 'P&L', 'Strategy'].map((h) => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: h === 'Symbol' || h === 'Strategy' ? 'left' : 'right', color: t.textMuted, fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const inv = p.entryPrice * p.qty;
                  const cur = (p.currentPrice ?? p.entryPrice) * p.qty;
                  const pl = p.pnl ?? 0;
                  return (
                    <tr key={p.id} className="table-row-hover" style={{ borderBottom: `1px solid ${t.isLight ? '#f1f5f9' : 'rgba(30,41,59,0.4)'}` }}>
                      <td style={{ padding: '14px 14px', fontWeight: 700, color: t.textPrimary, fontSize: 14 }}>{p.symbol}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{p.qty}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>₹{p.entryPrice.toFixed(2)}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', color: t.textPrimary, fontFamily: 'ui-monospace,monospace', fontWeight: 600 }}>₹{(p.currentPrice ?? p.entryPrice).toFixed(2)}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{fmt(inv)}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', color: t.textPrimary, fontFamily: 'ui-monospace,monospace' }}>{fmt(cur)}</td>
                      <td style={{ padding: '14px 14px', textAlign: 'right', fontWeight: 800, fontFamily: 'ui-monospace,monospace', fontSize: 14, color: clr(pl) }}>
                        {pl >= 0 ? '+' : ''}{fmt(pl)}
                      </td>
                      <td style={{ padding: '14px 14px' }}>
                        <span style={{ fontSize: 10, padding: '4px 10px', borderRadius: 6, fontWeight: 700, color: 'var(--fg-muted)', background: 'var(--surface-4)', border: '1px solid var(--line-2)' }}>
                          {p.strategy.replace(/_/g, ' ')}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Row 4: Market Overview ────────────────────────────────── */}
      {monitoredSymbols.length > 0 && (
        <div className="card-hover" style={{ ...card, padding: '28px 28px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Market Overview</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>{monitoredSymbols.length} symbols monitored</p>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }} className="max-md:!grid-cols-2 max-sm:!grid-cols-1">
            {monitoredSymbols.map((symbol) => {
              const symbolTicks = ticks[symbol] || [];
              const lastPrice = lastPrices[symbol] || 0;
              const openPrice = openPrices[symbol] || lastPrice;
              const changePct = openPrice > 0 ? ((lastPrice - openPrice) / openPrice) * 100 : 0;
              return (
                <MiniChartWidget
                  key={symbol}
                  symbol={symbol}
                  priceTicks={symbolTicks}
                  lastPrice={lastPrice}
                  changePercent={changePct}
                  onClick={() => navigate('/soldier')}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* ── Row 5: Sentiment Bias + News ────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

        {/* Bias Matrix */}
        <div className="card-hover" style={{ ...card, padding: '28px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Sentiment Bias</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>{bias.length} symbols tracked</p>
            </div>
            <div style={{ padding: 8, borderRadius: 10, background: 'rgba(167,139,250,0.1)' }}>
              <Shield size={20} color="#a78bfa" />
            </div>
          </div>
          {bias.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No bias data</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {bias.slice(0, 8).map((b, i) => {
                const bColor = b.bias === 'BULLISH' ? 'var(--bull)' : b.bias === 'BEARISH' ? 'var(--bear)' : 'var(--fg-muted)';
                const confPct = Math.round(b.confidence * 100);
                return (
                  <div key={b.ticker} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '13px 0', borderBottom: i < Math.min(bias.length, 8) - 1 ? `1px solid ${t.isLight ? '#f1f5f9' : 'rgba(30,41,59,0.4)'}` : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ width: 9, height: 9, borderRadius: '50%', background: bColor, boxShadow: `0 0 6px ${bColor}` }} />
                      <span style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary }}>{b.ticker}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ width: 60, height: 4, borderRadius: 2, background: t.isLight ? '#e2e8f0' : 'rgba(30,41,59,0.8)', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${confPct}%`, borderRadius: 2, background: bColor, opacity: 0.7 }} />
                      </div>
                      <span style={{ fontSize: 11, padding: '3px 10px', borderRadius: 5, fontWeight: 700, color: bColor, background: `color-mix(in srgb, ${bColor} 14%, transparent)`, minWidth: 68, textAlign: 'center' }}>{b.bias}</span>
                      <span className="lt-tabular" style={{ fontSize: 11, color: 'var(--fg-muted)', minWidth: 32, textAlign: 'right' }}>{confPct}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* News Feed */}
        <div className="card-hover" style={{ ...card, padding: '28px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Latest News</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>{news.length} articles</p>
            </div>
            <div style={{ padding: 8, borderRadius: 10, background: 'rgba(251,191,36,0.1)' }}>
              <Newspaper size={20} color="#fbbf24" />
            </div>
          </div>
          {news.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No news yet</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxHeight: 320, overflowY: 'auto' }}>
              {news.slice(0, 10).map((n, i) => {
                const nColor = n.sentiment === 'BULLISH' ? 'var(--bull)' : n.sentiment === 'BEARISH' ? 'var(--bear)' : 'var(--fg-muted)';
                return (
                  <div key={n.id} style={{ padding: '13px 0', borderBottom: i < Math.min(news.length, 10) - 1 ? `1px solid ${t.borderSubtle}` : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-secondary)', margin: 0, lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</p>
                        <p style={{ fontSize: 10, color: t.textMuted, margin: '5px 0 0' }}>{n.ticker} · {n.source}</p>
                      </div>
                      <span style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, fontWeight: 700, color: nColor, background: `${nColor}15`, flexShrink: 0, letterSpacing: '0.05em' }}>{n.sentiment}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
