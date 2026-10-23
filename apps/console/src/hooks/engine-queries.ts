'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { BulkResult } from '@/lib/types/domain';
import type { EngineDefinition, EngineRunInput, EngineRunsParams, OptionSource, StartWorkflowInput } from '@/lib/types/engine';
import { useTeamQuery } from './team-query';

const ek = {
  nodeTypes: ['engine', 'node-types'] as const,
  definition: (id: string, version?: number) => ['engine', 'definition', id, version ?? 'latest'] as const,
  runs: (p: EngineRunsParams = {}) => ['engine', 'runs', p] as const,
  run: (id: string) => ['engine', 'run', id] as const,
  options: (source: string) => ['engine', 'options', source] as const,
};

/** A run stops changing once it succeeds, fails or is cancelled (ops_engine.store.runs.TERMINAL). */
export const TERMINAL_RUN = ['succeeded', 'failed', 'cancelled'];

export const useNodeTypes = () => useTeamQuery({ queryKey: ek.nodeTypes, queryFn: () => api.engine.nodeTypes(), staleTime: 5 * 60_000 });

/** The latest version, or the one a run is pinned to. */
export const useDefinition = (workflowId: string, version?: number) =>
  useTeamQuery({ queryKey: ek.definition(workflowId, version), queryFn: () => api.engine.definition(workflowId, version), retry: false, enabled: !!workflowId });

/** The server's checks for the definition on screen; nothing is saved. */
export const useValidateDefinition = () => useMutation({ mutationFn: (d: EngineDefinition) => api.engine.validate(d) });

export function usePublishDefinition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (d: EngineDefinition) => api.engine.publish(d),
    onSuccess: (p) => qc.invalidateQueries({ queryKey: ['engine', 'definition', p.workflowId] }),
  });
}

/** Opens a publish request for a draft; the Workflows list and Reviews show it at once. */
export function useRequestDefinitionPublish(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { version?: number; note: string }) => api.engine.requestPublish(workflowId, input),
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ['engine', 'definition', workflowId] }),
        qc.invalidateQueries({ queryKey: ['workflows'] }),
        qc.invalidateQueries({ queryKey: ['reviews'] }),
      ]),
  });
}

export function useSetDefinitionPaused(workflowId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (paused: boolean) => api.engine.setPaused(workflowId, paused),
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: ['engine', 'definition', workflowId] }), qc.invalidateQueries({ queryKey: ['workflows'] })]),
  });
}

/** Choices for a node form field; `steps` is the definition on screen, so it is never fetched. */
export const useEngineOptions = (source: OptionSource | undefined) =>
  useTeamQuery({
    queryKey: ek.options(source ?? 'none'),
    queryFn: () => api.engine.options(source as Exclude<OptionSource, 'steps'>),
    enabled: !!source && source !== 'steps',
    staleTime: 60_000,
  });

export function useCancelEngineRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.engine.cancelRun(runId),
    onSettled: (_r, _e, runId) => Promise.all([qc.invalidateQueries({ queryKey: ek.run(runId) }), qc.invalidateQueries({ queryKey: ['engine', 'runs'] }), qc.invalidateQueries({ queryKey: ['reviews'] })]),
  });
}

export function useStartEngineRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: EngineRunInput) => api.engine.startRun(i),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engine', 'runs'] }),
  });
}

/** Starts a run from its trigger's start form: a test email, a form, whatever kind the trigger declares. */
export function useStartWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: StartWorkflowInput) => api.engine.startWorkflow(i),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engine', 'runs'] }),
  });
}

/** One page of the team's runs; polled, since workers move runs on without the page asking. */
export const useEngineRuns = (p: EngineRunsParams) =>
  usePagedQuery({ queryKey: ek.runs(p), queryFn: () => api.engine.runs(p), refetchInterval: 5_000 });

/** A run's detail, polled while a worker may still be moving it; a run waiting on a person is polled more slowly. */
export const useEngineRun = (runId: string) =>
  useTeamQuery({
    queryKey: ek.run(runId),
    queryFn: () => api.engine.run(runId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (!status || TERMINAL_RUN.includes(status)) return status ? false : 1_500;
      return status === 'waiting' ? 5_000 : 1_500;
    },
    // A run page left open in another tab still moves to the run's end, so it never shows Running after it finished.
    refetchIntervalInBackground: true,
  });

/** Deletes v2 drafts one by one; a workflow that has run comes back as skipped with the server's reason. */
export function useDeleteDefinitions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]): Promise<BulkResult> => {
      const result: BulkResult = { updated: [], skipped: [] };
      for (const id of ids) {
        try {
          await api.engine.deleteDefinition(id);
          result.updated.push(id);
        } catch (e) {
          result.skipped.push({ id, reason: e instanceof Error ? e.message : 'Not deleted' });
        }
      }
      return result;
    },
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: ['workflows'] }), qc.invalidateQueries({ queryKey: ['engine', 'definition'] })]),
  });
}
