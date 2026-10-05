'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ChangeConflict, ChangeDecisionInput, ChangeListParams } from '@/lib/types/knowledge-changes';

/** Under 'knowledge' so a decision also refreshes knowledge base pages that show change counts. */
const ROOT = ['knowledge', 'changes'] as const;

export const useKnowledgeChanges = (p: ChangeListParams) => useQuery({ queryKey: [...ROOT, p], queryFn: () => api.knowledgeChanges.list(p), placeholderData: keepPreviousData });
export const useKnowledgeChange = (id: string | null) => useQuery({ queryKey: [...ROOT, 'one', id], queryFn: () => api.knowledgeChanges.get(id!), enabled: !!id });

export function useDecideKnowledgeChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: ChangeDecisionInput & { id: string }) => api.knowledgeChanges.decide(id, input),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ROOT }), qc.invalidateQueries({ queryKey: ['notifications'] })]),
  });
}

export function useResolveChangeConflict() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: NonNullable<ChangeConflict['resolution']> }) => api.knowledgeChanges.resolveConflict(id, resolution),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROOT }),
  });
}
