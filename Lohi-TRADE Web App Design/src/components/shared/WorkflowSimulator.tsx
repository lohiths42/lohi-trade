/**
 * WorkflowSimulator — DAG-aware walkthrough explainer for an agentic
 * architecture.
 *
 * The canvas on top (WorkflowCanvas) renders the real graph with
 * parallel fan-out, fan-in, sideband channels, and feedback loops. The
 * Prev/Next panel below describes the currently-active node *and* names
 * its parallel siblings, upstream producers, downstream consumers, and
 * sideband channels so the reader always knows how the current step is
 * wired in — not just what comes before and after it.
 *
 * Surface-aware: every color is read from the CSS tokens so Trade gets
 * the neon-indigo finish and Research gets editorial monochrome.
 */

import { useMemo, useState, type ReactNode } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Shield,
  Zap,
} from 'lucide-react';
import WorkflowCanvas, { type Sideband } from './WorkflowCanvas';

export interface WorkflowArtifact {
  /** Short name (e.g. "ChunkHit[]", "SizedOrder"). */
  name: string;
  /** Type or shape hint rendered as a <code> pill. */
  shape: string;
  /** One-line plain-English description. */
  hint?: string;
}

export interface WorkflowStep {
  /** Human-readable agent/role name. */
  role: string;
  /** What this role is responsible for in one sentence. */
  responsibility: string;
  /** Incoming artefact (null for the first step). */
  incoming: WorkflowArtifact | null;
  /** Outgoing artefact (null for the terminal step). */
  outgoing: WorkflowArtifact | null;
  /**
   * When true, this step is a deterministic boundary — schema validation,
   * numeric validator, citation check, guardrail filter, etc.
   */
  deterministic?: boolean;
  /** Rich explanation surfaced in the detail pane. */
  details: ReactNode;

  // ── DAG extensions ──────────────────────────────────────────────────────

  /**
   * Zero-based indices of steps whose primary output feeds this step.
   * When omitted, defaults to `[i - 1]` so callers that pass a linear list
   * still work without modification.
   */
  upstreams?: number[];

  /**
   * Tag used to group parallel siblings (e.g. all six Research sub-agents
   * can share `parallelGroup: 'Sub_Agents'`). Surfaced on the node chip
   * and on the detail pane so the reader sees the concurrent fan-out.
   */
  parallelGroup?: string;

  /**
   * Secondary edges: memory / cache reads, Redis stream publishes,
   * feedback loops, telemetry writes. Kind drives the edge color and the
   * cube's channel ring.
   */
  sidebands?: Sideband[];

  /**
   * A short identifier (e.g. `'plan'`, `'filings'`). Used in detail-pane
   * labels when describing sibling groups.
   */
  shortId?: string;
}

export interface WorkflowSimulatorProps {
  steps: WorkflowStep[];
  stepNumberPrefix?: string;
}

// ─── Component ────────────────────────────────────────────────────────────

export default function WorkflowSimulator({
  steps,
  stepNumberPrefix = 'Step',
}: WorkflowSimulatorProps) {
  const [index, setIndex] = useState(0);
  const active = steps[index];
  const canPrev = index > 0;
  const canNext = index < steps.length - 1;

  const progressPct = useMemo(
    () => Math.round(((index + 1) / steps.length) * 100),
    [index, steps.length],
  );

  // Derive the parallel siblings of the active step — same `parallelGroup`
  // or (as a fallback) nodes that share the same set of upstreams.
  const { parallelSiblings, upstreams, downstreams, sidebands } = useMemo(() => {
    const activeUps = active.upstreams ?? (index > 0 ? [index - 1] : []);
    const siblings: number[] = [];
    for (let i = 0; i < steps.length; i++) {
      if (i === index) continue;
      const s = steps[i];
      const sharedGroup =
        active.parallelGroup && s.parallelGroup === active.parallelGroup;
      const sameUps =
        !active.parallelGroup &&
        s.upstreams &&
        s.upstreams.length === activeUps.length &&
        s.upstreams.every((u) => activeUps.includes(u));
      if (sharedGroup || sameUps) siblings.push(i);
    }
    const ups = activeUps.filter((u) => u >= 0 && u < steps.length);
    const downs: number[] = [];
    for (let i = 0; i < steps.length; i++) {
      const sUps = steps[i].upstreams ?? (i > 0 ? [i - 1] : []);
      if (sUps.includes(index)) downs.push(i);
    }
    return {
      parallelSiblings: siblings,
      upstreams: ups,
      downstreams: downs,
      sidebands: active.sidebands ?? [],
    };
  }, [active, index, steps]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* ── Interactive DAG canvas ────────────────────────────────── */}
      <WorkflowCanvas
        steps={steps}
        activeIndex={index}
        onNodeClick={(i) => setIndex(i)}
      />

      {/* ── Step detail ───────────────────────────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '260px 1fr',
          gap: 28,
          border: '1px solid var(--line-3)',
          borderRadius: 4,
          background: 'var(--surface-2)',
        }}
      >
        {/* Left: pipeline index (still a flat list for quick jumps) */}
        <aside
          style={{
            padding: '20px 0 20px 20px',
            borderRight: '1px solid var(--line-2)',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              paddingRight: 20,
              marginBottom: 10,
            }}
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.16em',
                textTransform: 'uppercase',
                color: 'var(--fg-muted)',
              }}
            >
              Nodes
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: 'var(--fg-muted)',
                fontFeatureSettings: '"tnum" 1',
              }}
            >
              {progressPct}%
            </span>
          </div>
          <ol style={{ margin: 0, padding: 0, listStyle: 'none' }}>
            {steps.map((step, i) => (
              <li key={i}>
                <button
                  onClick={() => setIndex(i)}
                  aria-current={i === index ? 'step' : undefined}
                  style={{
                    all: 'unset',
                    cursor: 'pointer',
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '10px 14px 10px 0',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      position: 'relative',
                      width: 22,
                      flexShrink: 0,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      paddingTop: 2,
                    }}
                  >
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background:
                          i === index
                            ? 'var(--fg-primary)'
                            : 'var(--surface-2)',
                        border:
                          i === index
                            ? '1.5px solid var(--fg-primary)'
                            : '1.5px solid var(--line-3)',
                      }}
                    />
                    {i < steps.length - 1 && (
                      <span
                        style={{
                          flex: 1,
                          width: 1.5,
                          background: 'var(--line-2)',
                          marginTop: 2,
                          minHeight: 22,
                        }}
                      />
                    )}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span
                      style={{
                        display: 'block',
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: '0.1em',
                        textTransform: 'uppercase',
                        color:
                          i === index ? 'var(--fg-primary)' : 'var(--fg-muted)',
                      }}
                    >
                      {stepNumberPrefix} {i + 1}
                      {step.deterministic && (
                        <Shield
                          size={10}
                          style={{ marginLeft: 6, verticalAlign: 'middle' }}
                          aria-label="Deterministic boundary"
                        />
                      )}
                    </span>
                    <span
                      style={{
                        display: 'block',
                        fontSize: 13,
                        fontWeight: i === index ? 700 : 500,
                        color:
                          i === index
                            ? 'var(--fg-primary)'
                            : 'var(--fg-secondary)',
                        marginTop: 2,
                        lineHeight: 1.3,
                      }}
                    >
                      {step.role}
                    </span>
                    {step.parallelGroup && (
                      <span
                        style={{
                          display: 'inline-block',
                          marginTop: 4,
                          fontSize: 9,
                          fontWeight: 700,
                          letterSpacing: '0.12em',
                          textTransform: 'uppercase',
                          padding: '1px 6px',
                          borderRadius: 999,
                          color: 'var(--accent-2)',
                          background:
                            'color-mix(in srgb, var(--accent) 12%, transparent)',
                          border:
                            '1px solid color-mix(in srgb, var(--accent) 30%, transparent)',
                        }}
                      >
                        {step.parallelGroup}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        {/* Right: active node detail */}
        <section
          style={{
            padding: '24px 24px 20px',
            display: 'flex',
            flexDirection: 'column',
            gap: 18,
            minHeight: 460,
          }}
        >
          <header>
            <p
              style={{
                margin: 0,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.16em',
                textTransform: 'uppercase',
                color: active.deterministic ? 'var(--warn)' : 'var(--fg-muted)',
              }}
            >
              {stepNumberPrefix} {index + 1}
              {active.deterministic ? ' · Deterministic boundary' : ' · Agent role'}
              {active.parallelGroup ? ` · ${active.parallelGroup}` : ''}
            </p>
            <h3
              style={{
                margin: '6px 0 0',
                fontSize: 22,
                fontWeight: 700,
                color: 'var(--fg-primary)',
                letterSpacing: '-0.01em',
              }}
            >
              {active.role}
            </h3>
            <p
              style={{
                margin: '8px 0 0',
                fontSize: 14,
                color: 'var(--fg-secondary)',
                maxWidth: 720,
                lineHeight: 1.55,
              }}
            >
              {active.responsibility}
            </p>
          </header>

          {/* Wiring summary row — the "how it's connected" panel */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
              gap: 10,
              background: 'var(--surface-3)',
              border: '1px solid var(--line-2)',
              padding: 14,
              borderRadius: 2,
            }}
          >
            <WiringCell
              label="Upstream"
              indices={upstreams}
              steps={steps}
              onPick={setIndex}
              emptyLabel="Entry point"
            />
            <WiringCell
              label={
                parallelSiblings.length > 0
                  ? `Concurrent with · ${parallelSiblings.length}`
                  : 'Concurrent with'
              }
              indices={parallelSiblings}
              steps={steps}
              onPick={setIndex}
              emptyLabel="None — runs alone in this column"
              accent="accent"
            />
            <WiringCell
              label="Downstream"
              indices={downstreams}
              steps={steps}
              onPick={setIndex}
              emptyLabel="Terminal node"
            />
          </div>

          {/* Artefact flow */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 32px 1fr',
              gap: 10,
              alignItems: 'stretch',
            }}
          >
            <ArtifactCard label="Incoming" artifact={active.incoming} />
            <div
              aria-hidden
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--fg-muted)',
              }}
            >
              <ArrowRight size={18} />
            </div>
            <ArtifactCard label="Outgoing" artifact={active.outgoing} />
          </div>

          {/* Sideband channels */}
          {sidebands.length > 0 && (
            <div>
              <p
                style={{
                  margin: '0 0 6px',
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                  color: 'var(--fg-muted)',
                }}
              >
                Sideband channels · {sidebands.length}
              </p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {sidebands.map((sb, i) => (
                  <SidebandChip
                    key={i}
                    sideband={sb}
                    targetRole={steps[sb.to]?.role ?? ''}
                    onClick={() => setIndex(sb.to)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Deterministic boundary callout */}
          {active.deterministic && (
            <div
              style={{
                padding: '10px 14px',
                border: '1px solid var(--warn)',
                borderLeftWidth: 3,
                background: 'var(--warn-soft)',
                color: 'var(--warn)',
                fontSize: 12,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                borderRadius: 2,
              }}
            >
              <Shield size={14} />
              Deterministic boundary — pure function, no LLM runs here. Runs in
              parallel with adjacent agents; never blocks concurrent branches.
            </div>
          )}

          {/* Rich detail */}
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.7,
              color: 'var(--fg-secondary)',
              maxWidth: 760,
            }}
          >
            {active.details}
          </div>

          {/* Controls */}
          <footer
            style={{
              marginTop: 'auto',
              paddingTop: 16,
              borderTop: '1px solid var(--line-2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 10,
            }}
          >
            <button
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={!canPrev}
              style={{
                all: 'unset',
                cursor: canPrev ? 'pointer' : 'not-allowed',
                opacity: canPrev ? 1 : 0.4,
                padding: '8px 14px',
                borderRadius: 999,
                border: '1px solid var(--line-3)',
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--fg-primary)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <ChevronLeft size={13} /> Prev
            </button>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: 'var(--fg-muted)',
                fontFeatureSettings: '"tnum" 1',
              }}
            >
              {index + 1} / {steps.length}
            </span>
            <button
              onClick={() => setIndex((i) => Math.min(steps.length - 1, i + 1))}
              disabled={!canNext}
              style={{
                all: 'unset',
                cursor: canNext ? 'pointer' : 'not-allowed',
                opacity: canNext ? 1 : 0.4,
                padding: '8px 14px',
                borderRadius: 999,
                background: 'var(--fg-primary)',
                color: 'var(--surface-2)',
                fontSize: 12,
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {index === steps.length - 1 ? (
                <>
                  Done <CheckCircle2 size={13} />
                </>
              ) : (
                <>
                  Next <ChevronRight size={13} />
                </>
              )}
            </button>
          </footer>
        </section>
      </div>
    </div>
  );
}

// ─── Wiring cell ───────────────────────────────────────────────────────────

function WiringCell({
  label,
  indices,
  steps,
  onPick,
  emptyLabel,
  accent,
}: {
  label: string;
  indices: number[];
  steps: WorkflowStep[];
  onPick: (i: number) => void;
  emptyLabel: string;
  accent?: 'accent';
}) {
  return (
    <div>
      <p
        style={{
          margin: '0 0 6px',
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--fg-muted)',
        }}
      >
        {label}
      </p>
      {indices.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12, color: 'var(--fg-muted)' }}>
          {emptyLabel}
        </p>
      ) : (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {indices.map((i) => (
            <button
              key={i}
              onClick={() => onPick(i)}
              style={{
                all: 'unset',
                cursor: 'pointer',
                padding: '3px 8px',
                borderRadius: 2,
                fontSize: 11,
                fontWeight: 600,
                color:
                  accent === 'accent'
                    ? 'var(--accent-2)'
                    : 'var(--fg-primary)',
                background:
                  accent === 'accent'
                    ? 'color-mix(in srgb, var(--accent) 10%, transparent)'
                    : 'var(--surface-2)',
                border:
                  accent === 'accent'
                    ? '1px solid color-mix(in srgb, var(--accent) 30%, transparent)'
                    : '1px solid var(--line-3)',
              }}
            >
              {steps[i]?.role ?? `Step ${i + 1}`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Sideband chip ─────────────────────────────────────────────────────────

function SidebandChip({
  sideband,
  targetRole,
  onClick,
}: {
  sideband: Sideband;
  targetRole: string;
  onClick: () => void;
}) {
  const kind = sideband.kind ?? 'stream';
  const color =
    kind === 'feedback' ? 'var(--warn)'
      : kind === 'memory' || kind === 'cache' ? 'var(--accent-2)'
      : 'var(--fg-muted)';
  const bg =
    kind === 'feedback' ? 'var(--warn-soft)'
      : kind === 'memory' || kind === 'cache'
        ? 'color-mix(in srgb, var(--accent) 10%, transparent)'
        : 'var(--surface-3)';
  return (
    <button
      onClick={onClick}
      style={{
        all: 'unset',
        cursor: 'pointer',
        padding: '5px 10px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        color,
        background: bg,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: color,
        }}
      />
      {sideband.label ?? kind}
      <span style={{ opacity: 0.7 }}>→ {targetRole}</span>
    </button>
  );
}

// ─── Artifact card ────────────────────────────────────────────────────────

function ArtifactCard({
  label,
  artifact,
}: {
  label: string;
  artifact: WorkflowArtifact | null;
}) {
  return (
    <div
      style={{
        padding: 14,
        border: '1px solid var(--line-2)',
        borderRadius: 2,
        background: 'var(--surface-3)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minHeight: 90,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--fg-muted)',
        }}
      >
        <Zap size={11} />
        {label} artifact
      </div>
      {artifact ? (
        <>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--fg-primary)',
            }}
          >
            {artifact.name}
          </div>
          <code
            style={{
              fontSize: 11,
              padding: '2px 7px',
              border: '1px solid var(--line-2)',
              borderRadius: 2,
              background: 'var(--surface-2)',
              color: 'var(--fg-secondary)',
              alignSelf: 'flex-start',
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            }}
          >
            {artifact.shape}
          </code>
          {artifact.hint && (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: 'var(--fg-muted)',
                lineHeight: 1.5,
              }}
            >
              {artifact.hint}
            </p>
          )}
        </>
      ) : (
        <p
          style={{
            margin: 0,
            fontSize: 12,
            color: 'var(--fg-muted)',
            fontStyle: 'italic',
          }}
        >
          —
        </p>
      )}
    </div>
  );
}
