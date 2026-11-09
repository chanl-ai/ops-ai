'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ChangeDecisionInput, ChangeListParams } from '@/lib/types/knowledge-changes';
import { useTeamQuery } from './team-query';

/** Under 'knowledge' so knowledge base pages that show change counts refresh with knowledge writes. */
const ROOT = ['knowledge', 'changes'] as const;

export const useKnowledgeChanges = (p: ChangeListParams) => usePagedQuery({ queryKey: [...ROOT, p], queryFn: () => api.knowledgeChanges.list(p) });
export const useKnowledgeChange = (id: string | null) => useTeamQuery({ queryKey: [...ROOT, 'one', id], queryFn: () => api.knowledgeChanges.get(id!), enabled: !!id });

function useChangeWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  // Under 'knowledge': an approved pair is searchable at once, so base counts and item questions refresh too.
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['knowledge'] }) });
}

export const useDecideChanges = () => useChangeWrite((i: ChangeDecisionInput) => api.knowledgeChanges.decide(i));
export const useEditChange = () => useChangeWrite(({ id, question, answer }: { id: string; question: string; answer: string }) => api.knowledgeChanges.edit(id, { question, answer }));
