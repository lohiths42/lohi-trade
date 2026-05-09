import { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { Radio, Search, Wifi, WifiOff, Zap, Pause, Play, Plus, X } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';

/**
 * MarketDataPage — spec §2.13 /market-data
 * Monitor tick-subscription health; live-stream last 500 ticks.
 */

interface Tick {
  ts: number;
  symbol: string;
  price: number;
  qty: number;
  broker: string;
}

const BROKERS = ['Zerodha', 'Dhan', 'Upstox'] as const;
type Broker = (typeof BROKERS)[number];

interface Subscription {
  broker: Broker;
  symbol: string;
}

export default function MarketDataPage() {
  const [subs, setSubs] = useState<Subscription[]>([
    { broker: 'Zerodha', symbol: 'RELIANCE' },
    { broker: 'Zerodha', symbol: 'INFY' },
    { broker: 'Dhan', symbol: 'NIFTY 50' },
  ]);
  const [ticks, setTicks] = useState<Tick[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState('');
  const [stats, setStats] = useState<Record<Broker, { tps: number; lastHb: number; dropped: number; connected: boolean }>>({
    Zerodha: { tps: 0, lastHb: Date.now(), dropped: 0, connected: true },
    Dhan: { tps: 0, lastHb: Date.now(), dropped: 0, connected: true },
    Upstox: { tps: 0, lastHb: Date.now(), dropped: 2, connected: false },
  });
  const [addSymbol, setAddSymbol] = useState('');

  // Mock tick stream
  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      setTicks((prev) => {
        const batch: Tick[] = [];
        for (const sub of subs) {
          if (Math.random() < 0.85) {
            batch.push({
              ts: Date.now(),
              symbol: sub.symbol,
              price: +(1000 + Math.random() * 2500).toFixed(2),
              qty: Math.floor(Math.random() * 1000) + 1,
              broker: sub.broker,
            });
          }
        }
        const next = [...batch, ...prev].slice(0, 500);
        return next;
      });
      setStats((s) => {
        const copy = { ...s };
        (Object.keys(copy) as Broker[]).forEach((k) => {
          copy[k] = { ...copy[k], tps: +(Math.random() * 80 + 20).toFixed(1), lastHb: copy[k].connected ? Date.now() : copy[k].lastHb };
        });
        return copy;
      });
    }, 300);
    return () => clearInterval(id);
  }, [paused, subs]);

  const filtered = useMemo(() => {
    const q = filter.trim().toUpperCase();
    if (!q) return ticks;
    return ticks.filter((t) => t.symbol.includes(q) || t.broker.toUpperCase().includes(q));
  }, [ticks, filter]);

  const removeSub = (s: Subscription) => setSubs((prev) => prev.filter((x) => !(x.broker === s.broker && x.symbol === s.symbol)));
  const addSub = (broker: Broker) => {
    const sym = addSymbol.trim().toUpperCase();
    if (!sym) return;
    setSubs((prev) => prev.some((s) => s.broker === broker && s.symbol === sym) ? prev : [...prev, { broker, symbol: sym }]);
    setAddSymbol('');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Radio size={16} />}
        title="Market Data"
        subtitle="Tick subscriptions, feed statistics, and raw stream"
        actions={
          <button onClick={() => setPaused((p) => !p)} style={chipBtn}>
            {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? 'Resume' : 'Pause'} feed
          </button>
        }
      />

      {/* Broker stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
        {(Object.keys(stats) as Broker[]).map((b) => {
          const s = stats[b];
          const gap = Math.round((Date.now() - s.lastHb) / 1000);
          return (
            <BentoCard key={b} accent={s.connected ? 'indigo' : 'rose'}>
              <div style={{ padding: 20, minHeight: 110 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: s.connected ? 'var(--bull)' : 'var(--bear)',
                      boxShadow: `0 0 8px ${s.connected ? 'var(--bull)' : 'var(--bear)'}`,
                    }} />
                    <strong style={{ fontSize: 13, color: 'var(--fg-primary)', fontWeight: 700 }}>{b}</strong>
                  </div>
                  {s.connected ? <Wifi size={13} color="var(--bull)" /> : <WifiOff size={13} color="var(--bear)" />}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 14 }}>
                  <StatCol label="Ticks/s" value={s.tps} format={(v) => v.toFixed(0)} color="var(--fg-primary)" />
                  <StatCol label="Dropped" value={s.dropped} format={(v) => String(Math.round(v))} color={s.dropped > 0 ? 'var(--warn)' : 'var(--fg-primary)'} />
                  <StatCol label="Last HB" value={gap} format={(v) => `${v}s`} color={gap < 5 ? 'var(--bull)' : gap < 30 ? 'var(--warn)' : 'var(--bear)'} />
                </div>
              </div>
            </BentoCard>
          );
        })}
      </div>

      {/* Subscriptions manager */}
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <h3 style={sideTitle}>Subscriptions <span style={{ fontWeight: 500, color: 'var(--fg-muted)', marginLeft: 8 }}>{subs.length} symbols</span></h3>
          <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
            {subs.map((s, i) => (
              <motion.span
                key={i}
                layout
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                style={subChip}
              >
                <strong style={{ color: 'var(--fg-primary)', fontWeight: 600 }}>{s.symbol}</strong>
                <span style={{ color: 'var(--fg-muted)' }}>· {s.broker}</span>
                <button onClick={() => removeSub(s)} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', color: 'var(--fg-muted)', cursor: 'pointer' }}>
                  <X size={12} />
                </button>
              </motion.span>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
            <input
              value={addSymbol}
              onChange={(e) => setAddSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol · e.g. TCS"
              style={{ ...input, width: 220 }}
              onKeyDown={(e) => { if (e.key === 'Enter') addSub('Zerodha'); }}
            />
            {BROKERS.map((b) => (
              <button key={b} onClick={() => addSub(b)} style={chipBtn}>
                <Plus size={12} /> Add to {b}
              </button>
            ))}
          </div>
        </div>
      </BentoCard>

      {/* Live tick log */}
      <BentoCard reveal>
        <div style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 24px', borderBottom: '1px solid var(--line-2)' }}>
            <h3 style={sideTitle}>Tick log <span style={{ fontWeight: 500, color: 'var(--fg-muted)', marginLeft: 8 }}>last 500 ticks</span></h3>
            <div style={{ position: 'relative' }}>
              <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-muted)' }} />
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" style={{ ...input, paddingLeft: 30, width: 180 }} />
            </div>
          </div>
          <div style={{ maxHeight: 360, overflowY: 'auto' }} className="lt-scroll">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead className="lt-glass" style={{ position: 'sticky', top: 0, zIndex: 2, background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)' }}>
                <tr>
                  {['Time', 'Symbol', 'Broker', 'LTP', 'Qty'].map((h) => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: ['LTP', 'Qty'].includes(h) ? 'right' : 'left', fontSize: 10, fontWeight: 700, color: 'var(--fg-muted)', letterSpacing: '0.1em', textTransform: 'uppercase', borderBottom: '1px solid var(--line-2)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={5} style={{ padding: 40, textAlign: 'center', color: 'var(--fg-muted)', fontSize: 12 }}>No ticks match</td></tr>
                ) : (
                  filtered.map((t, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--line-1)' }}>
                      <td style={{ padding: '8px 14px', color: 'var(--fg-muted)', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{new Date(t.ts).toLocaleTimeString('en-IN', { hour12: false }).padEnd(8)}.{String(t.ts % 1000).padStart(3, '0')}</td>
                      <td style={{ padding: '8px 14px', fontWeight: 600, color: 'var(--fg-primary)' }}>{t.symbol}</td>
                      <td style={{ padding: '8px 14px', color: 'var(--fg-secondary)' }}>{t.broker}</td>
                      <td className="lt-tabular" style={{ padding: '8px 14px', textAlign: 'right', color: 'var(--fg-primary)', fontWeight: 600 }}>₹{t.price.toFixed(2)}</td>
                      <td className="lt-tabular" style={{ padding: '8px 14px', textAlign: 'right', color: 'var(--fg-secondary)' }}>{t.qty}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </BentoCard>
    </div>
  );
}

function StatCol({ label, value, format, color }: { label: string; value: number; format: (v: number) => string; color: string }) {
  return (
    <div>
      <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, margin: 0 }}>{label}</p>
      <p className="lt-tabular" style={{ fontSize: 16, color, fontWeight: 700, margin: '4px 0 0', letterSpacing: '-0.02em' }}>
        <AnimatedNumber value={value} format={format} color={color} />
      </p>
    </div>
  );
}

const sideTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
  display: 'inline-flex', alignItems: 'center',
};
const chipBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 10px',
  borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
};
const subChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 10px 5px 12px',
  borderRadius: 999, background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  fontSize: 12,
};
const input: React.CSSProperties = {
  padding: '7px 11px', borderRadius: 'var(--r-sm)', background: 'var(--surface-3)',
  border: '1px solid var(--line-2)', color: 'var(--fg-primary)', fontSize: 12, outline: 'none',
  fontFamily: 'inherit',
};
