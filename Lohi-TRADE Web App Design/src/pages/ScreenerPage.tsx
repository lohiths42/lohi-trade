import { useState, useCallback } from 'react';
import {
  Filter, Download, ChevronLeft, ChevronRight, Loader2, ArrowUpDown,
  ChevronDown, ChevronUp, SlidersHorizontal, X,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useThemeColors } from '../hooks/use-theme-colors';
import PageHeader from '../components/shared/PageHeader';
import { api } from '../lib/api-client';

interface RangeFilter { min?: string; max?: string }

interface Filters {
  pe_ratio: RangeFilter;
  pb_ratio: RangeFilter;
  market_cap: RangeFilter;
  dividend_yield: RangeFilter;
  roe: RangeFilter;
  debt_to_equity: RangeFilter;
  rsi_14: RangeFilter;
  price_change_1d: RangeFilter;
  return_1y: RangeFilter;
  sector: string;
  market_cap_category: string;
}

const EMPTY_FILTERS: Filters = {
  pe_ratio: {}, pb_ratio: {}, market_cap: {}, dividend_yield: {},
  roe: {}, debt_to_equity: {}, rsi_14: {}, price_change_1d: {},
  return_1y: {}, sector: '', market_cap_category: '',
};

const FILTER_LABELS: Record<string, string> = {
  pe_ratio: 'PE Ratio', pb_ratio: 'PB Ratio', market_cap: 'Market Cap',
  dividend_yield: 'Dividend Yield %', roe: 'ROE %', debt_to_equity: 'Debt/Equity',
  rsi_14: 'RSI (14)', price_change_1d: 'Price Change 1D %', return_1y: 'Return 1Y %',
};

const SORT_COLUMNS = [
  { key: 'symbol', label: 'Symbol' },
  { key: 'company_name', label: 'Company' },
  { key: 'sector', label: 'Sector' },
  { key: 'market_cap', label: 'Market Cap' },
  { key: 'pe_ratio', label: 'PE' },
  { key: 'dividend_yield', label: 'Div Yield' },
  { key: 'price_change_1d', label: '1D Chg' },
  { key: 'return_1y', label: '1Y Return' },
];

interface ResultItem {
  security_id: number;
  symbol: string;
  company_name: string;
  sector?: string;
  market_cap?: string;
  market_cap_category?: string;
  pe_ratio?: string;
  dividend_yield?: string;
  price_change_1d?: string;
  return_1y?: string;
  [key: string]: any;
}

export default function ScreenerPage() {
  const t = useThemeColors();
  const navigate = useNavigate();
  const [filters, setFilters] = useState<Filters>({ ...EMPTY_FILTERS });
  const [results, setResults] = useState<ResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [sortBy, setSortBy] = useState('market_cap');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(true);
  const [searched, setSearched] = useState(false);
  const pageSize = 50;

  const buildBody = useCallback(() => {
    const body: Record<string, any> = { sort_by: sortBy, order: sortOrder, page, page_size: pageSize };
    for (const [key, label] of Object.entries(FILTER_LABELS)) {
      const f = filters[key as keyof Filters] as RangeFilter;
      if (f?.min || f?.max) {
        body[key] = {};
        if (f.min) body[key].min = parseFloat(f.min);
        if (f.max) body[key].max = parseFloat(f.max);
      }
    }
    if (filters.sector) body.sector = filters.sector;
    if (filters.market_cap_category) body.market_cap_category = filters.market_cap_category;
    return body;
  }, [filters, sortBy, sortOrder, page]);

  const runSearch = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const body = buildBody();
      body.page = p;
      const res = await api.screenerSearch(body);
      setResults(res.items ?? []);
      setTotal(res.total ?? 0);
      setTotalPages(res.total_pages ?? 1);
      setSearched(true);
    } catch {
      setResults([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [buildBody, page]);

  const handleSearch = () => { setPage(1); runSearch(1); };

  const handleSort = (col: string) => {
    if (sortBy === col) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortOrder('desc');
    }
  };

  const handleExportCsv = async () => {
    try {
      const body = buildBody();
      const blob = await api.screenerExportCsv(body);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'screener_results.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  };

  const handleReset = () => { setFilters({ ...EMPTY_FILTERS }); setResults([]); setTotal(0); setSearched(false); };

  const updateRange = (key: string, field: 'min' | 'max', value: string) => {
    setFilters((prev) => ({ ...prev, [key]: { ...(prev[key as keyof Filters] as RangeFilter), [field]: value } }));
  };

  const appliedFilters = Object.entries(FILTER_LABELS).filter(([key]) => {
    const f = filters[key as keyof Filters] as RangeFilter;
    return f?.min || f?.max;
  }).map(([key, label]) => {
    const f = filters[key as keyof Filters] as RangeFilter;
    return `${label}: ${f.min ?? '—'}–${f.max ?? '—'}`;
  });
  if (filters.sector) appliedFilters.push(`Sector: ${filters.sector}`);
  if (filters.market_cap_category) appliedFilters.push(`Cap: ${filters.market_cap_category}`);

  const card: React.CSSProperties = {
    background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<SlidersHorizontal size={16} />}
        title="Stock Screener"
        subtitle="Filter stocks by fundamental and technical parameters"
        actions={
          <>
            <button onClick={() => setShowFilters((v) => !v)} style={{
              padding: '6px 12px', borderRadius: 'var(--r-sm)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
              border: '1px solid var(--line-2)', background: 'var(--surface-3)', color: 'var(--fg-secondary)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Filter size={12} /> {showFilters ? 'Hide Filters' : 'Show Filters'}
            </button>
          {searched && (
            <button onClick={handleExportCsv} style={{
              padding: '6px 12px', borderRadius: 'var(--r-sm)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
              border: 'none', background: 'linear-gradient(135deg, #059669, #047857)', color: 'white',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Download size={12} /> Export CSV
            </button>
          )}
          </>
        }
      />

      {/* Filter Panel */}
      {showFilters && (
        <div style={{ ...card, padding: 20 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
            {Object.entries(FILTER_LABELS).map(([key, label]) => (
              <div key={key}>
                <label style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</label>
                <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  <input
                    type="number"
                    placeholder="Min"
                    value={(filters[key as keyof Filters] as RangeFilter)?.min ?? ''}
                    onChange={(e) => updateRange(key, 'min', e.target.value)}
                    style={{
                      flex: 1, padding: '6px 8px', borderRadius: 6, fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.inputBorder}`,
                      color: t.textPrimary, outline: 'none', minWidth: 0,
                    }}
                  />
                  <input
                    type="number"
                    placeholder="Max"
                    value={(filters[key as keyof Filters] as RangeFilter)?.max ?? ''}
                    onChange={(e) => updateRange(key, 'max', e.target.value)}
                    style={{
                      flex: 1, padding: '6px 8px', borderRadius: 6, fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.inputBorder}`,
                      color: t.textPrimary, outline: 'none', minWidth: 0,
                    }}
                  />
                </div>
              </div>
            ))}
            {/* Sector select */}
            <div>
              <label style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Sector</label>
              <select
                value={filters.sector}
                onChange={(e) => setFilters((p) => ({ ...p, sector: e.target.value }))}
                style={{
                  width: '100%', marginTop: 4, padding: '6px 8px', borderRadius: 6, fontSize: 12,
                  background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary, outline: 'none',
                }}
              >
                <option value="">All Sectors</option>
                {['Pharma', 'IT/Technology', 'Banking & Finance', 'FMCG', 'Energy', 'Automobile', 'Telecom', 'Real Estate', 'Infrastructure', 'Chemicals', 'Insurance', 'Miscellaneous'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            {/* Market Cap Category */}
            <div>
              <label style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Market Cap</label>
              <select
                value={filters.market_cap_category}
                onChange={(e) => setFilters((p) => ({ ...p, market_cap_category: e.target.value }))}
                style={{
                  width: '100%', marginTop: 4, padding: '6px 8px', borderRadius: 6, fontSize: 12,
                  background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textPrimary, outline: 'none',
                }}
              >
                <option value="">All</option>
                <option value="large-cap">Large Cap</option>
                <option value="mid-cap">Mid Cap</option>
                <option value="small-cap">Small Cap</option>
              </select>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button onClick={handleSearch} style={{
              padding: '8px 20px', borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: 'pointer',
              border: 'none', background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: 'white',
            }}>
              Search
            </button>
            <button onClick={handleReset} style={{
              padding: '8px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              border: `1px solid ${t.borderPrimary}`, background: 'transparent', color: t.textSecondary,
              display: 'flex', alignItems: 'center', gap: 4,
            }}>
              <X size={12} /> Reset
            </button>
          </div>
        </div>
      )}

      {/* Filter Summary + Total Count */}
      {searched && (
        <div style={{
          display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8,
          padding: '10px 16px', borderRadius: 10,
          background: t.bgMuted, border: `1px solid ${t.borderPrimary}`,
        }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.textPrimary }}>
            {total.toLocaleString()} matching stocks
          </span>
          {appliedFilters.length > 0 && (
            <>
              <span style={{ fontSize: 11, color: t.textMuted }}>|</span>
              {appliedFilters.map((f, i) => (
                <span key={i} style={{
                  padding: '2px 8px', borderRadius: 6, fontSize: 10, fontWeight: 600,
                  background: t.accentBg, color: t.accentText,
                }}>{f}</span>
              ))}
            </>
          )}
        </div>
      )}

      {/* Results Table */}
      {searched && (
        <div style={{ ...card, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${t.borderPrimary}` }}>
                  {SORT_COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handleSort(col.key)}
                      style={{
                        padding: '12px 16px', textAlign: 'left', fontSize: 10, fontWeight: 700,
                        color: sortBy === col.key ? t.accentText : t.textMuted,
                        textTransform: 'uppercase', letterSpacing: '0.08em', cursor: 'pointer',
                        userSelect: 'none', whiteSpace: 'nowrap',
                      }}
                    >
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        {col.label}
                        {sortBy === col.key ? (
                          sortOrder === 'asc' ? <ChevronUp size={11} /> : <ChevronDown size={11} />
                        ) : (
                          <ArrowUpDown size={10} style={{ opacity: 0.3 }} />
                        )}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={SORT_COLUMNS.length} style={{ padding: 40, textAlign: 'center' }}>
                      <Loader2 size={20} color={t.textMuted} style={{ animation: 'spin 1s linear infinite' }} />
                    </td>
                  </tr>
                ) : results.length === 0 ? (
                  <tr>
                    <td colSpan={SORT_COLUMNS.length} style={{ padding: 40, textAlign: 'center', color: t.textMuted }}>
                      No results found
                    </td>
                  </tr>
                ) : (
                  results.map((r) => (
                    <tr
                      key={r.security_id}
                      onClick={() => navigate(`/stocks/${r.symbol}`)}
                      style={{ borderBottom: `1px solid ${t.borderSubtle}`, cursor: 'pointer', transition: 'background 0.1s' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = t.bgHover)}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '10px 16px', fontWeight: 700, color: t.accentText }}>{r.symbol}</td>
                      <td style={{ padding: '10px 16px', color: t.textPrimary, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.company_name}</td>
                      <td style={{ padding: '10px 16px', color: t.textSecondary }}>{r.sector ?? '—'}</td>
                      <td style={{ padding: '10px 16px', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{r.market_cap ?? '—'}</td>
                      <td style={{ padding: '10px 16px', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{r.pe_ratio ?? '—'}</td>
                      <td style={{ padding: '10px 16px', color: t.textSecondary, fontFamily: 'ui-monospace,monospace' }}>{r.dividend_yield ? `${r.dividend_yield}%` : '—'}</td>
                      <td style={{ padding: '10px 16px', fontFamily: 'ui-monospace,monospace' }}>
                        {r.price_change_1d ? (
                          <span style={{ color: parseFloat(r.price_change_1d) >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>
                            {parseFloat(r.price_change_1d) >= 0 ? '+' : ''}{r.price_change_1d}%
                          </span>
                        ) : '—'}
                      </td>
                      <td style={{ padding: '10px 16px', fontFamily: 'ui-monospace,monospace' }}>
                        {r.return_1y ? (
                          <span style={{ color: parseFloat(r.return_1y) >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>
                            {parseFloat(r.return_1y) >= 0 ? '+' : ''}{r.return_1y}%
                          </span>
                        ) : '—'}
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
              padding: '14px 16px', borderTop: `1px solid ${t.borderPrimary}`,
            }}>
              <button
                disabled={page <= 1}
                onClick={() => { setPage((p) => Math.max(1, p - 1)); runSearch(Math.max(1, page - 1)); }}
                style={{
                  padding: '6px 10px', borderRadius: 8, border: `1px solid ${t.borderPrimary}`,
                  background: t.bgMuted, color: t.textSecondary, cursor: page <= 1 ? 'not-allowed' : 'pointer',
                  opacity: page <= 1 ? 0.4 : 1, display: 'flex', alignItems: 'center',
                }}
              >
                <ChevronLeft size={14} />
              </button>
              <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 600 }}>
                Page {page} of {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); runSearch(Math.min(totalPages, page + 1)); }}
                style={{
                  padding: '6px 10px', borderRadius: 8, border: `1px solid ${t.borderPrimary}`,
                  background: t.bgMuted, color: t.textSecondary, cursor: page >= totalPages ? 'not-allowed' : 'pointer',
                  opacity: page >= totalPages ? 0.4 : 1, display: 'flex', alignItems: 'center',
                }}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
