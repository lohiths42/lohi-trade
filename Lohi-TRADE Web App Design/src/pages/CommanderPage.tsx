import { useState, useEffect, useMemo } from 'react';
import { Shield, Newspaper, Search, Filter, Ban, Brain } from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { api } from '../lib/api-client';
import { useCommanderStore } from '../stores/commander-store';
import { useThemeColors } from '../hooks/use-theme-colors';
import PageHeader from '../components/shared/PageHeader';
import type { Bias, NewsArticle, Sentiment } from '../lib/types';

const BIAS_CLR: Record<Sentiment, string> = { BULLISH: 'var(--bull)', BEARISH: 'var(--bear)', NEUTRAL: 'var(--fg-muted)' };

export default function CommanderPage() {
  const t = useThemeColors();
  const card: React.CSSProperties = { background: t.bgCardGradient, border: `1px solid ${t.borderPrimary}`, borderRadius: 16 };
  const bias = useCommanderStore((s) => s.bias);
  const news = useCommanderStore((s) => s.news);
  const setBias = useCommanderStore((s) => s.setBias);
  const setNews = useCommanderStore((s) => s.setNews);
  const [loading, setLoading] = useState(true);
  const [tickerFilter, setTickerFilter] = useState('ALL');
  const [sentFilter, setSentFilter] = useState<string>('ALL');
  const [search, setSearch] = useState('');
  const [selectedArticle, setSelectedArticle] = useState<NewsArticle | null>(null);
  const [timelineTicker, setTimelineTicker] = useState<string>('');

  useEffect(() => {
    Promise.all([
      api.getBias().then(setBias).catch(() => {}),
      api.getNews().then(setNews).catch(() => {}),
    ]).finally(() => setLoading(false));
    const id = setInterval(() => {
      api.getBias().then(setBias).catch(() => {});
      api.getNews().then(setNews).catch(() => {});
    }, 10000);
    return () => clearInterval(id);
  }, [setBias, setNews]);

  const tickers = useMemo(() => [...new Set(bias.map((b) => b.ticker))], [bias]);

  // Auto-select first ticker for timeline
  useEffect(() => {
    if (!timelineTicker && tickers.length > 0) setTimelineTicker(tickers[0]);
  }, [tickers, timelineTicker]);

  // Sentiment timeline data for selected ticker (last 24h of articles)
  const sentimentTimeline = useMemo(() => {
    if (!timelineTicker) return [];
    const tickerNews = news.filter((n) => n.ticker === timelineTicker).sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
    let cumScore = 0;
    return tickerNews.map((n) => {
      cumScore += n.boostedScore;
      return { time: new Date(n.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), score: parseFloat(cumScore.toFixed(3)), raw: n.boostedScore };
    });
  }, [news, timelineTicker]);

  // Rejected signals due to bias (articles with opposing sentiment to potential trades)
  const rejectedSignals = useMemo(() => {
    // Show articles where bias blocked a potential trade direction
    return news.filter((n) => {
      const b = bias.find((bi) => bi.ticker === n.ticker);
      if (!b) return false;
      // If bias is BEARISH and article is BULLISH (would block BUY signals), or vice versa
      return (b.bias === 'BEARISH' && n.sentiment === 'BULLISH') || (b.bias === 'BULLISH' && n.sentiment === 'BEARISH');
    }).slice(0, 20);
  }, [news, bias]);

  const filteredNews = useMemo(() => {
    let list = news;
    if (tickerFilter !== 'ALL') list = list.filter((n) => n.ticker === tickerFilter);
    if (sentFilter !== 'ALL') list = list.filter((n) => n.sentiment === sentFilter);
    if (search) list = list.filter((n) => n.title.toLowerCase().includes(search.toLowerCase()));
    return list;
  }, [news, tickerFilter, sentFilter, search]);

  const sourceStats = useMemo(() => {
    const map = new Map<string, { count: number; totalScore: number }>();
    news.forEach((n) => {
      const s = map.get(n.source) ?? { count: 0, totalScore: 0 };
      s.count++; s.totalScore += n.rawScore;
      map.set(n.source, s);
    });
    return [...map.entries()].map(([source, { count, totalScore }]) => ({ source, count, avgScore: totalScore / count })).sort((a, b) => b.count - a.count);
  }, [news]);

  if (loading) return <div style={{ padding: 48, textAlign: 'center', color: t.textMuted }}>Loading sentiment data…</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader icon={<Brain size={16} />} title="The Commander" subtitle="AI sentiment analysis · symbol bias and news scoring" />

      {/* Bias Matrix + Source Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        {/* Bias Table */}
        <div style={{ ...card, padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Symbol Bias</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>{bias.length} symbols tracked</p>
            </div>
            <Shield size={18} color="#a78bfa" />
          </div>
          {bias.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No bias data</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${t.borderPrimary}` }}>
                    {['Symbol', 'Bias', 'Score', 'Confidence', 'Articles', 'Updated'].map((h) => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: h === 'Symbol' || h === 'Bias' ? 'left' : 'right', color: t.textMuted, fontWeight: 600, fontSize: 10, textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bias.map((b) => (
                    <tr key={b.ticker} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: t.textPrimary }}>{b.ticker}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700, color: BIAS_CLR[b.bias], background: `${BIAS_CLR[b.bias]}15` }}>{b.bias}</span>
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'ui-monospace,monospace', color: t.textSecondary }}>{b.score.toFixed(3)}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'ui-monospace,monospace', color: t.textSecondary }}>{(b.confidence * 100).toFixed(0)}%</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: t.textMuted }}>{b.articleCount}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: t.textMuted, fontSize: 11 }}>{new Date(b.createdAt).toLocaleTimeString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Source Stats */}
        <div style={{ ...card, padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: '0 0 16px' }}>News Sources</h3>
          {sourceStats.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No sources</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {sourceStats.map((s, i) => (
                <div key={s.source} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: i < sourceStats.length - 1 ? `1px solid ${t.borderSubtle}` : 'none' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>{s.source}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: 11, color: t.textMuted }}>{s.count} articles</span>
                    <span style={{ fontSize: 11, fontFamily: 'ui-monospace,monospace', color: s.avgScore > 0 ? '#34d399' : s.avgScore < 0 ? '#f87171' : t.textSecondary }}>{s.avgScore > 0 ? '+' : ''}{s.avgScore.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Sentiment Timeline + Rejected Signals */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div style={{ ...card, padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Sentiment Timeline</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>Cumulative bias score evolution</p>
            </div>
            <select value={timelineTicker} onChange={(e) => setTimelineTicker(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '6px 10px', fontSize: 11, color: t.textPrimary }}>
              {tickers.map((tk) => <option key={tk} value={tk}>{tk}</option>)}
            </select>
          </div>
          {sentimentTimeline.length === 0 ? (
            <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: t.textMuted, fontSize: 13 }}>No timeline data for {timelineTicker || 'selected ticker'}</div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={sentimentTimeline}>
                <CartesianGrid strokeDasharray="3 3" stroke={t.isLight ? '#e2e8f0' : 'rgba(30,41,59,0.6)'} />
                <XAxis dataKey="time" stroke={t.borderSecondary} tick={{ fill: t.textMuted, fontSize: 9 }} tickLine={false} axisLine={false} />
                <YAxis stroke={t.borderSecondary} tick={{ fill: t.textMuted, fontSize: 10 }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: t.isLight ? '#ffffff' : '#020617', border: `1px solid ${t.borderPrimary}`, borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="score" stroke="#a78bfa" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div style={{ ...card, padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <Ban size={16} color="#f87171" />
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: 0 }}>Rejected by Bias</h3>
              <p style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>{rejectedSignals.length} conflicting signals</p>
            </div>
          </div>
          {rejectedSignals.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No rejected signals</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxHeight: 200, overflowY: 'auto' }}>
              {rejectedSignals.map((n, i) => {
                const b = bias.find((bi) => bi.ticker === n.ticker);
                return (
                  <div key={n.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: i < rejectedSignals.length - 1 ? `1px solid ${t.borderSubtle}` : 'none' }}>
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontSize: 11, fontWeight: 600, color: t.textSecondary, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>{n.title}</p>
                      <p style={{ fontSize: 9, color: t.textMuted, margin: '2px 0 0' }}>{n.ticker} · Bias: {b?.bias ?? '?'}</p>
                    </div>
                    <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, fontWeight: 700, color: BIAS_CLR[n.sentiment], background: `${BIAS_CLR[n.sentiment]}15`, flexShrink: 0 }}>{n.sentiment}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* News Feed */}
      <div style={{ ...card, padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, margin: 0 }}>News Feed</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>{filteredNews.length} articles</p>
          </div>
          <Newspaper size={18} color="#fbbf24" />
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
            <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search headlines…" style={{ width: '100%', background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '7px 10px 7px 30px', fontSize: 12, color: t.textPrimary, outline: 'none' }} />
          </div>
          <select value={tickerFilter} onChange={(e) => setTickerFilter(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '7px 12px', fontSize: 12, color: t.textPrimary }}>
            <option value="ALL">All Tickers</option>
            {tickers.map((tk) => <option key={tk} value={tk}>{tk}</option>)}
          </select>
          <select value={sentFilter} onChange={(e) => setSentFilter(e.target.value)} style={{ background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, padding: '7px 12px', fontSize: 12, color: t.textPrimary }}>
            <option value="ALL">All Sentiment</option>
            <option value="BULLISH">Bullish</option>
            <option value="BEARISH">Bearish</option>
            <option value="NEUTRAL">Neutral</option>
          </select>
        </div>

        {filteredNews.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: t.textMuted, fontSize: 13 }}>No articles match filters</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxHeight: 500, overflowY: 'auto' }}>
            {filteredNews.slice(0, 50).map((n, i) => {
              const nc = BIAS_CLR[n.sentiment];
              return (
                <div key={n.id} onClick={() => setSelectedArticle(n)} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, padding: '12px 0', borderBottom: i < Math.min(filteredNews.length, 50) - 1 ? `1px solid ${t.borderSubtle}` : 'none', cursor: 'pointer' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: 12, fontWeight: 600, color: t.textSecondary, margin: 0, lineHeight: 1.4 }}>{n.title}</p>
                    <p style={{ fontSize: 10, color: t.textMuted, margin: '4px 0 0' }}>{n.ticker} · {n.source} · {new Date(n.createdAt).toLocaleTimeString()}</p>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
                    <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, fontWeight: 700, color: nc, background: `${nc}15` }}>{n.sentiment}</span>
                    <span style={{ fontSize: 10, color: t.textMuted, fontFamily: 'ui-monospace,monospace' }}>{n.confidence.toFixed(2)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Article Detail Modal */}
      {selectedArticle && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgOverlay }} onClick={() => setSelectedArticle(null)}>
          <div style={{ ...card, padding: 28, width: 480, maxHeight: '80vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: '0 0 8px', lineHeight: 1.4 }}>{selectedArticle.title}</h3>
            <p style={{ fontSize: 11, color: t.textMuted, marginBottom: 16 }}>{selectedArticle.source} · {selectedArticle.ticker} · {new Date(selectedArticle.createdAt).toLocaleString()}</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
              {[
                { label: 'Sentiment', value: selectedArticle.sentiment, color: BIAS_CLR[selectedArticle.sentiment] },
                { label: 'Raw Score', value: selectedArticle.rawScore.toFixed(4), color: t.textSecondary },
                { label: 'Boosted Score', value: selectedArticle.boostedScore.toFixed(4), color: t.textSecondary },
              ].map((m) => (
                <div key={m.label} style={{ background: t.inputBg, borderRadius: 8, padding: '10px 12px' }}>
                  <p style={{ fontSize: 9, color: t.textMuted, textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>{m.label}</p>
                  <p style={{ fontSize: 14, fontWeight: 700, color: m.color, fontFamily: 'ui-monospace,monospace', margin: 0 }}>{m.value}</p>
                </div>
              ))}
            </div>
            <button onClick={() => setSelectedArticle(null)} style={{ width: '100%', padding: '8px', fontSize: 12, fontWeight: 600, color: t.textSecondary, background: t.inputBg, border: `1px solid ${t.inputBorder}`, borderRadius: 8, cursor: 'pointer' }}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
