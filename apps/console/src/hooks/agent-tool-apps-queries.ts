'use client';

import { keepPreviousData, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { useTeamInfiniteQuery } from './team-query';
import { useDebounced } from './use-debounced';

/**
 * An agent's tools by app: the apps (searched, connected first, each with how many of its tools the agent holds) and
 * one app's tools, both paged by the server. The keys start with `agent`, which a tools grant refreshes, so a grant
 * made anywhere redraws the section and an open picker.
 */
const KEY = (agentId: string) => ['agent', agentId, 'tool-apps'] as const;

/** `granted: true` is the Tools section (apps the agent holds a tool of); without it, the picker's catalog. */
export function useAgentToolApps(agentId: string, p: { search?: string; granted?: boolean; limit?: number; enabled?: boolean }) {
  const search = useDebounced(p.search ?? '');
  const limit = p.limit ?? 24;
  return useTeamInfiniteQuery({
    queryKey: [...KEY(agentId), 'apps', { search, granted: p.granted ?? null, limit }],
    queryFn: ({ pageParam }) => api.agents.toolApps(agentId, { search, granted: p.granted, cursor: pageParam, limit }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
    enabled: p.enabled,
  });
}

export function useAgentToolAppTools(agentId: string, appId: string | null, p: { search?: string; granted?: boolean; limit?: number; enabled?: boolean }) {
  const search = useDebounced(p.search ?? '');
  const limit = p.limit ?? 50;
  return useTeamInfiniteQuery({
    queryKey: [...KEY(agentId), 'tools', appId, { search, granted: p.granted ?? null, limit }],
    queryFn: ({ pageParam }) => api.agents.toolAppTools(agentId, appId ?? '', { search, granted: p.granted, cursor: pageParam, limit }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
    enabled: Boolean(appId) && (p.enabled ?? true),
  });
}

/** Reads an agent's tool apps again, for after a connection is made from the picker. */
export function useRefreshAgentToolApps(agentId: string) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: KEY(agentId) });
}
