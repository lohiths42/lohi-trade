/**
 * `/research/:symbol` — ResearchSymbolPage.
 *
 * Shows a per-symbol research view:
 *   - Snapshot when fresh (serves instantly, Req 5.5, Req 11.4)
 *   - Filings timeline + provenance derived from the brief's `AgentResult`s
 *   - BriefViewer for the research sections (summary, thesis, risks, etc.)
 *   - Inline citations via `BriefViewer` → `CitationDrawer`
 *
 * Task 17.4 — Requirements: 6.2, 6.6, design §3.13.
 */

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Brain, Clock, RefreshCw } from 'lucide-react';
import PageHeader from '../../components/shared/PageHeader';
import RefusalBanner from '../../components/research/RefusalBanner';
import BriefViewer from '../../components/research/BriefViewer';
import AgentCard from '../../components/research/AgentCard';
import NoDataState from '../../components/research/NoDataState';
import { useThemeColors } from '../../hooks/use-theme-colors';
import { useResearchStream } from '../../hooks/use-research-stream';
import { useResearchStore } from '../../stores/research-store';
import { researchApi } from '../../lib/research-api';
import type { AgentName, ResearchBrief, ResearchSnapshot } from '../../lib/research-types';

const ALL_AGENTS: AgentName[] = [
  'filings',
  'fundamentals',
  'news_sentiment',
  'technicals',
  'peer_sector',
  'macro',
];

export default function ResearchSymbolPage() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = (rawSymbol ?? '').toUpperCase();
  const t = useThemeColors();

  const [snapshot, setSnapshot] = useState<ResearchSnapshot | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);
  const [rerunning, setRerunning] = useState(false);

  const startRun = useResearchStore((s) => s.startRun);
  const activeRunId = useResearchStore((s) => s.activeRunId);
  const activeRun = useResearchStore((s) =>
    s.activeRunId ? s.runs[s.activeRunId] ?? null : null,
  );

  useResearchStream(activeRunId);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoadingSnapshot(true);
    researchApi
      .getResearchSnapshot(symbol)
      .then((snap) => {
        if (alive) setSnapshot(snap);
      })
      .catch(() => {
        if (alive) setSnapshot(null);
      })
      .finally(() => {
        if (alive) setLoadingSnapshot(false);
      });
    return () => {
      alive = false;
    };
  }, [symbol]);

  // Prefer the live run's brief once it's available; fall back to Snapshot.
  const brief: ResearchBrief | null = useMemo(() => {
    if (activeRun?.brief) return activeRun.brief;
    if (snapshot?.brief) return snapshot.brief;
    return null;
  }, [activeRun?.brief, snapshot]);

  const provenance = brief?.provenance ?? [];
  // Map provenance by agent, fall back to "no_data" when agent missing.
  const provenanceByAgent = useMemo(() => {
    const map = new Map<AgentName, (typeof provenance)[number]>();
    for (const p of provenance) map.set(p.agent, p);
    return map;
  }, [provenance]);

  async function handleRerun() {
    if (!symbol || rerunning) return;
    setRerunning(true);
    try {
      const res = await researchApi.startResearchRun({
        symbol,
        prompt: `Refresh research brief for ${symbol}`,
      });
      startRun({ runId: res.run_id, symbol, prompt: `Refresh research brief for ${symbol}` });
    } finally {
      setRerunning(false);
    }
  }

  const card: React.CSSProperties = {
    background: t.bgCardGradient,
    border: `1px solid ${t.borderPrimary}`,
    borderRadius: 16,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <PageHeader
        icon={<Brain size={16} />}
        title={symbol || 'Symbol'}
        subtitle="Per-symbol research · filings, fundamentals, technicals, peers, macro"
        actions={
          <button
            type="button"
            onClick={handleRerun}
            disabled={rerunning}
            style={{
              all: 'unset',
              cursor: rerunning ? 'not-allowed' : 'pointer',
              padding: '8px 14px',
              borderRadius: 10,
              fontSize: 12,
              fontWeight: 600,
              color: t.textPrimary,
              background: t.bgMuted,
              border: `1px solid ${t.borderPrimary}`,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <RefreshCw size={12} className={rerunning ? 'spin' : undefined} aria-hidden />
            {rerunning ? 'Starting…' : 'Re-run'}
          </button>
        }
      />

      <RefusalBanner compact />

      {snapshot ? (
        <div
          style={{
            ...card,
            padding: '10px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12,
            color: t.textMuted,
          }}
        >
          <Clock size={12} aria-hidden />
          Snapshot generated {new Date(snapshot.generated_at).toLocaleString()}
          {snapshot.stale ? (
            <span
              style={{
                marginLeft: 8,
                fontSize: 10,
                padding: '2px 8px',
                borderRadius: 999,
                fontWeight: 700,
                color: t.warn as string,
                background: t.warnSoft as string,
              }}
            >
              STALE
            </span>
          ) : null}
        </div>
      ) : loadingSnapshot ? (
        <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>Checking snapshot…</p>
      ) : null}

      <div style={{ ...card, padding: 20 }}>
        <BriefViewer
          brief={brief}
          streaming={
            activeRun?.streamingState === 'streaming'
            || activeRun?.streamingState === 'starting'
          }
        />
      </div>

      <div style={{ ...card, padding: 20 }}>
        <h3
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 700,
            color: t.textPrimary,
            marginBottom: 12,
          }}
        >
          Agent traces
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {ALL_AGENTS.map((agent) => {
            const p = provenanceByAgent.get(agent);
            if (p) {
              return <AgentCard key={agent} result={p} />;
            }
            if (!brief) return null;
            return <NoDataState key={agent} agent={agent} />;
          })}
        </div>
      </div>
    </div>
  );
}
