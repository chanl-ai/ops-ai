'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { CreateFromTemplateInput, TemplateFilters, TemplateSubmissionInput } from '@/lib/types/templates';

/** Template keys start with 'templates'; creating an agent from one also refreshes agents and evals. */
export const tk = {
  list: (p: unknown) => ['templates', 'list', p] as const,
  one: (id: string) => ['templates', 'one', id] as const,
};

export const useTemplates = (p: ListParams<TemplateFilters>, enabled = true) => useQuery({ queryKey: tk.list(p), queryFn: () => api.templates.list(p), placeholderData: keepPreviousData, enabled });
export const useTemplate = (id: string | null) => useQuery({ queryKey: tk.one(id ?? ''), queryFn: () => api.templates.get(id!), enabled: !!id });

export function useCreateFromTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: CreateFromTemplateInput) => api.templates.createAgent(i),
    onSuccess: () => Promise.all(['templates', 'agents', 'agent', 'overview', 'tools', 'skills'].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  });
}

export function useSubmitTemplate() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: TemplateSubmissionInput) => api.templates.submit(i), onSuccess: () => Promise.all(['templates', 'reviews', 'logs', 'notifications'].map((k) => qc.invalidateQueries({ queryKey: [k] }))) });
}
