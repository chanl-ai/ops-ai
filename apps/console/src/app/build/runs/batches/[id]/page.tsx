'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Download, Layers, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { CopyButton } from '@/components/shared/copy-button';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { TextCell } from '@/components/shared/table-cells';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { RunStatus } from '@/components/workflows/run-journal/run-status';
import { useBatch, useBatchResultsCsv, useRetryBatch } from '@/hooks/batch-queries';
import { useDefinition } from '@/hooks/engine-queries';
import { agentsApiUrl } from '@/lib/api';
import { plural } from '@/lib/format';
import type { BatchRow, BatchView } from '@/lib/types/batches';
import type { PaginationState } from '@/lib/types/pagination';

const text = (v: unknown): string => (v === undefined || v === null ? '' : typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v));

/** A row's output in one line: a value as it is, an object as its first few fields. */
function outputLine(r: BatchRow): string {
  const out = r.output;
  const fields =
    out && typeof out === 'object' && !Array.isArray(out)
      ? Object.entries(out as Record<string, unknown>)
          .slice(0, 3)
          .map(([k, v]) => `${k}: ${text(v)}`)
          .join(' · ')
      : text(out);
  return [r.outcome, fields].filter(Boolean).join(' · ');
}

/** The row's inputs in one line, so a person can tell which row of the file it is. */
const inputLine = (r: BatchRow) =>
  Object.values(r.input)
    .slice(0, 2)
    .map(text)
    .filter(Boolean)
    .join(' · ');

/** The headline counts, as the server counted them; a run waiting for a person is never counted as failed. */
function headline(b: BatchView): string {
  const unit = b.origin === 'check' ? 'file' : 'row';
  const more = [b.failed ? `${b.failed} failed` : '', b.waiting ? `${b.waiting} waiting for a person` : '', b.removed ? `${b.removed} removed` : ''].filter(Boolean);
  // A spreadsheet's batch reads as it always has: "10 of 12 finished".
  return `${b.finished} of ${b.origin === 'check' ? plural(b.total, unit) : b.total} finished${more.length ? `, ${more.join(', ')}` : ''}`;
}

function underHeadline(b: BatchView): string {
  const unit = b.origin === 'check' ? 'file' : 'row';
  if (b.running || b.pending) return `${[b.running ? `${b.running} running` : '', b.pending ? `${b.pending} waiting to start` : ''].filter(Boolean).join(', ')}. The counts change as each run ends.`;
  if (b.retryable) {
    const left = b.notRetryable ? ` ${plural(b.notRetryable, unit)} that never ran cannot be retried.` : '';
    return `Retry starts only the ${plural(b.retryable, unit)} whose run failed; ${unit}s that succeeded do not run again.${left}`;
  }
  if (b.notRetryable) return `${plural(b.notRetryable, unit)} never ran, so a retry cannot change ${b.notRetryable === 1 ? 'it' : 'them'}.`;
  return 'No failures, so there is nothing to retry.';
}

function batchState(b: BatchView): { label: string; tone: string } {
  if (b.stopped) return { label: 'Stopped', tone: 'border-warning/40 bg-warning/10 text-warning-text' };
  if (b.running || b.pending) return { label: 'Running', tone: 'border-primary/40 bg-primary/10 text-primary' };
  if (b.waiting) return { label: 'Waiting for a person', tone: 'border-primary/40 bg-primary/10 text-primary' };
  if (b.failed) return { label: 'Finished with failures', tone: 'border-warning/40 bg-warning/10 text-warning-text' };
  return { label: 'Finished', tone: 'border-success/40 bg-success/10 text-success-text' };
}

/**
 * A batch's page: one run of a workflow per row of a file. The headline counts the rows as their runs end and
 * the page polls while any row is waiting or running; the table lists every row, failed first, each opening its run.
 * Retry failed rows starts a new attempt for the failed rows only; Download as CSV gives the same table.
 */
/**
 * How far the batch has got, as the track the Progress primitive draws: the finished share, then the failed share in
 * the error colour, so a batch with failures never reads as all green. The primitive draws one value only.
 */
function BatchBar({ finished, failed, total }: { finished: number; failed: number; total: number }) {
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={finished + failed}
      aria-label={`${finished} of ${total} rows finished, ${failed} failed`}
      className="bg-primary/20 flex h-1.5 w-full overflow-hidden rounded-full"
    >
      <div className="bg-primary h-full transition-all" style={{ width: `${pct(finished)}%` }} data-testid="batch-bar-finished" data-share={finished} />
      <div className="bg-destructive h-full transition-all" style={{ width: `${pct(failed)}%` }} data-testid="batch-bar-failed" data-share={failed} />
    </div>
  );
}

export default function BatchPage() {
  const { id } = useParams<{ id: string }>();
  return <Batch id={id} />;
}

function Batch({ id }: { id: string }) {
  const query = useBatch(id);
  const batch = query.data;
  const definition = useDefinition(batch?.workflowId ?? '');
  const retry = useRetryBatch(id);
  const [retryError, setRetryError] = React.useState<string>();
  const csv = useBatchResultsCsv(id);

  if (query.isPending)
    return (
      <PageLayout icon={Layers} title="Batch" backHref="/build/workflows">
        <PageSkeleton statCards={1} tableRows={6} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError || !batch)
    return (
      <PageLayout icon={Layers} title="Batch" backHref="/build/workflows">
        <QueryError what="this batch" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      </PageLayout>
    );

  const name = definition.data?.name || definition.data?.definition.name || batch.workflowId;
  const state = batchState(batch);
  const check = batch.origin === 'check';
  const unit = check ? 'file' : 'row';
  const description = check
    ? `${plural(batch.total, 'new or changed file')} from one check of a watched folder, one ${batch.mode === 'test' ? 'test run' : 'live run'} of ${name} each`
    : `${plural(batch.total, 'row')} of ${batch.fileName}, one ${batch.mode === 'test' ? 'test run' : 'live run'} of ${name} each`;
  const workflowHref = `/build/workflows/definitions/${encodeURIComponent(batch.workflowId)}`;

  const download = async () => {
    try {
      const link = await csv.mutateAsync();
      const a = document.createElement('a');
      a.href = link.url;
      a.download = link.name;
      a.click();
      // The link is the page's own copy of the bytes; it is let go once the browser has taken the download.
      setTimeout(() => URL.revokeObjectURL(link.url), 60_000);
    } catch (e) {
      toast.error('Couldn’t download the results', { description: (e as Error).message });
    }
  };

  return (
    <PageLayout
      icon={Layers}
      title={`${name} · ${batch.fileName}`}
      description={description}
      badge={
        <Badge variant="outline" className={`font-normal ${state.tone}`} data-testid="batch-state">
          {state.label}
        </Badge>
      }
      backHref={`${workflowHref}/batches`}
      actions={
        <>
          {batch.mayRetry && (
            <LoadingButton
              isLoading={retry.isPending}
              loadingText="Retrying…"
              disabled={batch.retryable === 0}
              data-testid="batch-retry-failed"
              onClick={async () => {
                setRetryError(undefined);
                try {
                  const { retried, notRetryable } = await retry.mutateAsync();
                  toast.success(`Starting ${plural(retried, unit)} again`, notRetryable ? { description: `${plural(notRetryable, unit)} never ran and cannot be retried.` } : undefined);
                } catch (e) {
                  setRetryError(e instanceof Error ? e.message : `The failed ${unit}s were not started again`);
                }
              }}
            >
              <RotateCcw /> Retry failed {unit}s{batch.retryable ? ` (${batch.retryable})` : ''}
            </LoadingButton>
          )}
          <LoadingButton variant="outline" isLoading={csv.isPending} loadingText="Preparing…" onClick={download} data-testid="batch-download">
            <Download /> Download as CSV
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-6">
        {retryError && (
          <Alert variant="destructive" data-testid="batch-retry-error">
            <AlertTitle>Could not retry</AlertTitle>
            <AlertDescription>{retryError}</AlertDescription>
          </Alert>
        )}
        {batch.stopped && (
          <Alert data-testid="batch-stopped">
            <AlertTitle>Stopped</AlertTitle>
            <AlertDescription>{batch.stopped.reason}</AlertDescription>
          </Alert>
        )}
        <div className="flex min-w-0 flex-col gap-3 rounded-lg border bg-card p-4">
          <div className="text-2xl font-semibold tabular-nums" data-testid="batch-headline">
            {headline(batch)}
          </div>
          <BatchBar finished={batch.finished} failed={batch.failed} total={batch.total} />
          <p className="text-sm text-muted-foreground">{underHeadline(batch)}</p>
        </div>
        <Section
          title="Results"
          description={check ? 'One line per file, with its status and output, failed first. Each opens its run.' : `One line per row of ${batch.fileName}, with its status and output, failed first. Each opens its run.`}
          flush
        >
          <div className="min-w-0 p-2">
            <BatchRows rows={batch.rows} check={check} />
          </div>
        </Section>
        <Section title="Use from a script" description="Read this batch from code or the command line.">
          <div className="flex min-w-0 flex-col gap-2 text-sm" data-testid="batch-script">
            {[`${agentsApiUrl}/batches/${batch.id}`, `opsai batches get ${batch.id} --json`].map((line) => (
              <div key={line} className="flex min-w-0 items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 font-mono text-xs" title={line}>
                  {line}
                </code>
                <CopyButton text={line} />
              </div>
            ))}
          </div>
        </Section>
      </div>
    </PageLayout>
  );
}

type Line = BatchRow & { key: string; rowTestId: string; href?: string; onRowClick?: () => void };

const PAGE_SIZE = 50;

/**
 * Every row of the batch, in the API's order (failed first), each opening its run. The batch holds at most 500 rows
 * and the API returns them all, so the pages here are slices of that one answer.
 */
function BatchRows({ rows, check }: { rows: BatchRow[]; check: boolean }) {
  const router = useRouter();
  const [paging, setPaging] = React.useState<PaginationState>({ page: 1, pageSize: PAGE_SIZE });
  const lines: Line[] = React.useMemo(
    () =>
      rows.map((r) => {
        const href = r.runId ? `/build/runs/${encodeURIComponent(r.runId)}` : undefined;
        return { ...r, key: String(r.row), rowTestId: 'batch-row', href, onRowClick: href ? () => router.push(href) : undefined };
      }),
    [rows, router],
  );
  const pages = Math.max(1, Math.ceil(lines.length / paging.pageSize));
  const page = Math.min(paging.page, pages);
  const shown = lines.slice((page - 1) * paging.pageSize, page * paging.pageSize);
  const columns = React.useMemo<ColumnDef<Line>[]>(
    () => [
      check
        ? {
            id: 'file',
            header: 'File',
            meta: { kind: 'name' },
            cell: ({ row }) => {
              const r = row.original;
              const file = text(r.input.name) || `File ${r.row}`;
              return (
                <div className="flex min-w-0 flex-col" title={[file, r.reason].filter(Boolean).join(' · ')}>
                  <span className="truncate">{file}</span>
                  {r.reason && (
                    <span className="text-xs text-destructive-text" data-testid="batch-row-reason">
                      <TextCell>{r.reason}</TextCell>
                    </span>
                  )}
                </div>
              );
            },
          }
        : { id: 'input', header: 'Input', meta: { kind: 'name' }, cell: ({ row }) => <span title={inputLine(row.original)}>{inputLine(row.original) || `Row ${row.original.row}`}</span> },
      ...(check ? [] : [{ accessorKey: 'row', header: 'Row', meta: { kind: 'number' }, cell: ({ row }) => row.original.row } as ColumnDef<Line>]),
      {
        accessorKey: 'status',
        header: 'Status',
        meta: { kind: 'status' },
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1.5">
            {row.original.status === 'removed' ? (
              <span className="text-sm text-muted-foreground" data-testid="batch-row-removed">
                Removed at the source
              </span>
            ) : (
              <RunStatus status={row.original.status} />
            )}
            {row.original.attempt > 1 && <span className="text-xs text-muted-foreground">attempt {row.original.attempt}</span>}
          </span>
        ),
      },
      {
        id: 'output',
        header: 'Output',
        meta: { kind: 'description' },
        cell: ({ row }) => {
          const r = row.original;
          const out = outputLine(r);
          return (
            <div title={[r.error, out].filter(Boolean).join(' · ')}>
              {r.error ? <span className="text-destructive-text">{r.error}</span> : out || <span className="text-muted-foreground">{r.status === 'pending' ? 'Not started yet' : r.runId ? '—' : 'Never ran'}</span>}
              {r.error && out ? <span className="text-muted-foreground"> · {out}</span> : null}
            </div>
          );
        },
      },
      {
        id: 'run',
        header: () => <span className="sr-only">Run</span>,
        meta: { kind: 'date' },
        cell: ({ row }) =>
          row.original.href ? (
            <Link href={row.original.href} className="text-sm font-medium underline underline-offset-2" data-testid="batch-row-run">
              Open run
            </Link>
          ) : null,
      },
    ],
    [check],
  );
  return (
    <DataTableWithViews
      columns={columns}
      data={shown}
      getRowId={(r) => r.key}
      hideViewSwitcher
      serverPagination={{ enabled: true, total: lines.length, page, pageSize: paging.pageSize, totalPages: pages, onPaginationChange: setPaging }}
    />
  );
}
