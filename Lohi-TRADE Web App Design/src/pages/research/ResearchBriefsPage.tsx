/**
 * `/research/briefs` — long-form archive of every Research_Brief in Quartr
 * editorial style: hairline rows, serif headlines, wide-tracked kickers.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { researchApi } from '../../lib/research-api';
import type { ResearchRunSummary } from '../../lib/research-types';

export default function ResearchBriefsPage() {
  const [runs, setRuns] = useState<ResearchRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    researchApi
      .listResearchRuns()
      .then((r) => { if (alive) setRuns(r); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ paddingBottom: 20, borderBottom: '1px solid var(--line-3)' }}>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Archive
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0' }}>
          Briefs
        </h1>
        <p className="qr-body qr-body--lg" style={{ margin: 0, maxWidth: 640 }}>
          Every cited brief you have produced, newest first. Click through to re-read or
          continue the conversation in chat.
        </p>
      </header>

      {loading ? (
        <p style={{ fontSize: 12, color: 'var(--fg-muted)' }}>Loading briefs…</p>
      ) : runs.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          No briefs yet. Start one from the dashboard masthead.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {runs.map((r) => (
            <li
              key={r.run_id}
              onClick={() =>
                navigate(r.symbol ? `/research/${r.symbol}` : '/research/chat')
              }
              className="qr-tile"
              style={{
                cursor: 'pointer',
                display: 'grid',
                gridTemplateColumns: '100px 1fr 140px auto',
                gap: 20,
                alignItems: 'start',
              }}
            >
              <div>
                {r.symbol && (
                  <p
                    className="qr-tabular"
                    style={{
                      margin: 0,
                      fontSize: 14,
                      fontWeight: 800,
                      color: 'var(--fg-primary)',
                    }}
                  >
                    {r.symbol}
                  </p>
                )}
                <p className="qr-kicker" style={{ margin: r.symbol ? '4px 0 0' : 0 }}>
                  {r.status}
                  {r.partial ? ' · partial' : ''}
                  {r.quality === 'low' ? ' · low quality' : ''}
                </p>
              </div>
              <h3
                className="qr-serif"
                style={{
                  margin: 0,
                  fontSize: 18,
                  fontWeight: 500,
                  lineHeight: 1.3,
                  color: 'var(--fg-primary)',
                  overflow: 'hidden',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {r.prompt}
              </h3>
              <p
                className="qr-kicker qr-tabular"
                style={{ margin: 0, textAlign: 'right' }}
              >
                {new Date(r.created_at).toLocaleDateString()}
              </p>
              <ArrowRight size={14} color="var(--fg-muted)" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
