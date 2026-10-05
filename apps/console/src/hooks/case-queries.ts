'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ActionDecision, CaseFilters, CaseView, EmailWorkflowConfig, SampleMailInput } from '@/lib/types/cases';
import type { ListParams } from '@/lib/types/query';

/** Every case key starts with 'cases', so one invalidation refreshes the list, the record and the view counts. */
export const ck = {
  list: (p: unknown) => ['cases', 'list', p] as const,
  one: (id: string) => ['cases', 'one', id] as const,
  queues: ['cases', 'queues'] as const,
};

export const useCases = (p: ListParams<CaseFilters> & { view: CaseView }) =>
  useQuery({ queryKey: ck.list(p), queryFn: () => api.cases.list(p), placeholderData: keepPreviousData });
export const useCase = (id: string) => useQuery({ queryKey: ck.one(id), queryFn: () => api.cases.get(id) });
export const useCaseQueues = () => useQuery({ queryKey: ck.queues, queryFn: api.cases.queues, staleTime: 60_000 });

/** Case writes change the Overview counts too. */
function useWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(['cases', 'overview'].map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

export const useSetCaseField = (id: string) => useWrite(({ key, value }: { key: string; value: string }) => api.cases.setField(id, key, value));
export const useAssignCases = () => useWrite(({ ids, assignee }: { ids: string[]; assignee: string }) => api.cases.assign(ids, assignee));
export const useCloseCases = () => useWrite(({ ids, reason }: { ids: string[]; reason: string }) => api.cases.close(ids, reason));
export const useDecideAction = (caseId: string) =>
  useWrite(({ actionId, decision, reason }: { actionId: string; decision: ActionDecision; reason?: string }) => api.cases.decideAction(caseId, actionId, { decision, reason }));
export const useEditAction = (caseId: string) => useWrite(({ actionId, input }: { actionId: string; input: string }) => api.cases.editAction(caseId, actionId, input));
export const useTestSampleMail = () => useMutation({ mutationFn: ({ config, input }: { config: EmailWorkflowConfig; input: SampleMailInput }) => api.cases.testSampleMail(config, input) });
