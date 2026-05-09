import { useState, useEffect, useMemo } from 'react';
import {
  PieChart, Pie, Cell, Legend, Tooltip as RTooltip, ResponsiveContainer,
} from 'recharts';
import { TrendingUp, Download, BarChart3, Target, Activity, Calendar, Printer } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api-client';
import { exportToCsv, formatFilename } from '../lib/csv-exporter';
import { generateReport } from '../lib/report-generator';
import type { EquityCurvePoint, DailyPnL, StrategyMetrics, Trade } from '../lib/types';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import ChartSwitcher from '../components/shared/ChartSwitcher';
import { bentoStagger, revealVariants } from '../lib/motion';

const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const PIE_COLORS = ['var(--bull)', 'var(--bear)'];
const STRAT_COLORS = ['#60a5fa', '#a78bfa', '#fbbf24', '#f472b6', '#34d399'];

/* ── Small metric card ───────────────────────────────────────────────── */
function MetricPill({
  label, value, numericValue, color, icon, format = (v) => v.toString(),
}: {
  label: string;
  value: string;
  numericValue?: number;
  color: string;
  icon: React.ReactNode;
  format?: (v: number) => string;
}) {
  return (
    <BentoCard accent="none">
      <motion.div variants={revealVariants} style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 108 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ padding: 5, borderRadius: 6, background: `color-mix(in srgb, ${color} 14%, transparent)`, color, display: 'flex' }}>{icon}</div>
          <span style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700, color: 'var(--fg-muted)' }}>{label}</span>
        </div>
        <div className="lt-tabular" style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: '-0.02em' }}>
          {numericValue !== undefined ? (
            <AnimatedNumber value={numericValue} format={format} color={color} />
          ) : value}
        </div>
      </motion.div>
    </BentoCard>
  );
}

export default function AnalyticsPage() {
  const [equity, setEquity] = useState<EquityCurvePoint[]>([]);
  const [daily, setDaily] = useState<DailyPnL[]>([]);
  const [strats, setStrats] = useState<StrategyMetrics[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  useEffect(() => {
    Promise.all([
      api.getEquityCurve().catch(() => []),
      api.getDailyPnl().catch(() => []),
      api.getStrategyPerformance().catch(() => []),
      api.getTrades().catch(() => []),
    ]).then(([eq, dp, sp, tr]) => {
      setEquity(eq); setDaily(dp); setStrats(sp); setTrades(tr);
    }).finally(() => setLoading(false));
  }, []);

  const summary = useMemo(() => {
    const totalPnl = strats.reduce((a, s) => a + s.totalPnl, 0);
    const totalTrades = strats.reduce((a, s) => a + s.tradesCount, 0);
    const wins = trades.filter((tr) => (tr.realizedPnl ?? 0) > 0).length;
    const losses = trades.filter((tr) => (tr.realizedPnl ?? 0) < 0).length;
    const maxDD = strats.reduce((a, s) => Math.min(a, s.maxDrawdown), 0);
    const avgProfit = totalTrades > 0 ? totalPnl / totalTrades : 0;
    const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
    const grossProfit = trades.filter((tr) => (tr.realizedPnl ?? 0) > 0).reduce((a, tr) => a + (tr.realizedPnl ?? 0), 0);
    const grossLoss = Math.abs(trades.filter((tr) => (tr.realizedPnl ?? 0) < 0).reduce((a, tr) => a + (tr.realizedPnl ?? 0), 0));
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
    const dailyReturns = daily.map((d) => d.pnl);
    const meanReturn = dailyReturns.length > 0 ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
    const stdDev = dailyReturns.length > 1 ? Math.sqrt(dailyReturns.reduce((a, r) => a + (r - meanReturn) ** 2, 0) / (dailyReturns.length - 1)) : 0;
    const sharpeRatio = stdDev > 0 ? (meanReturn / stdDev) * Math.sqrt(252) : 0;
    return { totalPnl, totalTrades, wins, losses, maxDD, avgProfit, winRate, profitFactor, sharpeRatio };
  }, [strats, trades, daily]);

  const filteredTrades = useMemo(() => {
    let list = trades;
    if (dateFrom) list = list.filter((tr) => tr.entryTime >= dateFrom);
    if (dateTo) list = list.filter((tr) => tr.entryTime <= dateTo + 'T23:59:59');
    return list;
  }, [trades, dateFrom, dateTo]);

  const filteredDaily = useMemo(() => {
    let list = daily;
    if (dateFrom) list = list.filter((d) => d.date >= dateFrom);
    if (dateTo) list = list.filter((d) => d.date <= dateTo);
    return list;
  }, [daily, dateFrom, dateTo]);

  const hourlyPnl = useMemo(() => {
    const hours: Record<number, number> = {};
    for (let h = 9; h <= 15; h++) hours[h] = 0;
    filteredTrades.forEach((tr) => {
      if (!tr.entryTime) return;
      const h = new Date(tr.entryTime).getHours();
      if (h >= 9 && h <= 15) hours[h] += tr.realizedPnl ?? 0;
    });
    return Object.entries(hours).map(([h, pnl]) => ({ hour: `${h}:00`, pnl }));
  }, [filteredTrades]);

  const holdingTimes = useMemo(() => {
    const buckets: Record<string, number> = { '<5m': 0, '5-15m': 0, '15-30m': 0, '30-60m': 0, '1-2h': 0, '>2h': 0 };
    filteredTrades.forEach((tr) => {
      if (!tr.entryTime || !tr.exitTime) return;
      const mins = (new Date(tr.exitTime).getTime() - new Date(tr.entryTime).getTime()) / 60000;
      if (mins < 5) buckets['<5m']++;
      else if (mins < 15) buckets['5-15m']++;
      else if (mins < 30) buckets['15-30m']++;
      else if (mins < 60) buckets['30-60m']++;
      else if (mins < 120) buckets['1-2h']++;
      else buckets['>2h']++;
    });
    return Object.entries(buckets).map(([range, count]) => ({ range, count }));
  }, [filteredTrades]);

  const winLossData = [
    { name: 'Wins', value: summary.wins },
    { name: 'Losses', value: summary.losses },
  ];

  const topWins = useMemo(() => [...filteredTrades].filter((tr) => tr.realizedPnl != null).sort((a, b) => (b.realizedPnl ?? 0) - (a.realizedPnl ?? 0)).slice(0, 10), [filteredTrades]);
  const topLosses = useMemo(() => [...filteredTrades].filter((tr) => tr.realizedPnl != null).sort((a, b) => (a.realizedPnl ?? 0) - (b.realizedPnl ?? 0)).slice(0, 10), [filteredTrades]);

  const exportCSV = () => {
    exportToCsv({
      filename: formatFilename('analytics'),
      columns: [
        { header: 'Date', key: 'entryTime' },
        { header: 'Symbol', key: 'symbol' },
        { header: 'Side', key: 'side' },
        { header: 'Strategy', key: 'strategy' },
        { header: 'Entry Price', key: 'entryPrice' },
        { header: 'Exit Price', key: 'exitPrice' },
        { header: 'Quantity', key: 'qty' },
        { header: 'Realized P&L', key: 'realizedPnl' },
      ],
      data: filteredTrades as unknown as Record<string, unknown>[],
    });
  };

  const handleReport = () => {
    const topW = [...filteredTrades].filter((tr) => tr.realizedPnl != null).sort((a, b) => (b.realizedPnl ?? 0) - (a.realizedPnl ?? 0)).slice(0, 3);
    const topL = [...filteredTrades].filter((tr) => tr.realizedPnl != null).sort((a, b) => (a.realizedPnl ?? 0) - (b.realizedPnl ?? 0)).slice(0, 3);
    generateReport({
      date: new Date().toLocaleDateString(),
      totalPnl: summary.totalPnl,
      winRate: summary.winRate,
      tradesCount: summary.totalTrades,
      strategyBreakdown: strats,
      topWinners: topW,
      topLosers: topL,
      equityCurve: equity,
    });
  };

  if (loading) return <div style={{ padding: 48, textAlign: 'center', color: 'var(--fg-muted)' }}>Loading analytics…</div>;

  const actionBtn: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px',
    fontSize: 11, fontWeight: 600, color: 'var(--fg-secondary)',
    background: 'var(--surface-3)', border: '1px solid var(--line-2)',
    borderRadius: 'var(--r-sm)', cursor: 'pointer',
  };
  const inputStyle: React.CSSProperties = {
    background: 'var(--surface-3)', border: '1px solid var(--line-2)',
    borderRadius: 'var(--r-sm)', padding: '4px 8px', fontSize: 11,
    color: 'var(--fg-primary)', outline: 'none',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<BarChart3 size={16} />}
        title="Analytics"
        subtitle="Trade statistics, returns, drawdown, and risk"
        actions={
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Calendar size={12} style={{ color: 'var(--fg-muted)' }} />
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={inputStyle} />
              <span style={{ color: 'var(--fg-muted)', fontSize: 11 }}>to</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={inputStyle} />
              {(dateFrom || dateTo) && (
                <button onClick={() => { setDateFrom(''); setDateTo(''); }} style={{ fontSize: 10, color: 'var(--fg-muted)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Clear</button>
              )}
            </div>
            <button onClick={exportCSV} style={actionBtn}><Download size={12} /> CSV</button>
            <button onClick={handleReport} style={actionBtn}><Printer size={12} /> Report</button>
          </>
        }
      />

      {/* Key metrics */}
      <motion.div
        variants={bentoStagger} initial="hidden" animate="visible"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 14 }}
      >
        <MetricPill
          label="Total P&L"
          value={fmt(summary.totalPnl)}
          numericValue={summary.totalPnl}
          format={(v) => `${v >= 0 ? '+' : ''}${fmt(v)}`}
          color={summary.totalPnl >= 0 ? 'var(--bull)' : 'var(--bear)'}
          icon={<TrendingUp size={14} />}
        />
        <MetricPill
          label="Win Rate"
          value={`${summary.winRate.toFixed(1)}%`}
          numericValue={summary.winRate}
          format={(v) => `${v.toFixed(1)}%`}
          color={summary.winRate >= 50 ? 'var(--bull)' : 'var(--warn)'}
          icon={<Target size={14} />}
        />
        <MetricPill
          label="Profit Factor"
          value={summary.profitFactor === Infinity ? '∞' : summary.profitFactor.toFixed(2)}
          color={summary.profitFactor >= 1.5 ? 'var(--bull)' : 'var(--warn)'}
          icon={<BarChart3 size={14} />}
        />
        <MetricPill
          label="Sharpe Ratio"
          value={summary.sharpeRatio.toFixed(2)}
          numericValue={summary.sharpeRatio}
          format={(v) => v.toFixed(2)}
          color={summary.sharpeRatio >= 1 ? 'var(--bull)' : summary.sharpeRatio >= 0 ? 'var(--warn)' : 'var(--bear)'}
          icon={<Activity size={14} />}
        />
        <MetricPill
          label="Max Drawdown"
          value={fmt(summary.maxDD)}
          color="var(--bear)"
          icon={<Activity size={14} />}
        />
      </motion.div>

      {/* Equity Curve + Win/Loss */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 4px' }}>Equity Curve</h3>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginBottom: 14 }}>Cumulative P&L over time</p>
            <ChartSwitcher
              id="analytics-equity"
              height={240}
              defaultKind="area"
              allowedKinds={['area', 'line', 'bar']}
              seriesLabel="P&L"
              color="var(--bull)"
              valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
              linearData={equity.map((p) => ({ x: p.date, y: p.cumulativePnl }))}
            />
          </div>
        </BentoCard>

        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 4px' }}>Trade Distribution</h3>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginBottom: 14 }}>{summary.wins}W / {summary.losses}L of {summary.totalTrades}</p>
            {summary.totalTrades === 0 ? (
              <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--fg-muted)', fontSize: 13 }}>No trades</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={winLossData} cx="50%" cy="50%" innerRadius={52} outerRadius={80} paddingAngle={4} dataKey="value" stroke="none">
                    {winLossData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                  </Pie>
                  <Legend formatter={(v) => <span style={{ color: 'var(--fg-secondary)', fontSize: 11 }}>{v}</span>} />
                  <RTooltip contentStyle={{ background: 'color-mix(in srgb, var(--surface-3) 88%, transparent)', backdropFilter: 'blur(12px)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-sm)', fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </BentoCard>
      </div>

      {/* Daily P&L */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 4px' }}>Daily P&L</h3>
          <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginBottom: 14 }}>{dateFrom || dateTo ? 'Filtered range' : 'Last 30 days'}</p>
          <ChartSwitcher
            id="analytics-daily"
            height={220}
            defaultKind="bar"
            allowedKinds={['bar', 'area', 'line']}
            seriesLabel="Daily P&L"
            color="var(--accent-2)"
            valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
            linearData={filteredDaily.map((d) => ({ x: d.date, y: d.pnl }))}
          />
        </div>
      </BentoCard>

      {/* Strategy breakdown */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 16px' }}>Strategy Breakdown</h3>
          {strats.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--fg-muted)', fontSize: 13 }}>No data</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line-2)' }}>
                    {['Strategy', 'Trades', 'Win Rate', 'Avg Profit', 'Total P&L', 'Max Drawdown'].map((h) => (
                      <th key={h} style={{ padding: '10px 12px', textAlign: h === 'Strategy' ? 'left' : 'right', color: 'var(--fg-muted)', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {strats.map((s, i) => (
                    <tr key={s.strategy} style={{ borderBottom: '1px solid var(--line-1)' }}>
                      <td style={{ padding: '12px', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: STRAT_COLORS[i % STRAT_COLORS.length] }} />
                        <span style={{ fontWeight: 600, color: 'var(--fg-primary)' }}>{s.strategy.replace(/([A-Z])/g, ' $1').trim()}</span>
                      </td>
                      <td className="lt-tabular" style={{ padding: '12px', textAlign: 'right', color: 'var(--fg-secondary)' }}>{s.tradesCount}</td>
                      <td className="lt-tabular" style={{ padding: '12px', textAlign: 'right', color: s.winRate >= 50 ? 'var(--bull)' : 'var(--warn)' }}>{s.winRate.toFixed(1)}%</td>
                      <td className="lt-tabular" style={{ padding: '12px', textAlign: 'right', color: s.avgProfit >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{fmt(s.avgProfit)}</td>
                      <td className="lt-tabular" style={{ padding: '12px', textAlign: 'right', fontWeight: 700, color: s.totalPnl >= 0 ? 'var(--bull)' : 'var(--bear)' }}>{s.totalPnl >= 0 ? '+' : ''}{fmt(s.totalPnl)}</td>
                      <td className="lt-tabular" style={{ padding: '12px', textAlign: 'right', color: 'var(--bear)' }}>{fmt(s.maxDrawdown)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </BentoCard>

      {/* Hourly P&L + Holding Time */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 4px' }}>Hourly P&L</h3>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginBottom: 14 }}>P&L by hour of day</p>
            <ChartSwitcher
              id="analytics-hourly"
              height={200}
              defaultKind="bar"
              allowedKinds={['bar', 'line', 'area']}
              seriesLabel="Hourly P&L"
              color="var(--accent-2)"
              valueFormat={(v) => `₹${(v / 1000).toFixed(0)}k`}
              linearData={hourlyPnl.map((h) => ({ x: h.hour, y: h.pnl }))}
            />
          </div>
        </BentoCard>

        <BentoCard reveal>
          <div style={{ padding: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 4px' }}>Holding Time Distribution</h3>
            <p style={{ fontSize: 11, color: 'var(--fg-muted)', marginBottom: 14 }}>How long positions are held</p>
            <ChartSwitcher
              id="analytics-holding"
              height={200}
              defaultKind="bar"
              allowedKinds={['bar', 'line', 'area']}
              seriesLabel="Trades"
              color="#60a5fa"
              linearData={holdingTimes.map((h) => ({ x: h.range, y: h.count }))}
            />
          </div>
        </BentoCard>
      </div>

      {/* Top Wins / Losses */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {[
          { title: 'Top Winning Trades', data: topWins, color: 'var(--bull)' },
          { title: 'Top Losing Trades', data: topLosses, color: 'var(--bear)' },
        ].map(({ title, data, color }) => (
          <BentoCard key={title} reveal>
            <div style={{ padding: 24 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-primary)', margin: '0 0 16px' }}>{title}</h3>
              {data.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: 'var(--fg-muted)', fontSize: 13 }}>No trades</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                  {data.map((tr, i) => (
                    <div key={tr.tradeId} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: i < data.length - 1 ? '1px solid var(--line-1)' : 'none' }}>
                      <div>
                        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg-primary)' }}>{tr.symbol}</span>
                        <span style={{ fontSize: 10, color: 'var(--fg-muted)', marginLeft: 8 }}>{tr.strategy.replace(/_/g, ' ')}</span>
                      </div>
                      <span className="lt-tabular" style={{ fontSize: 13, fontWeight: 700, color }}>{(tr.realizedPnl ?? 0) >= 0 ? '+' : ''}{fmt(tr.realizedPnl ?? 0)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </BentoCard>
        ))}
      </div>
    </div>
  );
}
