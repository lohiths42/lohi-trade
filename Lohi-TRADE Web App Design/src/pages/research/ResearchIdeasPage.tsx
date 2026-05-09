/**
 * `/research/ideas` — ResearchIdeasPage.
 *
 * Quartr-style editorial feed of AI-synthesised stock ideas. Monochrome
 * tiles separated by hairline rules, not cards. A chip row at the top
 * filters the archetype cohort.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lightbulb } from 'lucide-react';
import { researchApi } from '../../lib/research-api';
import {
  SECTOR_META,
  type Sector,
  type StockArchetype,
  type StockIdea,
} from '../../lib/research-ideas-types';

const ARCHETYPES: { key: StockArchetype; label: string }[] = [
  { key: 'compounder', label: 'Compounders' },
  { key: 'value', label: 'Value' },
  { key: 'growth', label: 'Growth' },
  { key: 'cyclical', label: 'Cyclical' },
  { key: 'turnaround', label: 'Turnaround' },
  { key: 'special_situation', label: 'Special Sit.' },
  { key: 'dividend', label: 'Dividend' },
];

const SECTOR_FILTER_KEYS: Sector[] = [
  'financials',
  'information_technology',
  'healthcare',
  'consumer_staples',
  'consumer_discretionary',
  'industrials',
  'energy',
  'materials',
];

export default function ResearchIdeasPage() {
  const navigate = useNavigate();
  const [ideas, setIdeas] = useState<StockIdea[]>([]);
  const [filter, setFilter] = useState<StockArchetype | 'all'>('all');
  const [sectorFilter, setSectorFilter] = useState<Sector | 'all'>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    researchApi
      .listResearchIdeas()
      .then((i) => { if (alive) setIdeas(i); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const filtered = useMemo(() => {
    let out = ideas;
    if (filter !== 'all') out = out.filter((i) => i.archetype === filter);
    if (sectorFilter !== 'all') out = out.filter((i) => i.sector === sectorFilter);
    return out;
  }, [ideas, filter, sectorFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <header
        style={{
          paddingBottom: 20,
          borderBottom: '1px solid var(--line-3)',
        }}
      >
        <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
          Edge · Feed
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0 10px' }}>
          Ideas
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 720 }}>
          Cited investment hypotheses, filtered by archetype. Promoted only when the Judge
          clears groundedness ≥ 0.7 and conviction ≥ 0.5. No price targets. No buy/sell
          calls. You see the thesis; you decide.
        </p>
      </header>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="qr-kicker" style={{ margin: 0, marginRight: 4 }}>
            Archetype
          </span>
          <Chip label="All" active={filter === 'all'} onClick={() => setFilter('all')} />
          {ARCHETYPES.map((a) => (
            <Chip
              key={a.key}
              label={a.label}
              active={filter === a.key}
              onClick={() => setFilter(a.key)}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="qr-kicker" style={{ margin: 0, marginRight: 4 }}>
            Sector
          </span>
          <Chip
            label="All"
            active={sectorFilter === 'all'}
            onClick={() => setSectorFilter('all')}
          />
          {SECTOR_FILTER_KEYS.map((s) => (
            <Chip
              key={s}
              label={SECTOR_META[s].short}
              active={sectorFilter === s}
              onClick={() => setSectorFilter(s)}
            />
          ))}
        </div>
      </div>

      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading ideas…</p>
      ) : filtered.length === 0 ? (
        <section
          style={{
            padding: 40,
            textAlign: 'center',
            borderTop: '1px solid var(--line-3)',
            borderBottom: '1px solid var(--line-3)',
          }}
        >
          <Lightbulb size={28} color="var(--fg-muted)" style={{ margin: '0 auto 10px' }} />
          <h3 className="qr-serif" style={{ margin: '0 0 6px', fontSize: 18, fontWeight: 500 }}>
            No ideas in this bucket yet
          </h3>
          <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: 0 }}>
            Ideas are promoted automatically as Judge-approved briefs land.
          </p>
        </section>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {filtered.map((idea) => (
            <IdeaRow
              key={idea.idea_id}
              idea={idea}
              onOpen={() => navigate(`/research/${idea.symbol}`)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      style={{
        all: 'unset',
        cursor: 'pointer',
        padding: '6px 14px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        color: active ? 'var(--surface-2)' : 'var(--fg-primary)',
        background: active ? 'var(--fg-primary)' : 'transparent',
        border: `1px solid ${active ? 'var(--fg-primary)' : 'var(--line-3)'}`,
        transition: 'all var(--dur-2) var(--ease-out)',
      }}
    >
      {label}
    </button>
  );
}

function IdeaRow({ idea, onOpen }: { idea: StockIdea; onOpen: () => void }) {
  return (
    <li
      onClick={onOpen}
      className="qr-tile"
      style={{
        cursor: 'pointer',
        display: 'grid',
        gridTemplateColumns: '80px 1fr 120px',
        gap: 20,
        alignItems: 'start',
      }}
    >
      {/* Symbol column */}
      <div>
        <p
          className="qr-tabular"
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 800,
            color: 'var(--fg-primary)',
          }}
        >
          {idea.symbol}
        </p>
        <p className="qr-kicker" style={{ margin: '4px 0 0' }}>
          {idea.archetype.replace('_', ' ')}
        </p>
        <p
          className="qr-kicker"
          style={{ margin: '2px 0 0', color: 'var(--fg-subtle)' }}
        >
          {SECTOR_META[idea.sector]?.short ?? 'Other'}
        </p>
      </div>

      {/* Thesis column */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
          {idea.direction !== 'neutral' && (
            <span
              className={
                idea.direction === 'bullish'
                  ? 'qr-tag qr-tag--bull'
                  : 'qr-tag qr-tag--bear'
              }
            >
              {idea.direction}
            </span>
          )}
          {idea.tags.slice(0, 3).map((t) => (
            <span key={t} className="qr-tag">
              {t}
            </span>
          ))}
        </div>
        <h3
          className="qr-serif"
          style={{
            margin: 0,
            fontSize: 20,
            fontWeight: 500,
            lineHeight: 1.22,
            color: 'var(--fg-primary)',
          }}
        >
          {idea.headline}
        </h3>
        <p
          className="qr-body"
          style={{
            margin: '8px 0 12px',
            maxWidth: 640,
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {idea.thesis_short}
        </p>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            maxWidth: 360,
          }}
        >
          <div className="qr-meter" aria-hidden style={{ flex: 1 }}>
            <span style={{ width: `${Math.max(0, Math.min(100, idea.conviction * 100))}%` }} />
          </div>
          <span
            className="qr-kicker"
            style={{ margin: 0 }}
          >
            {idea.conviction_band}
          </span>
        </div>
      </div>

      {/* Conviction column */}
      <div style={{ textAlign: 'right' }}>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Conviction
        </p>
        <p
          className="qr-tabular"
          style={{
            margin: '4px 0 0',
            fontSize: 40,
            fontWeight: 600,
            color: 'var(--fg-primary)',
            lineHeight: 1,
            letterSpacing: '-0.02em',
          }}
        >
          {Math.round(idea.conviction * 100)}
        </p>
        <p className="qr-kicker" style={{ margin: '6px 0 0' }}>
          {idea.key_citations.length} citations
        </p>
      </div>
    </li>
  );
}
