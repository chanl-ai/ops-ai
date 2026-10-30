'use client';

import * as React from 'react';
import { ArrowRight, Loader2 } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { FileUpload, type UploadItem } from '@/components/shared/file-upload';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useBatchDryRun } from '@/hooks/batch-queries';
import type { BatchDryRun, BatchMode } from '@/lib/types/batches';
import { plural } from '@/lib/format';

/** A file checked against the workflow's inputs and ready to start: its id and the dry run's answer. */
export interface CheckedFile {
  fileId: string;
  name: string;
  dry: BatchDryRun;
}

const SAMPLE = 5;
const cell = (v: unknown) => (v === undefined || v === null ? '' : typeof v === 'string' ? v : JSON.stringify(v));
const quoted = (names: string[]) => names.map((n) => `“${n}”`).join(', ');

/**
 * The Start run dialog's Start from a file tab (c-535): a CSV or Excel file is uploaded to Files, then checked
 * against the workflow's inputs without starting anything (the dry run): the row count, which column feeds which
 * input, the columns left out and the first rows as the runs will get them. A refusal (too many rows, no column
 * naming an input) shows here and nothing starts. The dialog's footer starts the runs once `onChecked` has a file.
 */
export function StartFromFile({
  workflowId,
  mode,
  inputs,
  onChecked,
  startError,
}: {
  workflowId: string;
  mode: BatchMode;
  /** The trigger's inputs by key, for their titles. */
  inputs: Record<string, { title?: string }>;
  onChecked: (file: CheckedFile | null) => void;
  /** Why starting the runs failed, shown with the dry run. */
  startError?: string;
}) {
  const [file, setFile] = React.useState<{ fileId: string; name: string } | null>(null);
  const dry = useBatchDryRun(workflowId);
  const { mutateAsync: check, reset } = dry;
  const onCheckedRef = React.useRef(onChecked);
  onCheckedRef.current = onChecked;
  // Each new file or mode is checked again; an answer for a file no longer chosen is dropped.
  const asked = React.useRef(0);
  React.useEffect(() => {
    const n = ++asked.current;
    onCheckedRef.current(null);
    reset();
    if (!file) return;
    check({ fileId: file.fileId, mode }).then(
      (answer) => {
        if (n === asked.current) onCheckedRef.current({ ...file, dry: answer });
      },
      () => undefined,
    );
  }, [file, mode, check, reset]);

  const titles = Object.entries(inputs).map(([k, s]) => s.title || k);
  const title = (key: string) => inputs[key]?.title || key;
  const answer = dry.data;
  const columns = answer ? Object.entries(answer.mapping) : [];
  const keys = columns.map(([, key]) => key).filter((k, i, all) => all.indexOf(k) === i);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <FileUpload
        id="batch-file"
        purpose="case_attachment"
        types={['csv', 'xlsx']}
        testId="batch-file"
        title="Drop a CSV or Excel file here or choose one"
        hint={`Its first row names the inputs: ${titles.join(', ')}. Up to 500 rows, one run each.`}
        onChange={(items: UploadItem[]) => {
          const ready = items.find((i) => i.phase === 'ready' && i.fileId);
          const next = ready ? { fileId: ready.fileId!, name: ready.name } : null;
          setFile((prev) => (prev?.fileId === next?.fileId ? prev : next));
        }}
      />
      {dry.isPending && file && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="batch-checking">
          <Loader2 className="size-4 animate-spin" /> Checking {file.name}: counting rows and matching columns to inputs
        </p>
      )}
      {dry.isError && file && (
        <Alert variant="destructive" data-testid="batch-refused">
          <AlertTitle>{file.name} cannot start runs</AlertTitle>
          <AlertDescription>{dry.error.message} Nothing was started.</AlertDescription>
        </Alert>
      )}
      {answer && file && (
        <div className="flex min-w-0 flex-col gap-4" data-testid="batch-dry-run">
          <p className="text-sm">
            <span className="font-medium">{file.name}</span> has <span className="font-medium tabular-nums">{plural(answer.rows, 'row')}</span>, one run each.
          </p>
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium">Columns</div>
            <ul className="divide-y rounded-md border">
              {columns.map(([column, key]) => (
                <li key={column} className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="min-w-0 break-all font-mono text-xs">{column}</span>
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-label="feeds" />
                  <span className="min-w-0 break-words">{title(key)}</span>
                </li>
              ))}
            </ul>
            {answer.ignored.length > 0 && (
              <p className="text-xs text-muted-foreground" data-testid="batch-ignored">
                {quoted(answer.ignored)} {answer.ignored.length === 1 ? 'matches no input and is left out.' : 'match no input and are left out.'}
              </p>
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <div className="text-sm font-medium">
              First {Math.min(SAMPLE, answer.rows)} of {plural(answer.rows, 'row')}
            </div>
            <SampleRows sample={answer.sample.slice(0, SAMPLE)} keys={keys} title={title} />
          </div>
          <p className="text-xs text-muted-foreground">Failed rows can be retried from the batch page.</p>
        </div>
      )}
      {startError && (
        <Alert variant="destructive" data-testid="batch-start-error">
          <AlertTitle>The runs did not start</AlertTitle>
          <AlertDescription>{startError}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

type SampleLine = { key: string; n: number; values: Record<string, unknown> };

/** The dry run's first rows, one column per input a column of the file feeds. */
function SampleRows({ sample, keys, title }: { sample: Record<string, unknown>[]; keys: string[]; title: (key: string) => string }) {
  const lines = React.useMemo<SampleLine[]>(() => sample.map((values, i) => ({ key: String(i + 1), n: i + 1, values })), [sample]);
  const columns = React.useMemo<ColumnDef<SampleLine>[]>(
    () => [
      { id: 'n', header: '#', meta: { kind: 'number' }, cell: ({ row }) => <span className="text-muted-foreground">{row.original.n}</span> },
      ...keys.map<ColumnDef<SampleLine>>((k, i) => ({
        id: `in-${k}`,
        header: title(k),
        meta: i === 0 ? { kind: 'name' } : undefined,
        cell: ({ row }) => <span title={cell(row.original.values[k])}>{cell(row.original.values[k])}</span>,
      })),
    ],
    [keys, title],
  );
  return <DataTableWithViews columns={columns} data={lines} getRowId={(r) => r.key} hideViewSwitcher />;
}
