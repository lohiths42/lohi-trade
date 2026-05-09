import type { ReactNode } from 'react';
import { motion, AnimatePresence, useReducedMotion } from 'motion/react';
import { Check, Lock, ArrowLeft } from 'lucide-react';
import LohiAvatar, { type LohiAction, type LohiMood } from './LohiAvatar';
import KnowledgeBomb from './KnowledgeBomb';

/**
 * OnboardingShell — the persistent frame around every onboarding step.
 *
 * Layout (desktop):
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │   Onboarding Integrity: ██████░░░░  62%       [← Back]  Step 2/4 │
 *   ├──────────────────────┬───────────────────────────────────────────┤
 *   │ Vertical timeline    │                                           │
 *   │ ● Blueprint          │             { children }                  │
 *   │ ● Syncing            │                                           │
 *   │ ○ Stress Test        │                                           │
 *   │ ○ Activation         │                                           │
 *   │                      │                                           │
 *   │ Lohi quote card      │                                           │
 *   └──────────────────────┴───────────────────────────────────────────┘
 *        "I built this app to be the tool I always wanted..."
 */

export interface OnboardingStep {
  key: string;
  title: string;
  quote: string;
}

interface Props {
  steps: OnboardingStep[];
  currentIndex: number;
  integrityPct: number;        // 0–100
  onBack?: () => void;
  children: ReactNode;
  /** Shown via KnowledgeBomb when set; pass `null` to dismiss. */
  knowledgeBomb?: { title: string; tip: string } | null;
  /** Called when the KnowledgeBomb closes (so parent clears it). */
  onKnowledgeBombDismiss?: () => void;
  /** Lohi's current gesture (re-triggers when `lohiActionKey` bumps). */
  lohiAction?: LohiAction;
  lohiActionKey?: number;
  lohiMood?: LohiMood;
}

export default function OnboardingShell({
  steps,
  currentIndex,
  integrityPct,
  onBack,
  children,
  knowledgeBomb,
  onKnowledgeBombDismiss,
  lohiAction = 'idle',
  lohiActionKey = 0,
  lohiMood = 'happy',
}: Props) {
  const reduce = useReducedMotion();
  const current = steps[currentIndex];
  const pct = Math.max(0, Math.min(100, integrityPct));

  return (
    <div className="ob-canvas">
      {/* ── Integrity header ────────────────────────────────────────── */}
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 20,
          padding: '18px 32px',
          background:
            'linear-gradient(180deg, rgba(5,6,8,0.92) 0%, rgba(5,6,8,0.55) 100%)',
          backdropFilter: 'saturate(140%) blur(14px)',
          WebkitBackdropFilter: 'saturate(140%) blur(14px)',
          borderBottom: '1px solid var(--ob-silver-1)',
        }}
      >
        <div
          style={{
            maxWidth: 1180,
            margin: '0 auto',
            display: 'grid',
            gridTemplateColumns: 'auto 1fr auto',
            alignItems: 'center',
            gap: 18,
          }}
        >
          {/* Back */}
          <div>
            {onBack ? (
              <button className="ob-ghost-btn" onClick={onBack}>
                <ArrowLeft size={13} /> Back
              </button>
            ) : (
              <span />
            )}
          </div>

          {/* Integrity bar */}
          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 6,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  color: 'var(--ob-silver-muted)',
                }}
              >
                Onboarding Integrity
              </span>
              <motion.span
                key={pct}
                initial={{ opacity: 0, y: -2 }}
                animate={{ opacity: 1, y: 0 }}
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  color: 'var(--ob-growth)',
                  fontFamily: 'ui-monospace, monospace',
                  letterSpacing: '-0.02em',
                }}
              >
                {pct}%
              </motion.span>
            </div>
            <div
              style={{
                position: 'relative',
                height: 4,
                borderRadius: 2,
                background: 'var(--ob-silver-1)',
                overflow: 'hidden',
              }}
            >
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{
                  duration: reduce ? 0 : 0.8,
                  ease: [0.22, 1, 0.36, 1],
                }}
                style={{
                  position: 'absolute',
                  inset: 0,
                  height: '100%',
                  width: `${pct}%`,
                  background:
                    'linear-gradient(90deg, var(--ob-growth) 0%, #8bf5c7 100%)',
                  boxShadow: '0 0 12px var(--ob-growth-glow)',
                }}
              />
            </div>
          </div>

          {/* Step counter */}
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--ob-silver-muted)',
              fontFamily: 'ui-monospace, monospace',
              whiteSpace: 'nowrap',
            }}
          >
            Step {currentIndex + 1} / {steps.length}
          </span>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────── */}
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          maxWidth: 1180,
          margin: '0 auto',
          padding: '40px 32px 100px',
          display: 'grid',
          gridTemplateColumns: '280px 1fr',
          gap: 40,
        }}
        className="ob-body-grid"
      >
        {/* ── Vertical timeline + Lohi quote ───────────────────────── */}
        <aside
          style={{ display: 'flex', flexDirection: 'column', gap: 28, paddingTop: 10 }}
        >
          <Timeline steps={steps} currentIndex={currentIndex} />

          {/* Lohi quote card */}
          <div className="ob-glass" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
              <LohiAvatar
                size="md"
                speaking
                action={lohiAction}
                actionKey={lohiActionKey}
                mood={lohiMood}
              />
              <div>
                <p
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    color: 'var(--ob-silver-muted)',
                    margin: 0,
                  }}
                >
                  Lohi
                </p>
                <p
                  style={{
                    fontSize: 11,
                    color: 'var(--ob-growth)',
                    margin: '2px 0 0',
                    fontWeight: 600,
                  }}
                >
                  Your Personal Quant
                </p>
              </div>
            </div>
            <AnimatePresence mode="wait">
              <motion.p
                key={current?.key}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  fontSize: 13,
                  lineHeight: 1.65,
                  color: 'var(--ob-silver-text)',
                  margin: 0,
                  fontStyle: 'italic',
                }}
              >
                &ldquo;{current?.quote}&rdquo;
              </motion.p>
            </AnimatePresence>
          </div>
        </aside>

        {/* ── Step content ─────────────────────────────────────────── */}
        <main style={{ minWidth: 0 }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={current?.key}
              initial={{ opacity: 0, x: reduce ? 0 : 24, filter: reduce ? 'none' : 'blur(6px)' }}
              animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, x: reduce ? 0 : -16, filter: reduce ? 'none' : 'blur(4px)' }}
              transition={{ duration: reduce ? 0 : 0.42, ease: [0.22, 1, 0.36, 1] }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* ── Lohi Guarantee footer ───────────────────────────────────── */}
      <footer
        style={{
          position: 'relative',
          zIndex: 1,
          padding: '20px 32px',
          borderTop: '1px solid var(--ob-silver-1)',
          background:
            'linear-gradient(180deg, transparent 0%, rgba(5,6,8,0.6) 100%)',
        }}
      >
        <div
          style={{
            maxWidth: 1180,
            margin: '0 auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <Lock size={12} style={{ color: 'var(--ob-growth)' }} />
          <p
            style={{
              fontSize: 12,
              color: 'var(--ob-silver-muted)',
              margin: 0,
              fontStyle: 'italic',
              textAlign: 'center',
            }}
          >
            &ldquo;Your security should be your top priority 🛡️😎&rdquo;
            <span
              style={{
                marginLeft: 10,
                fontStyle: 'normal',
                fontWeight: 700,
                letterSpacing: '0.1em',
                fontSize: 10,
                color: 'var(--ob-growth)',
                textTransform: 'uppercase',
              }}
            >
              — The Lohi Guarantee
            </span>
          </p>
        </div>
      </footer>

      {/* Floating knowledge bomb */}
      <KnowledgeBomb
        bomb={knowledgeBomb ?? null}
        onDismiss={onKnowledgeBombDismiss}
      />

      <style>{`
        @media (max-width: 860px) {
          .ob-body-grid {
            grid-template-columns: 1fr !important;
            gap: 24px !important;
          }
        }
      `}</style>
    </div>
  );
}

/* ── Vertical timeline ───────────────────────────────────────────── */
function Timeline({
  steps,
  currentIndex,
}: {
  steps: OnboardingStep[];
  currentIndex: number;
}) {
  return (
    <ol
      style={{
        position: 'relative',
        margin: 0,
        padding: 0,
        listStyle: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: 28,
      }}
    >
      {/* Rail */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          left: 11,
          top: 8,
          bottom: 8,
          width: 2,
          borderRadius: 2,
          background: 'var(--ob-silver-1)',
          overflow: 'hidden',
        }}
      >
        <motion.div
          initial={{ height: 0 }}
          animate={{
            height: `${(currentIndex / Math.max(1, steps.length - 1)) * 100}%`,
          }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          style={{
            width: '100%',
            background:
              'linear-gradient(180deg, var(--ob-growth) 0%, #8bf5c7 100%)',
            boxShadow: '0 0 12px var(--ob-growth-glow)',
          }}
        />
      </div>

      {steps.map((step, i) => {
        const state = i < currentIndex ? 'done' : i === currentIndex ? 'active' : 'upcoming';
        return (
          <li
            key={step.key}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 14,
              position: 'relative',
            }}
          >
            <div style={{ position: 'relative', zIndex: 1 }}>
              {state === 'done' && (
                <motion.div
                  initial={{ scale: 0.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                  style={nodeDone}
                >
                  <Check size={11} color="#001f14" strokeWidth={3} />
                </motion.div>
              )}
              {state === 'active' && (
                <motion.div
                  animate={{ boxShadow: [
                    '0 0 0 0 var(--ob-growth-glow)',
                    '0 0 0 6px rgba(0,214,127,0)',
                  ] }}
                  transition={{ duration: 1.8, repeat: Infinity }}
                  style={nodeActive}
                >
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: 'var(--ob-growth)',
                  }} />
                </motion.div>
              )}
              {state === 'upcoming' && <div style={nodeUpcoming} />}
            </div>
            <div style={{ minWidth: 0, flex: 1, paddingTop: 2 }}>
              <p
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                  color: state === 'upcoming' ? 'var(--ob-silver-muted)' : 'var(--ob-growth)',
                  margin: 0,
                }}
              >
                Step {i + 1}
              </p>
              <p
                style={{
                  fontSize: 14,
                  fontWeight: state === 'upcoming' ? 500 : 700,
                  color:
                    state === 'upcoming'
                      ? 'var(--ob-silver-muted)'
                      : 'var(--ob-silver-text)',
                  margin: '3px 0 0',
                  letterSpacing: '-0.01em',
                }}
              >
                {step.title}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const nodeBase: React.CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: '50%',
  display: 'grid',
  placeItems: 'center',
  flexShrink: 0,
};
const nodeDone: React.CSSProperties = {
  ...nodeBase,
  background: 'linear-gradient(180deg, #34eea0 0%, var(--ob-growth) 100%)',
  border: '1px solid color-mix(in srgb, var(--ob-growth) 70%, transparent)',
  boxShadow: '0 0 14px var(--ob-growth-glow)',
};
const nodeActive: React.CSSProperties = {
  ...nodeBase,
  background: 'var(--ob-obsidian-3)',
  border: '1.5px solid var(--ob-growth)',
};
const nodeUpcoming: React.CSSProperties = {
  ...nodeBase,
  background: 'var(--ob-obsidian-3)',
  border: '1.5px solid var(--ob-silver-1)',
};
