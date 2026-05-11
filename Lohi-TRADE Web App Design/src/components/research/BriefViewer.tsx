/**
 * `BriefViewer` — renders a `ResearchBrief` section-by-section with inline
 * citation markers that open a `CitationDrawer` on click.
 *
 * Section text contains `[cite:<chunk_id>]` markers produced by the
 * Report_Synthesizer. `renderSectionWithCitations` splits the text around
 * those markers and replaces each with a clickable `<button>` so citation
 * click-through works uniformly across sections.
 *
 * Task 17.6 — Requirements: 6.2, 6.5, design §3.13.
 */

import { useMemo, useState } from 'react';
import { FileText } from 'lucide-react';
import type { Citation, ResearchBrief } from '../../lib/research-types';
import { useThemeColors } from '../../hooks/use-theme-colors';
import CitationDrawer from './CitationDrawer';
import JudgeVerifyingBadge from './JudgeVerifyingBadge';

export interface BriefViewerProps {
  brief: ResearchBrief | null;
  /**
   * When `true`, renders a "streaming…" indicator beneath the title.
   * Partial sections are shown verbatim; missing sections render as empty.
   */
  streaming?: boolean;
  /** Optional handler invoked whenever a citation is clicked (for tests). */
  onCitationClick?: (citation: Citation) => void;
}

interface Section {
  key: keyof ResearchBrief;
  label: string;
}

const SECTIONS: Section[] = [
  { key: 'summary', label: 'Summary' },
  { key: 'thesis', label: 'Thesis' },
  { key: 'risks', label: 'Risks' },
  { key: 'financial_highlights', label: 'Financial Highlights' },
  { key: 'management_commentary', label: 'Management Commentary' },
  { key: 'technical_view', label: 'Technical View' },
  { key: 'peers', label: 'Peers' },
  { key: 'macro_context', label: 'Macro Context' },
];

const CITE_REGEX = /\[cite:([^\]]+)\]/g;

/**
 * Split section text around `[cite:<chunk_id>]` markers, producing an
 * interleaved list of plain-text and citation tokens.
 * Exported for use by property tests.
 */
export interface TextToken {
  kind: 'text';
  text: string;
}
export interface CiteToken {
  kind: 'cite';
  chunkId: string;
}
export type RenderToken = TextToken | CiteToken;

export function tokenizeSection(text: string): RenderToken[] {
  const tokens: RenderToken[] = [];
  let lastIndex = 0;
  // Reset regex state between calls — it's a module-level object.
  CITE_REGEX.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = CITE_REGEX.exec(text)) !== null) {
    if (m.index > lastIndex) {
      tokens.push({ kind: 'text', text: text.slice(lastIndex, m.index) });
    }
    tokens.push({ kind: 'cite', chunkId: m[1] });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    tokens.push({ kind: 'text', text: text.slice(lastIndex) });
  }
  return tokens;
}

export default function BriefViewer({
  brief,
  streaming = false,
  onCitationClick,
}: BriefViewerProps) {
  const t = useThemeColors();
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);

  // Build a chunk_id -> Citation lookup once per brief.
  const citationsById = useMemo(() => {
    const map = new Map<string, Citation>();
    if (brief?.citations) {
      for (const c of brief.citations) {
        if (c && typeof c.chunk_id === 'string') map.set(c.chunk_id, c);
      }
    }
    return map;
  }, [brief]);

  const handleCitationClick = (chunkId: string) => {
    const citation = citationsById.get(chunkId);
    // Synthesise a minimal Citation if the chunk_id isn't present in the
    // accumulated citations list yet. This keeps the drawer clickable during
    // streaming — the chunk text can still be fetched later.
    const resolved: Citation = citation ?? {
      chunk_id: chunkId,
      document_id: '',
      source_url: null,
      start_offset: 0,
      end_offset: 0,
    };
    setOpenCitation(resolved);
    onCitationClick?.(resolved);
  };

  if (!brief) {
    return (
      <div
        style={{
          padding: 24,
          borderRadius: 16,
          border: `1px dashed ${t.borderPrimary}`,
          background: t.bgMuted,
          color: t.textMuted,
          fontSize: 13,
          textAlign: 'center',
        }}
      >
        No brief yet. Start a research run to see sections appear here.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <FileText size={18} color={t.textSecondary as string} aria-hidden />
          <div style={{ minWidth: 0 }}>
            <h2
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 700,
                color: t.textPrimary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {brief.symbol ? `${brief.symbol} — Research Brief` : 'Research Brief'}
            </h2>
            <p style={{ margin: '2px 0 0', fontSize: 11, color: t.textMuted }}>
              {streaming ? 'Streaming…' : brief.partial ? 'Partial brief' : 'Complete'} ·{' '}
              {brief.citations.length} citation{brief.citations.length === 1 ? '' : 's'}
            </p>
          </div>
        </div>
        <JudgeVerifyingBadge pending={brief.judge_pending} report={brief.judge} />
      </header>

      {brief.quality === 'low' ? (
        <div
          role="alert"
          style={{
            padding: '10px 14px',
            borderRadius: 10,
            fontSize: 12,
            color: t.warn as string,
            background: t.warnSoft as string,
            border: `1px solid ${t.warn}`,
          }}
        >
          Quality: low — some sections were labelled "insufficient evidence" after a
          second Judge failure.
        </div>
      ) : null}

      {brief.budget_exhausted ? (
        <div
          role="alert"
          style={{
            padding: '10px 14px',
            borderRadius: 10,
            fontSize: 12,
            color: t.warn as string,
            background: t.warnSoft as string,
            border: `1px solid ${t.warn}`,
          }}
        >
          Token budget exhausted — brief returned partial.
        </div>
      ) : null}

      {SECTIONS.map((section) => {
        const raw = (brief[section.key] as string | undefined) ?? '';
        if (!raw.trim()) return null;
        const tokens = tokenizeSection(raw);
        return (
          <section
            key={section.key}
            data-testid={`brief-section-${section.key}`}
            style={{
              padding: '16px 18px',
              borderRadius: 12,
              border: `1px solid ${t.borderPrimary}`,
              background: t.bgCard,
            }}
          >
            <h3
              style={{
                margin: '0 0 10px',
                fontSize: 13,
                fontWeight: 700,
                color: t.textPrimary,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {section.label}
            </h3>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                lineHeight: 1.6,
                color: t.textSecondary,
                whiteSpace: 'pre-wrap',
              }}
            >
              {tokens.map((tok, i) =>
                tok.kind === 'text' ? (
                  <span key={i}>{tok.text}</span>
                ) : (
                  <CitationPill
                    key={i}
                    chunkId={tok.chunkId}
                    onClick={() => handleCitationClick(tok.chunkId)}
                  />
                ),
              )}
            </p>
          </section>
        );
      })}

      <CitationDrawer citation={openCitation} onClose={() => setOpenCitation(null)} />
    </div>
  );
}

function CitationPill({ chunkId, onClick }: { chunkId: string; onClick: () => void }) {
  const t = useThemeColors();
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="citation-pill"
      data-chunk-id={chunkId}
      aria-label={`Citation ${chunkId}`}
      style={{
        all: 'unset',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        padding: '0 6px',
        margin: '0 2px',
        borderRadius: 4,
        fontSize: 10,
        fontFamily: 'ui-monospace, monospace',
        fontWeight: 600,
        color: t.accentText,
        background: t.accentBg,
        border: `1px solid color-mix(in srgb, ${t.accentText} 30%, transparent)`,
        verticalAlign: 'baseline',
      }}
    >
      [{chunkId.slice(0, 8)}]
    </button>
  );
}
