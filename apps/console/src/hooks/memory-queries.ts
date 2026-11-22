'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import { usePagedQuery } from './paged-query';

/** What one page of the memory list asks the server for: the page, the words typed and one agent's memories. */
export interface MemoryAsk {
  page: number;
  pageSize: number;
  search?: string;
  agentId?: string;
}

/** Under 'chat' so a reply that saved something (chat invalidates its root) refreshes the list too. */
export const mk = { list: (ask: MemoryAsk) => ['chat', 'memories', ask] as const };

/** One page of what agents remember about the person, searched and filtered by agent on the server. */
export const useMemories = (ask: MemoryAsk) => usePagedQuery({ queryKey: mk.list(ask), queryFn: () => sdk((ops) => ops.raw.agents.memory_list_memories({ query: ask })) });

function useMemoryWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', 'memories'] }) });
}

export const useCorrectMemory = () => useMemoryWrite(({ id, value }: { id: string; value: string }) => api.chat.memories.correct(id, value));
export const useForgetMemory = () => useMemoryWrite((id: string) => api.chat.memories.forget(id));
/** Yes and No on a suggestion under a reply. */
export const useConfirmMemory = () => useMemoryWrite((id: string) => api.chat.memories.keep(id));
export const useDismissMemory = () => useMemoryWrite((id: string) => api.chat.memories.undo(id));
export const useForgetAgentMemories = () => useMemoryWrite((agentId: string) => api.chat.memories.forgetAgent(agentId));
/** Export records an audit row, so it is a mutation, not a cached read. */
export const useExportMemories = () => useMutation({ mutationFn: () => api.chat.memories.exportAll() });
