import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea,
} from 'recharts';
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  type IChartApi, type ISeriesApi,
} from 'lightweight-charts';
import {
  LineChart as LineIcon, AreaChart as AreaIcon, BarChart3,
  CandlestickChart, Columns3, Check, ZoomIn, ZoomOut, RotateCcw,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

/* ════════════════════════════════════════════════════════════════════════════
   ChartSwitcher
   A unified chart primitive with a user-selectable chart type.
   Persists the selection per-chart-id in localStorage.

   Supported:
     • line        — single series line (Recharts)
     • area        — gradient-filled area (Recharts, default for portfolio P&L)
     • bar         — vertical bars (Recharts, default for daily P&L, histograms)
     • candlestick — OHLC candles (Lightweight-Charts)
     • histogram   — volume / indicator bars (Lightweight-Charts)

   Data shape:
     • For line/area/bar:  [{ x: string, y: number }, ...]
     • For candlestick:    [{ time, open, high, low, close }, ...]
     • For histogram:      [{ time, value, color? }, ...]
   ════════════════════════════════════════════════════════════════════════════ */

export type ChartKind = 'line' | 'area' | 'bar' | 'candlestick' | 'histogram';

export interface LinearPoint { x: string | number; y: number; }
export interface CandlePoint { time: number | string; open: number; high: number; low: number; close: number; }
export interface HistogramPoint { time: number | string; value: number; color?: string; }

interface BaseProps {
  /** Unique id — the user's picked chart type is persisted under this key. */
  id: string;
  /** Chart height in px. */
  height?: number;
  /** Default chart type if user has not picked one yet. */
  defaultKind?: ChartKind;
  /** Restrict which chart types can be picked. */
  allowedKinds?: ChartKind[];
  /** Label for the primary series (tooltip + legend). */
  seriesLabel?: string;
  /** Format a value for tooltips (e.g., INR). */
  valueFormat?: (v: number) => string;
  /** Optional accent color. Defaults to `var(--bull)`. */
  color?: string;
  /** Optional title shown in the header bar next to picker. */
  title?: string;
}

interface LinearProps extends BaseProps {
  linearData: LinearPoint[];
  /** If candlestick/histogram is also offered, pass OHLC. */
  candleData?: CandlePoint[];
  histogramData?: HistogramPoint[];
}

type Props = LinearProps;

const ALL_KINDS: { kind: ChartKind; label: string; Icon: React.ElementType }[] = [
  { kind: 'area',        label: 'Area',        Icon: AreaIcon },
  { kind: 'line',        label: 'Line',        Icon: LineIcon },
  { kind: 'bar',         label: 'Bar',         Icon: BarChart3 },
  { kind: 'candlestick', label: 'Candles',     Icon: CandlestickChart },
  { kind: 'histogram',   label: 'Histogram',   Icon: Columns3 },
];

function storageKey(id: string) { return `lohi.chart.${id}`; }

function loadKind(id: string, fallback: ChartKind): ChartKind {
  try {
    const raw = localStorage.getItem(storageKey(id));
    if (raw && (['line', 'area', 'bar', 'candlestick', 'histogram'] as ChartKind[]).includes(raw as ChartKind)) {
      return raw as ChartKind;
    }
  } catch { /* ignore */ }
  return fallback;
}

function saveKind(id: string, kind: ChartKind) {
  try { localStorage.setItem(storageKey(id), kind); } catch { /* ignore */ }
}

export default function ChartSwitcher({
  id,
  height = 260,
  defaultKind = 'area',
  allowedKinds = ['area', 'line', 'bar'],
  seriesLabel = 'Value',
  valueFormat = (v) => v.toLocaleString(),
  color = 'var(--bull)',
  title,
  linearData,
  candleData,
  histogramData,
}: Props) {
  // Filter allowed kinds to those we have data for
  const available = useMemo(() => {
    return allowedKinds.filter((k) => {
      if (k === 'candlestick') return !!candleData && candleData.length > 0;
      if (k === 'histogram') return !!histogramData && histogramData.length > 0;
      return linearData.length > 0;
    });
  }, [allowedKinds, linearData, candleData, histogramData]);

  const [kind, setKind] = useState<ChartKind>(() => {
    const persisted = loadKind(id, defaultKind);
    return (allowedKinds.includes(persisted) ? persisted : defaultKind);
  });

  // If the persisted kind is no longer available (no data for it), fall back
  useEffect(() => {
    if (available.length === 0) return;
    if (!available.includes(kind)) setKind(available[0]);
  }, [available, kind]);

  const onPick = (k: ChartKind) => {
    setKind(k);
    saveKind(id, k);
  };

  const isEmpty = linearData.length === 0
    && (!candleData || candleData.length === 0)
    && (!histogramData || histogramData.length === 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* ── Header bar ────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        {title && (
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg-secondary)' }}>{title}</div>
        )}
        <ChartKindPicker
          active={kind}
          available={available.length ? available : allowedKinds}
          onPick={onPick}
        />
      </div>

      {/* ── Chart body ────────────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        <motion.div
          key={kind}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          style={{ height }}
        >
          {isEmpty ? (
            <EmptyChart height={height} />
          ) : kind === 'candlestick' && candleData && candleData.length > 0 ? (
            <LWChart kind="candlestick" candleData={candleData} height={height} />
          ) : kind === 'histogram' && histogramData && histogramData.length > 0 ? (
            <LWChart kind="histogram" histogramData={histogramData} color={color} height={height} />
          ) : (
            <RechartsSurface
              kind={kind === 'candlestick' || kind === 'histogram' ? 'area' : kind}
              data={linearData}
              color={color}
              height={height}
              seriesLabel={seriesLabel}
              valueFormat={valueFormat}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

/* ─── Picker ───────────────────────────────────────────────────────── */
function ChartKindPicker({
  active, available, onPick,
}: { active: ChartKind; available: ChartKind[]; onPick: (k: ChartKind) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Chart type"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 2, padding: 3,
        borderRadius: 'var(--r-sm)',
        background: 'var(--surface-4)',
        border: '1px solid var(--line-2)',
      }}
    >
      {ALL_KINDS.filter((k) => available.includes(k.kind)).map(({ kind, label, Icon }) => {
        const isActive = active === kind;
        return (
          <button
            key={kind}
            role="tab"
            aria-selected={isActive}
            title={label}
            onClick={() => onPick(kind)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              padding: '4px 8px', borderRadius: 6,
              fontSize: 11, fontWeight: 600,
              color: isActive ? 'var(--fg-primary)' : 'var(--fg-muted)',
              background: isActive ? 'var(--surface-2)' : 'transparent',
              border: isActive ? '1px solid var(--line-2)' : '1px solid transparent',
              boxShadow: isActive ? 'var(--elev-1)' : 'none',
              cursor: 'pointer',
              transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
            }}
          >
            <Icon size={12} />
            <span>{label}</span>
            {isActive && <Check size={10} style={{ opacity: 0.6 }} />}
          </button>
        );
      })}
    </div>
  );
}

/* ─── Empty state ──────────────────────────────────────────────────── */
function EmptyChart({ height }: { height: number }) {
  return (
    <div style={{
      height, display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'var(--fg-muted)', fontSize: 13,
      border: '1px dashed var(--line-2)', borderRadius: 'var(--r-sm)',
    }}>
      No data to display
    </div>
  );
}

/* ─── Recharts surface (line/area/bar) with zoom ───────────────────── */
function RechartsSurface({
  kind, data, color, height, seriesLabel, valueFormat,
}: {
  kind: 'line' | 'area' | 'bar';
  data: LinearPoint[];
  color: string;
  height: number;
  seriesLabel: string;
  valueFormat: (v: number) => string;
}) {
  const grid = 'color-mix(in srgb, var(--fg-muted) 22%, transparent)';
  const axisTick = { fill: 'var(--fg-muted)', fontSize: 10 };
  const gradId = useMemo(() => `cs-${kind}-${Math.random().toString(36).slice(2, 9)}`, [kind]);

  const tooltipStyle: React.CSSProperties = {
    background: 'color-mix(in srgb, var(--surface-3) 88%, transparent)',
    backdropFilter: 'blur(12px)',
    border: '1px solid var(--line-2)',
    borderRadius: 'var(--r-sm)',
    fontSize: 12, padding: '8px 12px',
    color: 'var(--fg-primary)',
    boxShadow: 'var(--elev-2)',
  };

  /* ── Zoom state ────────────────────────────────────────────────
     We store the visible [startIndex, endIndex] window into `data`.
     Dragging selects a new window; buttons adjust the window around
     its center; reset restores the full range.                    */
  const fullRange = useMemo(() => ({ start: 0, end: Math.max(0, data.length - 1) }), [data.length]);
  const [range, setRange] = useState(fullRange);
  useEffect(() => { setRange(fullRange); }, [fullRange]);

  const visible = useMemo(
    () => data.slice(range.start, range.end + 1),
    [data, range],
  );

  /* ── Drag-to-select zoom ──────────────────────────────────────── */
  const [dragFrom, setDragFrom] = useState<string | number | null>(null);
  const [dragTo, setDragTo] = useState<string | number | null>(null);

  const onMouseDown = useCallback((e: any) => {
    if (!e || e.activeLabel == null) return;
    setDragFrom(e.activeLabel);
    setDragTo(e.activeLabel);
  }, []);
  const onMouseMove = useCallback((e: any) => {
    if (dragFrom == null || !e || e.activeLabel == null) return;
    setDragTo(e.activeLabel);
  }, [dragFrom]);
  const onMouseUp = useCallback(() => {
    if (dragFrom == null || dragTo == null || dragFrom === dragTo) {
      setDragFrom(null); setDragTo(null);
      return;
    }
    // Convert the x-values back to indices in the FULL data array.
    const fi = data.findIndex((p) => p.x === dragFrom);
    const ti = data.findIndex((p) => p.x === dragTo);
    if (fi < 0 || ti < 0) { setDragFrom(null); setDragTo(null); return; }
    const lo = Math.min(fi, ti);
    const hi = Math.max(fi, ti);
    if (hi - lo >= 2) setRange({ start: lo, end: hi });
    setDragFrom(null); setDragTo(null);
  }, [dragFrom, dragTo, data]);

  /* ── Zoom controls ────────────────────────────────────────────── */
  const zoomBy = useCallback((factor: number) => {
    setRange((r) => {
      const span = r.end - r.start;
      const center = (r.end + r.start) / 2;
      const newSpan = Math.max(2, Math.min(data.length - 1, Math.round(span * factor)));
      let start = Math.round(center - newSpan / 2);
      let end = start + newSpan;
      if (start < 0) { start = 0; end = Math.min(data.length - 1, newSpan); }
      if (end > data.length - 1) { end = data.length - 1; start = Math.max(0, end - newSpan); }
      return { start, end };
    });
  }, [data.length]);
  const zoomIn = useCallback(() => zoomBy(0.6), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1.7), [zoomBy]);
  const resetZoom = useCallback(() => setRange(fullRange), [fullRange]);
  const zoomed = range.start !== fullRange.start || range.end !== fullRange.end;

  /* ── Keyboard shortcuts (when focused) ───────────────────────── */
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomIn(); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomOut(); }
      else if (e.key === '0') { e.preventDefault(); resetZoom(); }
    };
    el.addEventListener('keydown', onKey);
    return () => el.removeEventListener('keydown', onKey);
  }, [zoomIn, zoomOut, resetZoom]);

  const commonChartProps = {
    data: visible,
    onMouseDown,
    onMouseMove,
    onMouseUp,
    onMouseLeave: onMouseUp,
  };

  const renderZoomBand = () =>
    dragFrom != null && dragTo != null ? (
      <ReferenceArea
        x1={dragFrom}
        x2={dragTo}
        strokeOpacity={0.3}
        fill="color-mix(in srgb, var(--accent) 22%, transparent)"
        stroke="color-mix(in srgb, var(--accent) 60%, transparent)"
      />
    ) : null;

  const chartNode = kind === 'bar' ? (
    <BarChart {...commonChartProps}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.95} />
          <stop offset="100%" stopColor={color} stopOpacity={0.35} />
        </linearGradient>
      </defs>
      <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
      <XAxis dataKey="x" stroke={grid} tick={axisTick} tickLine={false} axisLine={false} />
      <YAxis stroke={grid} tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(v) => valueFormat(v as number)} />
      <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [valueFormat(v), seriesLabel]} cursor={{ fill: 'color-mix(in srgb, var(--fg-muted) 8%, transparent)' }} />
      <Bar dataKey="y" fill={`url(#${gradId})`} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      {renderZoomBand()}
    </BarChart>
  ) : kind === 'line' ? (
    <LineChart {...commonChartProps}>
      <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
      <XAxis dataKey="x" stroke={grid} tick={axisTick} tickLine={false} axisLine={false} />
      <YAxis stroke={grid} tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(v) => valueFormat(v as number)} />
      <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [valueFormat(v), seriesLabel]} cursor={{ stroke: 'color-mix(in srgb, var(--fg-muted) 30%, transparent)' }} />
      <Line type="monotone" dataKey="y" stroke={color} strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
      {renderZoomBand()}
    </LineChart>
  ) : (
    <AreaChart {...commonChartProps}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
      <XAxis dataKey="x" stroke={grid} tick={axisTick} tickLine={false} axisLine={false} />
      <YAxis stroke={grid} tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(v) => valueFormat(v as number)} />
      <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [valueFormat(v), seriesLabel]} cursor={{ stroke: 'color-mix(in srgb, var(--fg-muted) 30%, transparent)' }} />
      <Area type="monotone" dataKey="y" stroke={color} strokeWidth={2.25} fill={`url(#${gradId})`} dot={false} isAnimationActive={false} />
      {renderZoomBand()}
    </AreaChart>
  );

  return (
    <div
      ref={wrapRef}
      tabIndex={0}
      aria-label="Chart — drag to zoom, + / − / 0 to zoom with keyboard"
      style={{ position: 'relative', height, outline: 'none', userSelect: dragFrom != null ? 'none' : 'auto' }}
    >
      <ResponsiveContainer width="100%" height="100%">
        {chartNode}
      </ResponsiveContainer>

      {/* Zoom toolbar */}
      <ZoomToolbar
        zoomIn={zoomIn}
        zoomOut={zoomOut}
        reset={resetZoom}
        hasZoom={zoomed}
      />
    </div>
  );
}

/* ─── Zoom toolbar (shared) ───────────────────────────────────────── */
function ZoomToolbar({
  zoomIn, zoomOut, reset, hasZoom,
}: { zoomIn: () => void; zoomOut: () => void; reset: () => void; hasZoom: boolean }) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 8,
        right: 8,
        display: 'inline-flex',
        gap: 2,
        padding: 3,
        borderRadius: 'var(--r-sm)',
        background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)',
        backdropFilter: 'saturate(140%) blur(10px)',
        WebkitBackdropFilter: 'saturate(140%) blur(10px)',
        border: '1px solid var(--line-2)',
        boxShadow: 'var(--elev-1)',
        zIndex: 2,
      }}
    >
      <ZoomBtn label="Zoom in (+)" onClick={zoomIn}><ZoomIn size={12} /></ZoomBtn>
      <ZoomBtn label="Zoom out (−)" onClick={zoomOut}><ZoomOut size={12} /></ZoomBtn>
      {hasZoom && (
        <ZoomBtn label="Reset zoom (0)" onClick={reset} accent><RotateCcw size={12} /></ZoomBtn>
      )}
    </div>
  );
}

function ZoomBtn({
  label, onClick, children, accent = false,
}: { label: string; onClick: () => void; children: React.ReactNode; accent?: boolean }) {
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
        background: accent ? 'color-mix(in srgb, var(--accent) 16%, transparent)' : 'transparent',
        border: accent ? '1px solid color-mix(in srgb, var(--accent) 32%, transparent)' : '1px solid transparent',
        color: accent ? 'var(--accent-2)' : 'var(--fg-muted)',
        cursor: 'pointer',
        transition: 'background 120ms var(--ease-out), color 120ms var(--ease-out)',
      }}
      onMouseEnter={(e) => {
        if (!accent) {
          e.currentTarget.style.background = 'var(--surface-4)';
          e.currentTarget.style.color = 'var(--fg-primary)';
        }
      }}
      onMouseLeave={(e) => {
        if (!accent) {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.color = 'var(--fg-muted)';
        }
      }}
    >
      {children}
    </button>
  );
}

/* ─── Lightweight-Charts surface (candlestick / histogram) with zoom ─── */
function LWChart(props:
  | { kind: 'candlestick'; candleData: CandlePoint[]; height: number }
  | { kind: 'histogram'; histogramData: HistogramPoint[]; color: string; height: number }
) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick' | 'Histogram' | 'Line'> | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: props.height,
      layout: {
        background: { color: 'transparent' },
        textColor: getCssVar('--fg-muted', '#7b828d'),
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        fontSize: 11,
      },
      rightPriceScale: { borderColor: 'transparent' },
      timeScale: { borderColor: 'transparent', timeVisible: false, secondsVisible: false },
      grid: {
        horzLines: { color: 'color-mix(in srgb, #7b828d 18%, transparent)' },
        vertLines: { visible: false },
      },
      crosshair: { mode: 1 },
      autoSize: true,
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    chartRef.current = chart;

    if (props.kind === 'candlestick') {
      const s = chart.addSeries(CandlestickSeries, {
        upColor: getCssVar('--bull', '#00e38c'),
        downColor: getCssVar('--bear', '#ff4d6d'),
        borderVisible: false,
        wickUpColor: getCssVar('--bull', '#00e38c'),
        wickDownColor: getCssVar('--bear', '#ff4d6d'),
      });
      s.setData(props.candleData.map((c) => ({
        time: c.time as number,
        open: c.open, high: c.high, low: c.low, close: c.close,
      })));
      seriesRef.current = s as unknown as ISeriesApi<'Candlestick'>;
    } else {
      const s = chart.addSeries(HistogramSeries, {
        color: props.color,
        priceFormat: { type: 'volume' },
      });
      s.setData(props.histogramData.map((d) => ({
        time: d.time as number,
        value: d.value,
        color: d.color,
      })));
      seriesRef.current = s as unknown as ISeriesApi<'Histogram'>;
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.kind, props.height, JSON.stringify('candleData' in props ? props.candleData : props.histogramData)]);

  /* ── Zoom controls (logical-range based) ───────────────────────── */
  const zoomBy = useCallback((factor: number) => {
    const chart = chartRef.current;
    if (!chart) return;
    const ts = chart.timeScale();
    const vr = ts.getVisibleLogicalRange();
    if (!vr) return;
    const span = vr.to - vr.from;
    const center = (vr.to + vr.from) / 2;
    const newSpan = Math.max(4, span * factor);
    ts.setVisibleLogicalRange({ from: center - newSpan / 2, to: center + newSpan / 2 });
  }, []);
  const zoomIn = useCallback(() => zoomBy(0.7), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1.4), [zoomBy]);
  const resetZoom = useCallback(() => { chartRef.current?.timeScale().fitContent(); }, []);

  return (
    <div style={{ position: 'relative', width: '100%', height: props.height }}>
      <div ref={ref} style={{ width: '100%', height: '100%' }} />
      <ZoomToolbar zoomIn={zoomIn} zoomOut={zoomOut} reset={resetZoom} hasZoom={true} />
    </div>
  );
}

function getCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
