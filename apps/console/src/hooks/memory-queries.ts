'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { useTeamQuery } from './team-query';

/** Under 'chat' so a reply that saved something (chat invalidates its root) refreshes the list too. */
export const mk = { list: (agentId?: string) => ['chat', 'memories', agentId ?? 'all'] as const };

export const useMemories = (agentId?: string) => useTeamQuery({ queryKey: mk.list(agentId), queryFn: () => api.chat.memories.list(agentId) });

function useMemoryWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', 'memories'] }) });
}

export const useCorrectMemory = () => useMemoryWrite(({ id, value }: { id: string; value: string }) => api.chat.memories.correct(id, value));
export const useForgetMemory = () => useMemoryWrite((id: string) => api.chat.memories.forget(id));
export const useForgetAgentMemories = () => useMemoryWrite((agentId: string) => api.chat.memories.forgetAgent(agentId));
/** Export records an audit row, so it is a mutation, not a cached read. */
export const useExportMemories = () => useMutation({ mutationFn: () => api.chat.memories.exportAll() });
