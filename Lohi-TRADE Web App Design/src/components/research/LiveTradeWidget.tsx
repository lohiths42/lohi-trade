/**
 * LiveTradeWidget — compact trading panel embedded into the Research
 * surface so the user never has to leave the editorial view to act on a
 * research-backed idea.
 *
 * Quartr-inspired design: no colored chrome; dividing rules only;
 * numerals are typographic (large, tabular, serif-like). Live signals
 * appear as a tight list with directional letters rather than badges.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { useDashboardStore } from '../../stores/dashboard-store';
import { researchApi } from '../../lib/research-api';
import type { ResearchSignal } from '../../lib/research-ideas-types';
import ModeSwitcher from '../shared/ModeSwitcher';

export default function LiveTradeWidget() {
  const totalPnl = useDashboardStore((s) => s.totalPnl);
  const tradesCount = useDashboardStore((s) => s.tradesCount);
  const winRate = useDashboardStore((s) => s.winRate);
  const navigate = useNavigate();

  const [signals, setSignals] = useState<ResearchSignal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    researchApi
      .listResearchSignals(6)
      .then((items) => {
        if (alive) setSignals(items);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    const t = setInterval(async () => {
      const latest = await researchApi.listResearchSignals(6);
      if (alive) setSignals(latest);
    }, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const isUp = totalPnl >= 0;

  return (
    <section
      aria-labelledby="live-trade-widget-heading"
      style={{
        padding: '16px 0 0',
        borderTop: '1px solid var(--line-3)',
        display: 'flex',
        flexDirection: 'column',
        gap: 18,
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 10,
        }}
      >
        <div>
          <p className="qr-kicker" style={{ margin: 0 }}>
            Live · Trade
          </p>
          <h3
            id="live-trade-widget-heading"
            className="qr-serif"
            style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
          >
            Portfolio
          </h3>
        </div>
        <ModeSwitcher compact />
      </header>

      {/* Tabular metrics — newspaper style */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 0,
          borderTop: '1px solid var(--line-2)',
          borderBottom: '1px solid var(--line-2)',
        }}
      >
        <Metric
          label="P&L today"
          value={`${isUp ? '+' : ''}₹${totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          tone={isUp ? 'bull' : totalPnl === 0 ? 'neutral' : 'bear'}
          first
        />
        <Metric label="Trades" value={String(tradesCount)} tone="neutral" />
        <Metric label="Win rate" value={`${winRate.toFixed(1)}%`} tone="neutral" last />
      </div>

      {/* Research-derived signals */}
      <div>
        <p className="qr-kicker" style={{ margin: '0 0 10px' }}>
          From research · past 24h
        </p>
        {loading ? (
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: 0 }}>
            Loading signals…
          </p>
        ) : signals.length === 0 ? (
          <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: 0 }}>
            No research signals yet. High-conviction briefs will appear here.
          </p>
        ) : (
          <ul
            style={{
              listStyle: 'none',
              margin: 0,
              padding: 0,
              borderTop: '1px solid var(--line-2)',
            }}
          >
            {signals.slice(0, 4).map((s) => (
              <SignalRow key={s.signal_id} signal={s} />
            ))}
          </ul>
        )}
      </div>

      {/* Quick actions */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button onClick={() => navigate('/trade')} className="qr-btn">
          Open trade ticket
          <ArrowRight size={13} />
        </button>
        <button onClick={() => navigate('/positions')} className="qr-btn qr-btn--ghost">
          Positions
        </button>
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone,
  first,
  last,
}: {
  label: string;
  value: string;
  tone: 'bull' | 'bear' | 'neutral';
  first?: boolean;
  last?: boolean;
}) {
  const color =
    tone === 'bull' ? 'var(--bull)' : tone === 'bear' ? 'var(--bear)' : 'var(--fg-primary)';
  return (
    <div
      style={{
        padding: '12px 14px',
        borderLeft: first ? 'none' : '1px solid var(--line-2)',
        borderRight: last ? 'none' : 'none',
      }}
    >
      <p className="qr-kicker" style={{ margin: 0 }}>
        {label}
      </p>
      <p
        className="qr-tabular"
        style={{
          margin: '6px 0 0',
          fontSize: 18,
          fontWeight: 600,
          color,
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </p>
    </div>
  );
}

function SignalRow({ signal }: { signal: ResearchSignal }) {
  const navigate = useNavigate();
  const directionInitial =
    signal.direction === 'bullish' ? 'B' : signal.direction === 'bearish' ? 'S' : '·';
  const directionColor =
    signal.direction === 'bullish'
      ? 'var(--bull)'
      : signal.direction === 'bearish'
        ? 'var(--bear)'
        : 'var(--fg-muted)';
  return (
    <li>
      <button
        onClick={() => navigate(`/research/${signal.symbol}`)}
        style={{
          all: 'unset',
          cursor: 'pointer',
          width: '100%',
          padding: '10px 2px',
          borderBottom: '1px solid var(--line-2)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          boxSizing: 'border-box',
        }}
      >
        <span
          aria-label={`Direction ${signal.direction}`}
          style={{
            width: 18,
            textAlign: 'center',
            fontSize: 12,
            fontWeight: 800,
            color: directionColor,
            letterSpacing: '0.02em',
          }}
        >
          {directionInitial}
        </span>
        <span
          className="qr-tabular"
          style={{
            fontSize: 12,
            fontWeight: 800,
            color: 'var(--fg-primary)',
            width: 72,
          }}
        >
          {signal.symbol}
        </span>
        <span
          style={{
            flex: 1,
            fontSize: 12,
            color: 'var(--fg-secondary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            lineHeight: 1.4,
          }}
        >
          {signal.thesis_short}
        </span>
        <span
          className="qr-tabular"
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--fg-primary)',
          }}
        >
          {Math.round(signal.conviction * 100)}
        </span>
      </button>
    </li>
  );
}
