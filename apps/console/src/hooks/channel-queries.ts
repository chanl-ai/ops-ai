import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ChannelFilters, ChannelPatch } from '@/lib/types/channels';
import { useTeamQuery } from './team-query';

const ck = {
  list: (p: unknown) => ['channels', 'list', p] as const,
  live: (kind: string, id: string) => ['channels', 'live', kind, id] as const,
};

/** A page of the team's channels with one summary per kind; polled, as health and traffic move on their own. */
export const useChannels = (p: { page: number; pageSize: number } & ChannelFilters) =>
  usePagedQuery({ queryKey: ck.list(p), queryFn: () => api.channels.list(p), refetchInterval: 30_000 });

/** Every place an agent or workflow answers, with the version live there. */
export const useLivePlaces = (kind: 'agent' | 'workflow', id: string) => useTeamQuery({ queryKey: ck.live(kind, id), queryFn: () => api.channels.live(kind, id) });

export function useChangeChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ChannelPatch }) => api.channels.change(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}
