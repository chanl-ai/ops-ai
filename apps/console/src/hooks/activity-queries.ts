
import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ActivityFilters } from '@/lib/types/activity';
import { useTeamQuery } from './team-query';

/** A page of the workspace's activity; polled, since runs and emails keep arriving while the page is open. */
export const useActivity = (p: { page: number; pageSize: number } & ActivityFilters) =>
  usePagedQuery({ queryKey: ['activity', p], queryFn: () => api.activity.list(p), refetchInterval: 10_000 });

/** How many activity rows these sources have, counted by the server (one row asked for, the total read). */
export const useActivityCount = (source: string[]) =>
  useTeamQuery({ queryKey: ['activity', 'count', source], queryFn: async () => (await api.activity.list({ page: 1, pageSize: 1, source })).pagination.total, enabled: source.length > 0, staleTime: 30_000 });

/** Every background process and the latest jobs, for an account admin's Govern > Background page; polled like Activity. */
export const useBackground = () => useTeamQuery({ queryKey: ['activity', 'background'], queryFn: () => api.activity.background(), refetchInterval: 10_000, retry: false });
