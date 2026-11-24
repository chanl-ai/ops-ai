/** Live runs the live version; test runs the latest saved version. */
export type BatchMode = 'live' | 'test';

/** Starting a workflow once per row of a CSV or Excel file already uploaded to Files. */
export interface BatchInput {
  fileId: string;
  mode: BatchMode;
}

/** What a dry run shows before anything starts: the row count, how the header maps to inputs and the first rows. */
export interface BatchDryRun {
  rows: number;
  /** Each column of the header that names an input, and the input's key. */
  mapping: Record<string, string>;
  /** Columns that name no input, left out of every run. */
  ignored: string[];
  /** The first 5 rows as the runs will get them, keyed by input. */
  sample: Record<string, unknown>[];
}

export interface BatchStarted {
  id: string;
  total: number;
}

/** One row of the file: its latest attempt and, once started, its run. */
export interface BatchRow {
  /** 1-based row of the file, after the header. */
  row: number;
  attempt: number;
  /** `pending` until its run starts, then the run's own status; `removed` or `failed` for a check's file that never ran. */
  status: string;
  /** Why a check's file never ran: `too_large` or `fetch_failed`, with `reason` in words. */
  failureCode?: string | null;
  reason?: string | null;
  outcome: string | null;
  output: unknown;
  error: string | null;
  runId: string | null;
  input: Record<string, unknown>;
}

/** A batch's page: counts computed by the API and every row, failed first. */
export interface BatchView {
  id: string;
  workflowId: string;
  /** `upload`: a spreadsheet's rows. `check`: one check of a watched folder, whose label is `fileName`. */
  origin: 'upload' | 'check';
  fileName: string;
  watchId?: string | null;
  checkedAt?: string | null;
  mode: BatchMode;
  total: number;
  finished: number;
  failed: number;
  running: number;
  /** Runs paused on a person or a timer: never counted as failed or running. */
  waiting: number;
  pending: number;
  /** A check's files removed at the source; they never run. */
  removed: number;
  /** Failed rows whose run failed, which a retry starts again. */
  retryable: number;
  /** Failed rows a retry cannot change: a check's file that never ran. */
  notRetryable: number;
  /** Whether this person may retry: workflows.decide in the batch's team. */
  mayRetry: boolean;
  /** Set when the batch stopped starting rows, e.g. the team's model budget ran out. */
  stopped: { reason: string; at: string } | null;
  rows: BatchRow[];
}

/** One line of a workflow's Batches tab, counted by the API. */
export interface BatchLine {
  id: string;
  origin: 'upload' | 'check';
  label: string;
  createdAt: string;
  checkedAt: string | null;
  total: number;
  finished: number;
  waiting: number;
  failed: number;
  removed: number;
  running: number;
  pending: number;
  stopped: { reason: string; at: string } | null;
}
