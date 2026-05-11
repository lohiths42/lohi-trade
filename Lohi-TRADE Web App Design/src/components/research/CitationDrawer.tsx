/**
 * `CitationDrawer` — right-side panel that opens when a citation marker
 * is clicked inside a `BriefViewer`.
 *
 * Behaviour (Req 6.6):
 *   - When the citation carries a `source_url`, the drawer links out to
 *     the source (opening the document at the chunk's character offset if
 *     the backend supports it).
 *   - When `source_url` is null, the drawer displays the chunk text.
 *
 * The component is deliberately lightweight — no shadcn portal wrapper —
 * to match the existing modal convention used throughout the app.
 *
 * Task 17.7 — Requirements: 6.6, design §3.13.
 */

import { useEffect } from 'react';
import { X, ExternalLink } from 'lucide-react';
import type { Citation } from '../../lib/research-types';
import { useThemeColors } from '../../hooks/use-theme-colors';

export interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export default function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  const t = useThemeColors();
  const open = citation !== null;

  // Close on Escape for accessibility.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!citation) return null;

  const sourceUrl = citation.source_url
    ? buildSourceUrl(citation)
    : null;

  return (
    <div
      data-testid="citation-drawer"
      role="dialog"
      aria-modal="true"
      aria-label={`Citation ${citation.chunk_id}`}
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        background: t.bgOverlay,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(480px, 92vw)',
          height: '100%',
          background: t.bgCard,
          borderLeft: `1px solid ${t.borderPrimary}`,
          boxShadow: t.cardShadow,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 18px',
            borderBottom: `1px solid ${t.borderSubtle}`,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                fontWeight: 700,
                color: t.textPrimary,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              data-testid="citation-chunk-id"
            >
              {citation.chunk_id}
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 11, color: t.textMuted }}>
              Offsets {citation.start_offset}–{citation.end_offset}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close citation"
            style={{
              all: 'unset',
              cursor: 'pointer',
              padding: 6,
              borderRadius: 8,
              color: t.textMuted,
            }}
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        <div
          style={{
            flex: 1,
            padding: '16px 18px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          {sourceUrl ? (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer noopener"
              data-testid="citation-source-link"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                fontWeight: 600,
                color: t.accentText,
                textDecoration: 'none',
                padding: '8px 12px',
                borderRadius: 8,
                background: t.accentBg,
                width: 'fit-content',
              }}
            >
              <ExternalLink size={12} aria-hidden />
              Open source document
            </a>
          ) : null}

          {citation.chunk_text ? (
            <div>
              <p
                style={{
                  margin: '0 0 6px',
                  fontSize: 10,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: t.textMuted,
                  fontWeight: 700,
                }}
              >
                Chunk text
              </p>
              <div
                data-testid="citation-chunk-text"
                style={{
                  padding: 12,
                  borderRadius: 10,
                  background: t.bgMuted,
                  color: t.textSecondary,
                  fontSize: 12,
                  lineHeight: 1.6,
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'ui-monospace, monospace',
                }}
              >
                {citation.chunk_text}
              </div>
            </div>
          ) : !sourceUrl ? (
            <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>
              No source URL available and chunk text was not inlined in this citation.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/**
 * Build a canonical link to the source document. When the document host
 * supports fragment offsets (`#:~:text=…`) we could encode them here.
 * For now we just return the original URL; the chunk offset is shown in
 * the drawer header so users can locate it manually.
 */
function buildSourceUrl(citation: Citation): string | null {
  if (!citation.source_url) return null;
  return citation.source_url;
}
