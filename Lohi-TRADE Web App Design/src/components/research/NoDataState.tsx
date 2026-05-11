/**
 * `NoDataState` — explicit "No data available for <agent>" rendering.
 *
 * Surfaced when a Sub_Agent returned `kind: 'no_data'` (Req 1.3, Req 6.7).
 * Matches the muted card style used elsewhere in the dashboard so the
 * absence of data reads as intentional rather than broken.
 *
 * Task 17.10 — Requirements: 6.7, 1.3, design §3.13.
 */

import { Inbox } from 'lucide-react';
import type { AgentName } from '../../lib/research-types';
import { useThemeColors } from '../../hooks/use-theme-colors';

const AGENT_LABEL: Record<AgentName, string> = {
  filings: 'Filings',
  fundamentals: 'Fundamentals',
  news_sentiment: 'News & Sentiment',
  technicals: 'Technicals',
  peer_sector: 'Peer & Sector',
  macro: 'Macro',
  synthesizer: 'Report Synthesizer',
};

export interface NoDataStateProps {
  agent: AgentName;
  /** Optional reason surfaced by the Sub_Agent. */
  reason?: string | null;
}

export default function NoDataState({ agent, reason }: NoDataStateProps) {
  const t = useThemeColors();
  const label = AGENT_LABEL[agent] ?? agent;
  return (
    <div
      role="status"
      aria-label={`No data available for ${label}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '16px 20px',
        borderRadius: 12,
        border: `1px dashed ${t.borderPrimary}`,
        background: t.bgMuted,
        color: t.textMuted,
      }}
    >
      <Inbox size={18} aria-hidden />
      <div style={{ minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: t.textSecondary }}>
          No data available for {label}
        </p>
        {reason ? (
          <p style={{ margin: '2px 0 0', fontSize: 11, color: t.textMuted }}>{reason}</p>
        ) : null}
      </div>
    </div>
  );
}
