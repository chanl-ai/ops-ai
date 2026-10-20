'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ChangeListParams } from '@/lib/types/knowledge-changes';

/** Under 'knowledge' so knowledge base pages that show change counts refresh with knowledge writes. */
const ROOT = ['knowledge', 'changes'] as const;

export const useKnowledgeChanges = (p: ChangeListParams) => useQuery({ queryKey: [...ROOT, p], queryFn: () => api.knowledgeChanges.list(p), placeholderData: keepPreviousData });
export const useKnowledgeChange = (id: string | null) => useQuery({ queryKey: [...ROOT, 'one', id], queryFn: () => api.knowledgeChanges.get(id!), enabled: !!id });
