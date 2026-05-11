import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Loader2, TrendingUp, TrendingDown, BarChart3, Building2, RefreshCw } from 'lucide-react';
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { useThemeColors, chartPalette } from '../hooks/use-theme-colors';
import { api } from '../lib/api-client';
import PageHeader from '../components/shared/PageHeader';

interface StockDetail {
  security_id: number;
  symbol: string;
  company_name: string;
  exchange: string;
  sector?: string;
  industry?: string;
  market_cap_category?: string;
  listing_date?: string;
  face_value?: string;
  status: string;
  pe_ratio?: string;
  pb_ratio?: string;
  market_cap?: string;
  dividend_yield?: string;
  eps?: string;
  roe?: string;
  debt_to_equity?: string;
  revenue_growth_1y?: string;
  revenue_growth_3y?: string;
  profit_growth_1y?: string;
  profit_growth_3y?: string;
  return_1y?: string;
  cagr_3y?: string;
  cagr_5y?: string;
  high_52w?: string;
  low_52w?: string;
  rsi_14?: string;
  sma_50?: string;
  sma_200?: string;
  avg_volume_20d?: number;
  price_change_1d?: string;
  price_change_1w?: string;
  price_change_1m?: string;
  price_change_3m?: string;
  price_change_6m?: string;
  price_change_1y?: string;
  price_change_3y?: string;
  price_change_5y?: string;
}

interface ChartBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

const PERIOD_OPTIONS = [
  { label: '1D', period: '1d', interval: '5m' },
  { label: '5D', period: '5d', interval: '15m' },
  { label: '1M', period: '1mo', interval: '1h' },
  { label: '3M', period: '3mo', interval: '1d' },
  { label: '6M', period: '6mo', interval: '1d' },
  { label: '1Y', period: '1y', interval: '1d' },
  { label: '2Y', period: '2y', interval: '1wk' },
  { label: '5Y', period: '5y', interval: '1wk' },
];

function DataRow({ label, value, color }: { label: string; value?: string | number | null; color?: string }) {
  const t = useThemeColors();
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '8px 0', borderBottom: `1px solid ${t.borderSubtle}`,
    }}>
      <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'ui-monospace,monospace', color: color ?? t.textPrimary }}>
        {value ?? '—'}
      </span>
    </div>
  );
}

function ChangeValue({ value }: { value?: string }) {
  if (!value) return <span style={{ color: 'var(--fg-muted)' }}>—</span>;
  const n = parseFloat(value);
  const color = n >= 0 ? 'var(--bull)' : 'var(--bear)';
  return <span style={{ color, fontWeight: 600 }}>{n >= 0 ? '+' : ''}{value}%</span>;
}

/* ── Price Chart Component ─────────────────────────────────────────────── */
function PriceChart({ symbol, isDark }: { symbol: string; isDark: boolean }) {
  const t = useThemeColors();
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [activePeriod, setActivePeriod] = useState(4); // default 6M
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState('');
  const [priceInfo, setPriceInfo] = useState<{
    current_price: number | null;
    previous_close: number | null;
    change: number | null;
    change_percent: number | null;
  }>({ current_price: null, previous_close: null, change: null, change_percent: null });

  const loadChart = useCallback(async (periodIdx: number) => {
    const opt = PERIOD_OPTIONS[periodIdx];
    setChartLoading(true);
    setChartError('');
    try {
      const res = await api.getStockChart(symbol, opt.period, opt.interval);
      setPriceInfo({
        current_price: res.current_price,
        previous_close: res.previous_close,
        change: res.change,
        change_percent: res.change_percent,
      });

      if (!chartContainerRef.current) return;

      // Destroy old chart
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const cp = chartPalette(!isDark);
      const chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth,
        height: 420,
        layout: {
          background: { color: 'transparent' },
          textColor: cp.text,
          fontFamily: 'ui-monospace, SFMono-Regular, monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: cp.grid },
          horzLines: { color: cp.grid },
        },
        crosshair: { mode: 0 },
        rightPriceScale: { borderColor: cp.border },
        timeScale: {
          borderColor: cp.border,
          timeVisible: opt.interval !== '1d' && opt.interval !== '1wk' && opt.interval !== '1mo',
        },
      });
      chartRef.current = chart;

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: cp.bull,
        downColor: cp.bear,
        borderUpColor: cp.bull,
        borderDownColor: cp.bear,
        wickUpColor: cp.bull,
        wickDownColor: cp.bear,
      });
      candleSeriesRef.current = candleSeries;

      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      volumeSeriesRef.current = volumeSeries;

      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      // Parse bars
      const candleData = res.bars.map((b: ChartBar) => ({
        time: b.time.includes('T') ? Math.floor(new Date(b.time).getTime() / 1000) : b.time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

      const volumeData = res.bars.map((b: ChartBar) => ({
        time: b.time.includes('T') ? Math.floor(new Date(b.time).getTime() / 1000) : b.time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(52,211,153,0.3)' : 'rgba(248,113,113,0.3)',
      }));

      candleSeries.setData(candleData as any);
      volumeSeries.setData(volumeData as any);
      chart.timeScale().fitContent();

      // Resize observer
      const ro = new ResizeObserver(() => {
        if (chartContainerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      });
      ro.observe(chartContainerRef.current);

    } catch (err: any) {
      const msg = err?.detail || err?.message || 'Failed to load chart data';
      setChartError(msg.includes('429') || msg.includes('rate') ? 'Data provider rate limit — please wait a moment and retry' : msg);
    } finally {
      setChartLoading(false);
    }
  }, [symbol, isDark]);

  useEffect(() => {
    loadChart(activePeriod);
    return () => {
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    };
  }, [activePeriod, loadChart]);

  const isPositive = (priceInfo.change ?? 0) >= 0;
  const priceColor = isPositive ? '#34d399' : '#f87171';

  return (
    <div style={{
      background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`,
      borderRadius: 16, padding: 20, overflow: 'hidden',
    }}>
      {/* Price header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          {priceInfo.current_price != null && (
            <>
              <span style={{ fontSize: 28, fontWeight: 800, fontFamily: 'ui-monospace,monospace', color: t.textPrimary }}>
                ₹{priceInfo.current_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
              </span>
              {priceInfo.change != null && (
                <span style={{ fontSize: 14, fontWeight: 700, color: priceColor, display: 'flex', alignItems: 'center', gap: 4 }}>
                  {isPositive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  {isPositive ? '+' : ''}{priceInfo.change.toFixed(2)}
                  {priceInfo.change_percent != null && ` (${isPositive ? '+' : ''}${priceInfo.change_percent.toFixed(2)}%)`}
                </span>
              )}
            </>
          )}
        </div>

        {/* Period selector */}
        <div style={{ display: 'flex', gap: 4 }}>
          {PERIOD_OPTIONS.map((opt, i) => (
            <button
              key={opt.label}
              onClick={() => setActivePeriod(i)}
              style={{
                padding: '5px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                border: activePeriod === i ? '1px solid rgba(59,130,246,0.4)' : `1px solid ${t.borderPrimary}`,
                background: activePeriod === i ? 'rgba(59,130,246,0.15)' : 'transparent',
                color: activePeriod === i ? '#3b82f6' : t.textMuted,
                transition: 'all 0.15s',
              }}
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={() => loadChart(activePeriod)}
            style={{
              padding: '5px 8px', borderRadius: 6, border: `1px solid ${t.borderPrimary}`,
              background: 'transparent', color: t.textMuted, cursor: 'pointer', display: 'flex', alignItems: 'center',
            }}
            title="Refresh"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Chart area */}
      {chartLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 420 }}>
          <Loader2 size={24} color={t.textMuted} style={{ animation: 'spin 1s linear infinite' }} />
        </div>
      )}
      {chartError && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 420, color: '#f87171', fontSize: 13 }}>
          {chartError}
        </div>
      )}
      <div ref={chartContainerRef} style={{ display: chartLoading || chartError ? 'none' : 'block' }} />
    </div>
  );
}

/* ── Main Page Component ───────────────────────────────────────────────── */
export default function StockDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const t = useThemeColors();
  const [stock, setStock] = useState<StockDetail | null>(null);
  const [liveQuote, setLiveQuote] = useState<{
    current_price: number | null; previous_close: number | null;
    change: number | null; change_percent: number | null;
    day_high: number | null; day_low: number | null;
    open_price: number | null; volume: number | null;
    market_cap: number | null; pe_ratio: number | null;
    high_52w: number | null; low_52w: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    api.getStockDetail(symbol)
      .then((data) => { setStock(data); setError(''); })
      .catch(() => setError('Failed to load stock details'))
      .finally(() => setLoading(false));

    // Also fetch live quote on-demand (fresh from market data provider)
    api.getStockQuote(symbol)
      .then((q) => setLiveQuote(q))
      .catch(() => {}); // non-critical
  }, [symbol]);

  const card: React.CSSProperties = {
    background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16, padding: 20,
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 300 }}>
        <Loader2 size={24} color={t.textMuted} style={{ animation: 'spin 1s linear infinite' }} />
      </div>
    );
  }

  if (error || !stock) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <p style={{ color: '#f87171', fontSize: 14, fontWeight: 600 }}>{error || 'Stock not found'}</p>
        <button onClick={() => navigate(-1)} style={{
          marginTop: 12, padding: '8px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600,
          border: `1px solid ${t.borderPrimary}`, background: t.bgMuted, color: t.textSecondary, cursor: 'pointer',
        }}>Go Back</button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<BarChart3 size={16} />}
        title={stock.symbol}
        subtitle={stock.name ?? 'Stock detail'}
        actions={
          <button onClick={() => navigate(-1)} style={{
            padding: '6px 12px', borderRadius: 'var(--r-sm)', border: '1px solid var(--line-2)',
            background: 'var(--surface-3)', color: 'var(--fg-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, fontWeight: 600,
          }}>
            <ArrowLeft size={12} /> Back
          </button>
        }
      />

      {/* Header details */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: t.textPrimary, margin: 0 }}>{stock.symbol}</h1>
            <span style={{
              padding: '2px 8px', borderRadius: 6, fontSize: 10, fontWeight: 700,
              background: stock.status === 'ACTIVE' ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)',
              color: stock.status === 'ACTIVE' ? '#34d399' : '#f87171',
            }}>{stock.status}</span>
          </div>
          <p style={{ fontSize: 13, color: t.textSecondary, margin: '2px 0 0' }}>{stock.company_name}</p>
        </div>
      </div>

      {/* Info pills */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {stock.exchange && (
          <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: t.bgMuted, color: t.textSecondary, border: `1px solid ${t.borderPrimary}` }}>
            {stock.exchange}
          </span>
        )}
        {stock.sector && (
          <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: t.accentBg, color: t.accentText, border: `1px solid rgba(59,130,246,0.2)` }}>
            {stock.sector}
          </span>
        )}
        {stock.industry && (
          <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: t.bgMuted, color: t.textSecondary, border: `1px solid ${t.borderPrimary}` }}>
            {stock.industry}
          </span>
        )}
        {stock.market_cap_category && (
          <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: 'rgba(139,92,246,0.1)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.2)' }}>
            {stock.market_cap_category}
          </span>
        )}
      </div>

      {/* ── Live Quote Summary (on-demand from yfinance) ─────────── */}
      {liveQuote && liveQuote.current_price != null && (
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10,
          background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 14, padding: '14px 18px',
        }}>
          {[
            { label: 'Current Price', value: `₹${liveQuote.current_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`, color: t.textPrimary },
            { label: 'Change', value: liveQuote.change != null ? `${liveQuote.change >= 0 ? '+' : ''}${liveQuote.change.toFixed(2)} (${liveQuote.change_percent?.toFixed(2)}%)` : '—', color: (liveQuote.change ?? 0) >= 0 ? '#34d399' : '#f87171' },
            { label: 'Day High', value: liveQuote.day_high != null ? `₹${liveQuote.day_high.toLocaleString('en-IN')}` : '—', color: t.textSecondary },
            { label: 'Day Low', value: liveQuote.day_low != null ? `₹${liveQuote.day_low.toLocaleString('en-IN')}` : '—', color: t.textSecondary },
            { label: 'Open', value: liveQuote.open_price != null ? `₹${liveQuote.open_price.toLocaleString('en-IN')}` : '—', color: t.textSecondary },
            { label: 'Volume', value: liveQuote.volume != null ? liveQuote.volume.toLocaleString() : '—', color: t.textSecondary },
          ].map(({ label, value, color }) => (
            <div key={label}>
              <p style={{ fontSize: 10, color: t.textMuted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 2px' }}>{label}</p>
              <p style={{ fontSize: 14, fontWeight: 700, fontFamily: 'ui-monospace,monospace', color, margin: 0 }}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* ── Interactive Price Chart ──────────────────────────────────── */}
      {symbol && <PriceChart symbol={symbol} isDark={!t.isLight} />}

      {/* Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        {/* Fundamental Data */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <div style={{ padding: 6, borderRadius: 8, background: 'rgba(59,130,246,0.12)' }}>
              <Building2 size={14} color="#3b82f6" />
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>Fundamentals</span>
          </div>
          <DataRow label="Market Cap" value={stock.market_cap} />
          <DataRow label="PE Ratio" value={stock.pe_ratio} />
          <DataRow label="PB Ratio" value={stock.pb_ratio} />
          <DataRow label="EPS" value={stock.eps} />
          <DataRow label="Dividend Yield" value={stock.dividend_yield ? `${stock.dividend_yield}%` : undefined} />
          <DataRow label="ROE" value={stock.roe ? `${stock.roe}%` : undefined} />
          <DataRow label="Debt/Equity" value={stock.debt_to_equity} />
          <DataRow label="Revenue Growth (1Y)" value={stock.revenue_growth_1y ? `${stock.revenue_growth_1y}%` : undefined} />
          <DataRow label="Revenue Growth (3Y)" value={stock.revenue_growth_3y ? `${stock.revenue_growth_3y}%` : undefined} />
          <DataRow label="Profit Growth (1Y)" value={stock.profit_growth_1y ? `${stock.profit_growth_1y}%` : undefined} />
          <DataRow label="Profit Growth (3Y)" value={stock.profit_growth_3y ? `${stock.profit_growth_3y}%` : undefined} />
          <DataRow label="Face Value" value={stock.face_value} />
          <DataRow label="Listing Date" value={stock.listing_date} />
        </div>

        {/* Technical Data */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <div style={{ padding: 6, borderRadius: 8, background: 'rgba(139,92,246,0.12)' }}>
              <BarChart3 size={14} color="#8b5cf6" />
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>Technicals</span>
          </div>
          <DataRow label="RSI (14)" value={stock.rsi_14} />
          <DataRow label="SMA 50" value={stock.sma_50} />
          <DataRow label="SMA 200" value={stock.sma_200} />
          <DataRow label="52W High" value={stock.high_52w} />
          <DataRow label="52W Low" value={stock.low_52w} />
          <DataRow label="Avg Volume (20D)" value={stock.avg_volume_20d?.toLocaleString()} />
        </div>

        {/* Price Changes */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <div style={{ padding: 6, borderRadius: 8, background: 'rgba(52,211,153,0.12)' }}>
              <TrendingUp size={14} color="#34d399" />
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>Price Performance</span>
          </div>
          {[
            ['1 Day', stock.price_change_1d], ['1 Week', stock.price_change_1w],
            ['1 Month', stock.price_change_1m], ['3 Months', stock.price_change_3m],
            ['6 Months', stock.price_change_6m], ['1 Year', stock.price_change_1y],
            ['3 Years', stock.price_change_3y], ['5 Years', stock.price_change_5y],
          ].map(([label, val], i, arr) => (
            <div key={label as string} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: i < arr.length - 1 ? `1px solid ${t.borderSubtle}` : 'none',
            }}>
              <span style={{ fontSize: 12, color: t.textMuted }}>{label as string}</span>
              <ChangeValue value={val as string | undefined} />
            </div>
          ))}
        </div>

        {/* Returns */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <div style={{ padding: 6, borderRadius: 8, background: 'rgba(251,191,36,0.12)' }}>
              <TrendingUp size={14} color="#fbbf24" />
            </div>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>Returns</span>
          </div>
          {[
            ['1Y Return', stock.return_1y],
            ['3Y CAGR', stock.cagr_3y],
            ['5Y CAGR', stock.cagr_5y],
          ].map(([label, val], i, arr) => (
            <div key={label as string} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: i < arr.length - 1 ? `1px solid ${t.borderSubtle}` : 'none',
            }}>
              <span style={{ fontSize: 12, color: t.textMuted }}>{label as string}</span>
              <ChangeValue value={val as string | undefined} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
