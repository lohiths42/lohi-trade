import { motion } from 'motion/react';
import type { ReactNode } from 'react';
import { revealVariants } from '../../lib/motion';

/**
 * PageHeader — the standard page-top bar used across all routes.
 *
 * Features:
 *   • Motion reveal on mount
 *   • Sticky glass surface on scroll
 *   • Optional icon tile, subtitle, and right-side action slot
 *   • Responsive: actions collapse under the title on narrow screens
 *
 * Usage:
 *   <PageHeader
 *     icon={<BarChart3 size={16} />}
 *     title="Analytics"
 *     subtitle="Trade statistics, returns, and risk metrics"
 *     actions={<Button>Export CSV</Button>}
 *   />
 */
export default function PageHeader({
  icon, title, subtitle, actions,
}: {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <motion.div
      variants={revealVariants}
      initial="hidden"
      animate="visible"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 20,
        margin: '-28px -28px 0',
        padding: '16px 28px',
        background: 'color-mix(in srgb, var(--surface-1) 78%, transparent)',
        backdropFilter: 'saturate(140%) blur(14px)',
        WebkitBackdropFilter: 'saturate(140%) blur(14px)',
        borderBottom: '1px solid var(--line-2)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        {icon && (
          <div
            aria-hidden
            style={{
              width: 36, height: 36, borderRadius: 'var(--r-sm)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'color-mix(in srgb, var(--accent) 14%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent) 22%, transparent)',
              color: 'var(--accent-2)',
              flexShrink: 0,
            }}
          >
            {icon}
          </div>
        )}
        <div style={{ minWidth: 0 }}>
          <h1
            style={{
              fontSize: 20, fontWeight: 700, margin: 0,
              letterSpacing: '-0.02em', color: 'var(--fg-primary)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}
          >
            {title}
          </h1>
          {subtitle && (
            <p style={{
              fontSize: 12, margin: '2px 0 0', color: 'var(--fg-muted)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {actions}
        </div>
      )}
    </motion.div>
  );
}
