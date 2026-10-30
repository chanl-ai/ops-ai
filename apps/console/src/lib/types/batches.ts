/** Live runs the live version; test runs the latest saved version. */
export type BatchMode = 'live' | 'test';

/** Starting a workflow once per row of a CSV or Excel file already uploaded to Files (c-535). */
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
  /** `pending` until its run starts, then the run's own status. */
  status: string;
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
  fileName: string;
  mode: BatchMode;
  total: number;
  finished: number;
  failed: number;
  running: number;
  pending: number;
  /** Set when the batch stopped starting rows, e.g. the team's model budget ran out. */
  stopped: { reason: string; at: string } | null;
  rows: BatchRow[];
}
