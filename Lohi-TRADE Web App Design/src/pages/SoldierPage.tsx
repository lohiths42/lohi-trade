import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Crosshair, Search, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react';
import { createChart, ColorType, LineSeries, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, CandlestickData, LineData, HistogramData, Time, DeepPartial, LineStyleOptions, SeriesOptionsCommon, SeriesMarker } from 'lightweight-charts';
import PageHeader from '../components/shared/PageHeader';
import { api } from '../lib/api-client';
import { useThemeColors, chartPalette } from '../hooks/use-theme-colors';
import VirtualTable from '../components/shared/VirtualTable';
import type { Signal, StrategyMetrics, Trade, VirtualColumn } from '../lib/types';

// ─── Indicator Calculations ─────────────────────────────────────────────────

function calcEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  const k = 2 / (period + 1);
  let ema: number | null = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    if (ema === null) {
      ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
    } else {
      ema = data[i] * k + ema * (1 - k);
    }
    result.push(ema);
  }
  return result;
}

function calcBB(data: number[], period: number, mult: number): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const upper: (number | null)[] = [];
  const middle: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { upper.push(null); middle.push(null); lower.push(null); continue; }
    const slice = data.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / period;
    const std = Math.sqrt(slice.reduce((a, v) => a + (v - mean) ** 2, 0) / period);
    middle.push(mean);
    upper.push(mean + mult * std);
    lower.push(mean - mult * std);
  }
  return { upper, middle, lower };
}

function calcRSI(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [null];
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i < data.length; i++) {
    const change = data[i] - data[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    if (i <= period) {
      avgGain += gain; avgLoss += loss;
      if (i === period) { avgGain /= period; avgLoss /= period; result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)); }
      else result.push(null);
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
    }
  }
  return result;
}

function calcMACD(data: number[], fast: number = 12, slow: number = 26, signal: number = 9): { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] } {
  const emaFast = calcEMA(data, fast);
  const emaSlow = calcEMA(data, slow);
  const macdLine: (number | null)[] = emaFast.map((f, i) => f !== null && emaSlow[i] !== null ? f - emaSlow[i]! : null);
  const validMacd = macdLine.filter((v) => v !== null) as number[];
  const sigLine = calcEMA(validMacd, signal);
  // Align signal line back to full array
  const signalFull: (number | null)[] = [];
  let si = 0;
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] === null) { signalFull.push(null); }
    else { signalFull.push(si < sigLine.length ? sigLine[si] : null); si++; }
  }
  const histogram: (number | null)[] = macdLine.map((m, i) => m !== null && signalFull[i] !== null ? m - signalFull[i]! : null);
  return { macd: macdLine, signal: signalFull, histogram };
}

function calcSupertrend(highs: number[], lows: number[], closes: number[], period: number = 10, multiplier: number = 3): (number | null)[] {
  const result: (number | null)[] = [];
  const atr: number[] = [];
  // Calculate ATR
  for (let i = 0; i < closes.length; i++) {
    if (i === 0) { atr.push(highs[i] - lows[i]); result.push(null); continue; }
    const tr = Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1]));
    if (i < period) { atr.push(tr); result.push(null); continue; }
    const avgTr = i === period ? atr.slice(0, period).reduce((a, b) => a + b, 0) / period : (atr[i - 1] * (period - 1) + tr) / period;
    atr.push(avgTr);
    const hl2 = (highs[i] + lows[i]) / 2;
    const upperBand = hl2 + multiplier * avgTr;
    const lowerBand = hl2 - multiplier * avgTr;
    // Simplified: use lower band when price is above, upper when below
    const prev = result[i - 1];
    if (prev === null) { result.push(closes[i] > hl2 ? lowerBand : upperBand); }
    else if (closes[i] > prev) { result.push(Math.max(lowerBand, prev)); }
    else { result.push(Math.min(upperBand, prev)); }
  }
  return result;
}

// ─── Synthetic candle data generator (used when no real data available) ──────

function generateSyntheticCandles(symbol: string, count: number, intervalMinutes: number = 1): CandlestickData[] {
  const candles: CandlestickData[] = [];
  let price = 1500 + Math.random() * 1000;
  const baseDate = new Date();
  baseDate.setHours(9, 15, 0, 0);
  baseDate.setDate(baseDate.getDate() - Math.floor(count / 375));
  for (let i = 0; i < count; i++) {
    const d = new Date(baseDate.getTime() + i * intervalMinutes * 60000);
    if (d.getHours() >= 16) { baseDate.setDate(baseDate.getDate() + 1); baseDate.setHours(9, 15, 0, 0); continue; }
    const change = (Math.random() - 0.48) * price * 0.003;
    const open = price;
    const close = price + change;
    const high = Math.max(open, close) + Math.random() * price * 0.001;
    const low = Math.min(open, close) - Math.random() * price * 0.001;
    price = close;
    const ts = Math.floor(d.getTime() / 1000) as Time;
    candles.push({ time: ts, open, high, low, close });
  }
  return candles;
}

// ─── Price Chart Component ──────────────────────────────────────────────────

interface PriceChartProps {
  symbol: string;
  trades: Trade[];
  timeframe: number; // minutes: 1, 5, or 15
}

function PriceChart({ symbol, trades, timeframe }: PriceChartProps) {
  const t = useThemeColors();
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || !rsiContainerRef.current || !macdContainerRef.current) return;

    const cp = chartPalette(t.isLight);

    // Create main chart
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: cp.background }, textColor: cp.text, fontSize: 10 },
      grid: { vertLines: { color: cp.grid }, horzLines: { color: cp.grid } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: cp.border },
      timeScale: { borderColor: cp.border, timeVisible: true, secondsVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: 320,
    });
    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: cp.bull, downColor: cp.bear,
      borderUpColor: cp.bull, borderDownColor: cp.bear,
      wickUpColor: cp.bull, wickDownColor: cp.bear,
    });

    const candles = generateSyntheticCandles(symbol, timeframe === 1 ? 500 : timeframe === 5 ? 300 : 200, timeframe);
    candleSeries.setData(candles);

    const closes = candles.map((c) => c.close);
    const highs = candles.map((c) => c.high);
    const lows = candles.map((c) => c.low);
    const times = candles.map((c) => c.time);

    // EMA 9
    const ema9 = calcEMA(closes, 9);
    const ema9Series = chart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, title: 'EMA 9' });
    ema9Series.setData(ema9.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);

    // EMA 21
    const ema21 = calcEMA(closes, 21);
    const ema21Series = chart.addSeries(LineSeries, { color: '#fbbf24', lineWidth: 1, title: 'EMA 21' });
    ema21Series.setData(ema21.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);

    // Bollinger Bands
    const bb = calcBB(closes, 20, 2);
    const bbUpper = chart.addSeries(LineSeries, { color: 'rgba(167,139,250,0.4)', lineWidth: 1, title: 'BB Upper' });
    const bbLower = chart.addSeries(LineSeries, { color: 'rgba(167,139,250,0.4)', lineWidth: 1, title: 'BB Lower' });
    bbUpper.setData(bb.upper.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);
    bbLower.setData(bb.lower.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);

    // Supertrend
    const st = calcSupertrend(highs, lows, closes, 10, 3);
    const stSeries = chart.addSeries(LineSeries, { color: '#f472b6', lineWidth: 2, title: 'Supertrend', lineStyle: 2 });
    stSeries.setData(st.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);

    // Trade markers
    const symbolTrades = trades.filter((t) => t.symbol === symbol);
    const markers = symbolTrades.flatMap((t) => {
      const m: any[] = [];
      const entryTs = Math.floor(new Date(t.entryTime).getTime() / 1000) as Time;
      m.push({ time: entryTs, position: t.side === 'BUY' ? 'belowBar' : 'aboveBar', color: t.side === 'BUY' ? '#34d399' : '#f87171', shape: t.side === 'BUY' ? 'arrowUp' : 'arrowDown', text: `${t.side} ${t.entryPrice.toFixed(0)}` });
      if (t.exitTime) {
        const exitTs = Math.floor(new Date(t.exitTime).getTime() / 1000) as Time;
        m.push({ time: exitTs, position: t.side === 'BUY' ? 'aboveBar' : 'belowBar', color: '#a78bfa', shape: 'circle', text: `Exit ${(t.exitPrice ?? 0).toFixed(0)}` });
      }
      return m;
    }).sort((a, b) => (a.time as number) - (b.time as number));
    if (markers.length > 0) createSeriesMarkers(candleSeries, markers);

    // RSI sub-chart
    const rsiChart = createChart(rsiContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: cp.background }, textColor: cp.text, fontSize: 10 },
      grid: { vertLines: { color: cp.grid }, horzLines: { color: cp.grid } },
      rightPriceScale: { borderColor: cp.border },
      timeScale: { borderColor: cp.border, timeVisible: true, secondsVisible: false, visible: false },
      width: rsiContainerRef.current.clientWidth,
      height: 100,
    });
    rsiChartRef.current = rsiChart;

    const rsi = calcRSI(closes, 14);
    const rsiSeries = rsiChart.addSeries(LineSeries, { color: '#a78bfa', lineWidth: 2, title: 'RSI 14' });
    rsiSeries.setData(rsi.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);

    // Overbought/oversold lines
    const ob = rsiChart.addSeries(LineSeries, { color: 'rgba(248,113,113,0.3)', lineWidth: 1 });
    const os = rsiChart.addSeries(LineSeries, { color: 'rgba(52,211,153,0.3)', lineWidth: 1 });
    const rsiTimes = rsi.map((v, i) => v !== null ? times[i] : null).filter(Boolean) as Time[];
    ob.setData(rsiTimes.map((t) => ({ time: t, value: 70 })));
    os.setData(rsiTimes.map((t) => ({ time: t, value: 30 })));

    // Sync time scales
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        rsiChart.timeScale().setVisibleLogicalRange(range);
        macdChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    // MACD sub-chart
    const macdChart = createChart(macdContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: cp.background }, textColor: cp.text, fontSize: 10 },
      grid: { vertLines: { color: cp.grid }, horzLines: { color: cp.grid } },
      rightPriceScale: { borderColor: cp.border },
      timeScale: { borderColor: cp.border, timeVisible: true, secondsVisible: false, visible: false },
      width: macdContainerRef.current.clientWidth,
      height: 80,
    });
    macdChartRef.current = macdChart;

    const macdData = calcMACD(closes);
    const macdLineSeries = macdChart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 2, title: 'MACD' });
    macdLineSeries.setData(macdData.macd.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);
    const signalLineSeries = macdChart.addSeries(LineSeries, { color: '#f87171', lineWidth: 1, title: 'Signal' });
    signalLineSeries.setData(macdData.signal.map((v, i) => v !== null ? { time: times[i], value: v } : null).filter(Boolean) as LineData[]);
    // Zero line
    const zeroLine = macdChart.addSeries(LineSeries, { color: 'rgba(148,163,184,0.2)', lineWidth: 1 });
    const macdTimes = macdData.macd.map((v, i) => v !== null ? times[i] : null).filter(Boolean) as Time[];
    zeroLine.setData(macdTimes.map((t) => ({ time: t, value: 0 })));

    chart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();
    macdChart.timeScale().fitContent();

    // Resize handler
    const handleResize = () => {
      if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      if (rsiContainerRef.current) rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
      if (macdContainerRef.current) macdChart.applyOptions({ width: macdContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      rsiChart.remove();
      macdChart.remove();
    };
  }, [symbol, trades, timeframe, t]);

  return (
    <div>
      <div ref={chartContainerRef} style={{ width: '100%' }} />
      <div style={{ padding: '4px 12px 0', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 9, color: t.textMuted, fontWeight: 600 }}>RSI (14)</span>
        <span style={{ fontSize: 9, color: 'rgba(248,113,113,0.6)' }}>— 70 overbought</span>
        <span style={{ fontSize: 9, color: 'rgba(52,211,153,0.6)' }}>— 30 oversold</span>
      </div>
      <div ref={rsiContainerRef} style={{ width: '100%' }} />
      <div style={{ padding: '4px 12px 0', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 9, color: '#60a5fa', fontWeight: 600 }}>MACD</span>
        <span style={{ fontSize: 9, color: '#f87171' }}>— Signal</span>
      </div>
      <div ref={macdContainerRef} style={{ width: '100%' }} />
    </div>
  );
}

// ─── Main Soldier Page ──────────────────────────────────────────────────────

export default function SoldierPage() {
  const t = useThemeColors();
  const card: React.CSSProperties = { background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16 };
  const [signals, setSignals] = useState<Signal[]>([]);
  const [strats, setStrats] = useState<StrategyMetrics[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [stratFilter, setStratFilter] = useState('ALL');
  const [sideFilter, setSideFilter] = useState('ALL');
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [chartSymbol, setChartSymbol] = useState<string>('');
  const [showChart, setShowChart] = useState(false);
  const [timeframe, setTimeframe] = useState<number>(1);
  const [statusFilter, setStatusFilter] = useState('ALL');

  useEffect(() => {
    Promise.all([
      api.getSignals().catch(() => []),
      api.getStrategyPerformance().catch(() => []),
      api.getTrades().catch(() => []),
    ]).then(([sig, sp, tr]) => {
      setSignals(sig); setStrats(sp); setTrades(tr);
      // Auto-select first symbol for chart
      if (sig.length > 0 && !chartSymbol) setChartSymbol(sig[0].symbol);
    }).finally(() => setLoading(false));
    const id = setInterval(() => { api.getSignals().then(setSignals).catch(() => {}); }, 10000);
    return () => clearInterval(id);
  }, []);

  const strategies = useMemo(() => [...new Set(signals.map((s) => s.strategy))], [signals]);
  const symbols = useMemo(() => [...new Set(signals.map((s) => s.symbol))], [signals]);

  const filtered = useMemo(() => {
    let list = signals;
    if (search) list = list.filter((s) => s.symbol.toLowerCase().includes(search.toLowerCase()));
    if (stratFilter !== 'ALL') list = list.filter((s) => s.strategy === stratFilter);
    if (sideFilter !== 'ALL') list = list.filter((s) => s.side === sideFilter);
    if (statusFilter !== 'ALL') list = list.filter((s) => (s.status ?? 'ACCEPTED') === statusFilter);
    return list;
  }, [signals, search, stratFilter, sideFilter, statusFilter]);

  const signalColumns: VirtualColumn<Signal>[] = useMemo(() => [
    { header: 'Time', accessor: (s) => <span style={{ color: t.textMuted, fontSize: 11 }}>{new Date(s.timestamp).toLocaleTimeString()}</span> },
    { header: 'Symbol', accessor: (s) => <span style={{ fontWeight: 600, color: t.textPrimary }}>{s.symbol}</span> },
    { header: 'Strategy', accessor: (s) => <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600, color: t.textSecondary, background: t.bgMuted }}>{s.strategy.replace(/_/g, ' ')}</span> },
    { header: 'Side', accessor: (s) => (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: s.side === 'BUY' ? '#34d399' : '#f87171', background: s.side === 'BUY' ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)' }}>
        {s.side === 'BUY' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
        {s.side}
      </span>
    ) },
    { header: 'Price', accessor: (s) => <span style={{ fontFamily: 'ui-monospace,monospace', color: t.textPrimary }}>₹{Number(s.price).toFixed(2)}</span>, align: 'right' },
    { header: 'SL', accessor: (s) => <span style={{ fontFamily: 'ui-monospace,monospace', color: '#f87171', fontSize: 11 }}>{s.stopLoss ? `₹${Number(s.stopLoss).toFixed(2)}` : '—'}</span>, align: 'right' },
    { header: 'Target', accessor: (s) => <span style={{ fontFamily: 'ui-monospace,monospace', color: '#34d399', fontSize: 11 }}>{s.target ? `₹${Number(s.target).toFixed(2)}` : '—'}</span>, align: 'right' },
    { header: 'Status', accessor: (s) => {
      const st = s.status ?? 'ACCEPTED';
      const isAccepted = st === 'ACCEPTED';
      return <span title={s.rejectionReason ?? undefined} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: isAccepted ? '#34d399' : '#f87171', background: isAccepted ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)', cursor: s.rejectionReason ? 'help' : 'default' }}>{st}</span>;
    } },
  ], []);

  if (loading) return <div style={{ padding: 48, textAlign: 'center', color: t.textMuted }}>Loading signals…</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Crosshair size={16} />}
        title="The Soldier"
        subtitle="Technical analysis · signals generated across all strategies"
        actions={
          <button onClick={() => setShowChart(!showChart)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', fontSize: 11, fontWeight: 600, color: showChart ? 'var(--accent-2)' : 'var(--fg-secondary)', background: showChart ? 'color-mix(in srgb, var(--accent-2) 10%, transparent)' : 'var(--surface-3)', border: `1px solid ${showChart ? 'var(--accent-2)' : 'var(--line-2)'}`, borderRadius: 'var(--r-sm)', cursor: 'pointer' }}>
            <BarChart3 size={12} /> {showChart ? 'Hide Chart' : 'Show Chart'}
          </button>
        }
      />

      {/* Strategy Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(strats.length + 1, 5)}, 1fr)`, gap: 16 }}>
        <div style={{ ...card, padding: '16px 20px' }}>
          <p style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.08em' }}>Total Signals</p>
          <p style={{ fontSize: 22, fontWeight: 700, color: t.textPrimary, fontFamily: 'ui-monospace,monospace', marginTop: 4 }}>{signals.length}</p>
        </div>
        {strats.map((s) => (
          <div key={s.strategy} style={{ ...card, padding: '16px 20px' }}>
            <p style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.08em' }}>{s.strategy.replace(/([A-Z])/g, ' $1').trim()}</p>
            <p style={{ fontSize: 18, fontWeight: 700, color: s.totalPnl >= 0 ? '#34d399' : '#f87171', fontFamily: 'ui-monospace,monospace', marginTop: 4 }}>{s.winRate.toFixed(1)}% win</p>
            <p style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{s.tradesCount} trades</p>
          </div>
        ))}
      </div>

      {/* Price Chart */}
      {showChart && (
        <div style={{ ...card, padding: 16, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Price Chart</h3>
              <select value={chartSymbol} onChange={(e) => setChartSymbol(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 6, padding: '4px 8px', fontSize: 11, color: t.textPrimary }}>
                {symbols.length > 0 ? symbols.map((s) => <option key={s} value={s}>{s}</option>) : <option value="">No symbols</option>}
              </select>
              <div style={{ display: 'flex', gap: 2 }}>
                {[1, 5, 15].map((tf) => (
                  <button key={tf} onClick={() => setTimeframe(tf)} style={{ padding: '3px 10px', fontSize: 10, fontWeight: timeframe === tf ? 700 : 500, color: timeframe === tf ? '#60a5fa' : t.textMuted, background: timeframe === tf ? 'rgba(96,165,250,0.1)' : 'transparent', border: `1px solid ${timeframe === tf ? '#60a5fa' : t.inputBorder}`, borderRadius: 4, cursor: 'pointer' }}>{tf}m</button>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 9, color: '#60a5fa' }}>● EMA 9</span>
              <span style={{ fontSize: 9, color: '#fbbf24' }}>● EMA 21</span>
              <span style={{ fontSize: 9, color: '#a78bfa' }}>┈ BB(20,2)</span>
              <span style={{ fontSize: 9, color: '#f472b6' }}>┈ Supertrend</span>
            </div>
          </div>
          {chartSymbol ? <PriceChart symbol={chartSymbol} trades={trades} timeframe={timeframe} /> : (
            <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: t.textMuted, fontSize: 13 }}>Select a symbol to view chart</div>
          )}
        </div>
      )}

      {/* Filters */}
      <div style={{ ...card, padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search symbol…" style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 10px 8px 32px', fontSize: 12, color: t.textPrimary, outline: 'none' }} />
        </div>
        <select value={stratFilter} onChange={(e) => setStratFilter(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: t.textPrimary }}>
          <option value="ALL">All Strategies</option>
          {strategies.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={sideFilter} onChange={(e) => setSideFilter(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: t.textPrimary }}>
          <option value="ALL">All Sides</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: t.textPrimary }}>
          <option value="ALL">All Status</option>
          <option value="ACCEPTED">Accepted</option>
          <option value="REJECTED">Rejected</option>
        </select>
      </div>

      {/* Signals Table */}
      <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 48, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>
            <Crosshair size={32} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
            {signals.length === 0 ? 'No signals generated yet' : 'No signals match filters'}
          </div>
        ) : (
          <VirtualTable<Signal>
            data={filtered}
            rowHeight={48}
            columns={signalColumns}
            keyExtractor={(s) => `${s.symbol}-${s.timestamp}-${s.strategy}`}
            onRowClick={(s) => setSelectedSignal(s)}
            tableId="soldier-signals"
          />
        )}
      </div>

      {/* Signal Detail Modal */}
      {selectedSignal && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setSelectedSignal(null)}>
          <div style={{ ...card, padding: 28, width: 400 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 16px' }}>Signal Details</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              {[
                { label: 'Symbol', value: selectedSignal.symbol },
                { label: 'Strategy', value: selectedSignal.strategy.replace(/_/g, ' ') },
                { label: 'Side', value: selectedSignal.side },
                { label: 'Price', value: `₹${Number(selectedSignal.price).toFixed(2)}` },
                { label: 'Stop Loss', value: selectedSignal.stopLoss ? `₹${Number(selectedSignal.stopLoss).toFixed(2)}` : '—' },
                { label: 'Target', value: selectedSignal.target ? `₹${Number(selectedSignal.target).toFixed(2)}` : '—' },
                { label: 'Status', value: selectedSignal.status ?? 'ACCEPTED' },
                { label: 'Time', value: new Date(selectedSignal.timestamp).toLocaleString() },
              ].map((m) => (
                <div key={m.label} style={{ background: t.inputBg, borderRadius: 8, padding: '10px 12px' }}>
                  <p style={{ fontSize: 9, color: t.textMuted, textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>{m.label}</p>
                  <p style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: 0 }}>{m.value}</p>
                </div>
              ))}
            </div>
            {selectedSignal.rejectionReason && (
              <div style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)', borderRadius: 8, padding: '10px 12px', marginBottom: 16 }}>
                <p style={{ fontSize: 9, color: '#f87171', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>Rejection Reason</p>
                <p style={{ fontSize: 12, color: '#fca5a5', margin: 0 }}>{selectedSignal.rejectionReason}</p>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => { setChartSymbol(selectedSignal.symbol); setShowChart(true); setSelectedSignal(null); }} style={{ flex: 1, padding: '8px', fontSize: 12, fontWeight: 600, color: '#60a5fa', background: 'rgba(96,165,250,0.1)', border: '1px solid rgba(96,165,250,0.3)', borderRadius: 8, cursor: 'pointer' }}>View Chart</button>
              <button onClick={() => setSelectedSignal(null)} style={{ flex: 1, padding: '8px', fontSize: 12, fontWeight: 600, color: t.textSecondary, background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, cursor: 'pointer' }}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
