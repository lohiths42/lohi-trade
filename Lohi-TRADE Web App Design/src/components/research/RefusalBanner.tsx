/**
 * `RefusalBanner` — user-visible summary of the Refusal_Policy.
 *
 * Rendered at the top of the `/research` shell and on every refusal so users
 * always know what Lohi-Research will and will not do. Matches the
 * `docs/research/REFUSAL_POLICY.md` content at the summary level.
 *
 * Task 17.11 — Requirements: 16.29, design §3.13, §10.1.
 */

import { ShieldAlert } from 'lucide-react';
import { useThemeColors } from '../../hooks/use-theme-colors';

export interface RefusalBannerProps {
  /**
   * When `true`, renders the compact "policy reminder" variant shown on
   * every research page. When `false` (the default), renders the fuller
   * "this request was refused" variant with a highlighted border.
   */
  compact?: boolean;
  /** Optional refusal message surfaced alongside the policy summary. */
  message?: string;
}

const REFUSAL_ITEMS = [
  'Buy, sell, or hold recommendations',
  'Price targets',
  'Specific trade suggestions',
  'Order placement or fund transfers',
  'Code execution on your behalf',
];

export default function RefusalBanner({ compact = true, message }: RefusalBannerProps) {
  const t = useThemeColors();
  const borderColor = compact ? t.borderPrimary : t.warn;
  const bg = compact ? t.bgMuted : `color-mix(in srgb, ${t.warn} 8%, transparent)`;

  return (
    <div
      role="note"
      aria-label="Lohi-Research refusal policy"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        padding: compact ? '10px 14px' : '14px 18px',
        borderRadius: 12,
        border: `1px solid ${borderColor}`,
        background: bg,
      }}
    >
      <ShieldAlert
        size={compact ? 16 : 18}
        color={compact ? (t.textMuted as string) : (t.warn as string)}
        aria-hidden
        style={{ flexShrink: 0, marginTop: 1 }}
      />
      <div style={{ minWidth: 0 }}>
        <p
          style={{
            margin: 0,
            fontSize: compact ? 12 : 13,
            fontWeight: 600,
            color: t.textSecondary,
          }}
        >
          {compact
            ? 'Lohi-Research is a research tool, not a trading advisor.'
            : 'Request refused per the Lohi-Research refusal policy.'}
        </p>
        {message ? (
          <p style={{ margin: '4px 0 0', fontSize: 12, color: t.textMuted }}>{message}</p>
        ) : null}
        <p style={{ margin: '6px 0 0', fontSize: 11, color: t.textMuted }}>
          It will refuse:
        </p>
        <ul
          style={{
            margin: '4px 0 0',
            paddingLeft: 18,
            fontSize: 11,
            color: t.textMuted,
            lineHeight: 1.5,
          }}
        >
          {REFUSAL_ITEMS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
