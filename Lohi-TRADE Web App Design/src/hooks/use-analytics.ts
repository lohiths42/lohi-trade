/**
 * React Query hooks for analytics data.
 *
 * Three hooks in one file:
 * - useEquityCurve()  — wraps api.getEquityCurve(), refetch every 60s
 * - useDailyPnl()     — wraps api.getDailyPnl()
 * - useStrategyPerformance() — wraps api.getStrategyPerformance()
 *
 * Validates: Requirements 3.4
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api-client';
import type { EquityCurvePoint, DailyPnL, StrategyMetrics } from '../lib/types';

const EQUITY_REFETCH_INTERVAL_MS = 60_000;

export function useEquityCurve() {
  const { data, isLoading, error, refetch } = useQuery<EquityCurvePoint[], Error>({
    queryKey: ['analytics', 'equity-curve'],
    queryFn: api.getEquityCurve,
    refetchInterval: EQUITY_REFETCH_INTERVAL_MS,
  });

  return { data: data ?? [], isLoading, error, refetch };
}

export function useDailyPnl() {
  const { data, isLoading, error } = useQuery<DailyPnL[], Error>({
    queryKey: ['analytics', 'daily-pnl'],
    queryFn: api.getDailyPnl,
  });

  return { data: data ?? [], isLoading, error };
}

export function useStrategyPerformance() {
  const { data, isLoading, error } = useQuery<StrategyMetrics[], Error>({
    queryKey: ['analytics', 'strategy-performance'],
    queryFn: api.getStrategyPerformance,
  });

  return { data: data ?? [], isLoading, error };
}
