/**
 * `/research/sectors` — Sector discovery page.
 *
 * The auto-grouped counterpart to the archetype-grouped Themes page.
 * The backend classifier assigns every covered symbol to a `Sector`, then
 * publishes one `SectorCluster` per populated sector. This page surfaces
 * those clusters as a grid:
 *
 *   • A sector tile shows aggregate bias, member count, and a "View /
 *     Regenerate" action.
 *   • Opening a sector drills into a detail view that either renders the
 *     currently-published Theme (merged editorial across the cohort) or
 *     kicks off regeneration.
 *
 * This is the "pharma companies combined together" surface — it gives you
 * pharma, banks, IT, etc. as first-class cohorts with a single cited
 * editorial across all members.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Loader2, RefreshCw } from 'lucide-react';
import { researchApi } from '../../lib/research-api';
import {
  SECTOR_META,
  type Sector,
  type SectorCluster,
  type ThemeReport,
} from '../../lib/research-ideas-types';

export default function ResearchSectorsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSector = (searchParams.get('sector') as Sector | null) ?? null;
  const navigate = useNavigate();

  const [clusters, setClusters] = useState<SectorCluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [themeById, setThemeById] = useState<Record<string, ThemeReport>>({});
  const [regenerating, setRegenerating] = useState<Sector | null>(null);

  useEffect(() => {
    let alive = true;
    researchApi
      .listSectorClusters()
      .then((c) => {
        if (alive) setClusters(c);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // When a sector is selected, load its published theme if one exists.
  useEffect(() => {
    if (!selectedSector) return;
    const cluster = clusters.find((c) => c.sector === selectedSector);
    if (!cluster?.theme_id) return;
    if (themeById[cluster.theme_id]) return;
    researchApi
      .getResearchTheme(cluster.theme_id)
      .then((t) => {
        if (t) setThemeById((prev) => ({ ...prev, [t.theme_id]: t }));
      })
      .catch(() => void 0);
  }, [selectedSector, clusters, themeById]);

  const selectedCluster = useMemo(
    () => clusters.find((c) => c.sector === selectedSector) ?? null,
    [selectedSector, clusters],
  );

  async function regenerate(sector: Sector) {
    setRegenerating(sector);
    try {
      await researchApi.generateSectorTheme(sector);
      // Wait briefly and refresh the list so the new theme surfaces.
      setTimeout(async () => {
        const fresh = await researchApi.listSectorClusters();
        setClusters(fresh);
      }, 1400);
    } finally {
      setRegenerating(null);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────

  if (selectedSector && selectedCluster) {
    const theme = selectedCluster.theme_id
      ? themeById[selectedCluster.theme_id] ?? null
      : null;
    return (
      <SectorDetail
        cluster={selectedCluster}
        theme={theme}
        onBack={() => setSearchParams({})}
        onOpenSymbol={(sym) => navigate(`/research/${sym}`)}
        onRegenerate={() => regenerate(selectedCluster.sector)}
        regenerating={regenerating === selectedCluster.sector}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <header style={{ paddingBottom: 20, borderBottom: '1px solid var(--line-3)' }}>
        <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
          Edge · Sectors
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0' }}>
          Sectors
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 760 }}>
          Every covered symbol is auto-classified and merged into a sector cohort.
          Pharma companies are combined with pharma; banks with banks. Each sector is a
          single cited editorial drawn from every constituent's brief.
        </p>
      </header>

      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading sectors…</p>
      ) : clusters.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          No sector coverage yet. Add symbols to your watchlist and run a few briefs;
          sectors will populate as the classifier builds conviction.
        </p>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 0,
            borderTop: '1px solid var(--line-3)',
            borderLeft: '1px solid var(--line-3)',
          }}
        >
          {clusters.map((cluster) => (
            <SectorTile
              key={cluster.sector}
              cluster={cluster}
              onOpen={() => setSearchParams({ sector: cluster.sector })}
              onRegenerate={() => regenerate(cluster.sector)}
              regenerating={regenerating === cluster.sector}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Sector tile (grid cell) ───────────────────────────────────────────────

function SectorTile({
  cluster,
  onOpen,
  onRegenerate,
  regenerating,
}: {
  cluster: SectorCluster;
  onOpen: () => void;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  const meta = SECTOR_META[cluster.sector];
  const biasPct = Math.max(-100, Math.min(100, Math.round(cluster.bias * 100)));
  const biasColor =
    biasPct > 5
      ? 'var(--bull)'
      : biasPct < -5
        ? 'var(--bear)'
        : 'var(--fg-muted)';

  return (
    <article
      onClick={onOpen}
      style={{
        padding: '24px 20px',
        background: 'var(--surface-2)',
        borderRight: '1px solid var(--line-3)',
        borderBottom: '1px solid var(--line-3)',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        cursor: 'pointer',
        minHeight: 200,
        transition: 'background var(--dur-2) var(--ease-out)',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-3)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--surface-2)')}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <p className="qr-kicker" style={{ margin: 0 }}>
            {meta.short}
          </p>
          <h3
            className="qr-serif"
            style={{
              margin: '4px 0 0',
              fontSize: 20,
              fontWeight: 500,
              color: 'var(--fg-primary)',
              lineHeight: 1.22,
            }}
          >
            {meta.label}
          </h3>
        </div>
        <span
          className="qr-tabular"
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: 'var(--fg-primary)',
            letterSpacing: '-0.01em',
          }}
        >
          {cluster.members.length}
        </span>
      </div>

      {/* Bias bar */}
      <div>
        <p className="qr-kicker" style={{ margin: '0 0 6px' }}>
          Aggregate bias
        </p>
        <div
          aria-hidden
          style={{
            height: 2,
            background: 'var(--line-2)',
            position: 'relative',
          }}
        >
          {/* Center marker */}
          <span
            style={{
              position: 'absolute',
              left: '50%',
              top: -3,
              width: 1,
              height: 8,
              background: 'var(--line-3)',
            }}
          />
          <span
            style={{
              position: 'absolute',
              left: biasPct >= 0 ? '50%' : `${50 + biasPct / 2}%`,
              top: 0,
              bottom: 0,
              width: `${Math.abs(biasPct) / 2}%`,
              background: biasColor,
            }}
          />
        </div>
        <p
          className="qr-tabular"
          style={{
            margin: '6px 0 0',
            fontSize: 12,
            fontWeight: 600,
            color: biasColor,
          }}
        >
          {biasPct > 0 ? '+' : ''}
          {biasPct}%
        </p>
      </div>

      {/* Member preview */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {cluster.members.slice(0, 6).map((m) => (
          <span
            key={m.symbol}
            className="qr-tabular"
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 7px',
              border: '1px solid var(--line-2)',
              color: 'var(--fg-secondary)',
              borderRadius: 2,
            }}
          >
            {m.symbol}
          </span>
        ))}
        {cluster.members.length > 6 && (
          <span
            className="qr-kicker"
            style={{ alignSelf: 'center', margin: 0 }}
          >
            +{cluster.members.length - 6}
          </span>
        )}
      </div>

      {/* Footer row */}
      <div
        style={{
          marginTop: 'auto',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
        }}
      >
        {cluster.theme_id ? (
          <span className="qr-tag qr-tag--edge">Theme ready</span>
        ) : (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRegenerate();
            }}
            disabled={regenerating}
            className="qr-btn qr-btn--ghost"
            style={{ padding: '6px 10px', fontSize: 11 }}
          >
            {regenerating ? (
              <Loader2 size={11} className="spin" />
            ) : (
              <RefreshCw size={11} />
            )}
            {regenerating ? 'Generating' : 'Generate'}
          </button>
        )}
        <ArrowRight size={14} color="var(--fg-muted)" />
      </div>
    </article>
  );
}

// ─── Sector detail view ────────────────────────────────────────────────────

function SectorDetail({
  cluster,
  theme,
  onBack,
  onOpenSymbol,
  onRegenerate,
  regenerating,
}: {
  cluster: SectorCluster;
  theme: ThemeReport | null;
  onBack: () => void;
  onOpenSymbol: (sym: string) => void;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  const meta = SECTOR_META[cluster.sector];
  const biasPct = Math.max(-100, Math.min(100, Math.round(cluster.bias * 100)));
  const biasColor =
    biasPct > 5
      ? 'var(--bull)'
      : biasPct < -5
        ? 'var(--bear)'
        : 'var(--fg-muted)';

  return (
    <article style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <button onClick={onBack} className="qr-link" style={{ alignSelf: 'flex-start' }}>
        ← All sectors
      </button>

      <header
        style={{
          paddingBottom: 20,
          borderBottom: '1px solid var(--line-3)',
          display: 'flex',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
            Edge · Sectors · {meta.short}
          </p>
          <h2
            className="qr-display"
            style={{ margin: '12px 0 10px', maxWidth: 900 }}
          >
            {meta.label}
          </h2>
          {theme?.summary ? (
            <p
              className="qr-body qr-body--lg"
              style={{ margin: 0, maxWidth: 760 }}
            >
              {theme.summary}
            </p>
          ) : (
            <p
              className="qr-body qr-body--lg"
              style={{ margin: 0, maxWidth: 760, color: 'var(--fg-muted)' }}
            >
              No editorial yet for {meta.label.toLowerCase()}. Generate the cohort theme
              to merge every constituent brief into one cited report.
            </p>
          )}
        </div>
        <button
          onClick={onRegenerate}
          disabled={regenerating}
          className="qr-btn"
          style={{ flexShrink: 0 }}
        >
          {regenerating ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
          {regenerating ? 'Regenerating' : theme ? 'Regenerate' : 'Generate theme'}
        </button>
      </header>

      {/* Stats strip */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          borderTop: '1px solid var(--line-2)',
          borderBottom: '1px solid var(--line-2)',
        }}
      >
        <Stat label="Constituents" value={String(cluster.members.length)} />
        <Stat
          label="Aggregate bias"
          value={`${biasPct > 0 ? '+' : ''}${biasPct}%`}
          color={biasColor}
          border
        />
        <Stat
          label="Last refreshed"
          value={new Date(cluster.updated_at).toLocaleDateString()}
          border
        />
      </section>

      {/* Long-form report body */}
      {theme ? (
        <section
          className="qr-serif"
          style={{
            fontSize: 17,
            lineHeight: 1.74,
            color: 'var(--fg-primary)',
            whiteSpace: 'pre-wrap',
            maxWidth: 720,
          }}
        >
          {theme.report_md}
        </section>
      ) : null}

      <hr className="qr-rule" />

      {/* Constituents list */}
      <section>
        <div
          style={{
            paddingBottom: 14,
            borderBottom: '1px solid var(--line-3)',
            marginBottom: 4,
          }}
        >
          <p className="qr-kicker" style={{ margin: 0 }}>
            Cohort
          </p>
          <h3
            className="qr-serif"
            style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
          >
            {cluster.members.length} companies
          </h3>
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {cluster.members.map((m) => (
            <li
              key={m.symbol}
              onClick={() => onOpenSymbol(m.symbol)}
              className="qr-tile"
              style={{
                cursor: 'pointer',
                display: 'grid',
                gridTemplateColumns: '140px 1fr 120px 80px 40px',
                gap: 20,
                alignItems: 'center',
              }}
            >
              <span
                className="qr-tabular"
                style={{
                  fontSize: 14,
                  fontWeight: 800,
                  color: 'var(--fg-primary)',
                }}
              >
                {m.symbol}
              </span>
              <span className="qr-tag" style={{ justifySelf: 'start' }}>
                {m.archetype.replace('_', ' ')}
              </span>
              <div className="qr-meter" aria-hidden>
                <span
                  style={{
                    width: `${Math.max(0, Math.min(100, m.conviction * 100))}%`,
                  }}
                />
              </div>
              <span
                className="qr-tabular"
                style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg-primary)' }}
              >
                {Math.round(m.conviction * 100)}
              </span>
              <span
                className="qr-kicker"
                style={{ margin: 0, textAlign: 'right' }}
              >
                {m.direction}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}

function Stat({
  label,
  value,
  color,
  border,
}: {
  label: string;
  value: string;
  color?: string;
  border?: boolean;
}) {
  return (
    <div
      style={{
        padding: '16px 20px',
        borderLeft: border ? '1px solid var(--line-2)' : undefined,
      }}
    >
      <p className="qr-kicker" style={{ margin: 0 }}>
        {label}
      </p>
      <p
        className="qr-tabular"
        style={{
          margin: '6px 0 0',
          fontSize: 22,
          fontWeight: 600,
          color: color ?? 'var(--fg-primary)',
          letterSpacing: '-0.015em',
        }}
      >
        {value}
      </p>
    </div>
  );
}
