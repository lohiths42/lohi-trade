/**
 * `AgentCard` — collapsible per-Sub_Agent trace card.
 *
 * Shows agent name, (optionally) inputs and retrieved chunks, wall time,
 * and input/output token counts. Rendered once per `AgentResult` surfaced
 * on the chat and symbol pages so users can audit every tool call.
 *
 * Task 17.8 — Requirements: 6.3, design §3.13.
 */

import { useState, useId } from 'react';
import { ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import type { AgentResult } from '../../lib/research-types';
import { useThemeColors } from '../../hooks/use-theme-colors';
import NoDataState from './NoDataState';

const AGENT_LABEL: Record<AgentResult['agent'], string> = {
  filings: 'Filings Agent',
  fundamentals: 'Fundamentals Agent',
  news_sentiment: 'News & Sentiment Agent',
  technicals: 'Technicals Agent',
  peer_sector: 'Peer & Sector Agent',
  macro: 'Macro Agent',
  synthesizer: 'Report Synthesizer',
};

export interface AgentCardProps {
  result: AgentResult;
  /** Initial open/closed state. Defaults to closed to keep the page tidy. */
  defaultOpen?: boolean;
}

export default function AgentCard({ result, defaultOpen = false }: AgentCardProps) {
  const t = useThemeColors();
  const [open, setOpen] = useState<boolean>(defaultOpen);
  const panelId = useId();

  const isError = result.kind === 'error';
  const isNoData = result.kind === 'no_data';

  return (
    <div
      style={{
        border: `1px solid ${t.borderPrimary}`,
        borderRadius: 12,
        background: t.bgCard,
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        style={{
          all: 'unset',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          width: '100%',
          padding: '12px 16px',
          cursor: 'pointer',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          {open ? (
            <ChevronDown size={14} color={t.textMuted as string} aria-hidden />
          ) : (
            <ChevronRight size={14} color={t.textMuted as string} aria-hidden />
          )}
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: t.textPrimary,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {AGENT_LABEL[result.agent]}
          </span>
          {isError ? (
            <AlertTriangle size={12} color={t.warn as string} aria-hidden />
          ) : null}
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 11,
            color: t.textMuted,
            fontFamily: 'ui-monospace, monospace',
            flexShrink: 0,
          }}
        >
          <span title="Input / output tokens">
            {result.input_tokens}→{result.output_tokens}
          </span>
          <span title="Wall time">{result.wall_time_ms} ms</span>
        </div>
      </button>

      {open ? (
        <div
          id={panelId}
          style={{
            borderTop: `1px solid ${t.borderSubtle}`,
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          {isNoData ? (
            <NoDataState agent={result.agent} reason={result.reason} />
          ) : (
            <>
              {result.inputs && Object.keys(result.inputs).length > 0 ? (
                <Section title="Inputs" t={t}>
                  <pre
                    style={{
                      margin: 0,
                      padding: 10,
                      borderRadius: 8,
                      background: t.bgMuted,
                      color: t.textSecondary,
                      fontSize: 11,
                      fontFamily: 'ui-monospace, monospace',
                      overflowX: 'auto',
                    }}
                  >
                    {JSON.stringify(result.inputs, null, 2)}
                  </pre>
                </Section>
              ) : null}

              {result.retrieved_chunks && result.retrieved_chunks.length > 0 ? (
                <Section title={`Retrieved (${result.retrieved_chunks.length})`} t={t}>
                  <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none' }}>
                    {result.retrieved_chunks.slice(0, 8).map((c) => (
                      <li
                        key={c.chunk_id}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '4px 0',
                          fontSize: 11,
                          color: t.textSecondary,
                          fontFamily: 'ui-monospace, monospace',
                          borderBottom: `1px solid ${t.borderSubtle}`,
                        }}
                      >
                        <span
                          style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            maxWidth: '70%',
                          }}
                        >
                          {c.chunk_id}
                        </span>
                        <span style={{ color: t.textMuted }}>{c.score.toFixed(3)}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              ) : null}

              {result.content_md ? (
                <Section title="Output" t={t}>
                  <div
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      background: t.bgMuted,
                      color: t.textSecondary,
                      fontSize: 12,
                      lineHeight: 1.5,
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {result.content_md}
                  </div>
                </Section>
              ) : null}

              {isError ? (
                <div
                  role="alert"
                  style={{
                    padding: 10,
                    borderRadius: 8,
                    fontSize: 12,
                    color: t.warn as string,
                    background: t.warnSoft as string,
                    border: `1px solid ${t.warn}`,
                  }}
                >
                  {result.reason ?? 'Agent raised an exception.'}
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Section({
  title,
  t,
  children,
}: {
  title: string;
  t: ReturnType<typeof useThemeColors>;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p
        style={{
          margin: '0 0 6px',
          fontSize: 10,
          textTransform: 'uppercase',
          fontWeight: 700,
          letterSpacing: '0.05em',
          color: t.textMuted,
        }}
      >
        {title}
      </p>
      {children}
    </div>
  );
}
