import { useEffect, useMemo, useRef, useState, useLayoutEffect, useCallback } from 'react';
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, AreaSeries,
  type IChartApi, type ISeriesApi, type Time,
} from 'lightweight-charts';
import { BarChart3, CandlestickChart, LineChart as LineIcon, ZoomIn, ZoomOut, Maximize2, RotateCcw } from 'lucide-react';

/**
 * TradeSymbolChart — OHLCV chart for the Trade page.
 *
 * Design choices (post-debug):
 *   • Container div is ALWAYS mounted. We don't wrap it in AnimatePresence
 *     because Framer remounts on key change, and the chart library holds
 *     DOM references that break if the container flips out under it.
 *   • We build the chart ONCE on mount and rebuild only when `style` changes
 *     (candlestick ↔ line ↔ area require different series classes).
 *   • Symbol and timeframe changes just call `setData` on the existing series
 *     — much faster, no flicker.
 *   • `autoSize: true` needs a container with real dimensions at init time.
 *     We use a useLayoutEffect so the chart creates after layout is known.
 *
 * Future wiring:
 *   swap `generateSeries()` for `api.getStockChart(symbol, period, interval)`.
 */

type ChartStyle = 'candles' | 'line' | 'area';
type Timeframe = '1m' | '5m' | '15m' | '1h' | '1D';

const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1h', '1D'];
const STYLES: { id: ChartStyle; label: string; Icon: React.ElementType }[] = [
  { id: 'candles', label: 'Candles', Icon: CandlestickChart },
  { id: 'line',    label: 'Line',    Icon: LineIcon },
  { id: 'area',    label: 'Area',    Icon: BarChart3 },
];

interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number }

/** Deterministic-ish mock OHLCV for a given symbol + timeframe. */
function generateSeries(symbol: string, tf: Timeframe, count = 120): Candle[] {
  const seed = [...symbol].reduce((a, c) => a + c.charCodeAt(0), 0);
  const basePrice = 500 + (seed % 4000);
  const stepSec =
    tf === '1m' ? 60 :
    tf === '5m' ? 300 :
    tf === '15m' ? 900 :
    tf === '1h' ? 3600 : 86400;

  // Align start to the bucket boundary so time values are strictly increasing integers.
  const now = Math.floor(Date.now() / 1000);
  const lastBucket = now - (now % stepSec);
  const start = lastBucket - (count - 1) * stepSec;

  // Pseudo-random generator seeded by symbol so each symbol's chart looks stable.
  let state = (seed * 9301 + 49297) % 233280;
  const rand = () => {
    state = (state * 9301 + 49297) % 233280;
    return state / 233280;
  };

  let price = basePrice;
  const out: Candle[] = [];
  for (let i = 0; i < count; i++) {
    const drift = Math.sin((i + seed) / 18) * 0.4;
    const noise = (rand() - 0.5) * basePrice * 0.012;
    const open = price;
    const close = +(open + drift * basePrice * 0.004 + noise).toFixed(2);
    const high = +Math.max(open, close, open + rand() * basePrice * 0.006).toFixed(2);
    const low  = +Math.min(open, close, open - rand() * basePrice * 0.006).toFixed(2);
    const volume = Math.floor(1_000 + rand() * 9_000);
    out.push({ time: start + i * stepSec, open, high, low, close, volume });
    price = close;
  }
  return out;
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export default function TradeSymbolChart({ symbol, ltp }: { symbol: string; ltp?: number }) {
  const [tf, setTf] = useState<Timeframe>('5m');
  const [style, setStyle] = useState<ChartStyle>('candles');

  const wrapperRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Candlestick'> | ISeriesApi<'Line'> | ISeriesApi<'Area'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const resizeObsRef = useRef<ResizeObserver | null>(null);

  const data = useMemo(() => generateSeries(symbol, tf, 120), [symbol, tf]);
  const last = data[data.length - 1];
  const prev = data[data.length - 2] ?? last;
  const dayChange = last ? last.close - prev.close : 0;
  const dayChangePct = prev?.close ? (dayChange / prev.close) * 100 : 0;

  /* ── Build the chart ONCE, and whenever style changes ─────────── */
  useLayoutEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;

    // Width/height from layout. `autoSize` handles subsequent resizes.
    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      autoSize: false, // we manage via ResizeObserver to avoid race
      layout: {
        background: { color: 'transparent' },
        textColor: cssVar('--fg-muted', '#7b828d'),
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        fontSize: 11,
      },
      rightPriceScale: { borderColor: 'transparent', scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: 'transparent', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      grid: {
        horzLines: { color: cssVar('--line-1', 'rgba(255,255,255,0.06)') },
        vertLines: { visible: false },
      },
      crosshair: { mode: 1 },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    chartRef.current = chart;

    // ── Price series (varies by style) ──
    if (style === 'candles') {
      const s = chart.addSeries(CandlestickSeries, {
        upColor: cssVar('--bull', '#00e38c'),
        downColor: cssVar('--bear', '#ff4d6d'),
        borderVisible: false,
        wickUpColor: cssVar('--bull', '#00e38c'),
        wickDownColor: cssVar('--bear', '#ff4d6d'),
      });
      priceSeriesRef.current = s;
    } else if (style === 'line') {
      const s = chart.addSeries(LineSeries, {
        color: cssVar('--accent-2', '#22d3ee'),
        lineWidth: 2,
        priceLineVisible: true,
      });
      priceSeriesRef.current = s;
    } else {
      const s = chart.addSeries(AreaSeries, {
        lineColor: cssVar('--accent-2', '#22d3ee'),
        topColor: 'rgba(34, 211, 238, 0.38)',
        bottomColor: 'rgba(34, 211, 238, 0.02)',
        lineWidth: 2,
        priceLineVisible: true,
      });
      priceSeriesRef.current = s;
    }

    // ── Volume series on overlay price scale ──
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    // Overlay scale — stays at the bottom 22% of the chart area.
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });
    volumeSeriesRef.current = vol;

    // ── ResizeObserver keeps the chart matched to the container ──
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry || !chartRef.current) return;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        chartRef.current.resize(Math.floor(width), Math.floor(height));
      }
    });
    ro.observe(el);
    resizeObsRef.current = ro;

    return () => {
      ro.disconnect();
      resizeObsRef.current = null;
      try { chart.remove(); } catch { /* already removed */ }
      chartRef.current = null;
      priceSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [style]);

  /* ── Push data into the existing series when symbol/tf/data changes ── */
  useEffect(() => {
    const chart = chartRef.current;
    const price = priceSeriesRef.current;
    const vol = volumeSeriesRef.current;
    if (!chart || !price || !vol) return;

    if (style === 'candles') {
      (price as ISeriesApi<'Candlestick'>).setData(
        data.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })),
      );
    } else {
      (price as ISeriesApi<'Line'> | ISeriesApi<'Area'>).setData(
        data.map((c) => ({ time: c.time as Time, value: c.close })),
      );
    }

    vol.setData(data.map((c) => ({
      time: c.time as Time,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(0, 227, 140, 0.45)' : 'rgba(255, 77, 109, 0.45)',
    })));

    // Fit AFTER setData so the initial view isn't empty.
    chart.timeScale().fitContent();
  }, [data, style]);

  /* ── Live LTP: update the last candle / last line point ──────── */
  useEffect(() => {
    if (ltp == null || !priceSeriesRef.current || !last) return;
    try {
      if (style === 'candles') {
        (priceSeriesRef.current as ISeriesApi<'Candlestick'>).update({
          time: last.time as Time,
          open: last.open,
          high: Math.max(last.high, ltp),
          low: Math.min(last.low, ltp),
          close: ltp,
        });
      } else {
        (priceSeriesRef.current as ISeriesApi<'Line'> | ISeriesApi<'Area'>).update({
          time: last.time as Time,
          value: ltp,
        });
      }
    } catch { /* chart may be rebuilding — ignore */ }
  }, [ltp, last, style]);

  /* ── Zoom / pan controls ──────────────────────────────────────── */
  const zoomBy = useCallback((factor: number) => {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const vr = ts.getVisibleLogicalRange();
    if (!vr) return;
    const span = vr.to - vr.from;
    const center = (vr.to + vr.from) / 2;
    const newSpan = Math.max(4, span * factor); // min 4 candles visible
    ts.setVisibleLogicalRange({
      from: center - newSpan / 2,
      to: center + newSpan / 2,
    });
  }, []);

  const zoomIn = useCallback(() => zoomBy(0.7), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1.4), [zoomBy]);
  const fitAll = useCallback(() => { chartRef.current?.timeScale().fitContent(); }, []);
  const resetView = useCallback(() => { chartRef.current?.timeScale().resetTimeScale(); }, []);

  /* ── Keyboard zoom (+ / − / 0) when the chart wrapper has focus ── */
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomIn(); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomOut(); }
      else if (e.key === '0') { e.preventDefault(); fitAll(); }
    };
    el.addEventListener('keydown', onKey);
    return () => el.removeEventListener('keydown', onKey);
  }, [zoomIn, zoomOut, fitAll]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Symbol meta + controls */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <p style={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.08em', color: 'var(--fg-muted)', margin: 0, textTransform: 'uppercase' }}>
            {symbol} · Chart
          </p>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
            <span className="lt-tabular" style={{ fontSize: 16, fontWeight: 700, color: 'var(--fg-primary)', letterSpacing: '-0.02em' }}>
              ₹{(ltp ?? last?.close ?? 0).toFixed(2)}
            </span>
            <span
              className="lt-tabular"
              style={{
                fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 6,
                color: dayChange >= 0 ? 'var(--bull)' : 'var(--bear)',
                background: dayChange >= 0 ? 'var(--bull-soft)' : 'var(--bear-soft)',
              }}
            >
              {dayChange >= 0 ? '+' : ''}{dayChange.toFixed(2)} ({dayChangePct >= 0 ? '+' : ''}{dayChangePct.toFixed(2)}%)
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <SegmentedControl
            value={tf}
            onChange={(v) => setTf(v as Timeframe)}
            options={TIMEFRAMES.map((t) => ({ value: t, label: t }))}
          />
          <SegmentedControl
            value={style}
            onChange={(v) => setStyle(v as ChartStyle)}
            options={STYLES.map((s) => ({ value: s.id, label: s.label, icon: s.Icon }))}
            compact
          />
        </div>
      </div>

      {/* Chart surface — always mounted, never remounted by the parent. */}
      <div style={{ position: 'relative', width: '100%' }}>
        <div
          ref={wrapperRef}
          tabIndex={0}
          aria-label="Price chart — use + / − / 0 to zoom"
          style={{
            width: '100%',
            height: 320,
            minHeight: 200,
            position: 'relative',
            outline: 'none',
            contain: 'layout size',
          }}
        />

        {/* Floating zoom toolbar */}
        <div
          style={{
            position: 'absolute',
            top: 10,
            right: 10,
            display: 'inline-flex',
            gap: 2,
            padding: 3,
            borderRadius: 'var(--r-sm)',
            background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)',
            backdropFilter: 'saturate(140%) blur(10px)',
            WebkitBackdropFilter: 'saturate(140%) blur(10px)',
            border: '1px solid var(--line-2)',
            boxShadow: 'var(--elev-1)',
          }}
        >
          <IconBtn label="Zoom in (+)" onClick={zoomIn}><ZoomIn size={12} /></IconBtn>
          <IconBtn label="Zoom out (−)" onClick={zoomOut}><ZoomOut size={12} /></IconBtn>
          <IconBtn label="Fit all (0)" onClick={fitAll}><Maximize2 size={12} /></IconBtn>
          <IconBtn label="Reset view" onClick={resetView}><RotateCcw size={12} /></IconBtn>
        </div>
      </div>
    </div>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 24,
        height: 24,
        borderRadius: 6,
        background: 'transparent',
        border: '1px solid transparent',
        color: 'var(--fg-muted)',
        cursor: 'pointer',
        transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--surface-4)';
        e.currentTarget.style.color = 'var(--fg-primary)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent';
        e.currentTarget.style.color = 'var(--fg-muted)';
      }}
    >
      {children}
    </button>
  );
}

/* ─── Tiny segmented control ──────────────────────────────────────── */
function SegmentedControl({
  value, onChange, options, compact,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; icon?: React.ElementType }[];
  compact?: boolean;
}) {
  return (
    <div
      role="tablist"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 2, padding: 3,
        borderRadius: 'var(--r-sm)', background: 'var(--surface-4)',
        border: '1px solid var(--line-2)',
      }}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        const Icon = opt.icon;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            title={opt.label}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              padding: compact ? '4px 8px' : '4px 10px', borderRadius: 6,
              fontSize: 11, fontWeight: 600,
              color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
              background: active ? 'var(--surface-2)' : 'transparent',
              border: active ? '1px solid var(--line-2)' : '1px solid transparent',
              boxShadow: active ? 'var(--elev-1)' : 'none',
              cursor: 'pointer',
              transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
            }}
          >
            {Icon ? <Icon size={11} /> : null}
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
