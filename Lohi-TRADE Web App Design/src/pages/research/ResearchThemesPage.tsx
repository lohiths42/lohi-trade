/**
 * `/research/themes` — ResearchThemesPage.
 *
 * Merged thematic research, Quartr-style: black-and-white chrome, hairline
 * separators, serif editorial body. The composer lets you drop a cohort
 * of tickers; the AI router classifies each, fans out, and produces a
 * cross-cited cohort-level report.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Loader2, Plus } from 'lucide-react';
import { researchApi } from '../../lib/research-api';
import type {
  StockArchetype,
  ThemeReport,
} from '../../lib/research-ideas-types';

const ARCHETYPE_HINTS: StockArchetype[] = [
  'compounder',
  'value',
  'growth',
  'cyclical',
  'turnaround',
  'special_situation',
  'dividend',
];

export default function ResearchThemesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('id');
  const navigate = useNavigate();

  const [themes, setThemes] = useState<ThemeReport[]>([]);
  const [loading, setLoading] = useState(true);

  const [title, setTitle] = useState('');
  const [symbolsInput, setSymbolsInput] = useState('');
  const [archetypeHint, setArchetypeHint] = useState<StockArchetype | ''>('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    researchApi
      .listResearchThemes()
      .then((t) => { if (alive) setThemes(t); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const selectedTheme = useMemo(
    () => (selectedId ? themes.find((t) => t.theme_id === selectedId) ?? null : null),
    [themes, selectedId],
  );

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const symbols = symbolsInput
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!title.trim() || symbols.length < 2) {
      setError('Give the theme a title and at least 2 symbols.');
      return;
    }
    setSubmitting(true);
    try {
      await researchApi.generateResearchTheme({
        title: title.trim(),
        symbols,
        archetype_hint: archetypeHint || undefined,
      });
      setTitle('');
      setSymbolsInput('');
      setArchetypeHint('');
      setTimeout(async () => {
        const refreshed = await researchApi.listResearchThemes();
        setThemes(refreshed);
      }, 1200);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start theme generation.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
      <header
        style={{
          paddingBottom: 20,
          borderBottom: '1px solid var(--line-3)',
        }}
      >
        <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
          Edge · Cohort
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0' }}>
          Themes
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 760 }}>
          Merge multiple symbols into a single editorial thesis. The AI router classifies
          each ticker, runs per-symbol briefs in parallel, and stitches the outputs into one
          cohort-level report, cross-cited end to end.
        </p>
      </header>

      {selectedTheme ? (
        <ThemeDetail
          theme={selectedTheme}
          onBack={() => setSearchParams({})}
          onOpenSymbol={(s) => navigate(`/research/${s}`)}
        />
      ) : (
        <>
          {/* Composer */}
          <form
            onSubmit={handleGenerate}
            style={{
              padding: '24px 0',
              borderBottom: '1px solid var(--line-3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 14,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Plus size={14} />
              <h3
                className="qr-serif"
                style={{ margin: 0, fontSize: 18, fontWeight: 500 }}
              >
                Compose a new theme
              </h3>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '2fr 3fr', gap: 20 }}>
              <div>
                <p className="qr-kicker" style={{ margin: '0 0 4px' }}>
                  Title
                </p>
                <input
                  placeholder="India defence capex cycle"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="qr-input"
                />
              </div>
              <div>
                <p className="qr-kicker" style={{ margin: '0 0 4px' }}>
                  Symbols (comma or space)
                </p>
                <input
                  placeholder="HAL BEL DATAPATTNS BDL MIDHANI"
                  value={symbolsInput}
                  onChange={(e) => setSymbolsInput(e.target.value)}
                  className="qr-input"
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="qr-kicker" style={{ margin: 0 }}>
                Archetype hint
              </span>
              <Chip
                active={archetypeHint === ''}
                label="Auto"
                onClick={() => setArchetypeHint('')}
              />
              {ARCHETYPE_HINTS.map((a) => (
                <Chip
                  key={a}
                  active={archetypeHint === a}
                  label={a.replace('_', ' ')}
                  onClick={() => setArchetypeHint(a)}
                />
              ))}
            </div>

            {error && (
              <p style={{ margin: 0, fontSize: 12, color: 'var(--warn)' }}>{error}</p>
            )}

            <div>
              <button type="submit" disabled={submitting} className="qr-btn">
                {submitting ? <Loader2 size={13} className="spin" /> : null}
                {submitting ? 'Generating' : 'Generate theme'}
                {!submitting && <ArrowRight size={13} />}
              </button>
            </div>
          </form>

          <section>
            <div
              style={{
                paddingBottom: 14,
                borderBottom: '1px solid var(--line-3)',
                marginBottom: 4,
              }}
            >
              <p className="qr-kicker" style={{ margin: 0 }}>
                Archive
              </p>
              <h2
                className="qr-serif"
                style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 500 }}
              >
                Published themes
              </h2>
            </div>
            {loading ? (
              <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '20px 0' }}>
                Loading…
              </p>
            ) : themes.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--fg-muted)', margin: '20px 0' }}>
                No themes yet. Compose one above to produce a cohort editorial.
              </p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {themes.map((th) => (
                  <ThemeRow
                    key={th.theme_id}
                    theme={th}
                    onOpen={() => setSearchParams({ id: th.theme_id })}
                  />
                ))}
              </ul>
            )}
          </section>
        </>
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
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        all: 'unset',
        cursor: 'pointer',
        padding: '5px 12px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        color: active ? 'var(--surface-2)' : 'var(--fg-primary)',
        background: active ? 'var(--fg-primary)' : 'transparent',
        border: `1px solid ${active ? 'var(--fg-primary)' : 'var(--line-3)'}`,
      }}
    >
      {label}
    </button>
  );
}

function ThemeRow({
  theme,
  onOpen,
}: {
  theme: ThemeReport;
  onOpen: () => void;
}) {
  return (
    <li
      onClick={onOpen}
      className="qr-tile"
      style={{
        cursor: 'pointer',
        display: 'grid',
        gridTemplateColumns: '120px 1fr auto',
        gap: 20,
        alignItems: 'start',
      }}
    >
      <div>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Cohort
        </p>
        <p
          className="qr-tabular"
          style={{
            margin: '4px 0 0',
            fontSize: 14,
            fontWeight: 700,
            color: 'var(--fg-primary)',
          }}
        >
          {theme.members.length} companies
        </p>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
          {theme.archetypes.slice(0, 3).map((a) => (
            <span key={a} className="qr-tag">
              {a.replace('_', ' ')}
            </span>
          ))}
        </div>
        <h3
          className="qr-serif"
          style={{
            margin: 0,
            fontSize: 22,
            fontWeight: 500,
            lineHeight: 1.2,
            color: 'var(--fg-primary)',
          }}
        >
          {theme.title}
        </h3>
        <p
          className="qr-body"
          style={{
            margin: '8px 0 10px',
            maxWidth: 640,
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {theme.summary}
        </p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {theme.members.slice(0, 6).map((m) => (
            <span
              key={m.symbol}
              className="qr-tabular"
              style={{
                fontSize: 11,
                fontWeight: 700,
                padding: '2px 8px',
                color: 'var(--fg-secondary)',
                border: '1px solid var(--line-2)',
                borderRadius: 2,
              }}
            >
              {m.symbol}
            </span>
          ))}
          {theme.members.length > 6 && (
            <span className="qr-kicker" style={{ alignSelf: 'center', margin: 0 }}>
              +{theme.members.length - 6} more
            </span>
          )}
        </div>
      </div>
      <ArrowRight size={16} color="var(--fg-muted)" style={{ marginTop: 6 }} />
    </li>
  );
}

function ThemeDetail({
  theme,
  onBack,
  onOpenSymbol,
}: {
  theme: ThemeReport;
  onBack: () => void;
  onOpenSymbol: (sym: string) => void;
}) {
  return (
    <article style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <button onClick={onBack} className="qr-link" style={{ alignSelf: 'flex-start' }}>
        ← All themes
      </button>

      <header style={{ borderBottom: '1px solid var(--line-3)', paddingBottom: 20 }}>
        <p className="qr-kicker qr-kicker--edge" style={{ margin: 0 }}>
          Edge · Cohort
        </p>
        <h2
          className="qr-display"
          style={{ margin: '12px 0 10px', maxWidth: 900 }}
        >
          {theme.title}
        </h2>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 720 }}>
          {theme.summary}
        </p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 14 }}>
          {theme.archetypes.map((a) => (
            <span key={a} className="qr-tag">
              {a.replace('_', ' ')}
            </span>
          ))}
        </div>
      </header>

      {/* Long-form report body */}
      <section
        className="qr-serif"
        style={{
          fontSize: 17,
          lineHeight: 1.72,
          color: 'var(--fg-primary)',
          whiteSpace: 'pre-wrap',
          maxWidth: 720,
          columnGap: 40,
        }}
      >
        {theme.report_md}
      </section>

      <hr className="qr-rule" />

      <section>
        <div
          style={{
            paddingBottom: 14,
            borderBottom: '1px solid var(--line-3)',
            marginBottom: 4,
          }}
        >
          <p className="qr-kicker" style={{ margin: 0 }}>
            Cohort members
          </p>
          <h3
            className="qr-serif"
            style={{ margin: '4px 0 0', fontSize: 20, fontWeight: 500 }}
          >
            {theme.members.length} companies
          </h3>
        </div>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {theme.members.map((m) => (
            <li
              key={m.symbol}
              onClick={() => onOpenSymbol(m.symbol)}
              className="qr-tile"
              style={{
                cursor: 'pointer',
                display: 'grid',
                gridTemplateColumns: '120px 1fr 80px 40px',
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
              <div className="qr-meter" aria-hidden>
                <span style={{ width: `${Math.max(0, Math.min(100, m.conviction * 100))}%` }} />
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

      <p className="qr-kicker" style={{ textAlign: 'right' }}>
        {theme.citations.length} citations · updated {new Date(theme.updated_at).toLocaleString()}
      </p>
    </article>
  );
}
