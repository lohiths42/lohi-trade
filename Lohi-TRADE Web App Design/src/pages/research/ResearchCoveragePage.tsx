/**
 * `/research/coverage` — Watchlist coverage in Quartr's editorial tabular
 * format: hairline-separated rows, tabular numerics, no pills.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { useWatchlistStore } from '../../stores/watchlist-store';
import { researchApi } from '../../lib/research-api';
import type { ResearchSnapshot } from '../../lib/research-types';

interface CoverageRow {
  symbol: string;
  snapshot: ResearchSnapshot | null;
  loading: boolean;
}

export default function ResearchCoveragePage() {
  const symbols = useWatchlistStore((s) => s.symbols);
  const [rows, setRows] = useState<CoverageRow[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    setRows(symbols.map((s) => ({ symbol: s, snapshot: null, loading: true })));
    symbols.forEach(async (sym) => {
      const snap = await researchApi.getResearchSnapshot(sym).catch(() => null);
      if (!alive) return;
      setRows((prev) =>
        prev.map((r) => (r.symbol === sym ? { ...r, snapshot: snap, loading: false } : r)),
      );
    });
    return () => { alive = false; };
  }, [symbols]);

  async function reindex(symbol: string) {
    setRows((prev) =>
      prev.map((r) => (r.symbol === symbol ? { ...r, loading: true } : r)),
    );
    try {
      await researchApi.reindexSymbol(symbol);
      const snap = await researchApi.getResearchSnapshot(symbol);
      setRows((prev) =>
        prev.map((r) => (r.symbol === symbol ? { ...r, snapshot: snap, loading: false } : r)),
      );
    } catch {
      setRows((prev) =>
        prev.map((r) => (r.symbol === symbol ? { ...r, loading: false } : r)),
      );
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ paddingBottom: 20, borderBottom: '1px solid var(--line-3)' }}>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Workspace
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0' }}>
          Coverage
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 640 }}>
          Every symbol on your watchlist with its freshest snapshot, and a one-click
          re-index. Staleness is flagged when new filings land but regeneration is still
          queued.
        </p>
      </header>

      {symbols.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Add symbols to your Trade watchlist — Lohi Research will pre-compute coverage
          automatically as filings land.
        </p>
      ) : (
        <section>
          {/* Table header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1.2fr 1fr 1.3fr auto',
              padding: '12px 0',
              borderBottom: '1px solid var(--line-3)',
            }}
          >
            <span className="qr-kicker" style={{ margin: 0 }}>Symbol</span>
            <span className="qr-kicker" style={{ margin: 0 }}>Snapshot</span>
            <span className="qr-kicker" style={{ margin: 0 }}>Generated</span>
            <span />
          </div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {rows.map((row) => (
              <li
                key={row.symbol}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1.2fr 1fr 1.3fr auto',
                  padding: '14px 0',
                  alignItems: 'center',
                  borderBottom: '1px solid var(--line-2)',
                  fontSize: 13,
                }}
              >
                <button
                  onClick={() => navigate(`/research/${row.symbol}`)}
                  className="qr-tabular"
                  style={{
                    all: 'unset',
                    cursor: 'pointer',
                    fontWeight: 800,
                    fontSize: 14,
                    color: 'var(--fg-primary)',
                  }}
                >
                  {row.symbol}
                </button>
                {row.snapshot ? (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: row.snapshot.stale ? 'var(--warn)' : 'var(--bull)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.12em',
                    }}
                  >
                    {row.snapshot.stale ? 'Stale' : 'Fresh'}
                  </span>
                ) : (
                  <span style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No snapshot</span>
                )}
                <span
                  className="qr-tabular"
                  style={{ fontSize: 12, color: 'var(--fg-muted)' }}
                >
                  {row.snapshot
                    ? new Date(row.snapshot.generated_at).toLocaleString()
                    : '—'}
                </span>
                <button
                  onClick={() => reindex(row.symbol)}
                  aria-label={`Re-index ${row.symbol}`}
                  disabled={row.loading}
                  className="qr-btn qr-btn--ghost"
                  style={{ padding: '6px 12px', fontSize: 11 }}
                >
                  <RefreshCw size={11} className={row.loading ? 'spin' : undefined} />
                  Re-index
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
