import { useState, useEffect } from 'react';
import { FlaskConical, Download, ChevronLeft } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api-client';
import { exportToCsv, formatFilename } from '../lib/csv-exporter';
import type { Trade, StrategyMetrics, EquityCurvePoint } from '../lib/types';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import ChartSwitcher from '../components/shared/ChartSwitcher';
import { bentoStagger, revealVariants } from '../lib/motion';

const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;

interface BacktestSummary {
  id: string;
  strategy: string;
  dateRange: string;
  totalReturn: number;
  winRate: number;
  maxDrawdown: number;
  trades: number;
}

/* ── Small metric pill ──────────────────────────────────────────────── */
function MetricPill({
  label, value, numericValue, color, format = (v) => v.toString(),
}: {
  label: string; value: string; numericValue?: number; color: string;
  format?: (v: number) => string;
}) {
  return (
    <BentoCard accent="none">
      <motion.div variants={revealVariants} style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 98 }}>
        <span style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700, color: 'var(--fg-muted)' }}>{label}</span>
        <div className="lt-tabular" style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: '-0.02em' }}>
          {numericValue !== undefined
            ? <AnimatedNumber value={numericValue} format={format} color={color} />
            : value}
        </div>
      </motion.div>
    </BentoCard>
  );
}

export default function BacktestPage() {
  const [strats, setStrats] = useState<StrategyMetrics[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquityCurvePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStrat, setSelectedStrat] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.getStrategyPerformance().catch(() => []),
      api.getTrades().catch(() => []),
      api.getEquityCurve().catch(() => []),
    ]).then(([sp, tr, eq]) => { setStrats(sp); setTrades(tr); setEquity(eq); }).finally(() => setLoading(false));
  }, []);

  const backtests: BacktestSummary[] = strats.map((s) => {
    const stratTrades = trades.filter((tr) => tr.strategy === s.strategy);
    const dates = stratTrades.map((tr) => tr.entryTime).sort();
    return {
      id: s.strategy,
      strategy: s.strategy.replace(/([A-Z])/g, ' $1').trim(),
      dateRange: dates.length > 0 ? `${dates[0].split('T')[0]} → ${dates[dates.length - 1].split('T')[0]}` : 'N/A',
      totalReturn: s.totalPnl,
      winRate: s.winRate,
      maxDrawdown: s.maxDrawdown,
      trades: s.tradesCount,
    };
  });

  const detail = selectedStrat ? strats.find((s) => s.strategy === selectedStrat) : null;
  const detailTrades = selectedStrat ? trades.filter((tr) => tr.strategy === selectedStrat) : [];

  const exportCSV = () => {
    exportToCsv({
      filename: formatFilename('backtest'),
      columns: [
        { header: 'Entry Time', key: 'entryTime' },
        { header: 'Exit Time', key: 'exitTime', formatter: (v) => (v != null ? String(v) : '') },
        { header: 'Symbol', key: 'symbol' },
        { header: 'Side', key: 'side' },
        { header: 'Entry Price', key: 'entryPrice', formatter: (v) => String(v) },
        { header: 'Exit Price', key: 'exitPrice', formatter: (v) => (v != null ? String(v) : '') },
        { header: 'Quantity', key: 'qty', formatter: (v) => String(v) },
        { header: 'Realized P&L', key: 'realizedPnl', formatter: (v) => (v != null ? String(v) : '') },
      ],
      data: detailTrades as unknown as Record<string, unknown>[],
    });
  };

  if (loading) return <div style={{ padding: 48, textAlign: 'center', color: 'var(--fg-muted)' }}>Loading backtest data…</div>;

  /* ── Detail view ──────────────────────────────────────────────── */
  if (selectedStrat && detail) {
    // Transaction cost calc
    const turnover = detailTrades.reduce((a, tr) => a + (tr.entryPrice * tr.qty) + ((tr.exitPrice ?? tr.entryPrice) * tr.qty), 0);
    const stt = turnover * 0.00025;
    const gst = stt * 0.18;
    const stampDuty = turnover * 0.00015;
    const brokerage = detailTrades.length * 20;
    const exchangeFees = turnover * 0.0000345;
    const totalCosts = stt + gst + stampDuty + brokerage + exchangeFees;
    const netPnl = detail.totalPnl - totalCosts;

    // Monthly returns
    const monthlyMap = new Map<string, number>();
    detailTrades.forEach((tr) => {
      if (!tr.exitTime || tr.realizedPnl == null) return;
      const d = new Date(tr.exitTime);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      monthlyMap.set(key, (monthlyMap.get(key) ?? 0) + tr.realizedPnl);
    });
    const months = [...monthlyMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <PageHeader
          icon={<FlaskConical size={16} />}
          title={detail.strategy.replace(/([A-Z])/g, ' $1').trim()}
          subtitle="Backtest result · click Back to choose another"
          actions={
            <>
              <button onClick={() => setSelectedStrat(null)} style={backBtn}><ChevronLeft size={14} /> Back</button>
              <button onClick={exportCSV} style={primaryBtn}><Download size={12} /> CSV</button>
            </>
          }
        />

        {/* Metrics */}
        <motion.div
          variants={bentoStagger} initial="hidden" animate="visible"
          style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}
        >
          <MetricPill label="Total P&L" value={fmt(detail.totalPnl)} numericValue={detail.totalPnl} format={(v) => `${v >= 0 ? '+' : ''}${fmt(v)}`} color={detail.totalPnl >= 0 ? 'var(--bull)' : 'var(--bear)'} />
          <MetricPill label="Win Rate" value={`${detail.winRate.toFixed(1)}%`} numericValue={detail.winRate} format={(v) => `${v.toFixed(1)}%`} color={detail.winRate >= 50 ? 'var(--bull)' : 'var(--warn)'} />
          <MetricPill label="Max Drawdown" value={fmt(detail.maxDrawdown)} color="var(--bear)" />
          <MetricPill label="Trades" value={String(detail.tradesCount)} numericValue={detail.tradesCount} format={(v) => String(Math.round(v))} color="var(--fg-primary)" />
        </motion.div>

        {/* Equity curve */}
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 14px' }}>Equity Curve</h3>
            <ChartSwitcher
              id={`backtest-${detail.strategy}`}
              height={220}
              defaultKind="area"
              allowedKinds={['area', 'line', 'bar']}
              seriesLabel="P&L"
              color="var(--bull)"
              valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
              linearData={equity.map((p) => ({ x: p.date, y: p.cumulativePnl }))}
            />
          </div>
        </BentoCard>

        {/* Transaction costs */}
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 14px' }}>Transaction Cost Breakdown</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
              {[
                { label: 'STT', value: stt },
                { label: 'GST (18%)', value: gst },
                { label: 'Stamp Duty', value: stampDuty },
                { label: 'Brokerage', value: brokerage },
                { label: 'Exchange Fees', value: exchangeFees },
                { label: 'Total Costs', value: totalCosts, bold: true },
              ].map((c) => (
                <div key={c.label} style={costTile}>
                  <p style={costLabel}>{c.label}</p>
                  <p className="lt-tabular" style={{ fontSize: 14, fontWeight: c.bold ? 800 : 600, color: 'var(--bear)', margin: 0 }}>-{fmt(c.value)}</p>
                </div>
              ))}
              <div style={{ ...costTile, background: 'color-mix(in srgb, var(--bull) 8%, var(--surface-3))' }}>
                <p style={costLabel}>Net P&L</p>
                <p className="lt-tabular" style={{ fontSize: 14, fontWeight: 800, color: netPnl >= 0 ? 'var(--bull)' : 'var(--bear)', margin: 0 }}>{netPnl >= 0 ? '+' : ''}{fmt(netPnl)}</p>
              </div>
            </div>
          </div>
        </BentoCard>

        {/* Monthly returns heatmap */}
        {months.length > 0 && (
          <BentoCard reveal>
            <div style={{ padding: 24 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 14px' }}>Monthly Returns</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8 }}>
                {months.map(([month, pnl]) => {
                  const intensity = Math.min(1, Math.abs(pnl) / 10000);
                  const bg = pnl >= 0
                    ? `color-mix(in srgb, var(--bull) ${intensity * 30}%, var(--surface-3))`
                    : `color-mix(in srgb, var(--bear) ${intensity * 30}%, var(--surface-3))`;
                  return (
                    <div key={month} style={{ background: bg, borderRadius: 'var(--r-sm)', padding: '10px 12px', textAlign: 'center', border: '1px solid var(--line-2)' }}>
                      <p style={{ fontSize: 10, color: 'var(--fg-muted)', fontWeight: 600, marginBottom: 4 }}>{month}</p>
                      <p className="lt-tabular" style={{ fontSize: 14, fontWeight: 700, color: pnl >= 0 ? 'var(--bull)' : 'var(--bear)', margin: 0 }}>{pnl >= 0 ? '+' : ''}{fmt(pnl)}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          </BentoCard>
        )}

        {/* Trade log */}
        <BentoCard reveal>
          <div style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--line-2)' }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Trade Log</h3>
              <p style={{ fontSize: 11, color: 'var(--fg-muted)', margin: '4px 0 0' }}>{detailTrades.length} trades</p>
            </div>
            {detailTrades.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--fg-muted)', fontSize: 13 }}>No trades</div>
            ) : (
              <div style={{ overflowX: 'auto' }} className="lt-scroll">
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line-2)' }}>
                      {['Entry', 'Exit', 'Symbol', 'Side', 'Qty', 'Entry ₹', 'Exit ₹', 'P&L'].map((h) => (
                        <th key={h} style={{ padding: '10px 12px', textAlign: ['Qty', 'Entry ₹', 'Exit ₹', 'P&L'].includes(h) ? 'right' : 'left', color: 'var(--fg-muted)', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {detailTrades.map((tr) => {
                      const pl = tr.realizedPnl ?? 0;
                      return (
                        <tr key={tr.tradeId} style={{ borderBottom: '1px solid var(--line-1)' }}>
                          <td style={{ padding: '10px 12px', color: 'var(--fg-muted)', fontSize: 11 }}>{new Date(tr.entryTime).toLocaleString()}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--fg-muted)', fontSize: 11 }}>{tr.exitTime ? new Date(tr.exitTime).toLocaleString() : '—'}</td>
                          <td style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--fg-primary)' }}>{tr.symbol}</td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: tr.side === 'BUY' ? 'var(--bull)' : 'var(--bear)', background: tr.side === 'BUY' ? 'var(--bull-soft)' : 'var(--bear-soft)' }}>{tr.side}</span>
                          </td>
                          <td className="lt-tabular" style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--fg-secondary)' }}>{tr.qty}</td>
                          <td className="lt-tabular" style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--fg-secondary)' }}>{fmt(tr.entryPrice)}</td>
                          <td className="lt-tabular" style={{ padding: '10px 12px', textAlign: 'right', color: 'var(--fg-primary)' }}>{tr.exitPrice ? fmt(tr.exitPrice) : '—'}</td>
                          <td className="lt-tabular" style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700, color: pl >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{pl >= 0 ? '+' : ''}{fmt(pl)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </BentoCard>
      </div>
    );
  }

  /* ── List view ──────────────────────────────────────────────── */
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader icon={<FlaskConical size={16} />} title="Backtest Results" subtitle="Historical strategy performance · click a row for details" />

      {backtests.length === 0 ? (
        <BentoCard>
          <div style={{ padding: 48, textAlign: 'center' }}>
            <FlaskConical size={40} style={{ margin: '0 auto 12px', color: 'var(--fg-subtle)' }} />
            <p style={{ color: 'var(--fg-muted)', fontSize: 13 }}>No backtest data available. Run a paper simulation first.</p>
          </div>
        </BentoCard>
      ) : (
        <BentoCard>
          <div style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }} className="lt-scroll">
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line-2)' }}>
                    {['Strategy', 'Date Range', 'Trades', 'Win Rate', 'Total Return', 'Max Drawdown'].map((h) => (
                      <th key={h} style={{ padding: '12px', textAlign: h === 'Strategy' || h === 'Date Range' ? 'left' : 'right', color: 'var(--fg-muted)', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {backtests.map((b) => (
                    <tr
                      key={b.id}
                      onClick={() => setSelectedStrat(b.id)}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-4)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                      style={{ borderBottom: '1px solid var(--line-1)', cursor: 'pointer', transition: 'background 120ms var(--ease-out)' }}
                    >
                      <td style={{ padding: '14px 12px', fontWeight: 600, color: 'var(--fg-primary)' }}>{b.strategy}</td>
                      <td style={{ padding: '14px 12px', color: 'var(--fg-muted)', fontSize: 11 }}>{b.dateRange}</td>
                      <td className="lt-tabular" style={{ padding: '14px 12px', textAlign: 'right', color: 'var(--fg-secondary)' }}>{b.trades}</td>
                      <td className="lt-tabular" style={{ padding: '14px 12px', textAlign: 'right', color: b.winRate >= 50 ? 'var(--bull)' : 'var(--warn)' }}>{b.winRate.toFixed(1)}%</td>
                      <td className="lt-tabular" style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 700, color: b.totalReturn >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{b.totalReturn >= 0 ? '+' : ''}{fmt(b.totalReturn)}</td>
                      <td className="lt-tabular" style={{ padding: '14px 12px', textAlign: 'right', color: 'var(--bear)' }}>{fmt(b.maxDrawdown)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </BentoCard>
      )}
    </div>
  );
}

/* ── styles ──────────────────────────────────────────────────── */
const backBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px',
  fontSize: 11, fontWeight: 600, color: 'var(--fg-secondary)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  borderRadius: 'var(--r-sm)', cursor: 'pointer',
};
const primaryBtn: React.CSSProperties = { ...backBtn };
const costTile: React.CSSProperties = {
  background: 'var(--surface-3)', borderRadius: 'var(--r-sm)',
  padding: '10px 14px', border: '1px solid var(--line-2)',
};
const costLabel: React.CSSProperties = {
  fontSize: 9, color: 'var(--fg-muted)', textTransform: 'uppercase',
  fontWeight: 600, marginBottom: 6, letterSpacing: '0.08em',
};
