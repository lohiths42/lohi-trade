/**
 * LohiAvatarResearch — the editorial sibling of `LohiAvatar`.
 *
 * Same API surface and same rig (head + torso + arms + legs + breathing
 * halo + cursor parallax + blink + mood + gestures), but re-skinned for
 * the Research product identity we grounded in Quartr's brand guidelines:
 *
 *   • Monochrome palette — paper-white and graphite, with a single coral
 *     "Edge" accent used for the pen-antenna tip and the chest motif.
 *   • Reading glasses instead of a trader headset.
 *   • A tiny serif pen on top of the head (where the trader antenna was).
 *   • Chest motif is a three-line paragraph block (editorial), not
 *     ascending bars (trading).
 *   • Surface-aware: when the user is in light mode the head is ink on
 *     paper; in dark mode it inverts to paper on ink.
 *
 * Intentionally identical prop contract to `LohiAvatar` so pages that
 * import `LohiAvatarAuto` get the right skin automatically.
 */

import { useEffect, useRef, useState } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react';
import type { LohiAction, LohiMood } from '../onboarding/LohiAvatar';

// Tokens scoped to the research surface. Fall back to hardcoded values so
// the avatar renders even if research-theme.css has not mounted yet.
const INK_CSS = 'var(--fg-primary, #000000)';
const INK_SOFT_CSS = 'var(--fg-secondary, #2b2b2b)';
const PAPER_CSS = 'var(--surface-2, #ffffff)';
const PAPER_ALT_CSS = 'var(--surface-3, #f7f7f7)';
const HAIRLINE_CSS = 'var(--line-3, rgba(0,0,0,0.22))';
const EDGE_CSS = 'var(--editorial, #c1301b)';
const EDGE_GLOW_CSS = 'var(--editorial-soft, rgba(193, 48, 27, 0.18))';

export default function LohiAvatarResearch({
  size = 'md',
  speaking = false,
  thinking = false,
  action = 'idle',
  actionKey = 0,
  mood = 'happy',
}: {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  speaking?: boolean;
  thinking?: boolean;
  action?: LohiAction;
  actionKey?: number;
  mood?: LohiMood;
}) {
  const dim =
    size === 'sm' ? 48 : size === 'md' ? 96 : size === 'lg' ? 180 : 240;
  const uid = `lohi-r-${size}-${actionKey}`;

  const rootRef = useRef<HTMLDivElement>(null);
  const tiltX = useMotionValue(0);
  const tiltY = useMotionValue(0);
  const springX = useSpring(tiltX, { stiffness: 180, damping: 22 });
  const springY = useSpring(tiltY, { stiffness: 180, damping: 22 });
  const rotateY = useTransform(springX, [-1, 1], [-12, 12]);
  const rotateX = useTransform(springY, [-1, 1], [8, -8]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const el = rootRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / Math.max(220, window.innerWidth / 2);
      const dy = (e.clientY - cy) / Math.max(220, window.innerHeight / 2);
      tiltX.set(Math.max(-1, Math.min(1, dx)));
      tiltY.set(Math.max(-1, Math.min(1, dy)));
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, [tiltX, tiltY]);

  const [blink, setBlink] = useState(false);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const wait = 2200 + Math.random() * 3200;
      t = setTimeout(() => {
        setBlink(true);
        setTimeout(() => setBlink(false), 120);
        schedule();
      }, wait);
    };
    schedule();
    return () => clearTimeout(t);
  }, []);

  const mouthPath = getMouthPath(mood, speaking);

  return (
    <motion.div
      ref={rootRef}
      style={{
        position: 'relative',
        width: dim,
        height: dim * 1.35,
        flexShrink: 0,
        display: 'inline-block',
        perspective: 620,
      }}
      aria-label="Lohi, your research companion"
      role="img"
    >
      {/* Editorial halo — subtle, paper-warm */}
      <motion.div
        aria-hidden
        animate={
          speaking
            ? { scale: [1, 1.08, 1], opacity: [0.45, 0.75, 0.45] }
            : { scale: [1, 1.04, 1], opacity: [0.35, 0.55, 0.35] }
        }
        transition={{
          duration: speaking ? 2.2 : 3.8,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
        style={{
          position: 'absolute',
          left: '50%',
          top: Math.round(dim * 0.42),
          width: dim,
          height: dim,
          marginLeft: -dim / 2,
          marginTop: -dim / 2,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${EDGE_GLOW_CSS} 0%, transparent 70%)`,
          filter: 'blur(12px)',
          pointerEvents: 'none',
        }}
      />

      {/* Orbit ring — thinner, editorial hairline */}
      <motion.svg
        aria-hidden
        viewBox="0 0 100 100"
        width={dim}
        height={dim}
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          pointerEvents: 'none',
          overflow: 'visible',
        }}
        animate={{ rotate: 360 }}
        transition={{
          duration: thinking ? 3.2 : 20,
          repeat: Infinity,
          ease: 'linear',
        }}
      >
        <circle
          cx="50"
          cy="50"
          r="48"
          fill="none"
          stroke={HAIRLINE_CSS}
          strokeWidth="0.6"
          strokeDasharray="1 4"
          opacity="0.7"
        />
        <circle cx="50" cy="2" r="1.6" fill={EDGE_CSS}>
          <animate attributeName="opacity" values="0.4;1;0.4" dur="1.8s" repeatCount="indefinite" />
        </circle>
      </motion.svg>

      {/* Full body + head SVG */}
      <motion.svg
        viewBox="0 0 100 135"
        width={dim}
        height={dim * 1.35}
        style={{
          position: 'relative',
          display: 'block',
          overflow: 'visible',
        }}
        aria-hidden
      >
        <defs>
          {/* Head flat ink fill — with a very subtle rim lift */}
          <linearGradient id={`${uid}-head`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--fg-primary, #000000)" />
            <stop offset="100%" stopColor="var(--fg-secondary, #2b2b2b)" />
          </linearGradient>
          {/* Body — slightly lighter than head */}
          <linearGradient id={`${uid}-body`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--fg-secondary, #2b2b2b)" />
            <stop offset="100%" stopColor="var(--fg-primary, #000000)" />
          </linearGradient>
          {/* Limb — slightly warmer */}
          <linearGradient id={`${uid}-limb`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--fg-secondary, #2b2b2b)" />
            <stop offset="100%" stopColor="var(--fg-primary, #000000)" />
          </linearGradient>
          {/* Edge accent gradient — the single chromatic element */}
          <linearGradient id={`${uid}-edge`} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor={EDGE_CSS} stopOpacity="0.85" />
            <stop offset="100%" stopColor={EDGE_CSS} stopOpacity="1" />
          </linearGradient>
          <radialGradient id={`${uid}-cheek`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={EDGE_CSS} stopOpacity="0.25" />
            <stop offset="100%" stopColor={EDGE_CSS} stopOpacity="0" />
          </radialGradient>
          {/* Soft ground shadow */}
          <radialGradient id={`${uid}-shadow`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(0,0,0,0.25)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0)" />
          </radialGradient>
        </defs>

        {/* Ground shadow */}
        <ellipse cx="50" cy="128" rx="26" ry="3" fill={`url(#${uid}-shadow)`} />

        {/* Legs */}
        <Legs uid={uid} action={action} actionKey={actionKey} />

        {/* Torso */}
        <Torso uid={uid} />

        {/* Arms */}
        <Arms uid={uid} action={action} actionKey={actionKey} />

        {/* Head */}
        <motion.g
          style={{ rotateX, rotateY, originX: '50px', originY: '40px', transformBox: 'fill-box' }}
          animate={{ y: [0, -0.8, 0] }}
          transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <Head
            uid={uid}
            mood={mood}
            mouthPath={mouthPath}
            blink={blink}
            speaking={speaking}
            actionKey={actionKey}
          />
        </motion.g>
      </motion.svg>

      {/* Activity pulse — coral Edge mark, not green */}
      <motion.span
        aria-hidden
        animate={
          speaking
            ? { scale: [1, 1.3, 1], opacity: [0.75, 1, 0.75] }
            : { scale: 1, opacity: 0.9 }
        }
        transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          position: 'absolute',
          right: Math.round(dim * 0.1),
          top: Math.round(dim * 0.62),
          width: Math.max(6, Math.round(dim * 0.09)),
          height: Math.max(6, Math.round(dim * 0.09)),
          borderRadius: '50%',
          background: EDGE_CSS,
          boxShadow: `0 0 10px ${EDGE_GLOW_CSS}`,
          border: `2px solid ${PAPER_CSS}`,
          zIndex: 3,
        }}
      />
    </motion.div>
  );
}

// ─── Head (with reading glasses + serif pen instead of headset+antenna) ────

function Head({
  uid,
  mood,
  mouthPath,
  blink,
  speaking,
  actionKey,
}: {
  uid: string;
  mood: LohiMood;
  mouthPath: string;
  blink: boolean;
  speaking: boolean;
  actionKey: number;
}) {
  return (
    <g>
      {/* Head sphere */}
      <circle
        cx="50"
        cy="38"
        r="24"
        fill={`url(#${uid}-head)`}
        stroke={HAIRLINE_CSS}
        strokeWidth="0.5"
      />

      {/* Specular highlight on the paper-white cranium when dark */}
      <ellipse cx="43" cy="27" rx="5" ry="2.4" fill={PAPER_CSS} opacity="0.18" />

      {/* Cheek warmth */}
      <circle cx="38" cy="44" r="4" fill={`url(#${uid}-cheek)`} />
      <circle cx="62" cy="44" r="4" fill={`url(#${uid}-cheek)`} />

      {/* Serif PEN on top — the editorial antenna */}
      {/* Shaft */}
      <rect x="49.2" y="12" width="1.6" height="6" rx="0.6" fill={PAPER_CSS} opacity="0.9" />
      {/* Nib — coral Edge tip */}
      <path d="M48.4 10 L50 7 L51.6 10 Z" fill={EDGE_CSS}>
        <animate attributeName="opacity" values="0.7;1;0.7" dur="1.6s" repeatCount="indefinite" />
      </path>

      {/* Reading GLASSES (the editorial replacement for the headset) */}
      <g stroke={PAPER_CSS} strokeWidth="0.9" fill="none" opacity="0.92">
        {/* Bridge */}
        <path d="M44 39 Q 50 37, 56 39" strokeLinecap="round" />
        {/* Left lens */}
        <rect x="35.5" y="36.5" width="9" height="6" rx="2" />
        {/* Right lens */}
        <rect x="55.5" y="36.5" width="9" height="6" rx="2" />
        {/* Temple arms disappearing behind the head */}
        <path d="M35.5 39 L 30 37" strokeLinecap="round" />
        <path d="M64.5 39 L 70 37" strokeLinecap="round" />
      </g>
      {/* Lens glint */}
      <line x1="37" y1="37.5" x2="41" y2="37.5" stroke={PAPER_CSS} strokeWidth="0.5" opacity="0.6" />
      <line x1="57" y1="37.5" x2="61" y2="37.5" stroke={PAPER_CSS} strokeWidth="0.5" opacity="0.6" />

      {/* Eyebrows — mood-aware */}
      <motion.g
        animate={
          mood === 'focused' ? { y: 1 } : mood === 'happy' ? { y: -0.5 } : { y: 0 }
        }
        transition={{ duration: 0.35 }}
      >
        <rect
          x="37.5"
          y="33.5"
          width="6"
          height="1"
          rx="0.5"
          fill={PAPER_CSS}
          opacity="0.78"
          transform={mood === 'focused' ? 'rotate(-6 40.5 34)' : 'rotate(0 40.5 34)'}
        />
        <rect
          x="56.5"
          y="33.5"
          width="6"
          height="1"
          rx="0.5"
          fill={PAPER_CSS}
          opacity="0.78"
          transform={mood === 'focused' ? 'rotate(6 59.5 34)' : 'rotate(0 59.5 34)'}
        />
      </motion.g>

      {/* Eyes — through the glasses. Paper dots, not green bars. */}
      <motion.g
        animate={{ scaleY: blink ? 0.08 : 1 }}
        transition={{ duration: 0.1 }}
        style={{ transformOrigin: '40px 39.5px', transformBox: 'fill-box' as any }}
      >
        <circle cx="40" cy="39.5" r="1.3" fill={PAPER_CSS} />
      </motion.g>
      <motion.g
        animate={{ scaleY: blink ? 0.08 : 1 }}
        transition={{ duration: 0.1 }}
        style={{ transformOrigin: '60px 39.5px', transformBox: 'fill-box' as any }}
      >
        <circle cx="60" cy="39.5" r="1.3" fill={PAPER_CSS} />
      </motion.g>

      {/* Mouth */}
      <motion.path
        key={mouthPath + actionKey + (speaking ? 's' : 'q')}
        d={mouthPath}
        fill="none"
        stroke={PAPER_CSS}
        strokeWidth="1.1"
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 0.92 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      />

      {speaking && (
        <motion.ellipse
          cx="50"
          cy="48.2"
          rx="2"
          ry="0.8"
          fill={INK_CSS}
          stroke={PAPER_CSS}
          strokeWidth="0.6"
          animate={{ ry: [0.4, 1.2, 0.6, 1.0, 0.5], opacity: [0.7, 1, 0.8, 1, 0.7] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
    </g>
  );
}

// ─── Torso ────────────────────────────────────────────────────────────────
function Torso({ uid }: { uid: string }) {
  return (
    <g>
      <rect x="47" y="60" width="6" height="5" rx="1.5" fill={`url(#${uid}-body)`} />
      <path
        d="M34 68
           Q 50 63, 66 68
           L 68 95
           Q 50 100, 32 95
           Z"
        fill={`url(#${uid}-body)`}
        stroke={HAIRLINE_CSS}
        strokeWidth="0.5"
      />
      {/* Lapel / open-collar line — editorial */}
      <path
        d="M42 68 L 50 80 L 58 68"
        fill="none"
        stroke={PAPER_CSS}
        strokeWidth="0.8"
        opacity="0.4"
      />
      {/* Chest mark — three stacked paragraph rules (the editorial glyph) */}
      <g opacity="0.9">
        <rect x="44" y="82" width="12" height="0.9" rx="0.4" fill={PAPER_CSS} opacity="0.7" />
        <rect x="44" y="85" width="12" height="0.9" rx="0.4" fill={PAPER_CSS} opacity="0.55" />
        <rect x="44" y="88" width="8" height="0.9" rx="0.4" fill={`url(#${uid}-edge)`} />
      </g>
      {/* Belt */}
      <rect x="33" y="94" width="34" height="2" rx="1" fill={PAPER_CSS} opacity="0.15" />
    </g>
  );
}

// ─── Legs ─────────────────────────────────────────────────────────────────
function Legs({
  uid,
  action,
  actionKey,
}: {
  uid: string;
  action: LohiAction;
  actionKey: number;
}) {
  const celebrating = action === 'celebrate';
  return (
    <motion.g
      key={`rlegs-${actionKey}-${action}`}
      animate={
        celebrating ? { y: [0, -6, 0, -3, 0] } : { y: [0, 0.6, 0] }
      }
      transition={
        celebrating
          ? { duration: 0.9, times: [0, 0.3, 0.6, 0.8, 1], ease: 'easeOut' }
          : { duration: 3.2, repeat: Infinity, ease: 'easeInOut' }
      }
    >
      <motion.g
        style={{ transformOrigin: '44px 96px', transformBox: 'fill-box' as any }}
        animate={celebrating ? { rotate: [0, -8, 6, 0] } : { rotate: [0, 1.5, 0, -1.5, 0] }}
        transition={
          celebrating
            ? { duration: 0.9, times: [0, 0.3, 0.6, 1] }
            : { duration: 4.2, repeat: Infinity, ease: 'easeInOut' }
        }
      >
        <rect x="40" y="96" width="8" height="22" rx="3" fill={`url(#${uid}-limb)`} />
        <ellipse
          cx="44"
          cy="120"
          rx="6"
          ry="2.6"
          fill={INK_SOFT_CSS}
          stroke={HAIRLINE_CSS}
          strokeWidth="0.5"
        />
      </motion.g>
      <motion.g
        style={{ transformOrigin: '56px 96px', transformBox: 'fill-box' as any }}
        animate={celebrating ? { rotate: [0, 8, -6, 0] } : { rotate: [0, -1.5, 0, 1.5, 0] }}
        transition={
          celebrating
            ? { duration: 0.9, times: [0, 0.3, 0.6, 1] }
            : { duration: 4.2, repeat: Infinity, ease: 'easeInOut', delay: 0.6 }
        }
      >
        <rect x="52" y="96" width="8" height="22" rx="3" fill={`url(#${uid}-limb)`} />
        <ellipse
          cx="56"
          cy="120"
          rx="6"
          ry="2.6"
          fill={INK_SOFT_CSS}
          stroke={HAIRLINE_CSS}
          strokeWidth="0.5"
        />
      </motion.g>
    </motion.g>
  );
}

// ─── Arms ─────────────────────────────────────────────────────────────────
function Arms({
  uid,
  action,
  actionKey,
}: {
  uid: string;
  action: LohiAction;
  actionKey: number;
}) {
  return (
    <>
      <OneArm uid={uid} action={action} actionKey={actionKey} side="left" />
      <OneArm uid={uid} action={action} actionKey={actionKey} side="right" />
    </>
  );
}

function OneArm({
  uid,
  action,
  actionKey,
  side,
}: {
  uid: string;
  action: LohiAction;
  actionKey: number;
  side: 'left' | 'right';
}) {
  const SX = side === 'left' ? 66 : 34;
  const SY = 70;
  const mirror = side === 'right';

  let shoulder: any = mirror ? { rotate: [-8, -12, -8] } : { rotate: [8, 12, 8] };
  let shoulderTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut', delay: mirror ? 0 : 0.3 };
  let elbow: any = mirror ? { rotate: [-10, -14, -10] } : { rotate: [10, 14, 10] };
  let elbowTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut', delay: mirror ? 0.4 : 0 };

  if (!mirror && action === 'wave') {
    shoulder = { rotate: [8, -120, -120, -120, -120, 8] };
    shoulderTx = { duration: 1.6, times: [0, 0.15, 0.35, 0.6, 0.85, 1] };
    elbow = { rotate: [10, -10, 30, -15, 25, 10] };
    elbowTx = { duration: 1.6, times: [0, 0.15, 0.35, 0.55, 0.75, 1] };
  } else if (!mirror && action === 'thumbsUp') {
    shoulder = { rotate: [8, -40, -40, 8] };
    shoulderTx = { duration: 1.0, times: [0, 0.25, 0.75, 1], ease: 'easeOut' };
    elbow = { rotate: [10, -70, -70, 10] };
    elbowTx = { duration: 1.0, times: [0, 0.25, 0.75, 1], ease: 'easeOut' };
  } else if (!mirror && action === 'point') {
    shoulder = { rotate: [8, -55, -55, 8] };
    shoulderTx = { duration: 1.2, times: [0, 0.3, 0.8, 1] };
    elbow = { rotate: [10, 10, 10, 10] };
    elbowTx = { duration: 1.2 };
  } else if (action === 'celebrate') {
    shoulder = mirror
      ? { rotate: [-8, 145, 135, 145, -8] }
      : { rotate: [8, -145, -135, -145, 8] };
    shoulderTx = { duration: 1.0, times: [0, 0.25, 0.5, 0.75, 1] };
    elbow = { rotate: [mirror ? -10 : 10] };
    elbowTx = { duration: 1.0 };
  }

  return (
    <motion.g
      key={`ra-${side}-${actionKey}-${action}`}
      style={{ transformOrigin: `${SX}px ${SY}px`, transformBox: 'fill-box' as any }}
      animate={shoulder}
      transition={shoulderTx}
    >
      <rect x={SX - 3} y={SY} width="6" height="14" rx="3" fill={`url(#${uid}-limb)`} />
      <circle
        cx={SX}
        cy={SY}
        r="3"
        fill={INK_SOFT_CSS}
        stroke={PAPER_CSS}
        strokeWidth="0.4"
        opacity="0.8"
      />
      <motion.g
        style={{ transformOrigin: `${SX}px ${SY + 14}px`, transformBox: 'fill-box' as any }}
        animate={elbow}
        transition={elbowTx}
      >
        <rect x={SX - 2.6} y={SY + 13} width="5.2" height="14" rx="2.6" fill={`url(#${uid}-limb)`} />
        <circle cx={SX} cy={SY + 14} r="2" fill={INK_SOFT_CSS} />
        {/* Hand — for the editorial surface the hand is a small page/book
            on the gesturing left arm, or a simple dot on the idle right */}
        <g transform={`translate(${SX}, ${SY + 27})`}>
          {!mirror && action === 'point' ? (
            <PointingHand uid={uid} />
          ) : !mirror && (action === 'wave' || action === 'celebrate') ? (
            <OpenPalm uid={uid} />
          ) : !mirror && action === 'thumbsUp' ? (
            <ThumbsUpHand uid={uid} />
          ) : !mirror && action === 'idle' ? (
            <NotebookHand uid={uid} />
          ) : (
            <DefaultHand uid={uid} mirror={mirror} />
          )}
        </g>
      </motion.g>
    </motion.g>
  );
}

// ─── Hand shapes ──────────────────────────────────────────────────────────
function DefaultHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      <circle r="3" cx="0" cy="0" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" opacity="0.9" />
    </g>
  );
}

function OpenPalm({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      <rect x="-3" y="-2.5" width="6" height="6" rx="2.2" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" />
      {[-2.2, -0.8, 0.6, 2.0].map((x) => (
        <rect key={x} x={x - 0.4} y="-5.5" width="0.8" height="3.5" rx="0.4" fill={`url(#${uid}-limb)`} />
      ))}
      <rect x="2.8" y="-1" width="0.9" height="2.8" rx="0.4" fill={`url(#${uid}-limb)`} transform="rotate(-30 2.8 -1)" />
    </g>
  );
}

function ThumbsUpHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      <rect x="-3" y="-1.5" width="6" height="5" rx="2.2" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" />
      <rect x="-1" y="-6" width="2" height="4.5" rx="0.9" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" />
      <circle cx="1.8" cy="-5" r="0.5" fill={EDGE_CSS}>
        <animate attributeName="opacity" values="0.3;1;0.3" dur="1.2s" repeatCount="indefinite" />
      </circle>
    </g>
  );
}

function PointingHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      <rect x="-3" y="-2.5" width="5" height="5.5" rx="2" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" />
      <rect x="1.5" y="-1" width="5.5" height="2" rx="1" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" />
      <circle cx="7.2" cy="0" r="0.7" fill={EDGE_CSS}>
        <animate attributeName="opacity" values="0.4;1;0.4" dur="1s" repeatCount="indefinite" />
      </circle>
    </g>
  );
}

/**
 * NotebookHand — the editorial "holding a book" pose. A tiny paper
 * rectangle resting on the hand with a coral page-ribbon on top. This is
 * the idle gesture that makes the research avatar unmistakably editorial.
 */
function NotebookHand({ uid }: { uid: string }) {
  return (
    <g>
      {/* Hand knuckle */}
      <circle r="2.4" cx="0" cy="0" fill={`url(#${uid}-limb)`} stroke={PAPER_CSS} strokeWidth="0.4" opacity="0.9" />
      {/* Book */}
      <rect x="-4" y="-6.5" width="8" height="5.5" rx="0.6" fill={PAPER_CSS} stroke={HAIRLINE_CSS} strokeWidth="0.4" />
      {/* Page rules */}
      <line x1="-3" y1="-5" x2="3" y2="-5" stroke={HAIRLINE_CSS} strokeWidth="0.35" />
      <line x1="-3" y1="-3.5" x2="2" y2="-3.5" stroke={HAIRLINE_CSS} strokeWidth="0.35" />
      <line x1="-3" y1="-2" x2="2.5" y2="-2" stroke={HAIRLINE_CSS} strokeWidth="0.35" />
      {/* Ribbon */}
      <rect x="2" y="-6.8" width="1" height="3.2" fill={EDGE_CSS} />
    </g>
  );
}

// ─── Mouth ─────────────────────────────────────────────────────────────────
function getMouthPath(mood: LohiMood, speaking: boolean): string {
  if (speaking) return 'M45 48 Q 50 50, 55 48';
  if (mood === 'happy') return 'M45 47 Q 50 50.5, 55 47';
  if (mood === 'focused') return 'M46 48.5 Q 50 47.5, 54 48.5';
  return 'M46 48 Q 50 48.5, 54 48';
}
