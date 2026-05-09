import { useEffect, useRef, memo } from 'react';
import { animate, useMotionValue, useTransform, motion, useReducedMotion } from 'motion/react';

/**
 * AnimatedNumber — spring-interpolated numeric ticker for LTP / P&L.
 *
 * Performance contract:
 *   • Uses MotionValue, so the DOM text node updates WITHOUT re-rendering React.
 *   • Flash pulse is driven by CSS class swap, not Framer layout animation.
 *   • Safe to mount hundreds of these (one per watchlist row) at 20+ Hz tick rate.
 *
 * Usage:
 *   <AnimatedNumber value={ltp} format={(v) => `₹${v.toFixed(2)}`} />
 */
interface Props {
  /** Target number. Changes are interpolated over `durationMs`. */
  value: number;
  /** How to render the number. Receives the live interpolated value. */
  format?: (v: number) => string;
  /** Animation duration (ms). Keep short for tick data. */
  durationMs?: number;
  /** Emit an upward-pulse class when value increases, downward on decrease. */
  flash?: boolean;
  /** Optional className forwarded to the <motion.span>. */
  className?: string;
  /** Force a specific color (overrides bull/bear). */
  color?: string;
  /** If true, render in bull green when >= 0 and bear red when < 0. */
  semanticColor?: boolean;
}

function AnimatedNumberImpl({
  value,
  format = (v) => v.toFixed(2),
  durationMs = 320,
  flash = true,
  className,
  color,
  semanticColor = false,
}: Props) {
  const mv = useMotionValue(value);
  const display = useTransform(mv, (v) => format(v));
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  const reduce = useReducedMotion();

  useEffect(() => {
    const from = prev.current;
    prev.current = value;

    if (reduce || Math.abs(from - value) < Number.EPSILON) {
      mv.set(value);
      return;
    }

    // GPU-friendly: animate a MotionValue, not React state.
    const controls = animate(mv, value, {
      duration: durationMs / 1000,
      ease: [0.22, 1, 0.36, 1],
    });

    // Cheap CSS flash — no React re-render, no Framer layout.
    if (flash && ref.current) {
      const el = ref.current;
      const cls = value > from ? 'lt-flash-up' : 'lt-flash-down';
      el.classList.remove('lt-flash-up', 'lt-flash-down');
      // force reflow so animation restarts
      void el.offsetWidth;
      el.classList.add(cls);
    }

    return () => controls.stop();
  }, [value, durationMs, flash, mv, reduce]);

  const resolvedColor =
    color ?? (semanticColor ? (value >= 0 ? 'var(--bull)' : 'var(--bear)') : undefined);

  return (
    <motion.span
      ref={ref}
      className={`lt-tabular ${className ?? ''}`}
      style={{ color: resolvedColor, display: 'inline-block', willChange: 'contents' }}
    >
      {display}
    </motion.span>
  );
}

/** Memoized — value-equality prevents useless re-mounts from parent re-renders. */
export const AnimatedNumber = memo(AnimatedNumberImpl, (a, b) =>
  a.value === b.value &&
  a.durationMs === b.durationMs &&
  a.flash === b.flash &&
  a.color === b.color &&
  a.semanticColor === b.semanticColor &&
  a.className === b.className &&
  a.format === b.format,
);
