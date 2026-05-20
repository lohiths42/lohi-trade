/**
 * useFeatureGate — Hook for checking feature availability based on
 * service configuration status.
 *
 * Fetches service health from `/api/health/services` and provides
 * an `isFeatureAvailable(featureName)` function for use in components.
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 * Design: §Graceful Degradation
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { ServiceStatus, SetupStatusResponse } from '../lib/setup-types';

// ── Feature Dependency Map (mirrors backend FEATURE_DEPENDENCIES) ───────────

const FEATURE_DEPENDENCIES: Record<string, string[]> = {
  research_dashboard: ['nvidia_nim|ollama'],
  ai_analysis: ['nvidia_nim|ollama'],
  research_dashboard_local: ['ollama'],
  ai_analysis_local: ['ollama'],
  live_market_data: ['nubra'],
  real_time_quotes: ['nubra'],
  tick_streaming: ['nubra'],
  live_trading: ['broker_shoonya|broker_angelone'],
  order_execution: ['broker_shoonya|broker_angelone'],
  telegram_notifications: ['telegram'],
};

// ── Hook ────────────────────────────────────────────────────────────────────

export interface FeatureGateState {
  /** Whether the service health data has been loaded */
  loading: boolean;
  /** Error message if the fetch failed */
  error: string | null;
  /** All service statuses from the backend */
  services: ServiceStatus[];
  /** Whether initial setup has been completed */
  setupComplete: boolean;
  /** Check if a specific feature is available */
  isFeatureAvailable: (featureName: string) => boolean;
  /** Get the service name that a feature depends on (for banner display) */
  getRequiredServiceName: (featureName: string) => string | null;
  /** Get all unconfigured services */
  getUnconfiguredServices: () => ServiceStatus[];
  /** Refresh the service health data */
  refresh: () => Promise<void>;
}

const BASE_URL: string =
  ((import.meta as any).env?.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

export function useFeatureGate(): FeatureGateState {
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [setupComplete, setSetupComplete] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const response = await fetch(`${BASE_URL}/api/health/services`);
      if (!response.ok) {
        // If the endpoint isn't available, assume all features are available
        // (graceful degradation of the degradation check itself)
        setLoading(false);
        return;
      }
      const data: SetupStatusResponse = await response.json();
      setServices(data.services);
      setSetupComplete(data.setup_complete);
      setError(null);
    } catch (err) {
      // Network error — don't block the app, just log
      setError('Unable to fetch service health');
      console.warn('[useFeatureGate] Failed to fetch /api/health/services:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const isFeatureAvailable = useCallback(
    (featureName: string): boolean => {
      const deps = FEATURE_DEPENDENCIES[featureName];
      if (!deps) return true; // Unknown features are assumed available

      // If we haven't loaded services yet, assume available (don't block UI)
      if (services.length === 0 && loading) return true;

      for (const depExpr of deps) {
        const alternatives = depExpr.split('|').map((s) => s.trim());
        const satisfied = alternatives.some((groupId) => {
          const svc = services.find((s) => s.group_id === groupId);
          return svc?.status === 'configured';
        });
        if (!satisfied) return false;
      }
      return true;
    },
    [services, loading],
  );

  const getRequiredServiceName = useCallback(
    (featureName: string): string | null => {
      const deps = FEATURE_DEPENDENCIES[featureName];
      if (!deps) return null;

      for (const depExpr of deps) {
        const alternatives = depExpr.split('|').map((s) => s.trim());
        const satisfied = alternatives.some((groupId) => {
          const svc = services.find((s) => s.group_id === groupId);
          return svc?.status === 'configured';
        });
        if (!satisfied) {
          // Return the name of the first alternative service
          const firstAlt = alternatives[0];
          const svc = services.find((s) => s.group_id === firstAlt);
          return svc?.name ?? firstAlt;
        }
      }
      return null;
    },
    [services],
  );

  const getUnconfiguredServices = useCallback((): ServiceStatus[] => {
    return services.filter((s) => s.status === 'unconfigured' || s.status === 'error');
  }, [services]);

  return useMemo(
    () => ({
      loading,
      error,
      services,
      setupComplete,
      isFeatureAvailable,
      getRequiredServiceName,
      getUnconfiguredServices,
      refresh: fetchHealth,
    }),
    [loading, error, services, setupComplete, isFeatureAvailable, getRequiredServiceName, getUnconfiguredServices, fetchHealth],
  );
}

export default useFeatureGate;
