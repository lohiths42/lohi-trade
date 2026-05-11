import { useMemo } from 'react';
import { motion } from 'motion/react';
import { TrendingUp } from 'lucide-react';
import { AnimatedNumber } from '../shared/AnimatedNumber';

/**
 * ProjectionWidget — Lohi's live Future Value sparkline.
 *
 * Given a monthly contribution, annual return, and horizon, compute the
 * compound future value month-over-month and render a sparkline that
 * animates whenever inputs change.
 *
 *   FV = Σ contribution × (1 + r/12)^(months − t)
 *
 * The chart uses a pure SVG path — no chart library needed for 24 points.
 */
export default function ProjectionWidget({
  monthly,
  annualReturnPct = 12,
  years = 10,
}: {
  monthly: number;
  annualReturnPct?: number;
  years?: number;
}) {
  const { series, future } = useMemo(() => {
    const r = annualReturnPct / 100 / 12;
    const n = Math.max(1, years * 12);
    const points: number[] = [];
    let balance = 0;
    for (let i = 0; i < n; i++) {
      balance = balance * (1 + r) + monthly;
      points.push(balance);
    }
    // Downsample to ~24 pts for the sparkline
    const step = Math.max(1, Math.floor(n / 24));
    const sparse: number[] = [];
    for (let i = 0; i < n; i += step) sparse.push(points[i]);
    if (sparse[sparse.length - 1] !== points[n - 1]) sparse.push(points[n - 1]);
    return { series: sparse, future: points[n - 1] };
  }, [monthly, annualReturnPct, years]);

  // SVG path
  const path = useMemo(() => {
    if (!series.length) return '';
    const w = 240, h = 72, pad = 2;
    const min = Math.min(...series);
    const max = Math.max(...series, min + 1);
    const range = max - min || 1;
    const step = (w - pad * 2) / Math.max(1, series.length - 1);
    const coords = series.map((v, i) => {
      const x = pad + i * step;
      const y = h - pad - ((v - min) / range) * (h - pad * 2);
      return [x, y] as const;
    });
    const d = coords
      .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
      .join(' ');
    const fill = `${d} L${(pad + (series.length - 1) * step).toFixed(1)},${h - pad} L${pad},${h - pad} Z`;
    return { d, fill };
  }, [series]);

  return (
    <div
      className="ob-glass"
      style={{
        padding: '18px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            display: 'grid',
            placeItems: 'center',
            width: 26,
            height: 26,
            borderRadius: 8,
            background: 'var(--ob-growth-soft)',
            color: 'var(--ob-growth)',
          }}
        >
          <TrendingUp size={13} />
        </span>
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
          Lohi&apos;s Projection · {years}y @ {annualReturnPct.toFixed(0)}% p.a.
        </p>
      </div>

      <motion.div
        key={future}
        initial={{ scale: 0.98 }}
        animate={{ scale: 1 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        style={{
          fontSize: 28,
          fontWeight: 800,
          letterSpacing: '-0.02em',
          color: 'var(--ob-growth)',
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1,
        }}
      >
        ₹<AnimatedNumber
          value={future}
          format={(v) => v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          durationMs={480}
          flash={false}
          color="var(--ob-growth)"
        />
      </motion.div>

      {/* Sparkline */}
      <svg viewBox="0 0 240 72" width="100%" height={72} aria-hidden style={{ display: 'block' }}>
        <defs>
          <linearGradient id="proj-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--ob-growth)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--ob-growth)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {typeof path === 'object' && (
          <>
            <motion.path
              d={path.fill}
              fill="url(#proj-fill)"
              initial={false}
              animate={{ d: path.fill }}
              transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            />
            <motion.path
              d={path.d}
              fill="none"
              stroke="var(--ob-growth)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={false}
              animate={{ d: path.d }}
              transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            />
          </>
        )}
      </svg>

      <p
        style={{
          fontSize: 11,
          color: 'var(--ob-silver-muted)',
          margin: 0,
          lineHeight: 1.55,
        }}
      >
        Projected future value at ₹{monthly.toLocaleString('en-IN')} / month,
        compounded monthly. Markets vary — this is a model, not a promise.
      </p>
    </div>
  );
}
