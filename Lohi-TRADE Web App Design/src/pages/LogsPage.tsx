import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion } from 'motion/react';
import {
  RefreshCw, Search, Download, AlertTriangle, Info, Bug, AlertCircle,
  X, Play, Pause, Filter, ChevronDown, Layers, Server, Cpu, FileText,
} from 'lucide-react';
import { api } from '../lib/api-client';
import { exportToCsv, formatFilename } from '../lib/csv-exporter';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import { bentoStagger, revealVariants } from '../lib/motion';
import type { LogEntry } from '../lib/types';

/**
 * Logs & Audit — 2026 token-clean rewrite.
 *
 * Upgrades over the previous iteration:
 *   • Every color comes from the design-tokens palette. No raw hex
 *     values in the markup so the page flips cleanly with the theme
 *     store and inherits the Trade / Research accent per surface.
 *   • Header stats strip uses BentoCard + AnimatedNumber, matching
 *     OrdersPage / PositionsPage.
 *   • Level badges use the semantic bull / bear / warn / accent tokens
 *     — the same meaning as the rest of the app.
 *   • Row chrome uses `lt-glass` and `lt-bento` primitives instead of
 *     ad-hoc rgba surfaces so density and borders stay consistent.
 *   • Detail drawer uses the standard modal pattern (PaperTradeModal /
 *     SessionExpiredModal).
 */

const POLL_MS = 5_000;

// ─── Strategy detection ────────────────────────────────────────────────────

const STRATEGY_NAMES = [
  'MeanReversion', 'TrendFollowing', 'ORB', 'OpeningRangeBreakout',
  'VWAPBounce', 'StochasticRSI', 'ADXTrend', 'BollingerSqueeze',
  'PivotPoint', 'IchimokuCloud', 'MACDDivergence', 'ParabolicSARTrend',
  'VolumeBreakout', 'MultiMomentum',
  'MEAN_REVERSION', 'TREND_FOLLOWING',
];

function detectStrategy(log: LogEntry): string | null {
  const haystack = `${log.component} ${log.message} ${log.metadata ?? ''}`;
  for (const s of STRATEGY_NAMES) {
    if (haystack.includes(s)) return s.replace(/_/g, ' ');
  }
  return null;
}

// ─── Level meta (token-based) ──────────────────────────────────────────────

type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

const LVL: Record<
  LogLevel,
  {
    color: string;
    bg: string;
    border: string;
    icon: typeof Info;
    accent: 'indigo' | 'emerald' | 'rose' | 'cyan' | 'none';
  }
> = {
  DEBUG: {
    color: 'var(--fg-muted)',
    bg: 'var(--surface-4)',
    border: 'var(--line-3)',
    icon: Bug,
    accent: 'none',
  },
  INFO: {
    color: 'var(--accent-2)',
    bg: 'color-mix(in srgb, var(--accent) 12%, transparent)',
    border: 'color-mix(in srgb, var(--accent) 30%, transparent)',
    icon: Info,
    accent: 'cyan',
  },
  WARNING: {
    color: 'var(--warn)',
    bg: 'var(--warn-soft)',
    border: 'color-mix(in srgb, var(--warn) 30%, transparent)',
    icon: AlertTriangle,
    accent: 'none',
  },
  ERROR: {
    color: 'var(--bear)',
    bg: 'var(--bear-soft)',
    border: 'color-mix(in srgb, var(--bear) 30%, transparent)',
    icon: AlertCircle,
    accent: 'rose',
  },
};

type ViewMode = 'all' | 'system' | 'strategy';

// ─── Helpers ───────────────────────────────────────────────────────────────

function formatTimestamp(ts: string): string {
  const d = new Date(ts);
  const dd = d.getDate().toString().padStart(2, '0');
  const mon = d.toLocaleString('en', { month: 'short' });
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  const ss = d.getSeconds().toString().padStart(2, '0');
  return `${dd} ${mon}, ${hh}:${mm}:${ss}`;
}

// ─── Button primitives ─────────────────────────────────────────────────────

const HEADER_BTN: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  borderRadius: 'var(--r-sm)',
  fontSize: 11,
  fontWeight: 600,
  cursor: 'pointer',
  background: 'var(--surface-2)',
  border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)',
  transition: 'border-color var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out)',
};

// ─── Component ─────────────────────────────────────────────────────────────

export default function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [allLogs, setAllLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // URL-sync'd level filter (dashboard badges deep-link with ?level=warning).
  const [levelFilter, setLevelFilter] = useState<string>(() => {
    const p = searchParams.get('level');
    return p ? p.toUpperCase() : '';
  });
  const [componentFilter, setComponentFilter] = useState('');
  const [strategyFilter, setStrategyFilter] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch ALL logs; level filter is applied client-side so stats stay honest.
  const fetchLogs = useCallback(async () => {
    try {
      const p: { component?: string } = {};
      if (componentFilter) p.component = componentFilter;
      setAllLogs(await api.getLogs(p));
      setError(null);
    } catch {
      setError('Failed to load logs');
    } finally {
      setLoading(false);
    }
  }, [componentFilter]);

  useEffect(() => {
    setLoading(true);
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (autoRefresh) pollRef.current = setInterval(fetchLogs, POLL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [autoRefresh, fetchLogs]);

  // Keep the URL in sync with the level filter.
  useEffect(() => {
    if (levelFilter) {
      setSearchParams({ level: levelFilter.toLowerCase() }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  }, [levelFilter, setSearchParams]);

  useEffect(() => {
    const p = searchParams.get('level');
    if (p && p.toUpperCase() !== levelFilter) setLevelFilter(p.toUpperCase());
  }, [searchParams]);

  // Derived collections --------------------------------------------------

  const components = useMemo(
    () => Array.from(new Set(allLogs.map((l) => l.component))).sort(),
    [allLogs],
  );

  const stats = useMemo(() => {
    const s = { ERROR: 0, WARNING: 0, INFO: 0, DEBUG: 0 };
    allLogs.forEach((l) => {
      const k = l.eventType.toUpperCase() as LogLevel;
      if (k in s) s[k]++;
    });
    return s;
  }, [allLogs]);

  const annotated = useMemo(
    () => allLogs.map((l) => ({ ...l, _strategy: detectStrategy(l) })),
    [allLogs],
  );

  const strategies = useMemo(
    () =>
      Array.from(
        new Set(annotated.map((l) => l._strategy).filter(Boolean) as string[]),
      ).sort(),
    [annotated],
  );

  const filtered = useMemo(() => {
    let list = annotated;
    if (levelFilter) list = list.filter((l) => l.eventType.toUpperCase() === levelFilter);
    if (viewMode === 'system') list = list.filter((l) => !l._strategy);
    else if (viewMode === 'strategy') list = list.filter((l) => !!l._strategy);
    if (strategyFilter) list = list.filter((l) => l._strategy === strategyFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (l) =>
          l.message.toLowerCase().includes(q) ||
          l.component.toLowerCase().includes(q) ||
          (l._strategy?.toLowerCase().includes(q) ?? false),
      );
    }
    return list;
  }, [annotated, levelFilter, viewMode, strategyFilter, search]);

  const strategyGroups = useMemo(() => {
    if (viewMode !== 'strategy' && !strategyFilter) return null;
    const groups: Record<string, typeof filtered> = {};
    filtered.forEach((l) => {
      const key = l._strategy || 'Other';
      if (!groups[key]) groups[key] = [];
      groups[key].push(l);
    });
    return groups;
  }, [filtered, viewMode, strategyFilter]);

  const exportLogs = () =>
    exportToCsv({
      filename: formatFilename('logs'),
      columns: [
        { header: 'Timestamp', key: 'createdAt', formatter: (v) => new Date(v as string).toISOString() },
        { header: 'Level', key: 'eventType', formatter: (v) => String(v).toUpperCase() },
        { header: 'Component', key: 'component' },
        { header: 'Strategy', key: '_strategy', formatter: (v) => (v as string) || '—' },
        { header: 'Message', key: 'message' },
      ],
      data: filtered as unknown as Record<string, unknown>[],
    });

  const hasActiveFilter =
    !!levelFilter || !!strategyFilter || viewMode !== 'all' || !!search || !!componentFilter;

  // ── Loading skeleton ─────────────────────────────────────────────────
  if (loading && !allLogs.length) {
    return (
      <div>
        <PageHeader icon={<FileText size={16} />} title="Logs & Audit" subtitle="System event log" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 16 }}>
          {Array.from({ length: 10 }).map((_, i) => (
            <div
              key={i}
              className="lt-skeleton"
              style={{ height: 44, background: 'var(--surface-3)', borderRadius: 'var(--r-sm)' }}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────
  if (error && !allLogs.length) {
    return (
      <div>
        <PageHeader icon={<FileText size={16} />} title="Logs & Audit" subtitle="System event log" />
        <div
          style={{
            marginTop: 16,
            padding: 32,
            borderRadius: 'var(--r-md)',
            textAlign: 'center',
            background: 'var(--bear-soft)',
            border: '1px solid color-mix(in srgb, var(--bear) 30%, transparent)',
          }}
        >
          <p style={{ color: 'var(--bear)', fontSize: 13, margin: 0 }}>{error}</p>
          <button
            onClick={fetchLogs}
            style={{
              marginTop: 14,
              padding: '8px 16px',
              borderRadius: 'var(--r-sm)',
              background: 'color-mix(in srgb, var(--bear) 14%, transparent)',
              border: '1px solid color-mix(in srgb, var(--bear) 32%, transparent)',
              color: 'var(--bear)',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Main ─────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, height: '100%' }}>
      <PageHeader
        icon={<FileText size={16} />}
        title="Logs & Audit"
        subtitle={`${filtered.length.toLocaleString()} of ${allLogs.length.toLocaleString()} entries${
          levelFilter ? ` · ${levelFilter}` : ''
        }${strategyFilter ? ` · ${strategyFilter}` : ''}`}
        actions={
          <>
            <button
              onClick={() => setAutoRefresh((v) => !v)}
              style={{
                ...HEADER_BTN,
                background: autoRefresh ? 'var(--bull-soft)' : HEADER_BTN.background,
                borderColor: autoRefresh
                  ? 'color-mix(in srgb, var(--bull) 32%, transparent)'
                  : HEADER_BTN.border as string,
                color: autoRefresh ? 'var(--bull)' : (HEADER_BTN.color as string),
              }}
              aria-pressed={autoRefresh}
            >
              {autoRefresh ? <Pause size={12} /> : <Play size={12} />}
              {autoRefresh ? 'Live' : 'Auto'}
            </button>
            <button onClick={fetchLogs} style={HEADER_BTN}>
              <RefreshCw size={12} /> Refresh
            </button>
            <button onClick={exportLogs} style={HEADER_BTN}>
              <Download size={12} /> Export
            </button>
          </>
        }
      />

      {/* ── Stats strip — BentoCards, consistent with Orders / Positions ── */}
      <motion.div
        variants={bentoStagger}
        initial="hidden"
        animate="visible"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 14,
        }}
      >
        {(['ERROR', 'WARNING', 'INFO', 'DEBUG'] as const).map((lvl) => {
          const meta = LVL[lvl];
          const Icon = meta.icon;
          const active = levelFilter === lvl;
          return (
            <BentoCard
              key={lvl}
              accent={meta.accent}
              onClick={() => setLevelFilter(active ? '' : lvl)}
              role="button"
              aria-pressed={active}
              style={{
                cursor: 'pointer',
                borderColor: active ? meta.border : undefined,
                boxShadow: active
                  ? `0 0 0 1px ${meta.border} inset`
                  : undefined,
              }}
            >
              <motion.div variants={revealVariants} style={{ padding: '16px 18px' }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: 6,
                  }}
                >
                  <p
                    style={{
                      fontSize: 10,
                      color: 'var(--fg-muted)',
                      textTransform: 'uppercase',
                      fontWeight: 700,
                      letterSpacing: '0.12em',
                      margin: 0,
                    }}
                  >
                    {lvl.toLowerCase()}
                  </p>
                  <Icon size={13} color={meta.color} aria-hidden />
                </div>
                <p
                  className="lt-tabular"
                  style={{
                    fontSize: 24,
                    fontWeight: 700,
                    color: meta.color,
                    letterSpacing: '-0.02em',
                    margin: 0,
                  }}
                >
                  <AnimatedNumber
                    value={stats[lvl]}
                    color={meta.color}
                    format={(v) => Math.round(v).toLocaleString()}
                  />
                </p>
              </motion.div>
            </BentoCard>
          );
        })}
      </motion.div>

      {/* ── View mode tabs ───────────────────────────────────────────── */}
      <div
        role="tablist"
        aria-label="Log view mode"
        style={{
          display: 'inline-flex',
          gap: 2,
          padding: 3,
          width: 'fit-content',
          background: 'var(--surface-2)',
          border: '1px solid var(--line-2)',
          borderRadius: 'var(--r-pill)',
        }}
      >
        {(
          [
            { key: 'all' as ViewMode, label: 'All logs', icon: Layers },
            { key: 'system' as ViewMode, label: 'System', icon: Server },
            { key: 'strategy' as ViewMode, label: 'By strategy', icon: Cpu },
          ]
        ).map(({ key, label, icon: Icon }) => {
          const active = viewMode === key;
          return (
            <button
              key={key}
              role="tab"
              aria-selected={active}
              onClick={() => {
                setViewMode(key);
                if (key !== 'strategy') setStrategyFilter('');
              }}
              style={{
                all: 'unset',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                fontSize: 11.5,
                fontWeight: 700,
                letterSpacing: '0.06em',
                cursor: 'pointer',
                borderRadius: 'var(--r-pill)',
                color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
                background: active
                  ? 'color-mix(in srgb, var(--accent) 14%, transparent)'
                  : 'transparent',
                border: active
                  ? '1px solid color-mix(in srgb, var(--accent) 32%, transparent)'
                  : '1px solid transparent',
                transition: 'all var(--dur-2) var(--ease-out)',
              }}
            >
              <Icon size={13} />
              {label}
            </button>
          );
        })}
      </div>

      {/* ── Filter row: search + component + strategy + clear ─────── */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <div
          className="lt-glass"
          style={{
            flex: 1,
            minWidth: 240,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '0 12px',
            borderRadius: 'var(--r-sm)',
          }}
        >
          <Search size={13} color="var(--fg-muted)" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by message, component, or strategy…"
            style={{
              flex: 1,
              padding: '9px 0',
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--fg-primary)',
              fontSize: 13,
            }}
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              aria-label="Clear search"
              style={{
                all: 'unset',
                cursor: 'pointer',
                padding: 2,
                display: 'inline-flex',
                color: 'var(--fg-muted)',
              }}
            >
              <X size={13} />
            </button>
          )}
        </div>

        <SelectField
          label="Component"
          value={componentFilter}
          options={[{ value: '', label: 'All components' }, ...components.map((c) => ({ value: c, label: c }))]}
          onChange={setComponentFilter}
        />

        {strategies.length > 0 && (
          <SelectField
            label="Strategy"
            value={strategyFilter}
            highlight={!!strategyFilter}
            options={[
              { value: '', label: 'All strategies' },
              ...strategies.map((s) => ({ value: s, label: s })),
            ]}
            onChange={(v) => {
              setStrategyFilter(v);
              if (v) setViewMode('strategy');
            }}
          />
        )}

        {hasActiveFilter && (
          <button
            onClick={() => {
              setLevelFilter('');
              setStrategyFilter('');
              setViewMode('all');
              setSearch('');
              setComponentFilter('');
            }}
            style={{
              ...HEADER_BTN,
              color: 'var(--bear)',
              background: 'var(--bear-soft)',
              border: '1px solid color-mix(in srgb, var(--bear) 30%, transparent)',
            }}
          >
            <X size={12} /> Clear all
          </button>
        )}
      </div>

      {/* ── Strategy summary cards (strategy view) ───────────────── */}
      {viewMode === 'strategy' && !strategyFilter && strategyGroups && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 10,
          }}
        >
          {Object.entries(strategyGroups).map(([name, logs]) => {
            const errs = logs.filter((l) => l.eventType.toUpperCase() === 'ERROR').length;
            const warns = logs.filter((l) => l.eventType.toUpperCase() === 'WARNING').length;
            return (
              <button
                key={name}
                onClick={() => setStrategyFilter(name)}
                className="lt-bento"
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                  padding: '14px 16px',
                  textAlign: 'left',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Cpu size={14} color="var(--accent-2)" />
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>
                    {name}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
                  <span style={{ color: 'var(--fg-muted)' }}>
                    {logs.length.toLocaleString()} logs
                  </span>
                  {errs > 0 && (
                    <span style={{ color: 'var(--bear)', fontWeight: 700 }}>
                      {errs} errors
                    </span>
                  )}
                  {warns > 0 && (
                    <span style={{ color: 'var(--warn)', fontWeight: 700 }}>
                      {warns} warns
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* ── Log list ──────────────────────────────────────────────── */}
      <div
        className="lt-bento"
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          padding: 0,
        }}
      >
        {/* Table header */}
        <div
          className="lt-glass"
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 1,
            display: 'grid',
            gridTemplateColumns: '140px 88px 140px 130px 1fr',
            padding: '10px 16px',
            gap: 12,
            borderBottom: '1px solid var(--line-2)',
          }}
        >
          {['Timestamp', 'Level', 'Component', 'Strategy', 'Message'].map((h) => (
            <span
              key={h}
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: 'var(--fg-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
              }}
            >
              {h}
            </span>
          ))}
        </div>

        {/* Rows */}
        <div
          className="lt-scroll"
          style={{
            flex: 1,
            overflowY: 'auto',
            minHeight: 0,
          }}
        >
          {filtered.length === 0 ? (
            <div style={{ padding: 48, textAlign: 'center' }}>
              <Filter
                size={26}
                color="var(--fg-muted)"
                style={{ margin: '0 auto 10px', opacity: 0.5 }}
              />
              <p style={{ color: 'var(--fg-muted)', fontSize: 13, margin: 0 }}>
                No log entries match your filters.
              </p>
              {hasActiveFilter && (
                <button
                  onClick={() => {
                    setLevelFilter('');
                    setStrategyFilter('');
                    setViewMode('all');
                    setSearch('');
                    setComponentFilter('');
                  }}
                  style={{
                    ...HEADER_BTN,
                    marginTop: 12,
                    color: 'var(--accent-2)',
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            filtered.map((log, i) => {
              const lvl = (log.eventType.toUpperCase() as LogLevel);
              const meta = LVL[lvl] ?? LVL.INFO;
              const Icon = meta.icon;
              return (
                <div
                  key={log.id ?? i}
                  onClick={() => setSelected(log)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '140px 88px 140px 130px 1fr',
                    padding: '10px 16px',
                    gap: 12,
                    cursor: 'pointer',
                    borderLeft: `3px solid ${meta.border}`,
                    borderBottom: '1px solid var(--line-1)',
                    background: i % 2 === 0 ? 'transparent' : 'var(--surface-3)',
                    transition: 'background var(--dur-1) var(--ease-out)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = meta.bg)}
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background =
                      i % 2 === 0 ? 'transparent' : 'var(--surface-3)')
                  }
                >
                  <span
                    className="lt-tabular"
                    style={{
                      fontSize: 12,
                      color: 'var(--fg-muted)',
                      whiteSpace: 'nowrap',
                      fontFamily: 'ui-monospace, monospace',
                    }}
                  >
                    {formatTimestamp(log.createdAt)}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Icon size={12} color={meta.color} />
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: meta.color,
                        letterSpacing: '0.04em',
                      }}
                    >
                      {lvl}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: 'var(--fg-secondary)',
                      padding: '2px 8px',
                      borderRadius: 'var(--r-xs)',
                      background: 'var(--surface-4)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      alignSelf: 'center',
                      justifySelf: 'start',
                    }}
                  >
                    {log.component}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: '2px 8px',
                      borderRadius: 'var(--r-xs)',
                      color: log._strategy ? 'var(--accent-2)' : 'var(--fg-muted)',
                      background: log._strategy
                        ? 'color-mix(in srgb, var(--accent) 12%, transparent)'
                        : 'transparent',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      alignSelf: 'center',
                      justifySelf: 'start',
                    }}
                  >
                    {log._strategy ?? '—'}
                  </span>
                  <span
                    style={{
                      fontSize: 12.5,
                      color: 'var(--fg-secondary)',
                      lineHeight: 1.4,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {log.message}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Detail drawer ─────────────────────────────────────────── */}
      {selected && <LogDetail log={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

// ─── Select field ─────────────────────────────────────────────────────────

function SelectField({
  label,
  value,
  options,
  onChange,
  highlight = false,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  highlight?: boolean;
}) {
  return (
    <div style={{ position: 'relative' }}>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          appearance: 'none',
          padding: '9px 30px 9px 12px',
          borderRadius: 'var(--r-sm)',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          outline: 'none',
          minWidth: 160,
          color: highlight ? 'var(--accent-2)' : 'var(--fg-secondary)',
          background: highlight
            ? 'color-mix(in srgb, var(--accent) 10%, transparent)'
            : 'var(--surface-2)',
          border: `1px solid ${
            highlight
              ? 'color-mix(in srgb, var(--accent) 30%, transparent)'
              : 'var(--line-2)'
          }`,
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={13}
        color={highlight ? 'var(--accent-2)' : 'var(--fg-muted)'}
        style={{
          position: 'absolute',
          right: 10,
          top: '50%',
          transform: 'translateY(-50%)',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
}

// ─── Log detail modal ─────────────────────────────────────────────────────

function LogDetail({ log, onClose }: { log: LogEntry; onClose: () => void }) {
  const lvl = (log.eventType.toUpperCase() as LogLevel);
  const meta = LVL[lvl] ?? LVL.INFO;
  const Icon = meta.icon;
  const strat = detectStrategy(log);

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
        background: 'var(--scrim)',
        backdropFilter: 'saturate(140%) blur(8px)',
        WebkitBackdropFilter: 'saturate(140%) blur(8px)',
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="lt-bento"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620,
          maxWidth: '92vw',
          maxHeight: '84vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ height: 4, background: meta.border }} />

        <div
          style={{
            padding: '18px 24px 14px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                padding: 8,
                borderRadius: 'var(--r-sm)',
                background: meta.bg,
                border: `1px solid ${meta.border}`,
                display: 'inline-flex',
              }}
            >
              <Icon size={18} color={meta.color} />
            </div>
            <div>
              <p
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: meta.color,
                  margin: 0,
                  letterSpacing: '0.04em',
                }}
              >
                {lvl}
              </p>
              <p
                style={{
                  fontSize: 12,
                  color: 'var(--fg-muted)',
                  margin: '2px 0 0',
                  fontFamily: 'ui-monospace, monospace',
                }}
              >
                {formatTimestamp(log.createdAt)}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              all: 'unset',
              cursor: 'pointer',
              padding: 6,
              display: 'inline-flex',
              color: 'var(--fg-muted)',
            }}
          >
            <X size={18} />
          </button>
        </div>

        <div
          className="lt-scroll"
          style={{
            padding: '0 24px 24px',
            overflowY: 'auto',
            minHeight: 0,
          }}
        >
          <DetailField label="Component">
            <span
              style={{
                fontSize: 13,
                color: 'var(--fg-secondary)',
                padding: '4px 10px',
                borderRadius: 'var(--r-xs)',
                background: 'var(--surface-4)',
                display: 'inline-block',
              }}
            >
              {log.component}
            </span>
          </DetailField>

          {strat && (
            <DetailField label="Strategy">
              <span
                style={{
                  fontSize: 13,
                  color: 'var(--accent-2)',
                  padding: '4px 10px',
                  borderRadius: 'var(--r-xs)',
                  background: 'color-mix(in srgb, var(--accent) 12%, transparent)',
                  display: 'inline-block',
                }}
              >
                {strat}
              </span>
            </DetailField>
          )}

          <DetailField label="Message">
            <p
              style={{
                fontSize: 13,
                color: 'var(--fg-primary)',
                lineHeight: 1.6,
                margin: 0,
                padding: 14,
                borderRadius: 'var(--r-sm)',
                background: 'var(--surface-1)',
                border: '1px solid var(--line-2)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {log.message}
            </p>
          </DetailField>

          {log.metadata && (
            <DetailField label="Metadata">
              <pre
                style={{
                  fontSize: 12,
                  color: 'var(--fg-secondary)',
                  lineHeight: 1.5,
                  margin: 0,
                  padding: 14,
                  borderRadius: 'var(--r-sm)',
                  background: 'var(--surface-1)',
                  border: '1px solid var(--line-2)',
                  overflowX: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontFamily: 'ui-monospace, monospace',
                }}
              >
                {(() => {
                  try {
                    return JSON.stringify(JSON.parse(log.metadata!), null, 2);
                  } catch {
                    return log.metadata;
                  }
                })()}
              </pre>
            </DetailField>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function DetailField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          display: 'block',
          marginBottom: 6,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}
