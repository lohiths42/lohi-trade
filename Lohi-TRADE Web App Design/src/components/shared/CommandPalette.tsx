import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, ClipboardList, ShoppingCart, TrendingUp, History,
  BarChart3, FlaskConical, Brain, Crosshair, FileText, Settings,
  Search, ChevronRight, Globe, SlidersHorizontal, Gauge,
  ShieldCheck, Building2, Receipt, Link2, Activity,
  ShoppingBag, DollarSign, Zap,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { api } from '../../lib/api-client';
import { paletteVariants } from '../../lib/motion';

/* ─── Types ──────────────────────────────────────────────────────────── */
type CommandKind = 'nav' | 'symbol' | 'action';

interface CommandItem {
  id: string;
  label: string;
  hint?: string;          // secondary line (e.g., stock name, action preview)
  category: string;
  kind: CommandKind;
  icon: React.ElementType;
  color: string;
  to?: string;            // for nav / symbol (navigate to /stocks/:symbol)
  run?: () => void;       // for action
}

interface Props {
  open: boolean;
  onClose: () => void;
}

/* ─── Static nav commands ────────────────────────────────────────────── */
const NAV_COMMANDS: CommandItem[] = [
  { id: 'dashboard', label: 'Dashboard', category: 'Navigate', kind: 'nav', icon: LayoutDashboard, color: 'var(--accent)', to: '/' },
  { id: 'positions', label: 'Positions', category: 'Navigate', kind: 'nav', icon: ClipboardList, color: 'var(--accent)', to: '/positions' },
  { id: 'orders', label: 'Orders', category: 'Navigate', kind: 'nav', icon: ShoppingCart, color: 'var(--accent)', to: '/orders' },
  { id: 'stocks', label: 'Stock Universe', category: 'Navigate', kind: 'nav', icon: Globe, color: 'var(--accent)', to: '/universe' },
  { id: 'screener', label: 'Screener', category: 'Navigate', kind: 'nav', icon: SlidersHorizontal, color: 'var(--accent)', to: '/screener' },
  { id: 'strategies', label: 'Strategies', category: 'Navigate', kind: 'nav', icon: TrendingUp, color: 'var(--bull)', to: '/strategies' },
  { id: 'algo', label: 'Algo Performance', category: 'Navigate', kind: 'nav', icon: Gauge, color: 'var(--bull)', to: '/algo-performance' },
  { id: 'history', label: 'Trade History', category: 'Navigate', kind: 'nav', icon: History, color: 'var(--bull)', to: '/history' },
  { id: 'analytics', label: 'Analytics', category: 'Navigate', kind: 'nav', icon: BarChart3, color: 'var(--bull)', to: '/analytics' },
  { id: 'backtest', label: 'Backtests', category: 'Navigate', kind: 'nav', icon: FlaskConical, color: 'var(--bull)', to: '/backtest' },
  { id: 'watchlist', label: 'Watchlist & Alerts', category: 'Navigate', kind: 'nav', icon: Activity, color: 'var(--accent-2)', to: '/watchlist' },
  { id: 'commander', label: 'Commander', category: 'Navigate', kind: 'nav', icon: Brain, color: '#a78bfa', to: '/commander' },
  { id: 'soldier', label: 'Soldier', category: 'Navigate', kind: 'nav', icon: Crosshair, color: '#a78bfa', to: '/soldier' },
  { id: 'logs', label: 'Logs & Audit', category: 'Navigate', kind: 'nav', icon: FileText, color: '#a78bfa', to: '/logs' },
  { id: 'settings', label: 'Configuration', category: 'Navigate', kind: 'nav', icon: Settings, color: '#a78bfa', to: '/settings' },
  { id: 'verification', label: 'Verification', category: 'Navigate', kind: 'nav', icon: ShieldCheck, color: 'var(--warn)', to: '/verification' },
  { id: 'bank', label: 'Bank Accounts', category: 'Navigate', kind: 'nav', icon: Building2, color: 'var(--warn)', to: '/bank' },
  { id: 'funds', label: 'Fund Transactions', category: 'Navigate', kind: 'nav', icon: Receipt, color: 'var(--warn)', to: '/funds' },
  { id: 'brokers', label: 'Brokers', category: 'Navigate', kind: 'nav', icon: Link2, color: 'var(--warn)', to: '/settings/brokers' },
];

/* ─── Slash-command parser ───────────────────────────────────────────── */
interface ParsedOrder {
  side: 'BUY' | 'SELL';
  qty: number;
  symbol: string;
  price?: number;          // undefined = market
}

/**
 * Parse strings like:
 *   "/buy 100 INFY"
 *   "buy 50 RELIANCE @ 2450"
 *   "sell 25 TCS @ mkt"
 */
function parseOrderCommand(raw: string): ParsedOrder | null {
  const m = raw.trim().toLowerCase().match(/^\/?(buy|sell)\s+(\d+)\s+([a-z0-9.&_-]+)(?:\s*@\s*(mkt|market|\d+(?:\.\d+)?))?$/i);
  if (!m) return null;
  const [, side, qty, symbol, priceRaw] = m;
  const price = priceRaw && !/mkt|market/i.test(priceRaw) ? parseFloat(priceRaw) : undefined;
  return {
    side: side.toUpperCase() as 'BUY' | 'SELL',
    qty: parseInt(qty, 10),
    symbol: symbol.toUpperCase(),
    price,
  };
}

/* ─── Component ──────────────────────────────────────────────────────── */
export default function CommandPalette({ open, onClose }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const [symbolResults, setSymbolResults] = useState<Array<{ symbol: string; name?: string; exchange?: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  /* ─ Debounced symbol search ─ */
  useEffect(() => {
    const q = query.trim();
    // Don't search for slash-commands or empty
    if (!q || q.startsWith('/') || parseOrderCommand(q)) {
      setSymbolResults([]);
      return;
    }
    const handle = setTimeout(() => {
      api.searchStocks(q, 6)
        .then((res) => setSymbolResults((res.results ?? []).map((r: any) => ({
          symbol: r.symbol ?? r.tradingsymbol,
          name: r.name ?? r.company_name,
          exchange: r.exchange,
        }))))
        .catch(() => setSymbolResults([]));
    }, 120);
    return () => clearTimeout(handle);
  }, [query]);

  /* ─ Build flat list of commands (memoized) ─ */
  const { grouped, flat } = useMemo(() => {
    const q = query.trim();
    const parsed = parseOrderCommand(q);

    const items: CommandItem[] = [];

    // 1. Slash-command preview (always first when detected)
    if (parsed) {
      items.push({
        id: 'order-ticket',
        label: `${parsed.side} ${parsed.qty} ${parsed.symbol}`,
        hint: parsed.price ? `Limit @ ₹${parsed.price}` : 'Market order — review before submit',
        category: 'Action',
        kind: 'action',
        icon: parsed.side === 'BUY' ? ShoppingBag : DollarSign,
        color: parsed.side === 'BUY' ? 'var(--bull)' : 'var(--bear)',
        run: () => {
          // Open order ticket pre-filled on the stock detail page; never auto-submits.
          navigate(`/stocks/${parsed.symbol}`, { state: { prefillOrder: parsed } });
        },
      });
    }

    // 2. Symbol search results
    symbolResults.forEach((r) => {
      items.push({
        id: `sym-${r.symbol}`,
        label: r.symbol,
        hint: [r.name, r.exchange].filter(Boolean).join(' · '),
        category: 'Symbols',
        kind: 'symbol',
        icon: TrendingUp,
        color: 'var(--accent-2)',
        to: `/stocks/${r.symbol}`,
      });
    });

    // 3. Static nav commands — fuzzy filter
    const filteredNav = q && !parsed
      ? NAV_COMMANDS.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()))
      : NAV_COMMANDS;
    items.push(...filteredNav);

    // Group
    const g: Record<string, CommandItem[]> = {};
    const order = ['Action', 'Symbols', 'Navigate'];
    for (const cmd of items) {
      (g[cmd.category] ??= []).push(cmd);
    }
    const ordered: Record<string, CommandItem[]> = {};
    for (const cat of order) if (g[cat]?.length) ordered[cat] = g[cat];

    return {
      grouped: ordered,
      flat: Object.values(ordered).flat(),
    };
  }, [query, symbolResults, navigate]);

  /* ─ Lifecycle ─ */
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIdx(0);
      setSymbolResults([]);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    setActiveIdx((i) => Math.min(i, Math.max(flat.length - 1, 0)));
  }, [flat.length]);

  const executeItem = useCallback((item: CommandItem) => {
    if (item.kind === 'action' && item.run) item.run();
    else if (item.to) navigate(item.to);
    onClose();
  }, [navigate, onClose]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIdx((i) => Math.min(i + 1, flat.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const item = flat[activeIdx];
        if (item) executeItem(item);
      } else if (e.key === 'Escape') {
        onClose();
      }
    },
    [flat, activeIdx, executeItem, onClose],
  );

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx]);

  const parsedHint = parseOrderCommand(query);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            paddingTop: '16vh',
            background: 'var(--scrim)',
            backdropFilter: 'saturate(140%) blur(20px)',
            WebkitBackdropFilter: 'saturate(140%) blur(20px)',
          }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-label="Command palette"
            variants={paletteVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="lt-glass lt-scroll"
            style={{
              width: '100%', maxWidth: 620,
              borderRadius: 'var(--r-lg)',
              border: '1px solid var(--line-3)',
              boxShadow: 'var(--elev-3), 0 0 0 1px var(--accent-glow)',
              overflow: 'hidden',
              display: 'flex', flexDirection: 'column',
              maxHeight: '64vh',
              background: 'color-mix(in srgb, var(--surface-3) 85%, transparent)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* ─ Search row ─ */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '14px 18px',
              borderBottom: '1px solid var(--line-2)',
            }}>
              <Search size={17} color="var(--fg-muted)" style={{ flexShrink: 0 }} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
                onKeyDown={handleKeyDown}
                placeholder="Search pages, tickers · /buy 100 INFY"
                aria-label="Command input"
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  fontSize: 15, color: 'var(--fg-primary)', caretColor: 'var(--accent)',
                }}
              />
              {parsedHint && (
                <span style={{
                  fontSize: 10, padding: '3px 8px', borderRadius: 6, fontWeight: 700,
                  letterSpacing: '0.08em',
                  background: parsedHint.side === 'BUY' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                  color: parsedHint.side === 'BUY' ? 'var(--bull)' : 'var(--bear)',
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                }}>
                  <Zap size={10} /> ORDER
                </span>
              )}
            </div>

            {/* ─ Results ─ */}
            <div ref={listRef} className="lt-scroll" style={{ overflowY: 'auto', flex: 1 }}>
              {flat.length === 0 ? (
                <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--fg-subtle)', fontSize: 13 }}>
                  <p style={{ margin: 0 }}>No results</p>
                  <p style={{ margin: '8px 0 0', fontSize: 11 }}>
                    Try: <code style={{ padding: '1px 6px', borderRadius: 4, background: 'var(--surface-4)', color: 'var(--fg-muted)' }}>/buy 100 INFY</code>
                  </p>
                </div>
              ) : (
                Object.entries(grouped).map(([cat, items]) => (
                  <div key={cat}>
                    <div style={{
                      padding: '10px 18px 6px',
                      fontSize: 10, fontWeight: 800, color: 'var(--fg-subtle)',
                      textTransform: 'uppercase', letterSpacing: '0.14em',
                    }}>
                      {cat}
                    </div>
                    {items.map((item) => {
                      const gIdx = flat.indexOf(item);
                      const active = gIdx === activeIdx;
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          data-idx={gIdx}
                          onMouseEnter={() => setActiveIdx(gIdx)}
                          onClick={() => executeItem(item)}
                          style={{
                            width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                            padding: '10px 18px', border: 'none', cursor: 'pointer', textAlign: 'left',
                            background: active ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
                            borderLeft: `2px solid ${active ? item.color : 'transparent'}`,
                            color: 'var(--fg-primary)',
                            transition: 'background 120ms var(--ease-out)',
                          }}
                        >
                          <div style={{
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: active
                              ? `color-mix(in srgb, ${item.color} 18%, transparent)`
                              : 'var(--surface-4)',
                            border: `1px solid ${active ? `color-mix(in srgb, ${item.color} 30%, transparent)` : 'var(--line-2)'}`,
                          }}>
                            <Icon size={15} color={active ? item.color : 'var(--fg-muted)'} />
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 14, fontWeight: active ? 600 : 500, color: active ? 'var(--fg-primary)' : 'var(--fg-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {item.label}
                            </div>
                            {item.hint && (
                              <div style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {item.hint}
                              </div>
                            )}
                          </div>
                          {active && <ChevronRight size={14} color={item.color} style={{ opacity: 0.7, flexShrink: 0 }} />}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* ─ Footer ─ */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 16,
              padding: '10px 18px',
              borderTop: '1px solid var(--line-2)',
              background: 'color-mix(in srgb, var(--surface-1) 50%, transparent)',
            }}>
              <FooterKey label="↑↓" text="navigate" />
              <FooterKey label="↵" text="open" />
              <FooterKey label="esc" text="close" />
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: 'var(--fg-subtle)', fontWeight: 600, letterSpacing: '0.08em' }}>
                TIP: <code style={{ padding: '1px 6px', borderRadius: 4, background: 'var(--surface-4)', color: 'var(--fg-muted)' }}>/sell 50 TCS @ 3600</code>
              </span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function FooterKey({ label, text }: { label: string; text: string }) {
  return (
    <span style={{ fontSize: 11, color: 'var(--fg-subtle)' }}>
      <kbd style={{
        fontSize: 10, padding: '2px 6px', borderRadius: 4,
        background: 'var(--surface-4)', border: '1px solid var(--line-2)',
        color: 'var(--fg-muted)', marginRight: 6,
      }}>{label}</kbd>
      {text}
    </span>
  );
}
