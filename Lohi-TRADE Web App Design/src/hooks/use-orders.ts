/**
 * React Query hook for orders data.
 *
 * Wraps api.getOrders() with optional filter params
 * and syncs results into the Zustand orders store.
 *
 * Validates: Requirements 3.4
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api-client';
import type { Order } from '../lib/types';
import { useOrdersStore } from '../stores/orders-store';

export interface UseOrdersParams {
  status?: string;
  symbol?: string;
}

export function useOrders(params?: UseOrdersParams) {
  const setOrders = useOrdersStore((s) => s.setOrders);

  const { data, isLoading, error, refetch } = useQuery<Order[], Error>({
    queryKey: ['orders', params],
    queryFn: api.getOrders,
    select(orders) {
      setOrders(orders);
      return orders;
    },
  });

  return {
    orders: data ?? [],
    isLoading,
    error,
    refetch,
  };
}
