'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { BulkResult } from '@/lib/types/domain';
import type { EvalCaseInput } from '@/lib/types/evals';
import type { ListParams } from '@/lib/types/query';
import { useTeamQuery } from './team-query';

/** Eval keys sit under the agent's key, so a write that changes the agent's evals refreshes them all at once. */
export const ek = {
  root: (agentId: string) => ['agent', agentId, 'evals'] as const,
  cases: (agentId: string) => ['agent', agentId, 'evals', 'cases'] as const,
  runs: (agentId: string, p: unknown) => ['agent', agentId, 'evals', 'runs', p] as const,
  latest: (agentId: string) => ['agent', agentId, 'evals', 'latest'] as const,
  run: (runId: string) => ['eval-run', runId] as const,
};

export const useEvalCases = (agentId: string) => useTeamQuery({ queryKey: ek.cases(agentId), queryFn: () => api.evals.cases(agentId) });
export const useEvalRuns = (agentId: string, p: ListParams) => usePagedQuery({ queryKey: ek.runs(agentId, p), queryFn: () => api.evals.runs(agentId, p) });
export const useEvalRun = (runId: string | null) => useTeamQuery({ queryKey: ek.run(runId ?? ''), queryFn: () => api.evals.getRun(runId!), enabled: !!runId });

/** The newest kept run with its results: the id from page 1 of the runs list at a page size of 1, then the single read; null when none has run. */
export const useLatestEvalRun = (agentId: string) =>
  useTeamQuery({ queryKey: ek.latest(agentId), queryFn: async () => {
      const newest = (await api.evals.runs(agentId, { page: 1, pageSize: 1 })).data[0];
      return newest ? api.evals.getRun(newest.id) : null;
    },
  });

function useEvalWrite<A, R>(agentId: string, fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // A finished run changes the agent's version history and model risk's eval lines too.
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ek.root(agentId) }), qc.invalidateQueries({ queryKey: ['agent', agentId] }), qc.invalidateQueries({ queryKey: ['model-risk'] })]),
  });
}

export const useAddEvalCases = (agentId: string) => useEvalWrite(agentId, (cases: EvalCaseInput[]) => api.evals.addCases(agentId, cases));
export const useDeleteEvalCase = (agentId: string) => useEvalWrite(agentId, (id: string) => api.evals.removeCase(id));
export const useRunEvals = (agentId: string) => useEvalWrite(agentId, () => api.evals.run(agentId));

/** Deletes cases one by one; one the service refuses comes back as skipped with its reason. */
export const useBulkDeleteEvalCases = (agentId: string) =>
  useEvalWrite(agentId, async (ids: string[]): Promise<BulkResult> => {
    const result: BulkResult = { updated: [], skipped: [] };
    for (const id of ids) {
      try {
        await api.evals.removeCase(id);
        result.updated.push(id);
      } catch (e) {
        result.skipped.push({ id, reason: e instanceof Error ? e.message : 'Not deleted' });
      }
    }
    return result;
  });
