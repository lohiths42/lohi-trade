import { useState, useMemo, useEffect } from 'react';
import { History, ChevronLeft, ChevronRight, FileText, Search, Filter } from 'lucide-react';
import { motion } from 'motion/react';
import { useOrders } from '../hooks/use-orders';
import { useOrdersStore } from '../stores/orders-store';
import { api } from '../lib/api-client';
import { useThemeColors } from '../hooks/use-theme-colors';
import TradeJournal from '../components/history/TradeJournal';
import PageHeader from '../components/shared/PageHeader';
import type { Order, OrderStatus, Trade } from '../lib/types';

const PAGE_SIZE = 20;

/* ─── Status → semantic token color map ───────────────────────────── */
const STATUS_STYLE: Record<OrderStatus, { color: string; bg: string }> = {
  PENDING:   { color: 'var(--warn)',    bg: 'var(--warn-soft)' },
  OPEN:      { color: 'var(--accent-2)', bg: 'color-mix(in srgb, var(--accent) 14%, transparent)' },
  FILLED:    { color: 'var(--bull)',    bg: 'var(--bull-soft)' },
  CANCELLED: { color: 'var(--fg-muted)', bg: 'var(--surface-4)' },
  REJECTED:  { color: 'var(--bear)',    bg: 'var(--bear-soft)' },
};

const EXIT_STYLE: Record<string, { color: string; bg: string }> = {
  TARGET:    { color: 'var(--bull)', bg: 'var(--bull-soft)' },
  STOP_LOSS: { color: 'var(--bear)', bg: 'var(--bear-soft)' },
  DEFAULT:   { color: 'var(--warn)', bg: 'var(--warn-soft)' },
};

/* ─── Trade Row ─────────────────────────────────────────────────── */
function TradeRow({ trade, hasNote, onClick }: { trade: Trade; hasNote?: boolean; onClick?: () => void }) {
  const pnl = trade.realizedPnl ?? 0;
  const isProfit = pnl >= 0;
  const invested = trade.entryPrice * trade.qty;
  const exitStyle = trade.exitReason ? (EXIT_STYLE[trade.exitReason] ?? EXIT_STYLE.DEFAULT) : null;

  return (
    <tr
      onClick={onClick}
      style={{
        borderBottom: '1px solid var(--line-1)',
        cursor: 'pointer',
        transition: 'background var(--dur-2) var(--ease-out)',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--surface-3) 50%, transparent)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <td style={{ padding: '12px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, color: 'var(--fg-primary)' }}>{trade.symbol}</span>
          <span style={{
            fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
            color: trade.side === 'BUY' ? 'var(--bull)' : 'var(--bear)',
            background: trade.side === 'BUY' ? 'var(--bull-soft)' : 'var(--bear-soft)',
            letterSpacing: '0.06em',
          }}>{trade.side}</span>
          {hasNote && <FileText size={12} style={{ color: 'var(--accent-2)' }} />}
        </div>
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, fontWeight: 700, color: 'var(--fg-primary)' }}>
        {trade.qty}
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>
        ₹{trade.entryPrice.toLocaleString()}
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>
        {trade.exitPrice != null ? `₹${trade.exitPrice.toLocaleString()}` : '—'}
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 12, color: 'var(--fg-muted)' }}>
        ₹{invested.toLocaleString(undefined, { maximumFractionDigits: 0 })}
      </td>
      <td style={{ padding: '12px 16px' }}>
        <span className="lt-tabular" style={{
          fontSize: 13, fontWeight: 700,
          color: isProfit ? 'var(--bull)' : 'var(--bear)',
        }}>
          {isProfit ? '+' : ''}₹{pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </span>
      </td>
      <td style={{ padding: '12px 16px' }}>
        <span style={{
          fontSize: 11, padding: '4px 10px', borderRadius: 'var(--r-pill)',
          background: 'var(--surface-4)', color: 'var(--fg-secondary)',
          border: '1px solid var(--line-2)', fontWeight: 600, textTransform: 'capitalize',
        }}>
          {trade.strategy.replace(/_/g, ' ')}
        </span>
      </td>
      <td style={{ padding: '12px 16px' }}>
        {trade.exitReason && exitStyle && (
          <span style={{
            fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
            color: exitStyle.color, background: exitStyle.bg,
            border: `1px solid color-mix(in srgb, ${exitStyle.color} 28%, transparent)`,
            letterSpacing: '0.05em',
          }}>
            {trade.exitReason.replace(/_/g, ' ')}
          </span>
        )}
      </td>
      <td style={{ padding: '12px 16px', fontSize: 11, color: 'var(--fg-muted)' }}>
        {new Date(trade.entryTime).toLocaleString()}
      </td>
    </tr>
  );
}

/* ─── Order Row ─────────────────────────────────────────────────── */
function OrderRow({ order }: { order: Order }) {
  const style = STATUS_STYLE[order.status];
  return (
    <tr
      style={{
        borderBottom: '1px solid var(--line-1)',
        transition: 'background var(--dur-2) var(--ease-out)',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'color-mix(in srgb, var(--surface-3) 50%, transparent)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <td style={{ padding: '12px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, color: 'var(--fg-primary)' }}>{order.symbol}</span>
          <span style={{
            fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
            color: order.side === 'BUY' ? 'var(--bull)' : 'var(--bear)',
            background: order.side === 'BUY' ? 'var(--bull-soft)' : 'var(--bear-soft)',
            letterSpacing: '0.06em',
          }}>{order.side}</span>
        </div>
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 11, color: 'var(--fg-muted)' }}>
        {order.orderId}
      </td>
      <td style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>{order.orderType}</td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>
        {order.qty}
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>
        {order.price != null ? `₹${order.price.toLocaleString()}` : '—'}
      </td>
      <td style={{ padding: '12px 16px' }}>
        <span style={{
          fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 'var(--r-pill)',
          color: style.color, background: style.bg,
          border: `1px solid color-mix(in srgb, ${style.color} 28%, transparent)`,
          letterSpacing: '0.06em',
        }}>
          {order.status}
        </span>
      </td>
      <td className="lt-tabular" style={{ padding: '12px 16px', fontSize: 13, color: 'var(--fg-secondary)' }}>
        {order.filledQty}/{order.qty}
      </td>
      <td style={{ padding: '12px 16px', fontSize: 11, color: 'var(--fg-muted)' }}>
        {new Date(order.createdAt).toLocaleString()}
      </td>
    </tr>
  );
}

/* ─── History Page ──────────────────────────────────────────────── */
export default function HistoryPage() {
  useThemeColors(); // keep subscription so theme flips re-render
  const [tab, setTab] = useState<'trades' | 'orders'>('trades');
  const filters = useOrdersStore((s) => s.filters);
  const setFilters = useOrdersStore((s) => s.setFilters);
  const { orders, isLoading: ordersLoading, error: ordersError } = useOrders(filters);

  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [symbolFilter, setSymbolFilter] = useState('');
  const [journalTrade, setJournalTrade] = useState<Trade | null>(null);
  const [tradeIdsWithNotes] = useState<Set<string>>(new Set());

  useEffect(() => {
    setTradesLoading(true);
    api.getTrades().then(setTrades).catch(() => {}).finally(() => setTradesLoading(false));
  }, []);

  const [page, setPage] = useState(0);

  const filteredTrades = useMemo(() => {
    let result = trades;
    if (symbolFilter) {
      result = result.filter((t) => t.symbol.toLowerCase().includes(symbolFilter.toLowerCase()));
    }
    return result;
  }, [trades, symbolFilter]);

  const filteredOrders = useMemo(() => {
    let result = orders;
    if (filters.status) result = result.filter((o) => o.status === filters.status);
    if (filters.symbol) result = result.filter((o) => o.symbol.toLowerCase().includes(filters.symbol!.toLowerCase()));
    return result;
  }, [orders, filters]);

  const items = tab === 'trades' ? filteredTrades : filteredOrders;
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const paginatedTrades = filteredTrades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const paginatedOrders = filteredOrders.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const isLoading = tab === 'trades' ? tradesLoading : ordersLoading;
  const error = tab === 'trades' ? null : ordersError;

  // Trade summary stats
  const totalShares = filteredTrades.reduce((sum, t) => sum + t.qty, 0);
  const totalInvested = filteredTrades.reduce((sum, t) => sum + t.entryPrice * t.qty, 0);
  const totalPnl = filteredTrades.reduce((sum, t) => sum + (t.realizedPnl ?? 0), 0);
  const wins = filteredTrades.filter((t) => (t.realizedPnl ?? 0) >= 0).length;

  const handleSymbolChange = (val: string) => {
    setPage(0);
    setSymbolFilter(val);
    setFilters({ ...filters, symbol: val || undefined });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<History size={16} />}
        title="Trade History"
        subtitle={`${items.length} ${tab === 'trades' ? 'trade' : 'order'}${items.length !== 1 ? 's' : ''} found`}
      />

      {/* ── Tab Switcher + Filters row ────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        {/* Tab switcher */}
        <div
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 3,
            padding: 3, borderRadius: 'var(--r-sm)',
            background: 'var(--surface-2)',
            border: '1px solid var(--line-2)',
          }}
        >
          {(['trades', 'orders'] as const).map((id) => {
            const isActive = tab === id;
            const count = id === 'trades' ? trades.length : orders.length;
            return (
              <button
                key={id}
                onClick={() => { setTab(id); setPage(0); }}
                style={{
                  position: 'relative',
                  padding: '6px 14px', borderRadius: 6,
                  fontSize: 12, fontWeight: 700,
                  border: 'none', cursor: 'pointer',
                  background: isActive ? 'var(--surface-4)' : 'transparent',
                  color: isActive ? 'var(--fg-primary)' : 'var(--fg-muted)',
                  boxShadow: isActive ? 'var(--elev-1)' : 'none',
                  transition: 'all var(--dur-2) var(--ease-out)',
                  textTransform: 'capitalize',
                  letterSpacing: '0.02em',
                }}
              >
                {id}
                <span className="lt-tabular" style={{
                  marginLeft: 8, fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: isActive ? 'color-mix(in srgb, var(--accent) 18%, transparent)' : 'var(--surface-3)',
                  color: isActive ? 'var(--accent-2)' : 'var(--fg-muted)',
                  fontWeight: 700,
                }}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Status filter (orders tab) */}
        {tab === 'orders' && (
          <div style={{ position: 'relative' }}>
            <Filter
              size={13}
              style={{
                position: 'absolute', left: 12, top: '50%',
                transform: 'translateY(-50%)', color: 'var(--fg-muted)',
                pointerEvents: 'none',
              }}
            />
            <select
              value={filters.status ?? ''}
              onChange={(e) => { setPage(0); setFilters({ ...filters, status: e.target.value || undefined }); }}
              style={{
                appearance: 'none',
                padding: '8px 32px 8px 34px',
                borderRadius: 'var(--r-sm)', fontSize: 12, fontWeight: 600,
                background: 'var(--surface-2)',
                border: '1px solid var(--line-2)',
                color: 'var(--fg-secondary)',
                cursor: 'pointer', outline: 'none', minWidth: 160,
              }}
            >
              <option value="">All Statuses</option>
              <option value="PENDING">Pending</option>
              <option value="OPEN">Open</option>
              <option value="FILLED">Filled</option>
              <option value="CANCELLED">Cancelled</option>
              <option value="REJECTED">Rejected</option>
            </select>
          </div>
        )}

        {/* Symbol search */}
        <div style={{ position: 'relative', flex: 1, minWidth: 200, maxWidth: 320 }}>
          <Search
            size={13}
            style={{
              position: 'absolute', left: 12, top: '50%',
              transform: 'translateY(-50%)', color: 'var(--fg-muted)',
              pointerEvents: 'none',
            }}
          />
          <input
            type="text"
            placeholder="Filter by symbol…"
            value={symbolFilter}
            onChange={(e) => handleSymbolChange(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px 8px 34px',
              borderRadius: 'var(--r-sm)', fontSize: 13,
              background: 'var(--surface-2)',
              border: '1px solid var(--line-2)',
              color: 'var(--fg-primary)', outline: 'none',
              transition: 'border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out)',
            }}
            onFocus={(e) => {
              e.target.style.borderColor = 'color-mix(in srgb, var(--accent) 55%, var(--line-2))';
              e.target.style.boxShadow = '0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent)';
            }}
            onBlur={(e) => {
              e.target.style.borderColor = 'var(--line-2)';
              e.target.style.boxShadow = 'none';
            }}
          />
        </div>
      </div>

      {/* ── Summary bar (trades tab) ──────────────────────────── */}
      {tab === 'trades' && filteredTrades.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="lt-bento"
          style={{
            display: 'flex', alignItems: 'center', flexWrap: 'wrap',
            gap: 28, padding: '16px 22px',
          }}
        >
          <Stat label="Trades" value={filteredTrades.length.toLocaleString()} />
          <Divider />
          <Stat label="Shares" value={totalShares.toLocaleString()} />
          <Divider />
          <Stat label="Invested" value={`₹${totalInvested.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
          <Divider />
          <Stat
            label="Realized P&L"
            value={`${totalPnl >= 0 ? '+' : ''}₹${Math.abs(totalPnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
            color={totalPnl >= 0 ? 'var(--bull)' : 'var(--bear)'}
            glow
          />
          <Divider />
          <Stat
            label="Win Rate"
            value={`${filteredTrades.length > 0 ? ((wins / filteredTrades.length) * 100).toFixed(1) : '0'}%`}
          />
        </motion.div>
      )}

      {/* ── Table ─────────────────────────────────────────────── */}
      <div
        className="lt-bento"
        style={{ overflow: 'hidden' }}
      >
        {isLoading ? (
          <div style={{ padding: 28, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="lt-skeleton" style={{ height: 40, borderRadius: 'var(--r-sm)' }} />
            ))}
          </div>
        ) : error ? (
          <div style={{ padding: 32, textAlign: 'center' }}>
            <p style={{ color: 'var(--bear)', fontSize: 14, margin: 0, fontWeight: 600 }}>Failed to load data</p>
            <p style={{ color: 'var(--fg-muted)', fontSize: 12, margin: '6px 0 0' }}>{error.message}</p>
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: 48, textAlign: 'center' }}>
            <History size={28} style={{ color: 'var(--fg-muted)', opacity: 0.4, margin: '0 auto 10px' }} />
            <p style={{ color: 'var(--fg-muted)', fontSize: 13, margin: 0 }}>
              No {tab} match the current filters
            </p>
          </div>
        ) : tab === 'trades' ? (
          <div style={{ overflowX: 'auto' }} className="lt-scroll">
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--line-2)', background: 'var(--surface-1)' }}>
                  {['Symbol', 'Qty', 'Entry', 'Exit', 'Invested', 'P&L', 'Strategy', 'Exit Reason', 'Time'].map((h) => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginatedTrades.map((trade) => (
                  <TradeRow
                    key={trade.id}
                    trade={trade}
                    hasNote={tradeIdsWithNotes.has(trade.tradeId)}
                    onClick={() => setJournalTrade(trade)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }} className="lt-scroll">
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--line-2)', background: 'var(--surface-1)' }}>
                  {['Symbol', 'Order ID', 'Type', 'Qty', 'Price', 'Status', 'Filled', 'Time'].map((h) => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginatedOrders.map((order) => (
                  <OrderRow key={order.id} order={order} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 20px', borderTop: '1px solid var(--line-2)',
            }}
          >
            <span className="lt-tabular" style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
              Page {page + 1} of {totalPages}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <PagerBtn disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                <ChevronLeft size={16} />
              </PagerBtn>
              <PagerBtn
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              >
                <ChevronRight size={16} />
              </PagerBtn>
            </div>
          </div>
        )}
      </div>

      {/* Trade Journal Panel */}
      {journalTrade && (
        <TradeJournal
          tradeId={journalTrade.tradeId}
          symbol={journalTrade.symbol}
          onClose={() => setJournalTrade(null)}
        />
      )}
    </div>
  );
}

/* ─── Atoms ─────────────────────────────────────────────────────── */
const thStyle: React.CSSProperties = {
  padding: '12px 16px',
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--fg-muted)',
};

function Stat({ label, value, color, glow }: { label: string; value: string; color?: string; glow?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{
        fontSize: 10, color: 'var(--fg-muted)',
        textTransform: 'uppercase', letterSpacing: '0.14em', fontWeight: 700,
      }}>
        {label}
      </span>
      <span
        className="lt-tabular"
        style={{
          fontSize: 15, fontWeight: 800,
          color: color ?? 'var(--fg-primary)',
          textShadow: glow && color ? `0 0 18px color-mix(in srgb, ${color} 35%, transparent)` : undefined,
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </span>
    </div>
  );
}

function Divider() {
  return <span style={{ width: 1, height: 24, background: 'var(--line-2)' }} />;
}

function PagerBtn({
  disabled, onClick, children,
}: { disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: 6, borderRadius: 'var(--r-sm)',
        background: 'var(--surface-3)',
        border: '1px solid var(--line-2)',
        color: 'var(--fg-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.35 : 1,
        display: 'grid', placeItems: 'center',
        transition: 'all var(--dur-2) var(--ease-out)',
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent) 35%, var(--line-2))';
          e.currentTarget.style.color = 'var(--fg-primary)';
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--line-2)';
        e.currentTarget.style.color = 'var(--fg-secondary)';
      }}
    >
      {children}
    </button>
  );
}
