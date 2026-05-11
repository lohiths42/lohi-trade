import { useEffect, useState } from 'react';

/**
 * useBreakpoint — responsive breakpoint hook powered by matchMedia.
 *
 * Returns whether the viewport is below the given breakpoint (mobile).
 * Default breakpoint matches the platform spec: < 640px is "mobile".
 *
 * Used by the mobile read-only guard — below 640px, order submit buttons
 * are disabled unless the user explicitly enables narrow-viewport trading
 * in Settings.
 */
export function useBreakpoint(minWidthPx = 640): { isMobile: boolean; isDesktop: boolean } {
  const [isDesktop, setIsDesktop] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    return window.matchMedia(`(min-width: ${minWidthPx}px)`).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(`(min-width: ${minWidthPx}px)`);
    const handler = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    // Safari < 14 uses addListener; modern browsers use addEventListener
    if (mq.addEventListener) mq.addEventListener('change', handler);
    else mq.addListener(handler);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', handler);
      else mq.removeListener(handler);
    };
  }, [minWidthPx]);

  return { isMobile: !isDesktop, isDesktop };
}
