import { useEffect, useState } from 'react';
import { Smartphone, Shield } from 'lucide-react';
import { useBreakpoint } from '../../hooks/use-breakpoint';

/**
 * MobileOrderGuard — wraps order-submission UI and disables it on narrow
 * viewports unless the user has explicitly opted in via Settings.
 *
 * Rationale (platform spec):
 *   "Mobile: < 640px — read-only mode for safety (no order placement from
 *    narrow viewports by default; configurable)"
 *
 * The opt-in flag lives in localStorage under `lohi.allowMobileOrders`.
 * Settings page should expose a Switch that writes this flag.
 *
 * Usage:
 *   <MobileOrderGuard>
 *     <Button type="submit">Place order</Button>
 *   </MobileOrderGuard>
 */
const STORAGE_KEY = 'lohi.allowMobileOrders';

export function isMobileOrdersAllowed(): boolean {
  if (typeof window === 'undefined') return true;
  return localStorage.getItem(STORAGE_KEY) === '1';
}

export function setMobileOrdersAllowed(allowed: boolean): void {
  try { localStorage.setItem(STORAGE_KEY, allowed ? '1' : '0'); } catch { /* ignore */ }
}

export default function MobileOrderGuard({
  children,
  message = 'Order placement is disabled on narrow viewports. Enable it in Settings → Preferences.',
}: {
  children: React.ReactNode;
  message?: string;
}) {
  const { isMobile } = useBreakpoint(640);
  const [allowed, setAllowed] = useState<boolean>(() => isMobileOrdersAllowed());

  // Listen for storage changes so toggling in another tab updates immediately.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setAllowed(e.newValue === '1');
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  if (!isMobile || allowed) return <>{children}</>;

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 14px',
        borderRadius: 'var(--r-md)',
        background: 'var(--warn-soft)',
        border: '1px solid color-mix(in srgb, var(--warn) 30%, transparent)',
        color: 'var(--fg-secondary)',
        fontSize: 12,
        lineHeight: 1.5,
      }}
    >
      <div
        style={{
          padding: 6,
          borderRadius: 8,
          background: 'color-mix(in srgb, var(--warn) 18%, transparent)',
          color: 'var(--warn)',
          flexShrink: 0,
          display: 'flex',
        }}
      >
        <Smartphone size={14} />
      </div>
      <div style={{ flex: 1 }}>
        <strong style={{ color: 'var(--fg-primary)', fontWeight: 600, marginRight: 4 }}>
          <Shield size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />
          Safety mode
        </strong>
        {message}
      </div>
    </div>
  );
}
