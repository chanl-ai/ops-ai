'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { BatchInput } from '@/lib/types/batches';
import { useTeamQuery } from './team-query';

const key = (batchId: string) => ['batches', batchId] as const;

/** The dry run of a file against a workflow's inputs: the count, the mapping and the first rows. Starts nothing. */
export const useBatchDryRun = (workflowId: string) => useMutation({ mutationFn: (input: BatchInput) => api.batches.dryRun(workflowId, input) });

/** Starts one run per row of the file; the worker starts them a few at a time. */
export const useStartBatch = (workflowId: string) => useMutation({ mutationFn: (input: BatchInput) => api.batches.start(workflowId, input) });

/** A batch's counts and rows, polled while any row is still waiting to start or running. */
export const useBatch = (batchId: string) =>
  useTeamQuery({
    queryKey: key(batchId),
    queryFn: () => api.batches.get(batchId),
    refetchInterval: (q) => {
      const b = q.state.data;
      if (!b) return false;
      return b.pending > 0 || b.running > 0 ? 2_000 : false;
    },
    // A batch page left open in another tab still reaches the batch's end.
    refetchIntervalInBackground: true,
  });

/** Starts each failed row again; the page polls until those runs end. */
export function useRetryBatch(batchId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.batches.retryFailed(batchId), onSuccess: () => qc.invalidateQueries({ queryKey: key(batchId) }) });
}

/** The batch's results as a CSV link to download. */
export const useBatchResultsCsv = (batchId: string) => useMutation({ mutationFn: () => api.batches.resultsCsv(batchId) });
