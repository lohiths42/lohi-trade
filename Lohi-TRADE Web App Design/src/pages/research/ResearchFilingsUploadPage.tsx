/**
 * `/research/filings/upload` — Upload surface (moved from the old
 * ResearchFilingsPage when Filings became a browseable reader).
 *
 * Quartr-style form: dashed drop-zone rule, underline inputs, monochrome
 * call-to-action.
 */

import { useState } from 'react';
import { ArrowRight, Loader2, UploadCloud } from 'lucide-react';
import { researchApi } from '../../lib/research-api';

export default function ResearchFilingsUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [symbol, setSymbol] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError('Pick a PDF to upload.');
      return;
    }
    if (!symbol.trim()) {
      setError('Attach a symbol so we can route retrieval properly.');
      return;
    }
    setError(null);
    setSubmitting(true);
    const form = new FormData();
    form.append('file', file);
    form.append('symbol', symbol.trim().toUpperCase());
    try {
      const res = await researchApi.uploadResearchDocument(form);
      setResult(`Uploaded. document_id=${res.document_id}`);
      setFile(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ paddingBottom: 20, borderBottom: '1px solid var(--line-3)' }}>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Workspace
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0' }}>
          Upload a filing
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0 }}>
          Add a concall deck, annual report, or company presentation. Everything you
          upload is chunked, embedded, and scoped to your account — nothing is shared with
          other users, nothing leaves your configured providers.
        </p>
      </header>

      <form
        onSubmit={handleUpload}
        style={{ display: 'flex', flexDirection: 'column', gap: 18 }}
      >
        <div>
          <p className="qr-kicker" style={{ margin: '0 0 4px' }}>
            Symbol
          </p>
          <input
            aria-label="Symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE"
            className="qr-input"
          />
        </div>

        <label
          style={{
            padding: 40,
            borderRadius: 2,
            border: '1.5px dashed var(--line-3)',
            background: 'var(--surface-3)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            textAlign: 'center',
          }}
        >
          <UploadCloud size={26} color="var(--fg-muted)" />
          <p
            className="qr-serif"
            style={{
              margin: '12px 0 6px',
              fontSize: 17,
              fontWeight: 500,
              color: 'var(--fg-primary)',
            }}
          >
            {file ? file.name : 'Drop a PDF here, or click to pick one'}
          </p>
          <p className="qr-kicker" style={{ margin: 0 }}>
            PDF · up to 25 MB · tables preserved
          </p>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ display: 'none' }}
          />
        </label>

        {error && <p style={{ margin: 0, fontSize: 12, color: 'var(--warn)' }}>{error}</p>}
        {result && <p style={{ margin: 0, fontSize: 12, color: 'var(--bull)' }}>{result}</p>}

        <div>
          <button type="submit" disabled={submitting} className="qr-btn">
            {submitting ? <Loader2 size={13} className="spin" /> : null}
            {submitting ? 'Uploading' : 'Upload'}
            {!submitting && <ArrowRight size={13} />}
          </button>
        </div>
      </form>
    </div>
  );
}
