/**
 * `JudgeVerifyingBadge` — transient "verifying…" pill that transitions to
 * pass/fail once a `research:judge_report` event arrives.
 *
 * Three states:
 *   - `'verifying'` — Judge is running asynchronously (Req 15.8)
 *   - `'pass'`     — `safe_to_display=true`
 *   - `'fail'`     — `safe_to_display=false`
 *
 * Task 17.9 — Requirements: 15.8, design §3.13, §11.3.
 */

import { Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import type { JudgeReport } from '../../lib/research-types';
import { useThemeColors } from '../../hooks/use-theme-colors';

export interface JudgeVerifyingBadgeProps {
  /** `true` when the brief carries `judge_pending: true`. */
  pending: boolean;
  /** Latest judge report; `null` while pending. */
  report?: JudgeReport | null;
}

export default function JudgeVerifyingBadge({ pending, report }: JudgeVerifyingBadgeProps) {
  const t = useThemeColors();

  if (pending && !report) {
    return (
      <span
        data-testid="judge-verifying"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '3px 10px',
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
          color: t.textSecondary,
          background: t.bgMuted,
          border: `1px solid ${t.borderPrimary}`,
        }}
      >
        <Loader2 size={12} className="spin" aria-hidden />
        Verifying…
      </span>
    );
  }

  if (report && report.safe_to_display) {
    const scores = Object.values(report.groundedness_score ?? {});
    const min = scores.length ? Math.min(...scores) : 0;
    return (
      <span
        data-testid="judge-pass"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '3px 10px',
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
          color: t.bull as string,
          background: t.bullSoft as string,
          border: `1px solid ${t.bull}`,
        }}
      >
        <CheckCircle2 size={12} aria-hidden />
        Verified · {(min * 100).toFixed(0)}%
      </span>
    );
  }

  if (report && !report.safe_to_display) {
    return (
      <span
        data-testid="judge-fail"
        title={
          report.unsupported_claims.length
            ? `${report.unsupported_claims.length} unsupported claim(s)`
            : undefined
        }
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '3px 10px',
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
          color: t.warn as string,
          background: t.warnSoft as string,
          border: `1px solid ${t.warn}`,
        }}
      >
        <AlertTriangle size={12} aria-hidden />
        Unverified
      </span>
    );
  }

  return null;
}
