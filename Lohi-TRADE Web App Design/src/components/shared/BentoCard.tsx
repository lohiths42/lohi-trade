import { motion, type HTMLMotionProps } from 'motion/react';
import { forwardRef } from 'react';
import { revealVariants } from '../../lib/motion';

interface BentoCardProps extends HTMLMotionProps<'div'> {
  /** Grid span — mirrors CSS grid-column / grid-row. */
  colSpan?: number;
  rowSpan?: number;
  /** Reveal on scroll (IntersectionObserver under the hood). */
  reveal?: boolean;
  /** Subtle accent glow in corner. */
  accent?: 'indigo' | 'emerald' | 'rose' | 'cyan' | 'none';
}

const ACCENT_GLOW: Record<NonNullable<BentoCardProps['accent']>, string> = {
  indigo:  'radial-gradient(circle at 100% 0%, rgba(99,102,241,0.18), transparent 50%)',
  emerald: 'radial-gradient(circle at 100% 0%, rgba(0,227,140,0.16), transparent 50%)',
  rose:    'radial-gradient(circle at 100% 0%, rgba(255,77,109,0.16), transparent 50%)',
  cyan:    'radial-gradient(circle at 100% 0%, rgba(34,211,238,0.16), transparent 50%)',
  none:    'none',
};

/**
 * BentoCard — the atomic container of the 2026 dashboard.
 * Adds a subtle corner glow, bordered hairline, lift-on-hover, and an
 * optional scroll-reveal. All animations are transform/opacity only.
 */
export const BentoCard = forwardRef<HTMLDivElement, BentoCardProps>(
  ({ colSpan, rowSpan, reveal = false, accent = 'none', className, style, children, ...rest }, ref) => {
    const gridStyle: React.CSSProperties = {
      gridColumn: colSpan ? `span ${colSpan}` : undefined,
      gridRow: rowSpan ? `span ${rowSpan}` : undefined,
      backgroundImage: accent !== 'none' ? ACCENT_GLOW[accent] : undefined,
      ...style,
    };

    const motionProps = reveal
      ? {
          variants: revealVariants,
          initial: 'hidden' as const,
          whileInView: 'visible' as const,
          viewport: { once: true, margin: '-80px' },
        }
      : {};

    return (
      <motion.div
        ref={ref}
        className={`lt-bento ${className ?? ''}`}
        style={gridStyle}
        {...motionProps}
        {...rest}
      >
        {children}
      </motion.div>
    );
  },
);

BentoCard.displayName = 'BentoCard';
