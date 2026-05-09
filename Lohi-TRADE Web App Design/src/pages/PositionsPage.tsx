import { useState, useMemo } from 'react';
import { Shield, X, ArrowUpDown, Search, Edit3, Target, TrendingUp, TrendingDown, ClipboardList } from 'lucide-react';
import { motion } from 'motion/react';
import { usePositions } from '../hooks/use-positions';
import { api } from '../lib/api-client';
import { useThemeColors } from '../hooks/use-theme-colors';
import VirtualTable from '../components/shared/VirtualTable';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import { bentoStagger, revealVariants } from '../lib/motion';
import type { Position, VirtualColumn } from '../lib/types';

const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const clr = (n: number) => (n > 0 ? 'var(--bull)' : n < 0 ? 'var(--bear)' : 'var(--fg-muted)');

type SortKey = 'symbol' | 'qty' | 'entryPrice' | 'currentPrice' | 'pnl' | 'pnlPercent' | 'strategy';
type SortDir = 'asc' | 'desc';

export default function PositionsPage() {
  const t = useThemeColors();
  const card: React.CSSProperties = { background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16 };
  const { positions, isLoading, refetch } = usePositions();
  const [search, setSearch] = useState('');
  const [stratFilter, setStratFilter] = useState('ALL');
  const [sideFilter, setSideFilter] = useState('ALL');
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [editingSL, setEditingSL] = useState<Position | null>(null);
  const [editingTP, setEditingTP] = useState<Position | null>(null);
  const [slValue, setSlValue] = useState('');
  const [tpValue, setTpValue] = useState('');
  const [closing, setClosing] = useState<number | null>(null);
  const [confirmClose, setConfirmClose] = useState<Position | null>(null);

  const strategies = useMemo(() => [...new Set(positions.map((p) => p.strategy))], [positions]);

  const filtered = useMemo(() => {
    let list = positions;
    if (search) list = list.filter((p) => p.symbol.toLowerCase().includes(search.toLowerCase()));
    if (stratFilter !== 'ALL') list = list.filter((p) => p.strategy === stratFilter);
    if (sideFilter !== 'ALL') list = list.filter((p) => p.side === sideFilter);
    list = [...list].sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return list;
  }, [positions, search, stratFilter, sideFilter, sortKey, sortDir]);

  const totalInvested = positions.reduce((a, p) => a + p.entryPrice * p.qty, 0);
  const totalUnrealized = positions.reduce((a, p) => a + (p.pnl ?? 0), 0);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('asc'); }
  };

  const positionColumns: VirtualColumn<Position>[] = useMemo(() => [
    { header: 'Symbol', accessor: (p) => <span style={{ fontWeight: 600, color: t.textPrimary }}>{p.symbol}</span> },
    { header: 'Side', accessor: (p) => <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: p.side === 'BUY' ? '#34d399' : '#f87171', background: p.side === 'BUY' ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)' }}>{p.side}</span> },
    { header: 'Qty', accessor: (p) => <span style={{ color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{p.qty}</span>, align: 'right' },
    { header: 'Entry', accessor: (p) => <span style={{ color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{fmt(p.entryPrice)}</span>, align: 'right' },
    { header: 'CMP', accessor: (p) => <span style={{ color: t.textPrimary, fontFamily: 'ui-monospace,monospace', fontWeight: 600 }}>{fmt(p.currentPrice ?? p.entryPrice)}</span>, align: 'right' },
    { header: 'SL', accessor: (p) => <span style={{ color: '#f87171', fontFamily: 'ui-monospace,monospace', fontSize: 11 }}>{fmt(p.stopLoss)}</span>, align: 'right' },
    { header: 'Target', accessor: (p) => <span style={{ color: '#34d399', fontFamily: 'ui-monospace,monospace', fontSize: 11 }}>{fmt(p.target)}</span>, align: 'right' },
    { header: 'P&L', accessor: (p) => { const pl = p.pnl ?? 0; return <span style={{ fontWeight: 700, fontFamily: 'ui-monospace,monospace', color: clr(pl) }}>{pl >= 0 ? '+' : ''}{fmt(pl)}</span>; }, align: 'right' },
    { header: 'P&L %', accessor: (p) => { const plPct = p.pnlPercent ?? 0; return <span style={{ fontFamily: 'ui-monospace,monospace', color: clr(plPct) }}>{plPct >= 0 ? '+' : ''}{plPct.toFixed(2)}%</span>; }, align: 'right' },
    { header: 'Strategy', accessor: (p) => <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600, color: t.textSecondary, background: t.bgMuted }}>{p.strategy.replace(/_/g, ' ')}</span> },
    { header: 'Entry Time', accessor: (p) => <span style={{ color: t.textMuted, fontSize: 11 }}>{new Date(p.entryTime).toLocaleTimeString()}</span> },
    { header: 'Actions', accessor: (p) => (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
        <button onClick={(e) => { e.stopPropagation(); setEditingSL(p); setSlValue(String(p.stopLoss)); }} title="Edit Stop Loss" style={{ padding: 4, borderRadius: 4, background: 'rgba(248,113,113,0.1)', border: 'none', cursor: 'pointer', color: '#f87171' }}><Edit3 size={12} /></button>
        <button onClick={(e) => { e.stopPropagation(); setEditingTP(p); setTpValue(String(p.target)); }} title="Edit Target" style={{ padding: 4, borderRadius: 4, background: 'rgba(52,211,153,0.1)', border: 'none', cursor: 'pointer', color: '#34d399' }}><Target size={12} /></button>
        <button onClick={(e) => { e.stopPropagation(); handleClose(p); }} disabled={closing === p.id} title="Close Position" style={{ padding: 4, borderRadius: 4, background: 'rgba(239,68,68,0.15)', border: 'none', cursor: 'pointer', color: '#ef4444' }}><X size={12} /></button>
      </div>
    ), align: 'center' },
  ], [closing, t]);

  const handleClose = async (pos: Position) => {
    setConfirmClose(pos);
  };

  const doClose = async () => {
    if (!confirmClose) return;
    const id = confirmClose.id;
    setConfirmClose(null);
    setClosing(id);
    try { await api.closePosition(id); refetch(); } catch { /* ignore */ }
    finally { setClosing(null); }
  };

  const handleSaveSL = async () => {
    if (!editingSL) return;
    // In a real app this would call api.updateStopLoss(editingSL.id, parseFloat(slValue))
    setEditingSL(null);
  };

  const handleSaveTP = async () => {
    if (!editingTP) return;
    setEditingTP(null);
  };

  const SortHeader = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      onClick={() => toggleSort(k)}
      style={{ padding: '10px 12px', textAlign: k === 'symbol' || k === 'strategy' ? 'left' : 'right', color: t.textMuted, fontWeight: 600, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', cursor: 'pointer', userSelect: 'none' }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {label}
        <ArrowUpDown size={10} style={{ opacity: sortKey === k ? 1 : 0.3 }} />
      </span>
    </th>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<ClipboardList size={16} />}
        title="Positions"
        subtitle={`${positions.length} open · ${totalUnrealized >= 0 ? '+' : ''}${fmt(totalUnrealized)} unrealized`}
      />

      {/* Summary Bar */}
      <motion.div variants={bentoStagger} initial="hidden" animate="visible" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 14 }}>
        <BentoCard accent="indigo">
          <motion.div variants={revealVariants} style={{ padding: '18px 22px' }}>
            <p style={summaryLabel}>Open Positions</p>
            <p className="lt-tabular" style={summaryValue}>
              <AnimatedNumber value={positions.length} format={(v) => String(Math.round(v))} />
            </p>
          </motion.div>
        </BentoCard>
        <BentoCard accent="cyan">
          <motion.div variants={revealVariants} style={{ padding: '18px 22px' }}>
            <p style={summaryLabel}>Total Invested</p>
            <p className="lt-tabular" style={summaryValue}>
              <AnimatedNumber value={totalInvested} format={fmt} />
            </p>
          </motion.div>
        </BentoCard>
        <BentoCard accent={totalUnrealized >= 0 ? 'emerald' : 'rose'}>
          <motion.div variants={revealVariants} style={{ padding: '18px 22px' }}>
            <p style={summaryLabel}>Unrealized P&L</p>
            <p className="lt-tabular" style={{ ...summaryValue, color: totalUnrealized >= 0 ? 'var(--bull)' : 'var(--bear)' }}>
              <AnimatedNumber value={totalUnrealized} format={(v) => `${v >= 0 ? '+' : ''}${fmt(v)}`} semanticColor />
            </p>
          </motion.div>
        </BentoCard>
        <BentoCard accent="emerald">
          <motion.div variants={revealVariants} style={{ padding: '18px 22px' }}>
            <p style={summaryLabel}>In Profit</p>
            <p className="lt-tabular" style={{ ...summaryValue, color: 'var(--bull)' }}>
              {positions.filter((p) => (p.pnl ?? 0) > 0).length} / {positions.length}
            </p>
          </motion.div>
        </BentoCard>
      </motion.div>

      {/* Filters */}
      <div style={{ ...card, padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbol..."
            style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 10px 8px 32px', fontSize: 12, color: t.textPrimary, outline: 'none' }}
          />
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
      </div>

      {/* Table */}
      <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ padding: 48, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>Loading positions…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 48, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>
            <Shield size={32} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
            {positions.length === 0 ? 'No open positions' : 'No positions match filters'}
          </div>
        ) : (
          <VirtualTable<Position>
            data={filtered}
            rowHeight={48}
            columns={positionColumns}
            keyExtractor={(p) => p.id}
            tableId="positions"
          />
        )}
      </div>

      {/* Stop Loss Modal */}
      {editingSL && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setEditingSL(null)}>
          <div style={{ ...card, padding: 24, width: 360 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: '0 0 4px' }}>Modify Stop Loss</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginBottom: 16 }}>{editingSL.symbol} · Current SL: {fmt(editingSL.stopLoss)}</p>
            <input value={slValue} onChange={(e) => setSlValue(e.target.value)} type="number" step="0.05" style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 13, color: t.textPrimary, outline: 'none', marginBottom: 16 }} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setEditingSL(null)} style={{ padding: '6px 16px', fontSize: 12, color: t.textSecondary, background: 'none', border: 'none', cursor: 'pointer' }}>Cancel</button>
              <button onClick={handleSaveSL} style={{ padding: '6px 16px', fontSize: 12, fontWeight: 700, color: '#fff', background: '#ef4444', borderRadius: 6, border: 'none', cursor: 'pointer' }}>Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Target Modal */}
      {editingTP && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setEditingTP(null)}>
          <div style={{ ...card, padding: 24, width: 360 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: '0 0 4px' }}>Modify Target</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginBottom: 16 }}>{editingTP.symbol} · Current Target: {fmt(editingTP.target)}</p>
            <input value={tpValue} onChange={(e) => setTpValue(e.target.value)} type="number" step="0.05" style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 13, color: t.textPrimary, outline: 'none', marginBottom: 16 }} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setEditingTP(null)} style={{ padding: '6px 16px', fontSize: 12, color: t.textSecondary, background: 'none', border: 'none', cursor: 'pointer' }}>Cancel</button>
              <button onClick={handleSaveTP} style={{ padding: '6px 16px', fontSize: 12, fontWeight: 700, color: '#fff', background: '#10b981', borderRadius: 6, border: 'none', cursor: 'pointer' }}>Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Close Position Confirmation */}
      {confirmClose && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setConfirmClose(null)}>
          <div style={{ ...card, padding: 28, width: 400 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 8px' }}>Close Position</h3>
            <p style={{ fontSize: 12, color: t.textSecondary, lineHeight: 1.5, marginBottom: 16 }}>
              Close <span style={{ fontWeight: 700, color: t.textPrimary }}>{confirmClose.symbol}</span> ({confirmClose.side} {confirmClose.qty} shares)?
              A market order will be placed immediately.
            </p>
            <div style={{ background: t.inputBg, borderRadius: 8, padding: '10px 14px', marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, color: t.textMuted }}>Unrealized P&L</span>
              <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'ui-monospace,monospace', color: (confirmClose.pnl ?? 0) >= 0 ? '#34d399' : '#f87171' }}>{(confirmClose.pnl ?? 0) >= 0 ? '+' : ''}{fmt(confirmClose.pnl ?? 0)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setConfirmClose(null)} style={{ padding: '8px 18px', fontSize: 12, color: t.textSecondary, background: 'none', border: `1px solid ${t.borderSecondary}`, borderRadius: 8, cursor: 'pointer' }}>Cancel</button>
              <button onClick={doClose} style={{ padding: '8px 18px', fontSize: 12, fontWeight: 700, color: '#fff', background: '#dc2626', borderRadius: 8, border: 'none', cursor: 'pointer' }}>Close Position</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── shared styles ─────────────────────────────────────────────────── */
const summaryLabel: React.CSSProperties = {
  fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase',
  fontWeight: 700, letterSpacing: '0.12em', margin: 0,
};
const summaryValue: React.CSSProperties = {
  fontSize: 24, fontWeight: 700, color: 'var(--fg-primary)',
  marginTop: 6, letterSpacing: '-0.02em',
};
