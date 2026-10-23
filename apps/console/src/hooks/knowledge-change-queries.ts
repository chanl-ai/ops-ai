'use client';


import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ChangeListParams } from '@/lib/types/knowledge-changes';
import { useTeamQuery } from './team-query';

/** Under 'knowledge' so knowledge base pages that show change counts refresh with knowledge writes. */
const ROOT = ['knowledge', 'changes'] as const;

export const useKnowledgeChanges = (p: ChangeListParams) => usePagedQuery({ queryKey: [...ROOT, p], queryFn: () => api.knowledgeChanges.list(p) });
export const useKnowledgeChange = (id: string | null) => useTeamQuery({ queryKey: [...ROOT, 'one', id], queryFn: () => api.knowledgeChanges.get(id!), enabled: !!id });
