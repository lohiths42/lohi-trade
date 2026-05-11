/**
 * React Query hook for positions data.
 *
 * Wraps api.getPositions() with auto-refetch every 30 seconds
 * and syncs results into the Zustand positions store.
 *
 * Validates: Requirements 3.4
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api-client';
import type { Position } from '../lib/types';
import { usePositionsStore } from '../stores/positions-store';

const REFETCH_INTERVAL_MS = 30_000;

export function usePositions() {
  const setPositions = usePositionsStore((s) => s.setPositions);

  const { data, isLoading, error, refetch } = useQuery<Position[], Error>({
    queryKey: ['positions'],
    queryFn: api.getPositions,
    refetchInterval: REFETCH_INTERVAL_MS,
    select(positions) {
      setPositions(positions);
      return positions;
    },
  });

  return {
    positions: data ?? [],
    isLoading,
    error,
    refetch,
  };
}
