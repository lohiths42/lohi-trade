/**
 * `/research/filings` — Filings reader.
 *
 * Browseable archive of every document Lohi-Research has ingested for the
 * user: BSE/NSE announcements, annual reports, concall transcripts,
 * investor decks, uploaded PDFs. A sidebar lists filings filtered by
 * symbol and/or document type. Selecting a row opens an in-pane reader
 * that renders the document's canonical text with section anchors.
 *
 * Quartr-style: two-pane editorial layout, monochrome, hairline rules,
 * serif reading surface on the right.
 */

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FileText, Search, UploadCloud } from 'lucide-react';
import { Link } from 'react-router-dom';
import { researchApi } from '../../lib/research-api';
import type {
  FilingChunk,
  FilingDocument,
  FilingDocumentType,
} from '../../lib/research-ideas-types';

const TYPE_LABELS: Record<FilingDocumentType, string> = {
  announcement: 'Announcements',
  annual_report: 'Annual reports',
  concall: 'Concalls',
  shareholding: 'Shareholding',
  ir_deck: 'IR decks',
  user_upload: 'Uploads',
};

const TYPE_ORDER: FilingDocumentType[] = [
  'announcement',
  'annual_report',
  'concall',
  'shareholding',
  'ir_deck',
  'user_upload',
];

export default function ResearchFilingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const symbolFilter = (searchParams.get('symbol') ?? '').toUpperCase();
  const typeFilter = searchParams.get('type') as FilingDocumentType | null;
  const selectedId = searchParams.get('id');

  const [filings, setFilings] = useState<FilingDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [chunks, setChunks] = useState<FilingChunk[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [symbolInput, setSymbolInput] = useState(symbolFilter);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    researchApi
      .listFilings({
        symbol: symbolFilter || undefined,
        documentType: typeFilter || undefined,
        limit: 100,
      })
      .then((items) => {
        if (alive) setFilings(items);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [symbolFilter, typeFilter]);

  useEffect(() => {
    if (!selectedId) {
      setChunks([]);
      return;
    }
    let alive = true;
    setLoadingChunks(true);
    researchApi
      .getFilingChunks(selectedId)
      .then((c) => {
        if (alive) setChunks(c);
      })
      .finally(() => {
        if (alive) setLoadingChunks(false);
      });
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const selected = useMemo(
    () => filings.find((f) => f.document_id === selectedId) ?? null,
    [filings, selectedId],
  );

  function applySymbol(sym: string) {
    const next = new URLSearchParams(searchParams);
    const up = sym.trim().toUpperCase();
    if (up) next.set('symbol', up);
    else next.delete('symbol');
    next.delete('id');
    setSearchParams(next);
  }

  function applyType(type: FilingDocumentType | null) {
    const next = new URLSearchParams(searchParams);
    if (type) next.set('type', type);
    else next.delete('type');
    next.delete('id');
    setSearchParams(next);
  }

  function selectFiling(doc: FilingDocument) {
    const next = new URLSearchParams(searchParams);
    next.set('id', doc.document_id);
    setSearchParams(next);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, height: '100%' }}>
      {/* Header */}
      <header
        style={{
          paddingBottom: 16,
          borderBottom: '1px solid var(--line-3)',
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <p className="qr-kicker" style={{ margin: 0 }}>
            Workspace
          </p>
          <h1 className="qr-headline" style={{ margin: '6px 0 8px' }}>
            Filings
          </h1>
          <p
            className="qr-body qr-body--lg"
            style={{ margin: 0, maxWidth: 640 }}
          >
            Every document Lohi Research has ingested for you — concalls, annual reports,
            announcements, and uploads. Filter by symbol or type, then open any filing
            to read the canonical text.
          </p>
        </div>
        <Link to="/research/filings/upload" className="qr-btn qr-btn--ghost">
          <UploadCloud size={13} />
          Upload filing
        </Link>
      </header>

      {/* Two-pane layout */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '380px 1fr',
          gap: 24,
          flex: 1,
          minHeight: 0,
        }}
      >
        {/* Sidebar */}
        <aside
          style={{
            borderRight: '1px solid var(--line-3)',
            paddingRight: 20,
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
          }}
        >
          {/* Symbol filter */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              borderBottom: '1px solid var(--line-2)',
              paddingBottom: 10,
            }}
          >
            <Search size={13} color="var(--fg-muted)" />
            <input
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applySymbol(symbolInput);
              }}
              onBlur={() => applySymbol(symbolInput)}
              placeholder="Filter by symbol"
              className="qr-input"
              style={{ border: 0, padding: 0, fontSize: 13 }}
            />
            {symbolFilter && (
              <button
                onClick={() => {
                  setSymbolInput('');
                  applySymbol('');
                }}
                className="qr-kicker"
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                  color: 'var(--fg-muted)',
                }}
                aria-label="Clear symbol filter"
              >
                Clear
              </button>
            )}
          </div>

          {/* Type filter */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 6,
              padding: '12px 0',
              borderBottom: '1px solid var(--line-2)',
            }}
          >
            <Chip
              label="All"
              active={!typeFilter}
              onClick={() => applyType(null)}
            />
            {TYPE_ORDER.map((k) => (
              <Chip
                key={k}
                label={TYPE_LABELS[k]}
                active={typeFilter === k}
                onClick={() => applyType(k)}
              />
            ))}
          </div>

          {/* Filings list */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              minHeight: 0,
            }}
          >
            {loading ? (
              <p style={{ fontSize: 12, color: 'var(--fg-muted)', margin: '14px 0' }}>
                Loading filings…
              </p>
            ) : filings.length === 0 ? (
              <div
                style={{
                  padding: '32px 8px',
                  textAlign: 'center',
                  color: 'var(--fg-muted)',
                }}
              >
                <FileText
                  size={24}
                  style={{ margin: '0 auto 8px', opacity: 0.5 }}
                />
                <p style={{ fontSize: 13, margin: 0 }}>
                  No filings match. Try clearing the filters or uploading a document.
                </p>
              </div>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {filings.map((f) => (
                  <FilingRow
                    key={f.document_id}
                    doc={f}
                    active={f.document_id === selectedId}
                    onClick={() => selectFiling(f)}
                  />
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Reader pane */}
        <section
          style={{
            overflowY: 'auto',
            minHeight: 0,
            paddingRight: 4,
          }}
        >
          {!selected ? (
            <EmptyReader />
          ) : (
            <FilingReader
              doc={selected}
              chunks={chunks}
              loadingChunks={loadingChunks}
            />
          )}
        </section>
      </div>
    </div>
  );
}

// ─── Sidebar row ──────────────────────────────────────────────────────────

function FilingRow({
  doc,
  active,
  onClick,
}: {
  doc: FilingDocument;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        style={{
          all: 'unset',
          cursor: 'pointer',
          width: '100%',
          padding: '12px 10px',
          borderBottom: '1px solid var(--line-2)',
          display: 'block',
          background: active ? 'var(--surface-3)' : 'transparent',
          borderLeft: active
            ? '3px solid var(--fg-primary)'
            : '3px solid transparent',
          transition: 'background var(--dur-2) var(--ease-out)',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 4,
          }}
        >
          <span
            className="qr-tabular"
            style={{
              fontSize: 11,
              fontWeight: 800,
              color: 'var(--fg-primary)',
            }}
          >
            {doc.symbol}
          </span>
          <span className="qr-kicker" style={{ margin: 0 }}>
            {TYPE_LABELS[doc.document_type] ?? doc.document_type}
          </span>
        </div>
        <p
          className="qr-serif"
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 500,
            lineHeight: 1.3,
            color: 'var(--fg-primary)',
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {doc.title}
        </p>
        <p
          className="qr-kicker qr-tabular"
          style={{ margin: '6px 0 0', color: 'var(--fg-muted)' }}
        >
          {doc.published_at
            ? new Date(doc.published_at).toLocaleDateString()
            : new Date(doc.parsed_at).toLocaleDateString()}
          {' · '}
          {doc.page_count} pages
        </p>
      </button>
    </li>
  );
}

// ─── Reader pane ──────────────────────────────────────────────────────────

function EmptyReader() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        minHeight: 300,
        color: 'var(--fg-muted)',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <FileText size={26} style={{ margin: '0 auto 10px', opacity: 0.5 }} />
        <p className="qr-serif" style={{ margin: 0, fontSize: 16 }}>
          Select a filing to read
        </p>
      </div>
    </div>
  );
}

function FilingReader({
  doc,
  chunks,
  loadingChunks,
}: {
  doc: FilingDocument;
  chunks: FilingChunk[];
  loadingChunks: boolean;
}) {
  const body = useMemo(() => {
    if (chunks.length === 0) return doc.preview;
    return chunks
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((c) => c.text)
      .join('\n\n');
  }, [chunks, doc.preview]);

  return (
    <article style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ paddingBottom: 14, borderBottom: '1px solid var(--line-3)' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
          <span className="qr-tag">{TYPE_LABELS[doc.document_type]}</span>
          <span
            className="qr-tabular qr-tag"
            style={{ fontWeight: 800 }}
          >
            {doc.symbol}
          </span>
        </div>
        <h2
          className="qr-serif"
          style={{
            margin: 0,
            fontSize: 26,
            fontWeight: 500,
            lineHeight: 1.2,
            color: 'var(--fg-primary)',
          }}
        >
          {doc.title}
        </h2>
        <p
          className="qr-kicker qr-tabular"
          style={{ margin: '10px 0 0', color: 'var(--fg-muted)' }}
        >
          {doc.published_at
            ? `Published ${new Date(doc.published_at).toLocaleString()}`
            : `Parsed ${new Date(doc.parsed_at).toLocaleString()}`}
          {' · '}
          {doc.page_count} pages · {doc.chunk_count} chunks
        </p>
        {doc.source_url && (
          <p style={{ margin: '8px 0 0' }}>
            <a
              href={doc.source_url}
              target="_blank"
              rel="noreferrer"
              className="qr-link"
            >
              Source document
            </a>
          </p>
        )}
      </header>

      {/* Section anchors */}
      {doc.sections.length > 0 && (
        <nav
          aria-label="Document sections"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 10,
            padding: '10px 0',
            borderBottom: '1px solid var(--line-2)',
          }}
        >
          <span className="qr-kicker" style={{ alignSelf: 'center', margin: 0 }}>
            Sections:
          </span>
          {doc.sections.map((s) => (
            <span key={`${s.name}-${s.start_offset}`} className="qr-tag">
              {s.name.replace('_', ' ')}
            </span>
          ))}
        </nav>
      )}

      {/* Canonical text body */}
      <div
        className="qr-serif"
        style={{
          fontSize: 16,
          lineHeight: 1.72,
          color: 'var(--fg-primary)',
          whiteSpace: 'pre-wrap',
          maxWidth: 720,
        }}
      >
        {loadingChunks ? (
          <p style={{ color: 'var(--fg-muted)', fontSize: 13 }}>Loading document…</p>
        ) : (
          body
        )}
      </div>
    </article>
  );
}

// ─── Chip (shared) ────────────────────────────────────────────────────────

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
        padding: '4px 10px',
        borderRadius: 999,
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: '0.08em',
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
