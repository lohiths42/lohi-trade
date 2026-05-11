import { useState, useEffect, useCallback } from 'react';
import { Search, ChevronLeft, ChevronRight, Loader2, Globe } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useThemeColors } from '../hooks/use-theme-colors';
import PageHeader from '../components/shared/PageHeader';
import { api } from '../lib/api-client';

const SECTORS = [
  'All', 'Pharma', 'IT/Technology', 'AI/Deep Tech', 'Metals & Mining',
  'Banking & Finance', 'FMCG', 'Energy', 'Automobile', 'Telecom',
  'Real Estate', 'Infrastructure', 'Chemicals', 'Media & Entertainment',
  'Insurance', 'Miscellaneous',
];

const EXCHANGES = ['All', 'NSE', 'BSE', 'BOTH'];

interface SecurityRow {
  id?: number;
  symbol: string;
  company_name: string;
  exchange: string;
  sector?: string;
  market_cap_category?: string;
  status: string;
  instrument_type?: string;
}

export default function StockUniversePage() {
  const t = useThemeColors();
  const navigate = useNavigate();
  const [activeSector, setActiveSector] = useState('All');
  const [activeExchange, setActiveExchange] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [stocks, setStocks] = useState<SecurityRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const pageSize = 50;

  const fetchStocks = useCallback(async () => {
    setLoading(true);
    try {
      if (searchQuery.trim()) {
        const res = await api.searchStocks(searchQuery.trim(), pageSize);
        setStocks(res.results ?? []);
        setTotal(res.count ?? 0);
        setTotalPages(1);
      } else {
        const params: Record<string, any> = { page, page_size: pageSize };
        if (activeSector !== 'All') params.sector = activeSector;
        if (activeExchange !== 'All') params.exchange = activeExchange;
        const res = await api.listStocks(params);
        setStocks(res.items ?? []);
        setTotal(res.total ?? 0);
        setTotalPages(res.total_pages ?? 1);
      }
    } catch {
      setStocks([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [activeSector, activeExchange, searchQuery, page]);

  useEffect(() => { fetchStocks(); }, [fetchStocks]);
  useEffect(() => { setPage(1); }, [activeSector, activeExchange, searchQuery]);

  const card: React.CSSProperties = {
    background: t.bgCardGradient,
    border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Globe size={16} />}
        title="Stock Universe"
        subtitle={`${total.toLocaleString()} securities · NSE & BSE`}
      />

      {/* Search bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderRadius: 'var(--r-sm)',
        background: 'var(--surface-3)', border: '1px solid var(--line-2)',
      }}>
        <Search size={14} color="var(--fg-muted)" />
        <input
          type="text"
            placeholder="Search by symbol, name, or ISIN..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: 'transparent', border: 'none', outline: 'none', flex: 1,
              fontSize: 13, color: t.textPrimary,
            }}
          />
      </div>

      {/* Exchange + Sector Tabs */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {/* Exchange filter */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginRight: 4 }}>Exchange</span>
          {EXCHANGES.map((ex) => (
            <button
              key={ex}
              onClick={() => setActiveExchange(ex)}
              style={{
                padding: '5px 12px', borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                border: activeExchange === ex ? '1px solid rgba(139,92,246,0.4)' : `1px solid ${t.borderPrimary}`,
                background: activeExchange === ex ? 'rgba(139,92,246,0.15)' : t.bgMuted,
                color: activeExchange === ex ? '#a78bfa' : t.textSecondary,
                transition: 'all 0.15s',
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {/* Sector Tabs */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {SECTORS.map((s) => (
          <button
            key={s}
            onClick={() => setActiveSector(s)}
            style={{
              padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              border: activeSector === s ? '1px solid rgba(59,130,246,0.4)' : `1px solid ${t.borderPrimary}`,
              background: activeSector === s ? 'rgba(59,130,246,0.15)' : t.bgMuted,
              color: activeSector === s ? t.accentText : t.textSecondary,
              transition: 'all 0.15s',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: 'var(--surface-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }} className="lt-scroll">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead className="lt-glass" style={{ position: 'sticky', top: 0, zIndex: 2, background: 'color-mix(in srgb, var(--surface-2) 82%, transparent)' }}>
              <tr>
                {['Symbol', 'Company Name', 'Type', 'Exchange', 'Sector', 'Market Cap', 'Status'].map((h) => (
                  <th key={h} style={{
                    padding: '12px 16px', textAlign: 'left', fontSize: 10, fontWeight: 700,
                    color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.1em',
                    borderBottom: '1px solid var(--line-2)',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} style={{ padding: 40, textAlign: 'center' }}>
                    <Loader2 size={20} color="var(--fg-muted)" style={{ animation: 'spin 1s linear infinite' }} />
                  </td>
                </tr>
              ) : stocks.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ padding: 40, textAlign: 'center', color: 'var(--fg-muted)', fontSize: 13 }}>
                    No securities found
                  </td>
                </tr>
              ) : (
                stocks.map((s, i) => (
                  <tr key={s.symbol + i} style={{
                    borderBottom: '1px solid var(--line-1)',
                    transition: 'background 120ms var(--ease-out)',
                    cursor: 'pointer',
                  }}
                    onClick={() => navigate(`/stocks/${s.symbol}`)}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-4)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '13px 16px', fontWeight: 700, color: 'var(--accent-2)' }}>{s.symbol}</td>
                    <td style={{ padding: '13px 16px', color: 'var(--fg-primary)' }}>{s.company_name}</td>
                    <td style={{ padding: '13px 16px' }}>
                      <span style={{
                        padding: '3px 8px', borderRadius: 6, fontSize: 10, fontWeight: 700,
                        background: (s.instrument_type ?? 'Stock') === 'Mutual Fund' ? 'color-mix(in srgb, var(--warn) 14%, transparent)' : 'color-mix(in srgb, var(--accent-2) 14%, transparent)',
                        color: (s.instrument_type ?? 'Stock') === 'Mutual Fund' ? 'var(--warn)' : 'var(--accent-2)',
                      }}>{s.instrument_type ?? 'Stock'}</span>
                    </td>
                    <td style={{ padding: '13px 16px', color: 'var(--fg-secondary)' }}>{s.exchange}</td>
                    <td style={{ padding: '13px 16px', color: 'var(--fg-secondary)' }}>{s.sector ?? '—'}</td>
                    <td style={{ padding: '13px 16px', color: 'var(--fg-secondary)' }}>{s.market_cap_category ?? '—'}</td>
                    <td style={{ padding: '13px 16px' }}>
                      <span style={{
                        padding: '3px 8px', borderRadius: 6, fontSize: 10, fontWeight: 700,
                        background: s.status === 'ACTIVE' ? 'var(--bull-soft)' : 'var(--bear-soft)',
                        color: s.status === 'ACTIVE' ? 'var(--bull)' : 'var(--bear)',
                      }}>{s.status}</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12,
            padding: '14px 16px', borderTop: '1px solid var(--line-2)',
          }}>
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              style={{
                padding: '6px 10px', borderRadius: 'var(--r-sm)', border: '1px solid var(--line-2)',
                background: 'var(--surface-3)', color: 'var(--fg-secondary)', cursor: page <= 1 ? 'not-allowed' : 'pointer',
                opacity: page <= 1 ? 0.4 : 1, display: 'flex', alignItems: 'center',
              }}
            >
              <ChevronLeft size={14} />
            </button>
            <span style={{ fontSize: 12, color: 'var(--fg-muted)', fontWeight: 600 }}>
              Page {page} of {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              style={{
                padding: '6px 10px', borderRadius: 'var(--r-sm)', border: '1px solid var(--line-2)',
                background: 'var(--surface-3)', color: 'var(--fg-secondary)', cursor: page >= totalPages ? 'not-allowed' : 'pointer',
                opacity: page >= totalPages ? 0.4 : 1, display: 'flex', alignItems: 'center',
              }}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
