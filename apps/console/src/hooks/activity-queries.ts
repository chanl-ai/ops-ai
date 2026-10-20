import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ActivityFilters } from '@/lib/types/activity';

/** A page of the workspace's activity; polled, since runs and emails keep arriving while the page is open. */
export const useActivity = (p: { page: number; pageSize: number } & ActivityFilters) =>
  useQuery({ queryKey: ['activity', p], queryFn: () => api.activity.list(p), placeholderData: keepPreviousData, refetchInterval: 10_000 });

/** How many activity rows these sources have, counted by the server (one row asked for, the total read). */
export const useActivityCount = (source: string[]) =>
  useQuery({ queryKey: ['activity', 'count', source], queryFn: async () => (await api.activity.list({ page: 1, pageSize: 1, source })).pagination.total, enabled: source.length > 0, staleTime: 30_000 });
