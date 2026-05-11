import { useState, useEffect, useMemo } from 'react';
import { Search, FileText, Filter, ShoppingCart } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api-client';
import { useThemeColors } from '../hooks/use-theme-colors';
import VirtualTable from '../components/shared/VirtualTable';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import { bentoStagger, revealVariants } from '../lib/motion';
import type { Order, VirtualColumn } from '../lib/types';

const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;


const STATUS_COLORS: Record<string, { color: string; bg: string }> = {
  PENDING: { color: '#fbbf24', bg: 'rgba(251,191,36,0.1)' },
  OPEN: { color: 'var(--accent-2)', bg: 'color-mix(in srgb, var(--accent) 14%, transparent)' },
  FILLED: { color: 'var(--bull)', bg: 'var(--bull-soft)' },
  CANCELLED: { color: 'var(--fg-muted)', bg: 'var(--surface-4)' },
  REJECTED: { color: 'var(--bear)', bg: 'var(--bear-soft)' },
};

export default function OrdersPage() {
  const t = useThemeColors();
  const card: React.CSSProperties = { background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16 };
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [sideFilter, setSideFilter] = useState<string>('ALL');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<{ id: number; orderId: string; symbol: string } | null>(null);

  useEffect(() => {
    setLoading(true);
    api.getOrders().then(setOrders).catch(() => {}).finally(() => setLoading(false));
    const id = setInterval(() => { api.getOrders().then(setOrders).catch(() => {}); }, 10000);
    return () => clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    let list = orders;
    if (search) list = list.filter((o) => o.symbol.toLowerCase().includes(search.toLowerCase()) || o.orderId.includes(search));
    if (statusFilter !== 'ALL') list = list.filter((o) => o.status === statusFilter);
    if (sideFilter !== 'ALL') list = list.filter((o) => o.side === sideFilter);
    if (dateFrom) list = list.filter((o) => o.createdAt >= dateFrom);
    if (dateTo) list = list.filter((o) => o.createdAt <= dateTo + 'T23:59:59');
    return list;
  }, [orders, search, statusFilter, sideFilter, dateFrom, dateTo]);

  const stats = useMemo(() => ({
    total: orders.length,
    filled: orders.filter((o) => o.status === 'FILLED').length,
    pending: orders.filter((o) => o.status === 'PENDING' || o.status === 'OPEN').length,
    rejected: orders.filter((o) => o.status === 'REJECTED').length,
    fillRate: orders.length > 0 ? (orders.filter((o) => o.status === 'FILLED').length / orders.length * 100) : 0,
  }), [orders]);

  const handleCancel = async (id: number, orderId: string, symbol: string) => {
    setConfirmCancel({ id, orderId, symbol });
  };

  const doCancel = async () => {
    if (!confirmCancel) return;
    const { id, orderId } = confirmCancel;
    setConfirmCancel(null);
    setCancelling(orderId);
    try { await api.cancelOrder(id); api.getOrders().then(setOrders).catch(() => {}); } catch { /* ignore */ }
    finally { setCancelling(null); }
  };

  const orderColumns: VirtualColumn<Order>[] = useMemo(() => [
    { header: 'Order ID', accessor: (o) => <span style={{ color: t.textSecondary, fontFamily: 'ui-monospace,monospace', fontSize: 11 }}>{o.orderId.slice(0, 12)}…</span> },
    { header: 'Symbol', accessor: (o) => <span style={{ fontWeight: 600, color: t.textPrimary }}>{o.symbol}</span> },
    { header: 'Side', accessor: (o) => <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: o.side === 'BUY' ? '#34d399' : '#f87171', background: o.side === 'BUY' ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)' }}>{o.side}</span> },
    { header: 'Type', accessor: (o) => <span style={{ color: t.textSecondary, fontSize: 11 }}>{o.orderType}</span> },
    { header: 'Qty', accessor: (o) => <span style={{ color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{o.qty}</span>, align: 'right' },
    { header: 'Price', accessor: (o) => <span style={{ color: t.textPrimary, fontFamily: 'ui-monospace,monospace' }}>{o.price ? fmt(o.price) : '—'}</span>, align: 'right' },
    { header: 'Status', accessor: (o) => { const sc = STATUS_COLORS[o.status] ?? STATUS_COLORS.CANCELLED; return <span title={o.rejectionReason ?? undefined} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: sc.color, background: sc.bg, cursor: o.rejectionReason ? 'help' : 'default' }}>{o.status}</span>; } },
    { header: 'Time', accessor: (o) => <span style={{ color: t.textMuted, fontSize: 11 }}>{new Date(o.createdAt).toLocaleTimeString()}</span> },
    { header: 'Actions', accessor: (o) => (o.status === 'PENDING' || o.status === 'OPEN') ? (
      <button onClick={(e) => { e.stopPropagation(); handleCancel(o.id, o.orderId, o.symbol); }} disabled={cancelling === o.orderId} style={{ padding: '3px 10px', fontSize: 10, fontWeight: 700, color: '#f87171', background: 'rgba(248,113,113,0.1)', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
        {cancelling === o.orderId ? '…' : 'Cancel'}
      </button>
    ) : null },
  ], [cancelling, t]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<ShoppingCart size={16} />}
        title="Orders"
        subtitle={`${stats.total} orders · ${stats.filled} filled · ${stats.pending} pending`}
      />

      {/* Stats */}
      <motion.div variants={bentoStagger} initial="hidden" animate="visible" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 14 }}>
        {[
          { label: 'Total Orders', value: stats.total, color: 'var(--fg-primary)', accent: 'indigo' as const, format: (v: number) => String(Math.round(v)) },
          { label: 'Filled', value: stats.filled, color: 'var(--bull)', accent: 'emerald' as const, format: (v: number) => String(Math.round(v)) },
          { label: 'Pending', value: stats.pending, color: 'var(--warn)', accent: 'none' as const, format: (v: number) => String(Math.round(v)) },
          { label: 'Rejected', value: stats.rejected, color: 'var(--bear)', accent: 'rose' as const, format: (v: number) => String(Math.round(v)) },
          { label: 'Fill Rate', value: stats.fillRate, color: stats.fillRate >= 80 ? 'var(--bull)' : 'var(--warn)', accent: 'cyan' as const, format: (v: number) => `${v.toFixed(1)}%` },
        ].map((s) => (
          <BentoCard key={s.label} accent={s.accent}>
            <motion.div variants={revealVariants} style={{ padding: '18px 22px' }}>
              <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.12em' }}>{s.label}</p>
              <p className="lt-tabular" style={{ fontSize: 22, fontWeight: 700, color: s.color, marginTop: 6, letterSpacing: '-0.02em' }}>
                <AnimatedNumber value={s.value} format={s.format} color={s.color} />
              </p>
            </motion.div>
          </BentoCard>
        ))}
      </motion.div>

      {/* Filters */}
      <div style={{ ...card, padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input value={search} onChange={(e) => { setSearch(e.target.value); }} placeholder="Search symbol or order ID..." style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 10px 8px 32px', fontSize: 12, color: t.textPrimary, outline: 'none' }} />
        </div>
        <Filter size={14} style={{ color: t.textMuted }} />
        <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); }} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: t.textPrimary }}>
          <option value="ALL">All Status</option>
          {['PENDING', 'OPEN', 'FILLED', 'CANCELLED', 'REJECTED'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={sideFilter} onChange={(e) => { setSideFilter(e.target.value); }} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: t.textPrimary }}>
          <option value="ALL">All Sides</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); }} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '7px 10px', fontSize: 11, color: t.textPrimary, outline: 'none' }} />
        <span style={{ color: t.textMuted, fontSize: 11 }}>to</span>
        <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); }} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '7px 10px', fontSize: 11, color: t.textPrimary, outline: 'none' }} />
        {(dateFrom || dateTo) && (
          <button onClick={() => { setDateFrom(''); setDateTo(''); }} style={{ fontSize: 10, color: t.textMuted, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Clear</button>
        )}
      </div>

      {/* Table */}
      <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 48, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>Loading orders…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 48, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>
            <FileText size={32} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
            {orders.length === 0 ? 'No orders yet' : 'No orders match filters'}
          </div>
        ) : (
          <VirtualTable<Order>
            data={filtered}
            rowHeight={48}
            columns={orderColumns}
            keyExtractor={(o) => o.orderId}
            tableId="orders"
          />
        )}
      </div>

      {/* Cancel Order Confirmation */}
      {confirmCancel && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setConfirmCancel(null)}>
          <div style={{ background: t.bgCard, border: `1px solid ${t.borderSecondary}`, borderRadius: 14, padding: 28, width: 400 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 8px' }}>Cancel Order</h3>
            <p style={{ fontSize: 12, color: t.textSecondary, lineHeight: 1.5, marginBottom: 16 }}>
              Cancel order for <span style={{ fontWeight: 700, color: t.textPrimary }}>{confirmCancel.symbol}</span>?
              <br /><span style={{ fontSize: 10, color: t.textMuted }}>ID: {confirmCancel.orderId}</span>
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setConfirmCancel(null)} style={{ padding: '8px 18px', fontSize: 12, color: t.textSecondary, background: 'none', border: `1px solid ${t.borderSecondary}`, borderRadius: 8, cursor: 'pointer' }}>Keep Order</button>
              <button onClick={doCancel} style={{ padding: '8px 18px', fontSize: 12, fontWeight: 700, color: '#fff', background: '#dc2626', borderRadius: 8, border: 'none', cursor: 'pointer' }}>Cancel Order</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
