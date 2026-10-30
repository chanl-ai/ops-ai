import type { BatchDryRun, BatchInput, BatchStarted, BatchView } from '@/lib/types/batches';

/**
 * Batches (c-535): a workflow started once per row of a CSV or Excel file, followed on its own page. The file is
 * uploaded to Files first and passed by id. agents-service's routers/batches.py.
 */
export interface BatchesApi {
  /** Starts nothing. 422 `batch_too_many_rows` over 500 rows, 422 `batch_no_matching_columns` when no column names an input. */
  dryRun(workflowId: string, input: BatchInput): Promise<BatchDryRun>;
  /** Writes the batch; the workflow worker starts its rows a few at a time. Same refusals as the dry run. */
  start(workflowId: string, input: BatchInput): Promise<BatchStarted>;
  get(batchId: string): Promise<BatchView>;
  /** A new attempt for each failed row only. */
  retryFailed(batchId: string): Promise<{ retried: number }>;
  /** Every row as a CSV, fetched with the person's identity and handed back as a link the page can download. */
  resultsCsv(batchId: string): Promise<{ url: string; name: string }>;
}
