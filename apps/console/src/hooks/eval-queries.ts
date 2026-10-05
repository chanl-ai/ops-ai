'use client';

import * as React from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { EvalCaseFilters, EvalCaseInput, EvalRunFilters, SaveTurnInput } from '@/lib/types/evals';
import type { ListParams } from '@/lib/types/query';

/** Eval keys sit under the agent's key, so saving the agent (which starts a run) refreshes them too. */
export const ek = {
  root: (agentId: string) => ['agent', agentId, 'evals'] as const,
  suites: (agentId: string) => ['agent', agentId, 'evals', 'suites'] as const,
  cases: (agentId: string, p: unknown) => ['agent', agentId, 'evals', 'cases', p] as const,
  runs: (agentId: string, p: unknown) => ['agent', agentId, 'evals', 'runs', p] as const,
  run: (runId: string) => ['eval-run', runId] as const,
  latest: (agentId: string) => ['agent', agentId, 'evals', 'latest'] as const,
  options: (agentId: string) => ['agent', agentId, 'evals', 'options'] as const,
};

const paged = { placeholderData: keepPreviousData };

export const useEvalSuites = (agentId: string) => useQuery({ queryKey: ek.suites(agentId), queryFn: () => api.evals.suites(agentId) });
export const useEvalCases = (agentId: string, p: ListParams<EvalCaseFilters>) => useQuery({ queryKey: ek.cases(agentId, p), queryFn: () => api.evals.cases(agentId, p), ...paged });
export const useEvalRuns = (agentId: string, p: ListParams<EvalRunFilters>) => useQuery({ queryKey: ek.runs(agentId, p), queryFn: () => api.evals.runs(agentId, p), ...paged });
export const useEvalRun = (runId: string | null) =>
  useQuery({ queryKey: ek.run(runId ?? ''), queryFn: () => api.evals.getRun(runId!), enabled: !!runId, refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false) });
export const useEvalOptions = (agentId: string) => useQuery({ queryKey: ek.options(agentId), queryFn: () => api.evals.options(agentId), staleTime: 60_000 });

/**
 * The newest run, polled while it runs. When it completes, everything else on the Evals tab (suites, case
 * outcomes, history) and the agent's version history refresh once.
 */
export function useLatestEvalRun(agentId: string) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ek.latest(agentId), queryFn: () => api.evals.latest(agentId), refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false) });
  const status = query.data?.status;
  const prev = React.useRef(status);
  React.useEffect(() => {
    if (prev.current === 'running' && status === 'complete') {
      qc.invalidateQueries({ queryKey: ['agent', agentId] });
      qc.invalidateQueries({ queryKey: ['model-risk'] });
    }
    prev.current = status;
  }, [status, agentId, qc]);
  return query;
}

function useEvalWrite<A, R>(agentId: string, fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ek.root(agentId) }) });
}

export const useCreateEvalCase = (agentId: string) => useEvalWrite(agentId, (i: EvalCaseInput) => api.evals.createCase(agentId, i));
export const useImportEvalCases = (agentId: string) => useEvalWrite(agentId, (rows: EvalCaseInput[]) => api.evals.importCases(agentId, rows));
export const useEvalCaseFromTurn = (agentId: string) => useEvalWrite(agentId, (i: SaveTurnInput) => api.evals.caseFromTurn(agentId, i));
export const useDeleteEvalCase = (agentId: string) => useEvalWrite(agentId, (id: string) => api.evals.removeCase(id));
export const useBulkDeleteEvalCases = (agentId: string) => useEvalWrite(agentId, (ids: string[]) => api.evals.bulkRemoveCases(ids));
export const useRunEvals = (agentId: string) => useEvalWrite(agentId, () => api.evals.run(agentId));
