/**
 * `/research` — ResearchDashboardPage (editorial home).
 *
 * Quartr-inspired landing:
 *   • Pure monochrome, print-like masthead with a coral "Edge" kicker.
 *   • Long-form serif headline, sans-serif body.
 *   • Hairline-ruled sections — no colored chrome. Company brands and
 *     chart marks are the only color on the page.
 *   • Editorial tile grid beneath: Feed (ideas) · Themes · Live Trade,
 *     plus Recent briefs + Coverage as a two-column strip.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Loader2 } from 'lucide-react';
import RefusalBanner from '../../components/research/RefusalBanner';
import BriefViewer from '../../components/research/BriefViewer';
import LiveTradeWidget from '../../components/research/LiveTradeWidget';
import { ServiceStatusBanner } from '../../components/setup/ServiceStatusBanner';
import { useFeatureGate } from '../../hooks/useFeatureGate';
import { useResearchStore } from '../../stores/research-store';
import { useResearchStream } from '../../hooks/use-research-stream';
import { useWatchlistStore } from '../../stores/watchlist-store';
import { researchApi } from '../../lib/research-api';
import type { ResearchRunSummary } from '../../lib/research-types';
import {
  SECTOR_META,
  type SectorCluster,
  type StockIdea,
  type ThemeReport,
} from '../../lib/research-ideas-types';

export default function ResearchDashboardPage() {
  const navigate = useNavigate();
  const { isFeatureAvailable, getRequiredServiceName } = useFeatureGate();

  const [prompt, setPrompt] = useState('');
  const [symbol, setSymbol] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [ideas, setIdeas] = useState<StockIdea[]>([]);
  const [themes, setThemes] = useState<ThemeReport[]>([]);
  const [sectors, setSectors] = useState<SectorCluster[]>([]);
  const [recent, setRecent] = useState<ResearchRunSummary[]>([]);
  const [loadingFeeds, setLoadingFeeds] = useState(true);

  const startRun = useResearchStore((s) => s.startRun);
  const activeRunId = useResearchStore((s) => s.activeRunId);
  const activeRun = useResearchStore((s) =>
    s.activeRunId ? s.runs[s.activeRunId] ?? null : null,
  );
  const watchlist = useWatchlistStore((s) => s.symbols);

  useResearchStream(activeRunId);

  useEffect(() => {
    let alive = true;
    Promise.all([
      researchApi.listResearchIdeas(),
      researchApi.listResearchThemes(),
      researchApi.listSectorClusters(),
      researchApi.listResearchRuns(),
    ])
      .then(([i, th, sc, r]) => {
        if (!alive) return;
        setIdeas(i);
        setThemes(th);
        setSectors(sc);
        setRecent(r);
      })
      .finally(() => {
        if (alive) setLoadingFeeds(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const topIdeas = useMemo(() => ideas.slice(0, 5), [ideas]);
  const topThemes = useMemo(() => themes.slice(0, 3), [themes]);

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await researchApi.startResearchRun({
        prompt: prompt.trim(),
        symbol: symbol.trim() || undefined,
      });
      startRun({
        runId: res.run_id,
        symbol: symbol.trim() || null,
        prompt: prompt.trim(),
      });
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to start run');
    } finally {
      setSubmitting(false);
    }
  }

  const todayStr = new Date().toLocaleDateString(undefined, {
    dateStyle: 'full',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 36 }}>
      {/* ── Service Status Banner (Requirement 4.2, 4.3) ─────────── */}
      {!isFeatureAvailable('research_dashboard') && (
        <ServiceStatusBanner
          serviceName={getRequiredServiceName('research_dashboard') ?? 'NVIDIA NIM or Ollama'}
          featureDescription="The Research Dashboard requires an AI provider (NVIDIA NIM or local Ollama) to generate equity research briefs."
          configureLink="/settings"
        />
      )}

      {/* ── Masthead ──────────────────────────────────────────────── */}
      <section className="qr-masthead">
        <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
          Edge · {todayStr}
        </p>
        <h1
          className="qr-display"
          style={{ margin: '18px 0 14px', maxWidth: 880 }}
        >
          Numbers are easy. Understanding is hard.
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: '0 0 24px' }}>
          Lohi Research produces cited equity briefs over Indian-market filings,
          news, and concalls. Every claim is grounded, every number is checked,
          every brief is judged before you read it.
        </p>

        <form
          onSubmit={handleAsk}
          style={{
            display: 'flex',
            gap: 14,
            alignItems: 'flex-end',
            flexWrap: 'wrap',
            maxWidth: 880,
          }}
        >
          <div style={{ width: 140 }}>
            <p className="qr-kicker" style={{ margin: '0 0 4px' }}>
              Symbol
            </p>
            <input
              aria-label="Symbol (optional)"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="RELIANCE"
              className="qr-input"
            />
          </div>
          <div style={{ flex: 1, minWidth: 280 }}>
            <p className="qr-kicker" style={{ margin: '0 0 4px' }}>
              Your question
            </p>
            <input
              aria-label="Research prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="How is capex being financed this quarter?"
              className="qr-input"
            />
          </div>
          <button
            type="submit"
            disabled={submitting || !prompt.trim()}
            className="qr-btn"
          >
            {submitting ? <Loader2 size={13} className="spin" /> : null}
            {submitting ? 'Starting' : 'Run research'}
            {!submitting && <ArrowRight size={13} />}
          </button>
        </form>
        {submitError && (
          <p style={{ margin: '12px 0 0', fontSize: 12, color: 'var(--warn)' }}>
            {submitError}
          </p>
        )}
      </section>

      <RefusalBanner compact />

      {/* Active run preview */}
      {activeRun && (
        <section>
          <hr className="qr-rule" />
          <BriefViewer
            brief={activeRun.brief}
            streaming={
              activeRun.streamingState === 'streaming'
              || activeRun.streamingState === 'starting'
            }
          />
          <div style={{ marginTop: 12, textAlign: 'right' }}>
            <button onClick={() => navigate('/research/chat')} className="qr-link">
              Continue in chat →
            </button>
          </div>
        </section>
      )}

      {/* ── Editorial grid ───────────────────────────────────────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
          gap: 32,
        }}
      >
        <div style={{ gridColumn: 'span 5' }}>
          <IdeasColumn
            ideas={topIdeas}
            loading={loadingFeeds}
            onOpenAll={() => navigate('/research/ideas')}
            onOpen={(sym) => navigate(`/research/${sym}`)}
          />
        </div>
        <div style={{ gridColumn: 'span 4' }}>
          <ThemesColumn
            themes={topThemes}
            loading={loadingFeeds}
            onOpenAll={() => navigate('/research/themes')}
            onOpen={(id) => navigate(`/research/themes?id=${id}`)}
          />
        </div>
        <div style={{ gridColumn: 'span 3' }}>
          <LiveTradeWidget />
        </div>
      </section>

      <hr className="qr-rule" />

      {/* ── Sectors strip — the "pharma-together" view ────────────── */}
      <SectorStrip
        clusters={sectors}
        loading={loadingFeeds}
        onOpenAll={() => navigate('/research/sectors')}
        onOpenSector={(s) => navigate(`/research/sectors?sector=${s}`)}
      />

      <hr className="qr-rule" />

      {/* ── Recent briefs + Coverage ─────────────────────────────── */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr',
          gap: 40,
        }}
      >
        <RecentBriefsColumn loading={loadingFeeds} recent={recent} />
        <CoverageColumn
          symbols={watchlist.slice(0, 10)}
          onPick={(s) => navigate(`/research/${s}`)}
        />
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Editorial columns — pure typography, hairline separators
// ─────────────────────────────────────────────────────────────────────────

function ColumnHeader({
  kicker,
  title,
  actionLabel,
  onAction,
}: {
  kicker: string;
  title: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 10,
        paddingBottom: 14,
        borderBottom: '1px solid var(--line-3)',
        marginBottom: 6,
      }}
    >
      <div>
        <p className="qr-kicker" style={{ margin: 0 }}>
          {kicker}
        </p>
        <h3
          className="qr-serif"
          style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
        >
          {title}
        </h3>
      </div>
      <button onClick={onAction} className="qr-link">
        {actionLabel}
      </button>
    </div>
  );
}

function IdeasColumn({
  ideas,
  loading,
  onOpenAll,
  onOpen,
}: {
  ideas: StockIdea[];
  loading: boolean;
  onOpenAll: () => void;
  onOpen: (sym: string) => void;
}) {
  return (
    <section>
      <ColumnHeader
        kicker="Feed"
        title="Top ideas"
        actionLabel="View all"
        onAction={onOpenAll}
      />
      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Loading ideas…
        </p>
      ) : ideas.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '14px 0' }}>
          No ideas yet. The first high-conviction brief becomes an idea.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {ideas.map((idea) => (
            <li
              key={idea.idea_id}
              onClick={() => onOpen(idea.symbol)}
              className="qr-tile"
              style={{ cursor: 'pointer', display: 'flex', gap: 14 }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 6,
                    flexWrap: 'wrap',
                  }}
                >
                  <span
                    className="qr-tabular"
                    style={{
                      fontWeight: 800,
                      color: 'var(--fg-primary)',
                      fontSize: 12,
                    }}
                  >
                    {idea.symbol}
                  </span>
                  <span className="qr-tag">
                    {idea.archetype.replace('_', ' ')}
                  </span>
                  {idea.direction !== 'neutral' && (
                    <span
                      className={
                        idea.direction === 'bullish' ? 'qr-tag qr-tag--bull' : 'qr-tag qr-tag--bear'
                      }
                    >
                      {idea.direction}
                    </span>
                  )}
                </div>
                <p
                  className="qr-serif"
                  style={{
                    margin: 0,
                    fontSize: 17,
                    fontWeight: 500,
                    lineHeight: 1.28,
                    color: 'var(--fg-primary)',
                  }}
                >
                  {idea.headline}
                </p>
                <p
                  className="qr-body"
                  style={{
                    margin: '6px 0 10px',
                    overflow: 'hidden',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                  }}
                >
                  {idea.thesis_short}
                </p>
                <div className="qr-meter" aria-hidden>
                  <span
                    style={{
                      width: `${Math.max(0, Math.min(100, idea.conviction * 100))}%`,
                    }}
                  />
                </div>
              </div>
              <div
                style={{
                  width: 56,
                  textAlign: 'right',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-end',
                  gap: 4,
                }}
              >
                <span className="qr-kicker" style={{ margin: 0 }}>
                  {idea.conviction_band}
                </span>
                <span
                  className="qr-tabular"
                  style={{
                    fontSize: 26,
                    fontWeight: 700,
                    color: 'var(--fg-primary)',
                    lineHeight: 1,
                  }}
                >
                  {Math.round(idea.conviction * 100)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ThemesColumn({
  themes,
  loading,
  onOpenAll,
  onOpen,
}: {
  themes: ThemeReport[];
  loading: boolean;
  onOpenAll: () => void;
  onOpen: (id: string) => void;
}) {
  return (
    <section>
      <ColumnHeader
        kicker="Cohort"
        title="Themes"
        actionLabel="Explore"
        onAction={onOpenAll}
      />
      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Loading themes…
        </p>
      ) : themes.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '14px 0' }}>
          No themes yet. Merge symbols on the Themes page to produce a
          cohort-level editorial.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {themes.map((th) => (
            <li
              key={th.theme_id}
              onClick={() => onOpen(th.theme_id)}
              className="qr-tile"
              style={{ cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                {th.archetypes.slice(0, 2).map((a) => (
                  <span key={a} className="qr-tag">
                    {a.replace('_', ' ')}
                  </span>
                ))}
                <span
                  className="qr-kicker"
                  style={{ margin: 0, alignSelf: 'center' }}
                >
                  {th.members.length} companies
                </span>
              </div>
              <p
                className="qr-serif"
                style={{
                  margin: 0,
                  fontSize: 17,
                  fontWeight: 500,
                  lineHeight: 1.28,
                  color: 'var(--fg-primary)',
                }}
              >
                {th.title}
              </p>
              <p
                className="qr-body"
                style={{
                  margin: '6px 0 0',
                  overflow: 'hidden',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {th.summary}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentBriefsColumn({
  loading,
  recent,
}: {
  loading: boolean;
  recent: ResearchRunSummary[];
}) {
  const navigate = useNavigate();
  return (
    <section>
      <ColumnHeader
        kicker="Archive"
        title="Recent briefs"
        actionLabel="All briefs"
        onAction={() => navigate('/research/briefs')}
      />
      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Loading…
        </p>
      ) : recent.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Nothing yet. Ask anything in the masthead to create your first cited brief.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {recent.slice(0, 8).map((r) => (
            <li
              key={r.run_id}
              onClick={() =>
                navigate(r.symbol ? `/research/${r.symbol}` : '/research/chat')
              }
              className="qr-tile"
              style={{
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                gap: 16,
                alignItems: 'flex-start',
              }}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  {r.symbol && (
                    <span
                      className="qr-tabular"
                      style={{
                        fontSize: 12,
                        fontWeight: 800,
                        color: 'var(--fg-primary)',
                      }}
                    >
                      {r.symbol}
                    </span>
                  )}
                  <span
                    style={{
                      fontSize: 10,
                      textTransform: 'uppercase',
                      letterSpacing: '0.14em',
                      color:
                        r.status === 'error'
                          ? 'var(--warn)'
                          : r.status === 'done'
                            ? 'var(--bull)'
                            : 'var(--fg-muted)',
                    }}
                  >
                    · {r.status}
                  </span>
                </div>
                <p
                  className="qr-serif"
                  style={{
                    margin: '6px 0 0',
                    fontSize: 16,
                    fontWeight: 500,
                    color: 'var(--fg-primary)',
                    overflow: 'hidden',
                    display: '-webkit-box',
                    WebkitLineClamp: 1,
                    WebkitBoxOrient: 'vertical',
                  }}
                >
                  {r.prompt}
                </p>
                <p
                  className="qr-kicker"
                  style={{ margin: '6px 0 0' }}
                >
                  {new Date(r.created_at).toLocaleString()}
                </p>
              </div>
              <ArrowRight size={14} color="var(--fg-muted)" />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CoverageColumn({
  symbols,
  onPick,
}: {
  symbols: string[];
  onPick: (sym: string) => void;
}) {
  return (
    <section>
      <div
        style={{
          paddingBottom: 14,
          borderBottom: '1px solid var(--line-3)',
          marginBottom: 6,
        }}
      >
        <p className="qr-kicker" style={{ margin: 0 }}>
          Watchlist
        </p>
        <h3
          className="qr-serif"
          style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
        >
          Coverage
        </h3>
      </div>
      {symbols.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Add symbols to your Trade watchlist to line up coverage here.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {symbols.map((s) => (
            <li
              key={s}
              onClick={() => onPick(s)}
              style={{
                padding: '12px 0',
                borderTop: '1px solid var(--line-2)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                cursor: 'pointer',
              }}
            >
              <span
                className="qr-tabular"
                style={{ fontWeight: 800, fontSize: 13, color: 'var(--fg-primary)' }}
              >
                {s}
              </span>
              <ArrowRight size={13} color="var(--fg-muted)" />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


// ─── Sector strip — horizontal row of auto-grouped cohorts ───────────────

function SectorStrip({
  clusters,
  loading,
  onOpenAll,
  onOpenSector,
}: {
  clusters: SectorCluster[];
  loading: boolean;
  onOpenAll: () => void;
  onOpenSector: (sector: SectorCluster['sector']) => void;
}) {
  return (
    <section>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 10,
          paddingBottom: 14,
          borderBottom: '1px solid var(--line-3)',
          marginBottom: 4,
        }}
      >
        <div>
          <p className="qr-kicker" style={{ margin: 0 }}>
            By sector
          </p>
          <h3
            className="qr-serif"
            style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
          >
            Companies grouped by topic
          </h3>
        </div>
        <button onClick={onOpenAll} className="qr-link">
          All sectors
        </button>
      </div>

      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '14px 0' }}>
          Loading sectors…
        </p>
      ) : clusters.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '14px 0' }}>
          No sector coverage yet. Sectors populate as the classifier builds conviction on
          your watchlist symbols.
        </p>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 0,
            borderTop: '1px solid var(--line-3)',
            borderLeft: '1px solid var(--line-3)',
          }}
        >
          {clusters.slice(0, 8).map((cluster) => {
            const meta = SECTOR_META[cluster.sector];
            const biasPct = Math.max(-100, Math.min(100, Math.round(cluster.bias * 100)));
            const biasColor =
              biasPct > 5
                ? 'var(--bull)'
                : biasPct < -5
                  ? 'var(--bear)'
                  : 'var(--fg-muted)';
            return (
              <button
                key={cluster.sector}
                onClick={() => onOpenSector(cluster.sector)}
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                  padding: '16px 16px',
                  borderRight: '1px solid var(--line-3)',
                  borderBottom: '1px solid var(--line-3)',
                  background: 'var(--surface-2)',
                  transition: 'background var(--dur-2) var(--ease-out)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  minHeight: 110,
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = 'var(--surface-3)')
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = 'var(--surface-2)')
                }
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span className="qr-kicker" style={{ margin: 0 }}>
                    {meta.short}
                  </span>
                  <span
                    className="qr-tabular"
                    style={{ fontSize: 11, fontWeight: 700, color: biasColor }}
                  >
                    {biasPct > 0 ? '+' : ''}
                    {biasPct}%
                  </span>
                </div>
                <p
                  className="qr-serif"
                  style={{
                    margin: 0,
                    fontSize: 15,
                    fontWeight: 500,
                    lineHeight: 1.22,
                    color: 'var(--fg-primary)',
                  }}
                >
                  {meta.label}
                </p>
                <p
                  className="qr-tabular"
                  style={{
                    margin: 'auto 0 0',
                    fontSize: 11,
                    fontWeight: 600,
                    color: 'var(--fg-muted)',
                  }}
                >
                  {cluster.members.length} companies
                </p>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
