import { useEffect, useRef, useState } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react';

/**
 * LohiAvatar — the face (and now body) of the brand.
 *
 * A faux-3D quant mascot built entirely in SVG:
 *   • Head with radial shading, rim light, specular highlight, headset
 *   • Expressive eyes (brand mark) + mouth + eyebrows that react to mood
 *   • Torso with shoulders + a subtle chart-bar motif on the chest
 *   • Two arms with an elbow joint — arms perform the actual gestures
 *     (wave / thumbsUp / point / celebrate) instead of floating emoji
 *   • Two legs with feet that gently sway in idle
 *   • Breathing, blinking, cursor-parallax head tilt, orbit ring, halo
 *
 * Every color has a hardcoded fallback so the avatar renders even if
 * `onboarding.css` has not mounted yet.
 */

export type LohiAction = 'idle' | 'wave' | 'thumbsUp' | 'celebrate' | 'point';
export type LohiMood = 'happy' | 'neutral' | 'focused';

const GROWTH_CSS = 'var(--ob-growth, #00d67f)';
const GROWTH_GLOW_CSS = 'var(--ob-growth-glow, rgba(0, 214, 127, 0.45))';
const SILVER_CSS = 'var(--ob-silver-2, rgba(226, 232, 240, 0.28))';

export default function LohiAvatar({
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
  const uid = `lohi-${size}-${actionKey}`;

  /* ── Cursor parallax (head tilt) ──────────────────────────────── */
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

  /* ── Idle blink loop ──────────────────────────────────────────── */
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
        height: dim * 1.35, // extra room for body + legs
        flexShrink: 0,
        display: 'inline-block',
        perspective: 620,
      }}
      aria-label="Lohi, your personal quant"
      role="img"
    >
      {/* ── Breathing halo around the head ─────────────────────── */}
      <motion.div
        aria-hidden
        animate={
          speaking
            ? { scale: [1, 1.12, 1], opacity: [0.55, 0.95, 0.55] }
            : { scale: [1, 1.05, 1], opacity: [0.45, 0.75, 0.45] }
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
          background: `radial-gradient(circle, ${GROWTH_GLOW_CSS} 0%, transparent 70%)`,
          filter: 'blur(14px)',
          pointerEvents: 'none',
        }}
      />

      {/* ── Rotating orbit ring around head ─────────────────────── */}
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
          duration: thinking ? 3.2 : 14,
          repeat: Infinity,
          ease: 'linear',
        }}
      >
        <circle
          cx="50" cy="50" r="48"
          fill="none"
          stroke={SILVER_CSS}
          strokeWidth="1"
          strokeDasharray="2 6"
          opacity="0.8"
        />
        <circle cx="50" cy="2" r="2.4" fill={GROWTH_CSS}>
          <animate attributeName="opacity" values="0.6;1;0.6" dur="1.8s" repeatCount="indefinite" />
        </circle>
      </motion.svg>

      {/* ── Full body + head SVG ────────────────────────────────── */}
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
          {/* Head radial gradient */}
          <radialGradient id={`${uid}-head`} cx="30%" cy="25%" r="70%">
            <stop offset="0%" stopColor="#3d4a68" />
            <stop offset="40%" stopColor="#1e2638" />
            <stop offset="80%" stopColor="#0a0c14" />
            <stop offset="100%" stopColor="#050608" />
          </radialGradient>
          {/* Body gradient — slightly lighter than head on top, darker at base */}
          <linearGradient id={`${uid}-body`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2a3248" />
            <stop offset="55%" stopColor="#151a28" />
            <stop offset="100%" stopColor="#080a12" />
          </linearGradient>
          {/* Arm / leg gradient — matches body but a touch dimmer */}
          <linearGradient id={`${uid}-limb`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#1a2030" />
            <stop offset="100%" stopColor="#0a0c14" />
          </linearGradient>
          {/* Eye / mark gradient */}
          <linearGradient id={`${uid}-eye`} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="#00d67f" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#8bf5c7" stopOpacity="1" />
          </linearGradient>
          {/* Cheek warmth */}
          <radialGradient id={`${uid}-cheek`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#00d67f" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#00d67f" stopOpacity="0" />
          </radialGradient>
          {/* Glow filter for eyes + chest motif */}
          <filter id={`${uid}-glow`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="0.9" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Soft shadow */}
          <radialGradient id={`${uid}-shadow`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(0,0,0,0.55)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0)" />
          </radialGradient>
        </defs>

        {/* Ground shadow */}
        <ellipse cx="50" cy="128" rx="26" ry="3.5" fill={`url(#${uid}-shadow)`} />

        {/* ── Legs ─────────────────────────────────────────────── */}
        <Legs uid={uid} action={action} actionKey={actionKey} />

        {/* ── Torso ────────────────────────────────────────────── */}
        <Torso uid={uid} />

        {/* ── Arms (perform gestures) ──────────────────────────── */}
        <Arms uid={uid} action={action} actionKey={actionKey} />

        {/* ── Head group (parallax tilt via wrapper div) ───────── */}
        <motion.g
          style={{ rotateX, rotateY, originX: '50px', originY: '40px', transformBox: 'fill-box' }}
          // Idle breathing lift
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

      {/* ── Confetti burst ──────────────────────────────────────── */}
      {action === 'celebrate' && <Confetti keyId={actionKey} dim={dim} />}

      {/* ── Activity pulse dot ─────────────────────────────────── */}
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
          background: GROWTH_CSS,
          boxShadow: `0 0 12px ${GROWTH_GLOW_CSS}`,
          border: '2px solid #0a0c10',
          zIndex: 3,
        }}
      />
    </motion.div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Head — the expressive face
   ══════════════════════════════════════════════════════════════════════════ */
function Head({
  uid, mood, mouthPath, blink, speaking, actionKey,
}: {
  uid: string; mood: LohiMood; mouthPath: string; blink: boolean;
  speaking: boolean; actionKey: number;
}) {
  return (
    <g>
      {/* Head sphere */}
      <circle
        cx="50" cy="38" r="24"
        fill={`url(#${uid}-head)`}
        stroke="rgba(226,232,240,0.25)"
        strokeWidth="0.8"
      />

      {/* Rim light top-left */}
      <ellipse
        cx="41" cy="28" rx="12" ry="7"
        fill="rgba(139,245,199,0.22)"
        style={{ mixBlendMode: 'screen' as any }}
      />
      {/* Specular highlight */}
      <ellipse
        cx="43" cy="27" rx="5" ry="2.8"
        fill="rgba(255,255,255,0.55)"
        opacity="0.8"
      />

      {/* Cheeks */}
      <circle cx="38" cy="44" r="4.5" fill={`url(#${uid}-cheek)`} />
      <circle cx="62" cy="44" r="4.5" fill={`url(#${uid}-cheek)`} />

      {/* Headset band */}
      <path
        d="M32 32 C 32 18, 68 18, 68 32"
        fill="none"
        stroke="rgba(139,245,199,0.45)"
        strokeWidth="1.1"
        strokeLinecap="round"
      />
      <circle cx="32" cy="32" r="1.7" fill="#8bf5c7" />
      <circle cx="68" cy="32" r="1.7" fill="#8bf5c7" />
      {/* Antenna */}
      <line x1="50" y1="14" x2="50" y2="11" stroke="#8bf5c7" strokeWidth="0.8" />
      <circle cx="50" cy="10" r="1.3" fill="#8bf5c7">
        <animate attributeName="opacity" values="0.5;1;0.5" dur="1.5s" repeatCount="indefinite" />
      </circle>

      {/* Eyebrows — mood-aware */}
      <motion.g
        animate={
          mood === 'focused' ? { y: 1 } : mood === 'happy' ? { y: -0.5 } : { y: 0 }
        }
        transition={{ duration: 0.35 }}
      >
        <rect
          x="38" y="32" width="6.5" height="1.3" rx="0.6"
          fill="#8bf5c7" opacity="0.75"
          transform={mood === 'focused' ? 'rotate(-6 41.25 32.6)' : 'rotate(0 41.25 32.6)'}
        />
        <rect
          x="55.5" y="32" width="6.5" height="1.3" rx="0.6"
          fill="#8bf5c7" opacity="0.75"
          transform={mood === 'focused' ? 'rotate(6 58.75 32.6)' : 'rotate(0 58.75 32.6)'}
        />
      </motion.g>

      {/* Eyes — brand-mark ascending bars */}
      <g filter={`url(#${uid}-glow)`}>
        <motion.g
          animate={{ scaleY: blink ? 0.08 : 1 }}
          transition={{ duration: 0.1 }}
          style={{ transformOrigin: '41px 38px', transformBox: 'fill-box' as any }}
        >
          <rect x="38"   y="38" width="1.7" height="2.6" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.7" />
          <rect x="40.3" y="36.5" width="1.7" height="4.1" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.85" />
          <rect x="42.6" y="35"   width="1.7" height="5.6" rx="0.5" fill={`url(#${uid}-eye)`} />
        </motion.g>
        <motion.g
          animate={{ scaleY: blink ? 0.08 : 1 }}
          transition={{ duration: 0.1 }}
          style={{ transformOrigin: '59px 38px', transformBox: 'fill-box' as any }}
        >
          <rect x="55.4" y="38" width="1.7" height="2.6" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.7" />
          <rect x="57.7" y="36.5" width="1.7" height="4.1" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.85" />
          <rect x="60"   y="35"   width="1.7" height="5.6" rx="0.5" fill={`url(#${uid}-eye)`} />
        </motion.g>
      </g>

      {/* Mouth */}
      <motion.path
        key={mouthPath + actionKey + (speaking ? 's' : 'q')}
        d={mouthPath}
        fill="none"
        stroke="#8bf5c7"
        strokeWidth="1.2"
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 0.95 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      />

      {/* Speaking mouth pulse */}
      {speaking && (
        <motion.ellipse
          cx="50" cy="48.2"
          rx="2" ry="0.8"
          fill="#0a0c14"
          stroke="#8bf5c7"
          strokeWidth="0.7"
          animate={{ ry: [0.4, 1.2, 0.6, 1.0, 0.5], opacity: [0.7, 1, 0.8, 1, 0.7] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
    </g>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Torso — shoulders, neck, chest motif
   ══════════════════════════════════════════════════════════════════════════ */
function Torso({ uid }: { uid: string }) {
  return (
    <g>
      {/* Neck */}
      <rect x="47" y="60" width="6" height="5" rx="1.5" fill={`url(#${uid}-body)`} />

      {/* Torso — trapezoid-ish with rounded corners */}
      <path
        d="M34 68
           Q 50 63, 66 68
           L 68 95
           Q 50 100, 32 95
           Z"
        fill={`url(#${uid}-body)`}
        stroke="rgba(226,232,240,0.18)"
        strokeWidth="0.7"
      />

      {/* Collar highlight */}
      <path
        d="M38 69 Q 50 66, 62 69"
        fill="none"
        stroke="rgba(139,245,199,0.25)"
        strokeWidth="0.8"
        strokeLinecap="round"
      />

      {/* Chest brand-mark (three tiny ascending bars) */}
      <g filter={`url(#${uid}-glow)`} opacity="0.9">
        <rect x="45.5" y="82" width="1.8" height="3" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.6" />
        <rect x="48.5" y="80" width="1.8" height="5" rx="0.5" fill={`url(#${uid}-eye)`} opacity="0.8" />
        <rect x="51.5" y="78" width="1.8" height="7" rx="0.5" fill={`url(#${uid}-eye)`} />
      </g>

      {/* Belt / hip line */}
      <rect x="33" y="94" width="34" height="2.4" rx="1" fill="rgba(139,245,199,0.2)" />
    </g>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Legs — with gentle idle sway and a small hop on celebrate
   ══════════════════════════════════════════════════════════════════════════ */
function Legs({
  uid, action, actionKey,
}: { uid: string; action: LohiAction; actionKey: number }) {
  const celebrating = action === 'celebrate';

  return (
    <motion.g
      // Whole-body hop on celebrate, subtle idle sway otherwise
      key={`legs-${actionKey}-${action}`}
      animate={
        celebrating
          ? { y: [0, -6, 0, -3, 0] }
          : { y: [0, 0.6, 0] }
      }
      transition={
        celebrating
          ? { duration: 0.9, times: [0, 0.3, 0.6, 0.8, 1], ease: 'easeOut' }
          : { duration: 3.2, repeat: Infinity, ease: 'easeInOut' }
      }
    >
      {/* Left leg */}
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
        <ellipse cx="44" cy="120" rx="6" ry="2.6" fill="#0a0c14" stroke="rgba(139,245,199,0.3)" strokeWidth="0.6" />
      </motion.g>
      {/* Right leg */}
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
        <ellipse cx="56" cy="120" rx="6" ry="2.6" fill="#0a0c14" stroke="rgba(139,245,199,0.3)" strokeWidth="0.6" />
      </motion.g>
    </motion.g>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Arms — perform the actual gestures. Each arm is a two-segment rig
   (shoulder joint → upper arm → elbow → forearm → hand).
   ══════════════════════════════════════════════════════════════════════════ */
function Arms({
  uid, action, actionKey,
}: { uid: string; action: LohiAction; actionKey: number }) {
  return (
    <>
      <LeftArm uid={uid} action={action} actionKey={actionKey} />
      <RightArm uid={uid} action={action} actionKey={actionKey} />
    </>
  );
}

/* Left arm (Lohi's left = viewer's right) */
function LeftArm({
  uid, action, actionKey,
}: { uid: string; action: LohiAction; actionKey: number }) {
  // Shoulder pivot
  const SX = 66, SY = 70;

  // Default idle pose (slight inward tilt + gentle sway)
  let shoulder: any = { rotate: [8, 12, 8] };
  let shoulderTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut', delay: 0.3 };
  let elbow: any = { rotate: [10, 14, 10] };
  let elbowTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut' };
  let hand: React.ReactNode = <DefaultHand uid={uid} />;

  if (action === 'wave') {
    // Raised arm, open palm waving back and forth
    shoulder = { rotate: [8, -120, -120, -120, -120, 8] };
    shoulderTx = { duration: 1.6, times: [0, 0.15, 0.35, 0.6, 0.85, 1] };
    elbow = { rotate: [10, -10, 30, -15, 25, 10] };
    elbowTx = { duration: 1.6, times: [0, 0.15, 0.35, 0.55, 0.75, 1] };
    hand = <OpenPalm uid={uid} />;
  } else if (action === 'thumbsUp') {
    // Bent arm, fist at chest level, thumb up
    shoulder = { rotate: [8, -40, -40, 8] };
    shoulderTx = { duration: 1.0, times: [0, 0.25, 0.75, 1], ease: 'easeOut' };
    elbow = { rotate: [10, -70, -70, 10] };
    elbowTx = { duration: 1.0, times: [0, 0.25, 0.75, 1], ease: 'easeOut' };
    hand = <ThumbsUpHand uid={uid} />;
  } else if (action === 'point') {
    // Arm extended outward, index finger pointing right-forward
    shoulder = { rotate: [8, -55, -55, 8] };
    shoulderTx = { duration: 1.2, times: [0, 0.3, 0.8, 1] };
    elbow = { rotate: [10, 10, 10, 10] };
    elbowTx = { duration: 1.2 };
    hand = <PointingHand uid={uid} />;
  } else if (action === 'celebrate') {
    // Both arms up in a "yay"
    shoulder = { rotate: [8, -145, -135, -145, 8] };
    shoulderTx = { duration: 1.0, times: [0, 0.25, 0.5, 0.75, 1] };
    elbow = { rotate: [10, 10, 10, 10, 10] };
    elbowTx = { duration: 1.0 };
    hand = <OpenPalm uid={uid} />;
  }

  return (
    <motion.g
      key={`la-${actionKey}-${action}`}
      style={{ transformOrigin: `${SX}px ${SY}px`, transformBox: 'fill-box' as any }}
      animate={shoulder}
      transition={shoulderTx}
    >
      {/* Upper arm */}
      <rect x={SX - 3} y={SY} width="6" height="14" rx="3" fill={`url(#${uid}-limb)`} />
      <circle cx={SX} cy={SY} r="3" fill="#2a3248" stroke="rgba(139,245,199,0.3)" strokeWidth="0.5" />

      {/* Elbow + forearm */}
      <motion.g
        style={{ transformOrigin: `${SX}px ${SY + 14}px`, transformBox: 'fill-box' as any }}
        animate={elbow}
        transition={elbowTx}
      >
        <rect x={SX - 2.6} y={SY + 13} width="5.2" height="14" rx="2.6" fill={`url(#${uid}-limb)`} />
        <circle cx={SX} cy={SY + 14} r="2.2" fill="#151a28" />
        {/* Hand group — sits at the forearm tip */}
        <g transform={`translate(${SX}, ${SY + 27})`}>{hand}</g>
      </motion.g>
    </motion.g>
  );
}

/* Right arm (Lohi's right = viewer's left) — mirrored */
function RightArm({
  uid, action, actionKey,
}: { uid: string; action: LohiAction; actionKey: number }) {
  const SX = 34, SY = 70;

  let shoulder: any = { rotate: [-8, -12, -8] };
  let shoulderTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut' };
  let elbow: any = { rotate: [-10, -14, -10] };
  let elbowTx: any = { duration: 3.6, repeat: Infinity, ease: 'easeInOut', delay: 0.4 };
  let hand: React.ReactNode = <DefaultHand uid={uid} mirror />;

  if (action === 'celebrate') {
    shoulder = { rotate: [-8, 145, 135, 145, -8] };
    shoulderTx = { duration: 1.0, times: [0, 0.25, 0.5, 0.75, 1] };
    elbow = { rotate: [-10, -10, -10, -10, -10] };
    elbowTx = { duration: 1.0 };
    hand = <OpenPalm uid={uid} mirror />;
  }
  // For wave / point / thumbsUp, right arm stays idle and only left arm gestures
  // (like a real person, you use one dominant hand).

  return (
    <motion.g
      key={`ra-${actionKey}-${action}`}
      style={{ transformOrigin: `${SX}px ${SY}px`, transformBox: 'fill-box' as any }}
      animate={shoulder}
      transition={shoulderTx}
    >
      <rect x={SX - 3} y={SY} width="6" height="14" rx="3" fill={`url(#${uid}-limb)`} />
      <circle cx={SX} cy={SY} r="3" fill="#2a3248" stroke="rgba(139,245,199,0.3)" strokeWidth="0.5" />

      <motion.g
        style={{ transformOrigin: `${SX}px ${SY + 14}px`, transformBox: 'fill-box' as any }}
        animate={elbow}
        transition={elbowTx}
      >
        <rect x={SX - 2.6} y={SY + 13} width="5.2" height="14" rx="2.6" fill={`url(#${uid}-limb)`} />
        <circle cx={SX} cy={SY + 14} r="2.2" fill="#151a28" />
        <g transform={`translate(${SX}, ${SY + 27})`}>{hand}</g>
      </motion.g>
    </motion.g>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Hand shapes — small 8px-ish SVG glyphs drawn around the origin (0,0)
   ══════════════════════════════════════════════════════════════════════════ */
function DefaultHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      <circle r="3.2" cx="0" cy="0" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.35)" strokeWidth="0.4" />
    </g>
  );
}

function OpenPalm({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      {/* Palm */}
      <rect x="-3" y="-2.5" width="6" height="6" rx="2.2" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.4)" strokeWidth="0.4" />
      {/* Fingers (four tiny strokes) */}
      {[-2.2, -0.8, 0.6, 2.0].map((x) => (
        <rect key={x} x={x - 0.4} y="-5.5" width="0.8" height="3.5" rx="0.4" fill={`url(#${uid}-limb)`} />
      ))}
      {/* Thumb */}
      <rect x="2.8" y="-1" width="0.9" height="2.8" rx="0.4" fill={`url(#${uid}-limb)`} transform="rotate(-30 2.8 -1)" />
    </g>
  );
}

function ThumbsUpHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      {/* Fist */}
      <rect x="-3" y="-1.5" width="6" height="5" rx="2.2" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.4)" strokeWidth="0.4" />
      {/* Thumb sticking up */}
      <rect x="-1" y="-6" width="2" height="4.5" rx="0.9" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.5)" strokeWidth="0.4" />
      {/* Tiny sparkle */}
      <circle cx="1.8" cy="-5" r="0.6" fill="#8bf5c7">
        <animate attributeName="opacity" values="0.3;1;0.3" dur="1.2s" repeatCount="indefinite" />
      </circle>
    </g>
  );
}

function PointingHand({ uid, mirror = false }: { uid: string; mirror?: boolean }) {
  return (
    <g transform={mirror ? 'scale(-1, 1)' : undefined}>
      {/* Fist */}
      <rect x="-3" y="-2.5" width="5" height="5.5" rx="2" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.4)" strokeWidth="0.4" />
      {/* Index finger extended outward (right) */}
      <rect x="1.5" y="-1" width="5.5" height="2" rx="1" fill={`url(#${uid}-limb)`} stroke="rgba(139,245,199,0.5)" strokeWidth="0.4" />
      <circle cx="7.2" cy="0" r="0.8" fill="#8bf5c7">
        <animate attributeName="opacity" values="0.4;1;0.4" dur="1s" repeatCount="indefinite" />
      </circle>
    </g>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Mouth shapes per mood
   ══════════════════════════════════════════════════════════════════════════ */
function getMouthPath(mood: LohiMood, speaking: boolean): string {
  if (speaking) return 'M45 48 Q 50 50, 55 48';
  if (mood === 'happy') return 'M45 47 Q 50 50.5, 55 47';
  if (mood === 'focused') return 'M46 48.5 Q 50 47.5, 54 48.5';
  return 'M46 48 Q 50 48.5, 54 48';
}

/* ══════════════════════════════════════════════════════════════════════════
   Confetti — tiny burst on celebrate
   ══════════════════════════════════════════════════════════════════════════ */
function Confetti({ keyId, dim }: { keyId: number; dim: number }) {
  const bits = 18;
  const colors = ['#00d67f', '#8bf5c7', '#60a5fa', '#fbbf24', '#f472b6'];
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        left: '50%',
        top: Math.round(dim * 0.3),
        pointerEvents: 'none',
        zIndex: 5,
      }}
    >
      {Array.from({ length: bits }).map((_, i) => {
        const angle = (i / bits) * Math.PI * 2 + (keyId % 7) * 0.3;
        const dist = dim * (0.55 + Math.random() * 0.4);
        const dx = Math.cos(angle) * dist;
        const dy = Math.sin(angle) * dist - dim * 0.2;
        const c = colors[i % colors.length];
        return (
          <motion.span
            key={`${keyId}-${i}`}
            initial={{ x: 0, y: 0, opacity: 1, scale: 0.4 }}
            animate={{ x: dx, y: dy, opacity: 0, scale: 1 }}
            transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
            style={{
              position: 'absolute',
              width: 7, height: 7,
              borderRadius: i % 2 === 0 ? '50%' : '1.5px',
              background: c,
              boxShadow: `0 0 10px ${c}`,
              transform: 'translate(-50%,-50%)',
            }}
          />
        );
      })}
    </div>
  );
}
