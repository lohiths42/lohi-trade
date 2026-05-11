import { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import {
  ShoppingCart, TrendingUp, TrendingDown, Info, Zap, AlertTriangle, Check,
} from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import { AnimatedNumber } from '../components/shared/AnimatedNumber';
import MobileOrderGuard from '../components/shared/MobileOrderGuard';
import TradeSymbolChart from '../components/shared/TradeSymbolChart';
import { ServiceStatusBanner } from '../components/setup/ServiceStatusBanner';
import { useFeatureGate } from '../hooks/useFeatureGate';
import { useTradingModeStore } from '../stores/trading-mode-store';

/**
 * TradePage — spec §2.2 /trade. Manual discretionary order entry.
 *
 * Structure:
 *   • Left column: order-ticket form (symbol, side toggle, qty, type,
 *     price/trigger, product, validity, variety, broker, disclosed qty)
 *   • Right column: live LTP, bid/ask, day H/L, available margin,
 *     estimated charges breakdown (brokerage + STT + GST + exchange + stamp),
 *     risk preview
 *
 * Keyboard:
 *   B → focus Buy, S → focus Sell, Ctrl+Enter → submit
 *
 * Submit flow:
 *   1. Generate idempotency key (UUID v7) — backend responsibility
 *   2. Pre-trade risk checks executed server-side
 *   3. Confirmation modal (LIVE shows red banner)
 *   4. On confirm ⇒ /orders shows the new row
 */

type Side = 'BUY' | 'SELL';
type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
type Product = 'MIS' | 'CNC' | 'NRML';
type Validity = 'DAY' | 'IOC';
type Variety = 'REGULAR' | 'COVER' | 'BRACKET';

export default function TradePage() {
  const mode = useTradingModeStore((s) => s.mode);
  const { isFeatureAvailable, getRequiredServiceName } = useFeatureGate();
  const [side, setSide] = useState<Side>('BUY');
  const [symbol, setSymbol] = useState('RELIANCE');
  const [qty, setQty] = useState('10');
  const [orderType, setOrderType] = useState<OrderType>('MARKET');
  const [price, setPrice] = useState('');
  const [trigger, setTrigger] = useState('');
  const [product, setProduct] = useState<Product>('MIS');
  const [validity, setValidity] = useState<Validity>('DAY');
  const [variety, setVariety] = useState<Variety>('REGULAR');
  const [broker, setBroker] = useState('Zerodha');
  const [disclosed, setDisclosed] = useState('');
  const [reviewOpen, setReviewOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  // Live data (mocked). In production wire from usePriceTickStore.
  const [ltp, setLtp] = useState(2456.20);
  const [bid, setBid] = useState(2456.15);
  const [ask, setAsk] = useState(2456.25);
  const [dayHigh] = useState(2478.00);
  const [dayLow] = useState(2441.55);
  const [availableMargin] = useState(145_320);

  useEffect(() => {
    const id = setInterval(() => {
      setLtp((v) => +(v + (Math.random() - 0.5) * 0.4).toFixed(2));
      setBid((v) => +(v + (Math.random() - 0.5) * 0.4).toFixed(2));
      setAsk((v) => +(v + (Math.random() - 0.5) * 0.4).toFixed(2));
    }, 1200);
    return () => clearInterval(id);
  }, []);

  // Keyboard shortcuts (B, S, Ctrl+Enter)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isFormField = (e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'TEXTAREA' || (e.target as HTMLElement)?.tagName === 'SELECT';
      if (!isFormField && e.key.toLowerCase() === 'b') setSide('BUY');
      if (!isFormField && e.key.toLowerCase() === 's') setSide('SELL');
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        setReviewOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const numericQty = Math.max(0, parseInt(qty) || 0);
  const effectivePrice = orderType === 'MARKET' ? ltp : parseFloat(price) || ltp;
  const notional = numericQty * effectivePrice;

  // Indian charges (approx, per spec §3.4)
  const charges = useMemo(() => {
    const brokerage = Math.min(20, notional * 0.0003);
    const sttPct = side === 'SELL' ? 0.00025 : 0;
    const stt = notional * sttPct;
    const exchange = notional * 0.0000345;
    const gst = (brokerage + exchange) * 0.18;
    const sebi = notional * 0.000001;
    const stamp = side === 'BUY' ? notional * 0.00015 : 0;
    const total = brokerage + stt + exchange + gst + sebi + stamp;
    return { brokerage, stt, exchange, gst, sebi, stamp, total };
  }, [notional, side]);

  const riskBreach = notional > 1_00_000;

  const handleSubmit = () => {
    // Real impl: POST /api/orders with idempotency key (UUID v7 from server)
    setSubmitted(true);
    setReviewOpen(false);
    setTimeout(() => setSubmitted(false), 2200);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* ── Service Status Banner (Requirement 4.4) ─────────────── */}
      {!isFeatureAvailable('live_trading') && (
        <ServiceStatusBanner
          serviceName={getRequiredServiceName('live_trading') ?? 'Broker (Shoonya or Angel One)'}
          featureDescription="Live trading requires a broker API to be configured. Paper trading is still available without broker credentials."
          configureLink="/settings"
        />
      )}

      <PageHeader
        icon={<ShoppingCart size={16} />}
        title="Trade"
        subtitle="Manual order ticket · press B for Buy, S for Sell, Ctrl+Enter to review"
      />

      {/* Full-width chart for the symbol being traded */}
      <BentoCard reveal>
        <div style={{ padding: 20 }}>
          <TradeSymbolChart symbol={symbol} ltp={ltp} />
        </div>
      </BentoCard>

      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 16 }}>
        {/* Left — Order ticket */}
        <BentoCard reveal>
          <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* Side toggle */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <SideButton active={side === 'BUY'} color="var(--bull)" onClick={() => setSide('BUY')}>
                <TrendingUp size={14} /> BUY <kbd style={kbd}>B</kbd>
              </SideButton>
              <SideButton active={side === 'SELL'} color="var(--bear)" onClick={() => setSide('SELL')}>
                <TrendingDown size={14} /> SELL <kbd style={kbd}>S</kbd>
              </SideButton>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Symbol">
                <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} style={input} />
              </Field>
              <Field label="Quantity">
                <input value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ''))} style={input} />
              </Field>
            </div>

            <Field label="Order type">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                {(['MARKET', 'LIMIT', 'SL', 'SL-M'] as OrderType[]).map((t) => (
                  <Chip key={t} active={orderType === t} onClick={() => setOrderType(t)}>{t}</Chip>
                ))}
              </div>
            </Field>

            {(orderType === 'LIMIT' || orderType === 'SL') && (
              <Field label="Limit price">
                <input value={price} onChange={(e) => setPrice(e.target.value)} placeholder={ltp.toFixed(2)} style={input} />
              </Field>
            )}
            {(orderType === 'SL' || orderType === 'SL-M') && (
              <Field label="Trigger price">
                <input value={trigger} onChange={(e) => setTrigger(e.target.value)} placeholder={ltp.toFixed(2)} style={input} />
              </Field>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              <Field label="Product">
                <select value={product} onChange={(e) => setProduct(e.target.value as Product)} style={input}>
                  <option value="MIS">MIS · Intraday</option>
                  <option value="CNC">CNC · Delivery</option>
                  <option value="NRML">NRML · Carry</option>
                </select>
              </Field>
              <Field label="Validity">
                <select value={validity} onChange={(e) => setValidity(e.target.value as Validity)} style={input}>
                  <option value="DAY">DAY</option>
                  <option value="IOC">IOC</option>
                </select>
              </Field>
              <Field label="Variety">
                <select value={variety} onChange={(e) => setVariety(e.target.value as Variety)} style={input}>
                  <option value="REGULAR">Regular</option>
                  <option value="COVER">Cover</option>
                  <option value="BRACKET">Bracket</option>
                </select>
              </Field>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Broker">
                <select value={broker} onChange={(e) => setBroker(e.target.value)} style={input}>
                  {['Zerodha', 'Dhan', 'Upstox', 'Fyers', 'Angel One', 'Paper'].map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </Field>
              <Field label="Disclosed qty (optional)">
                <input value={disclosed} onChange={(e) => setDisclosed(e.target.value.replace(/\D/g, ''))} placeholder="0" style={input} />
              </Field>
            </div>

            <MobileOrderGuard>
              <button
                onClick={() => setReviewOpen(true)}
                disabled={!numericQty}
                style={{
                  marginTop: 6, padding: '12px 18px', borderRadius: 'var(--r-sm)',
                  background: `linear-gradient(180deg, color-mix(in srgb, ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'} 95%, white 5%), ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'})`,
                  border: `1px solid color-mix(in srgb, ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'} 55%, transparent)`,
                  color: '#fff', fontSize: 13, fontWeight: 700, letterSpacing: '0.04em',
                  cursor: numericQty ? 'pointer' : 'not-allowed',
                  opacity: numericQty ? 1 : 0.5,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                Review {side} · {numericQty} {symbol} <kbd style={{ ...kbd, background: 'rgba(255,255,255,0.18)', color: '#fff' }}>⌃↵</kbd>
              </button>
            </MobileOrderGuard>
          </div>
        </BentoCard>

        {/* Right — Live data + charges */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <BentoCard reveal accent="indigo">
            <div style={{ padding: 24 }}>
              <h3 style={sideTitle}>Live snapshot</h3>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 10 }}>
                <p className="lt-tabular" style={{ fontSize: 30, fontWeight: 800, color: 'var(--fg-primary)', margin: 0, letterSpacing: '-0.02em' }}>
                  ₹<AnimatedNumber value={ltp} format={(v) => v.toFixed(2)} flash />
                </p>
                <span style={{ fontSize: 11, color: 'var(--fg-muted)' }}>LTP</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 14 }}>
                <Snap label="Bid" value={bid} color="var(--bull)" />
                <Snap label="Ask" value={ask} color="var(--bear)" />
                <Snap label="Day high" value={dayHigh} />
                <Snap label="Day low" value={dayLow} />
              </div>
            </div>
          </BentoCard>

          <BentoCard reveal>
            <div style={{ padding: 24 }}>
              <h3 style={sideTitle}>Margin & charges</h3>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, fontSize: 12 }}>
                <span style={{ color: 'var(--fg-muted)' }}>Available margin</span>
                <span className="lt-tabular" style={{ color: 'var(--fg-primary)', fontWeight: 600 }}>₹{availableMargin.toLocaleString('en-IN')}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 4 }}>
                <span style={{ color: 'var(--fg-muted)' }}>Order notional</span>
                <span className="lt-tabular" style={{ color: 'var(--fg-primary)', fontWeight: 600 }}>₹{notional.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
              </div>

              <div style={{ borderTop: '1px solid var(--line-2)', marginTop: 12, paddingTop: 12 }}>
                <ChargeRow label="Brokerage" v={charges.brokerage} />
                <ChargeRow label="STT" v={charges.stt} />
                <ChargeRow label="Exchange txn" v={charges.exchange} />
                <ChargeRow label="GST (18%)" v={charges.gst} />
                <ChargeRow label="SEBI fees" v={charges.sebi} />
                <ChargeRow label="Stamp duty" v={charges.stamp} />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--line-1)' }}>
                  <span style={{ fontSize: 11, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>Total charges</span>
                  <span className="lt-tabular" style={{ fontSize: 13, color: 'var(--bear)', fontWeight: 700 }}>-₹{charges.total.toFixed(2)}</span>
                </div>
              </div>

              {riskBreach && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, padding: '8px 10px', borderRadius: 'var(--r-sm)', background: 'var(--warn-soft)', color: 'var(--warn)', fontSize: 11 }}>
                  <AlertTriangle size={12} /> Order exceeds ₹1L max · will be rejected by risk engine
                </div>
              )}
            </div>
          </BentoCard>
        </div>
      </div>

      {/* Review modal */}
      {reviewOpen && (
        <div
          role="dialog" aria-modal="true"
          onClick={() => setReviewOpen(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'grid', placeItems: 'center', background: 'var(--scrim)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}
        >
          <motion.div
            initial={{ scale: 0.94, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            onClick={(e) => e.stopPropagation()}
            className="lt-glass"
            style={{
              width: '100%', maxWidth: 440, padding: 24,
              borderRadius: 'var(--r-lg)', border: '1px solid var(--line-2)',
              boxShadow: 'var(--elev-3)',
            }}
          >
            {mode === 'LIVE' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 'var(--r-sm)', background: 'var(--bear-soft)', color: 'var(--bear)', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', marginBottom: 14 }}>
                <Zap size={12} /> LIVE MODE · REAL ORDER
              </div>
            )}
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--fg-primary)', margin: 0 }}>Review order</h3>
            <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '4px 0 16px' }}>You can cancel after submitting if the broker has not yet filled.</p>
            <dl style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '6px 14px', fontSize: 12, margin: 0 }}>
              <dt style={dt}>Side</dt><dd style={{ ...dd, color: side === 'BUY' ? 'var(--bull)' : 'var(--bear)', fontWeight: 700 }}>{side}</dd>
              <dt style={dt}>Symbol</dt><dd style={dd}>{symbol}</dd>
              <dt style={dt}>Quantity</dt><dd style={dd}>{numericQty}</dd>
              <dt style={dt}>Type</dt><dd style={dd}>{orderType}</dd>
              <dt style={dt}>Price</dt><dd style={dd}>₹{(orderType === 'MARKET' ? ltp : effectivePrice).toFixed(2)}</dd>
              <dt style={dt}>Product / Validity</dt><dd style={dd}>{product} / {validity}</dd>
              <dt style={dt}>Broker</dt><dd style={dd}>{broker}</dd>
              <dt style={dt}>Total charges</dt><dd style={dd}>₹{charges.total.toFixed(2)}</dd>
            </dl>
            <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
              <button onClick={() => setReviewOpen(false)} style={btnGhost}>Cancel</button>
              <button
                onClick={handleSubmit}
                style={{
                  flex: 1, padding: '10px 14px', borderRadius: 'var(--r-sm)',
                  background: `linear-gradient(180deg, color-mix(in srgb, ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'} 95%, white 5%), ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'})`,
                  color: '#fff', border: `1px solid color-mix(in srgb, ${side === 'BUY' ? 'var(--bull)' : 'var(--bear)'} 55%, transparent)`,
                  fontSize: 12, fontWeight: 700, cursor: 'pointer',
                }}
              >
                Confirm order
              </button>
            </div>
          </motion.div>
        </div>
      )}

      {submitted && (
        <motion.div
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 40, opacity: 0 }}
          style={{
            position: 'fixed', bottom: 32, left: '50%', transform: 'translateX(-50%)',
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '12px 18px', borderRadius: 'var(--r-md)',
            background: 'var(--bull-soft)', color: 'var(--bull)',
            border: '1px solid color-mix(in srgb, var(--bull) 30%, transparent)',
            fontSize: 13, fontWeight: 600, zIndex: 10000,
            boxShadow: 'var(--elev-2)',
          }}
        >
          <Check size={14} /> Order submitted. Track in <a href="/orders" style={{ color: 'inherit', textDecoration: 'underline' }}>Orders</a>.
        </motion.div>
      )}
    </div>
  );
}

/* ─── atoms ─────────────────────────────────────────────────────────── */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

function SideButton({ active, color, onClick, children }: { active: boolean; color: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: '12px 14px', borderRadius: 'var(--r-sm)',
        background: active ? `color-mix(in srgb, ${color} 14%, transparent)` : 'var(--surface-3)',
        color: active ? color : 'var(--fg-secondary)',
        border: `1px solid ${active ? `color-mix(in srgb, ${color} 40%, transparent)` : 'var(--line-2)'}`,
        fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', cursor: 'pointer',
        boxShadow: active ? `0 0 0 4px color-mix(in srgb, ${color} 10%, transparent)` : 'none',
        transition: 'all 160ms var(--ease-out)',
      }}
    >
      {children}
    </button>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '8px 10px', borderRadius: 'var(--r-sm)',
        fontSize: 11, fontWeight: 600,
        background: active ? 'var(--surface-2)' : 'transparent',
        color: active ? 'var(--fg-primary)' : 'var(--fg-muted)',
        border: active ? '1px solid var(--line-2)' : '1px solid transparent',
        cursor: 'pointer', transition: 'all 120ms var(--ease-out)',
      }}
    >
      {children}
    </button>
  );
}

function Snap({ label, value, color = 'var(--fg-primary)' }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <p style={{ fontSize: 10, color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', margin: 0, fontWeight: 700 }}>{label}</p>
      <p className="lt-tabular" style={{ fontSize: 14, color, fontWeight: 600, margin: '4px 0 0' }}>
        ₹<AnimatedNumber value={value} format={(v) => v.toFixed(2)} flash />
      </p>
    </div>
  );
}

function ChargeRow({ label, v }: { label: string; v: number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '3px 0' }}>
      <span style={{ color: 'var(--fg-muted)' }}>{label}</span>
      <span className="lt-tabular" style={{ color: 'var(--fg-secondary)' }}>-₹{v.toFixed(2)}</span>
    </div>
  );
}

/* ─── styles ────────────────────────────────────────────────────────── */
const sideTitle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  fontSize: 12, fontWeight: 700, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--fg-muted)', margin: 0,
};
const input: React.CSSProperties = {
  width: '100%', padding: '9px 11px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-primary)', fontSize: 13, outline: 'none',
  fontFamily: 'inherit',
};
const kbd: React.CSSProperties = {
  padding: '1px 6px', borderRadius: 4,
  background: 'var(--surface-4)', border: '1px solid var(--line-2)',
  color: 'var(--fg-muted)', fontSize: 10, fontFamily: 'ui-monospace, monospace',
  marginLeft: 4,
};
const btnGhost: React.CSSProperties = {
  padding: '10px 14px', borderRadius: 'var(--r-sm)',
  background: 'var(--surface-3)', border: '1px solid var(--line-2)',
  color: 'var(--fg-secondary)', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};
const dt: React.CSSProperties = { color: 'var(--fg-muted)', fontWeight: 500 };
const dd: React.CSSProperties = { color: 'var(--fg-primary)', margin: 0, textAlign: 'right', fontWeight: 600 };
