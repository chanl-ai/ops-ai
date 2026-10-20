'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ActionDecision, CaseFilters, CaseView, EmailWorkflowConfig, RunRowFilters, RunView, SampleMailInput, StartRunInput } from '@/lib/types/cases';
import type { ListParams } from '@/lib/types/query';

/** Every case key starts with 'cases', so one invalidation refreshes the list, the record and the view counts. */
export const ck = {
  list: (p: unknown) => ['cases', 'list', p] as const,
  one: (id: string) => ['cases', 'one', id] as const,
  queues: ['cases', 'queues'] as const,
  runs: (p: unknown) => ['cases', 'runs', p] as const,
  run: (id: string) => ['cases', 'run', id] as const,
  runState: (id: string) => ['cases', 'run-state', id] as const,
  startable: ['cases', 'startable'] as const,
};

export const useCases = (p: ListParams<CaseFilters> & { view: CaseView }) =>
  useQuery({ queryKey: ck.list(p), queryFn: () => api.cases.list(p), placeholderData: keepPreviousData });
export const useCase = (id: string) => useQuery({ queryKey: ck.one(id), queryFn: () => api.cases.get(id) });
/** Runs across every workflow for the Cases page. */
export const useCaseRuns = (p: ListParams<RunRowFilters> & { view: RunView }) =>
  useQuery({ queryKey: ck.runs(p), queryFn: () => api.cases.runs(p), placeholderData: keepPreviousData });
/** One run by id, for a `?run=` link to a run that is not on the current page. */
export const useCaseRun = (id: string | null) => useQuery({ queryKey: ck.run(id ?? ''), queryFn: () => api.cases.run(id!), enabled: !!id });
/** A run's thread state, read beside its row while its sheet or review is open. */
export const useRunState = (id: string | null) => useQuery({ queryKey: ck.runState(id ?? ''), queryFn: () => api.cases.runState(id!), enabled: !!id });
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
/** Workflows the Start run dialog offers, fetched while it is open. */
export const useStartableWorkflows = (enabled: boolean) => useQuery({ queryKey: ck.startable, queryFn: api.cases.startable, enabled, staleTime: 60_000 });
/** Starts a workflow run; resolves with its Cases row once the run stops. */
export const useStartRun = () => useWrite((input: StartRunInput) => api.cases.startRun(input));
export const useAssignRuns = () => useWrite(({ ids, assignee }: { ids: string[]; assignee: string }) => api.cases.assignRuns(ids, assignee));
export const useCloseCases = () => useWrite(({ ids, reason }: { ids: string[]; reason: string }) => api.cases.close(ids, reason));
export const useDecideAction = (caseId: string) =>
  useWrite(({ actionId, decision, reason }: { actionId: string; decision: ActionDecision; reason?: string }) => api.cases.decideAction(caseId, actionId, { decision, reason }));
export const useEditAction = (caseId: string) => useWrite(({ actionId, input }: { actionId: string; input: string }) => api.cases.editAction(caseId, actionId, input));
export const useTestSampleMail = () => useMutation({ mutationFn: ({ config, input }: { config: EmailWorkflowConfig; input: SampleMailInput }) => api.cases.testSampleMail(config, input) });
