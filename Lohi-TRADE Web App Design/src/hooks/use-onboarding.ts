import { useState, useCallback } from 'react';

const ONBOARDING_KEY = 'lohi_is_onboarded';

/**
 * Hook to manage onboarding state via localStorage.
 * Returns { isOnboarded, completeOnboarding, resetOnboarding }.
 */
export function useOnboarding() {
  const [isOnboarded, setIsOnboarded] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ONBOARDING_KEY) === 'true';
    } catch {
      return false;
    }
  });

  const completeOnboarding = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_KEY, 'true');
    } catch { /* ignore */ }
    setIsOnboarded(true);
  }, []);

  const resetOnboarding = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_KEY, 'false');
    } catch { /* ignore */ }
    setIsOnboarded(false);
  }, []);

  return { isOnboarded, completeOnboarding, resetOnboarding };
}
