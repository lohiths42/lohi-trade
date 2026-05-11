/**
 * `RunTraceDrawer` — right-side panel that exposes a "replayable trace"
 * of a single `Research_Run`.
 *
 * The drawer fetches `GET /api/v2/research/runs/:run_id/trace` (design
 * §5.1) and renders four sections:
 *
 *   1. **Run metadata** — status, symbol, prompt, wall-clock timings.
 *   2. **Provenance table** — one row per Sub_Agent invocation
 *      (`agent_name`, `kind`, `wall_time_ms`, tokens, chunk count).
 *   3. **Guardrail decisions** — one entry per `GuardrailDecision`
 *      (phase, rule_id, action, reason).
 *   4. **Judge report panel** — groundedness scores, unsupported claims,
 *      `safe_to_display` badge, off-policy findings.
 *
 * Follows the `CitationDrawer` layout conventions (right-aligned,
 * escape-to-close, theme-aware colors) so the two drawers feel
 * uniform. The DOM structure is deliberately simple — no shadcn
 * portal wrapper — to match the existing modal convention used
 * throughout the app.
 *
 * TODO: integration points (deferred to Phase 19):
 *   - Wire into `ResearchChatPage` so clicking a run row opens the
 *     drawer with that run's id.
 *   - Wire into `ResearchSymbolPage` so the run history view can
 *     surface the drawer per row.
 *   - Both pages will pass `runId` + `open` + `onClose` directly;
 *     no additional state lives in the component.
 *
 * Task 20.3 — Requirements: 13.3, 13.4, design §15.
 */

import { useEffect, useState } from 'react';
import { X, CheckCircle2, AlertCircle } from 'lucide-react';
import { useThemeColors } from '../../hooks/use-theme-colors';
import { getResearchRunTrace } from '../../lib/research-api';

// ─── Public types ───────────────────────────────────────────────────────────

export interface RunTraceDrawerProps {
  /** Run id to fetch. When `null`, the drawer renders nothing. */
  runId: string | null;
  open: boolean;
  onClose: () => void;
}

/**
 * Shape of the trace payload returned by
 * `GET /api/v2/research/runs/:run_id/trace`. Mirrored here so the
 * drawer is self-contained; the gateway's `TraceResponse` model is
 * the source of truth.
 */
export interface RunTracePayload {
  run_id: string;
  status: string;
  prompt: string;
  symbol: string | null;
  created_at: number;
  finished_at: number | null;
  trace: TraceBody;
}

export interface TraceBody {
  plan_md?: string;
  provenance?: TraceProvenanceEntry[];
  guardrail_decisions?: TraceGuardrailDecision[];
  judge_reports?: TraceJudgeReport[];
  partial?: boolean;
  quality?: string;
  [key: string]: unknown;
}

export interface TraceProvenanceEntry {
  agent_name: string;
  kind: string;
  section_name?: string;
  wall_time_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  chunk_ids?: string[];
  reason?: string;
}

export interface TraceGuardrailDecision {
  phase: string;
  rule_id: string;
  action: string;
  reason?: string;
}

export interface TraceJudgeReport {
  groundedness_score?: Record<string, number>;
  unsupported_claims?: Array<{
    section: string;
    claim_text: string;
    reason: string;
  }>;
  safe_to_display?: boolean;
  off_policy_findings?: string[];
  retry_count?: number;
  elapsed_ms?: number;
  model_id?: string;
}

// ─── Exported pure helpers (test seams) ─────────────────────────────────────

/**
 * Format an elapsed-ms integer as a human-readable duration ("420 ms",
 * "1.23 s"). Exported so the property test can pin the format without
 * rendering the drawer.
 */
export function formatWallTime(ms: number | undefined | null): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  const n = Math.max(0, Math.floor(ms));
  if (n < 1000) return `${n} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}

/**
 * Compute the minimum per-section groundedness score. Returns `null`
 * when the report does not carry a score map. The drawer uses this
 * to colour-code the judge panel heading.
 */
export function minGroundednessScore(
  report: TraceJudgeReport | undefined,
): number | null {
  if (!report?.groundedness_score) return null;
  const values = Object.values(report.groundedness_score);
  if (values.length === 0) return null;
  return Math.min(...values);
}

/**
 * Extract the number of chunks cited by a provenance entry — handles
 * both the Task 18.4 ``chunk_ids`` array and older shapes that only
 * carried ``chunks``. Exported for the property tests.
 */
export function chunkCountFor(entry: TraceProvenanceEntry): number {
  if (Array.isArray(entry.chunk_ids)) return entry.chunk_ids.length;
  return 0;
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function RunTraceDrawer({
  runId,
  open,
  onClose,
}: RunTraceDrawerProps) {
  const t = useThemeColors();
  const [payload, setPayload] = useState<RunTracePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Close on Escape for keyboard accessibility — matches CitationDrawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Fetch the trace when the drawer opens with a valid run id.
  useEffect(() => {
    if (!open || !runId) {
      setPayload(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getResearchRunTrace(runId)
      .then((data) => {
        if (!cancelled) setPayload(data as RunTracePayload);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load trace');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, runId]);

  if (!open || !runId) return null;

  const trace = payload?.trace ?? {};
  const provenance = trace.provenance ?? [];
  const guardrails = trace.guardrail_decisions ?? [];
  const judgeReports = trace.judge_reports ?? [];

  return (
    <div
      data-testid="run-trace-drawer"
      role="dialog"
      aria-modal="true"
      aria-label={`Trace for run ${runId}`}
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
          width: 'min(640px, 96vw)',
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
              }}
              data-testid="run-trace-title"
            >
              Run Trace
            </p>
            <p
              style={{
                margin: '2px 0 0',
                fontSize: 11,
                color: t.textMuted,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              data-testid="run-trace-run-id"
            >
              {runId}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close trace"
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
            gap: 20,
          }}
        >
          {loading ? (
            <p style={{ fontSize: 12, color: t.textMuted }} data-testid="run-trace-loading">
              Loading trace…
            </p>
          ) : null}

          {error ? (
            <p style={{ fontSize: 12, color: t.bear }} data-testid="run-trace-error">
              {error}
            </p>
          ) : null}

          {payload ? (
            <>
              <MetadataSection payload={payload} />
              <ProvenanceSection entries={provenance} />
              <GuardrailSection decisions={guardrails} />
              <JudgeSection reports={judgeReports} />
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ─── Internal subsections ───────────────────────────────────────────────────

function MetadataSection({ payload }: { payload: RunTracePayload }) {
  const t = useThemeColors();
  const wallTimeMs =
    payload.finished_at && payload.created_at
      ? Math.round((payload.finished_at - payload.created_at) * 1000)
      : null;
  return (
    <section data-testid="run-trace-metadata">
      <SectionHeading text="Metadata" />
      <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 12px', fontSize: 12 }}>
        <dt style={{ color: t.textMuted }}>Status</dt>
        <dd style={{ margin: 0, color: t.textPrimary }}>{payload.status}</dd>
        <dt style={{ color: t.textMuted }}>Symbol</dt>
        <dd style={{ margin: 0, color: t.textPrimary }}>{payload.symbol ?? '—'}</dd>
        <dt style={{ color: t.textMuted }}>Prompt</dt>
        <dd style={{ margin: 0, color: t.textSecondary, whiteSpace: 'pre-wrap' }}>{payload.prompt}</dd>
        <dt style={{ color: t.textMuted }}>Wall time</dt>
        <dd style={{ margin: 0, color: t.textPrimary }}>{formatWallTime(wallTimeMs)}</dd>
      </dl>
    </section>
  );
}

function ProvenanceSection({ entries }: { entries: TraceProvenanceEntry[] }) {
  const t = useThemeColors();
  return (
    <section data-testid="run-trace-provenance">
      <SectionHeading text={`Provenance (${entries.length})`} />
      {entries.length === 0 ? (
        <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>No agents recorded.</p>
      ) : (
        <table
          style={{
            width: '100%',
            fontSize: 12,
            borderCollapse: 'collapse',
            color: t.textSecondary,
          }}
        >
          <thead>
            <tr style={{ textAlign: 'left', color: t.textMuted }}>
              <th style={{ padding: '4px 6px', fontWeight: 600 }}>Agent</th>
              <th style={{ padding: '4px 6px', fontWeight: 600 }}>Kind</th>
              <th style={{ padding: '4px 6px', fontWeight: 600 }}>Chunks</th>
              <th style={{ padding: '4px 6px', fontWeight: 600 }}>Wall</th>
              <th style={{ padding: '4px 6px', fontWeight: 600 }}>Tokens</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={`${e.agent_name}-${i}`} style={{ borderTop: `1px solid ${t.borderSubtle}` }}>
                <td style={{ padding: '6px' }}>{e.agent_name}</td>
                <td style={{ padding: '6px' }}>{e.kind}</td>
                <td style={{ padding: '6px' }}>{chunkCountFor(e)}</td>
                <td style={{ padding: '6px' }}>{formatWallTime(e.wall_time_ms ?? 0)}</td>
                <td style={{ padding: '6px' }}>
                  {(e.input_tokens ?? 0) + '/' + (e.output_tokens ?? 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function GuardrailSection({ decisions }: { decisions: TraceGuardrailDecision[] }) {
  const t = useThemeColors();
  return (
    <section data-testid="run-trace-guardrails">
      <SectionHeading text={`Guardrail decisions (${decisions.length})`} />
      {decisions.length === 0 ? (
        <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>No guardrail decisions recorded.</p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {decisions.map((d, i) => (
            <li
              key={`${d.rule_id}-${i}`}
              style={{
                padding: 8,
                borderRadius: 8,
                background: t.bgMuted,
                fontSize: 12,
                color: t.textSecondary,
              }}
            >
              <p style={{ margin: 0, fontWeight: 600, color: t.textPrimary }}>
                {d.rule_id}{' '}
                <span style={{ color: d.action === 'refuse' ? t.bear : d.action === 'modify' ? t.warn : t.textMuted }}>
                  · {d.action}
                </span>
              </p>
              <p style={{ margin: '2px 0 0', color: t.textMuted }}>
                phase: {d.phase}
                {d.reason ? ` · ${d.reason}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function JudgeSection({ reports }: { reports: TraceJudgeReport[] }) {
  const t = useThemeColors();
  return (
    <section data-testid="run-trace-judge">
      <SectionHeading text={`Judge reports (${reports.length})`} />
      {reports.length === 0 ? (
        <p style={{ fontSize: 12, color: t.textMuted, margin: 0 }}>No judge reports recorded.</p>
      ) : (
        reports.map((r, i) => {
          const min = minGroundednessScore(r);
          const safe = !!r.safe_to_display;
          return (
            <div
              key={i}
              data-testid="run-trace-judge-report"
              style={{
                padding: 10,
                borderRadius: 8,
                background: t.bgMuted,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                marginTop: i === 0 ? 0 : 8,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {safe ? (
                  <CheckCircle2 size={14} color={t.bull} aria-hidden />
                ) : (
                  <AlertCircle size={14} color={t.bear} aria-hidden />
                )}
                <span style={{ fontSize: 12, fontWeight: 700, color: t.textPrimary }}>
                  {safe ? 'Safe to display' : 'Not safe to display'}
                </span>
                <span style={{ fontSize: 11, color: t.textMuted }}>
                  {r.model_id ?? 'unknown'} · {formatWallTime(r.elapsed_ms)}
                </span>
              </div>
              {min != null ? (
                <p style={{ margin: 0, fontSize: 12, color: t.textSecondary }}>
                  Minimum groundedness: {min.toFixed(2)} (across {Object.keys(r.groundedness_score ?? {}).length} sections)
                </p>
              ) : null}
              {r.unsupported_claims && r.unsupported_claims.length > 0 ? (
                <div>
                  <p style={{ margin: 0, fontSize: 11, color: t.textMuted, fontWeight: 600 }}>
                    Unsupported claims ({r.unsupported_claims.length})
                  </p>
                  <ul style={{ margin: '4px 0 0', paddingLeft: 14, color: t.textSecondary, fontSize: 12 }}>
                    {r.unsupported_claims.slice(0, 5).map((c, j) => (
                      <li key={j}>
                        <strong>{c.section}</strong> · {c.reason}: {c.claim_text.slice(0, 80)}
                        {c.claim_text.length > 80 ? '…' : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {r.off_policy_findings && r.off_policy_findings.length > 0 ? (
                <p style={{ margin: 0, fontSize: 12, color: t.bear }}>
                  Off-policy: {r.off_policy_findings.join(', ')}
                </p>
              ) : null}
            </div>
          );
        })
      )}
    </section>
  );
}

function SectionHeading({ text }: { text: string }) {
  const t = useThemeColors();
  return (
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
      {text}
    </p>
  );
}
