'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { History } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { RUN_LABEL, RunStatusBadge, TRIGGER_LABEL, backoffRetryAt } from '@/components/knowledge/knowledge-meta';
import { RunSheet } from '@/components/sources/run-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Progress } from '@/components/ui/progress';
import { useReprocessItems, useSourceRuns, useSyncRun, useSyncSource } from '@/hooks/knowledge-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, dateTime, duration, relativeTime } from '@/lib/format';
import type { RunFilters, RunStatus, SourceDetail, SyncRun } from '@/lib/types/knowledge';

type Row = SyncRun & { onRowClick: (r: SyncRun) => void };

/** Every sync run with its counts; `?run=` opens one in the run sheet. */
export function SourceHistoryTab({ source, onSync }: { source: SourceDetail; onSync: () => void }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const list = useListParams<RunFilters>(undefined, 20);
  const query = useSourceRuns(source.id, list.params);
  const runId = params.get('run');
  const run = useSyncRun(runId);
  const sync = useSyncSource();
  const reprocess = useReprocessItems();
  const setRun = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set('run', id);
    else next.delete('run');
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const runs = query.data?.data ?? [];
  const idx = runs.findIndex((r) => r.id === runId);
  const rows: Row[] = React.useMemo(() => runs.map((r) => ({ ...r, onRowClick: (x: SyncRun) => setRun(x.id) })), [runs]); // eslint-disable-line react-hooks/exhaustive-deps
  const facets = query.data?.facets ?? {};
  const blocked = source.status === 'revoked' ? 'Connection revoked' : source.running ? 'A run is in progress' : undefined;

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: 'startedAt',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Started" />,
        cell: ({ row }) => (
          <div className="whitespace-nowrap">
            <div>{dateTime(row.original.startedAt)}</div>
            <div className="text-xs text-muted-foreground">{relativeTime(row.original.startedAt)}</div>
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'trigger', header: ({ column }) => <DataTableColumnHeader column={column} title="Trigger" />, cell: ({ row }) => <span className="whitespace-nowrap">{TRIGGER_LABEL[row.original.trigger]}</span>, filterFn: facetFilterFn },
      { accessorKey: 'durationSec', header: ({ column }) => <DataTableColumnHeader column={column} title="Duration" />, cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{row.original.status === 'running' ? '—' : duration(row.original.durationSec)}</span> },
      { id: 'listed', accessorFn: (r) => r.counts.listed, header: ({ column }) => <DataTableColumnHeader column={column} title="Listed" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.counts.listed)}</span> },
      { id: 'changed', accessorFn: (r) => r.counts.upserted + r.counts.deleted, header: ({ column }) => <DataTableColumnHeader column={column} title="Changed" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.counts.upserted + row.original.counts.deleted)}</span> },
      { id: 'failed', accessorFn: (r) => r.counts.failed, header: ({ column }) => <DataTableColumnHeader column={column} title="Failed" />, cell: ({ row }) => <span className={row.original.counts.failed ? 'tabular-nums text-destructive' : 'tabular-nums'}>{count(row.original.counts.failed)}</span> },
      {
        accessorKey: 'status',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
        cell: ({ row }) => (
          <div className="flex flex-col gap-1">
            <RunStatusBadge status={row.original.status} />
            {row.original.status === 'running' && <Progress value={100} className="h-1 w-20 animate-pulse" aria-label="Sync running" />}
            {row.original.status === 'backing_off' && <span className="text-xs whitespace-nowrap text-muted-foreground">Retries {relativeTime(backoffRetryAt(row.original))}</span>}
          </div>
        ),
        filterFn: facetFilterFn,
      },
    ],
    [],
  );

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={6} />;
  if (query.isError && !query.data) return <QueryError what="sync runs" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  const startRun = (opts: { full?: boolean; retry?: boolean }, done: string) =>
    sync.mutate({ id: source.id, opts }, { onSuccess: (r) => (toast.success(done), setRun(r.id)), onError: (e) => toast.error('Couldn’t start the run', { description: e.message }) });

  return (
    <>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        hideViewSwitcher
        filters={[
          { column: 'status', title: 'Status', options: (Object.keys(RUN_LABEL) as RunStatus[]).map((s) => ({ label: RUN_LABEL[s], value: s, count: facets.status?.[s] ?? 0 })) },
          { column: 'trigger', title: 'Trigger', options: (Object.keys(TRIGGER_LABEL) as SyncRun['trigger'][]).map((t) => ({ label: TRIGGER_LABEL[t], value: t, count: facets.trigger?.[t] ?? 0 })) },
        ]}
        onColumnFiltersChange={list.onColumnFiltersChange}
        serverPagination={{
          enabled: true,
          total: query.data?.pagination.total ?? 0,
          page: list.pagination.page,
          pageSize: list.pagination.pageSize,
          totalPages: query.data?.pagination.totalPages,
          onPaginationChange: list.setPagination,
          isLoading: query.isFetching && query.isPlaceholderData,
        }}
        emptyState={
          <ListEmpty
            icon={History}
            noun="sync runs"
            filtered={list.isFiltered}
            description="A run is one pass over the source: list changes, fetch, parse, chunk, embed and upsert. Each one is recorded here."
            createLabel={source.status === 'revoked' || source.status === 'draft' ? undefined : 'Sync now'}
            onCreate={onSync}
          />
        }
      />
      <RunSheet
        run={runId ? (run.data ?? null) : null}
        onOpenChange={(o) => !o && setRun(null)}
        navigation={
          idx >= 0
            ? { currentIndex: idx, totalCount: runs.length, onPrev: idx > 0 ? () => setRun(runs[idx - 1].id) : undefined, onNext: idx < runs.length - 1 ? () => setRun(runs[idx + 1].id) : undefined }
            : undefined
        }
        blocked={blocked}
        busy={sync.isPending || reprocess.isPending}
        onRetryFailed={() => startRun({ retry: true }, 'Retrying failed items')}
        onRerun={() => run.data && startRun({ full: run.data.trigger === 'full', retry: run.data.trigger === 'retry' }, `Started a new ${TRIGGER_LABEL[run.data.trigger].toLowerCase()} run`)}
        onReprocessItem={(itemId, title) =>
          reprocess.mutate([itemId], { onSuccess: (res) => toastReprocess(res.updated.length, title), onError: (e) => toast.error('Couldn’t reprocess', { description: e.message }) })
        }
      />
    </>
  );
}

const toastReprocess = (updated: number, title: string) => (updated ? toast.success(`Reprocessing ${title}`) : toast.warning(`${title} can’t be reprocessed`, { description: 'It was excluded or deleted at the source.' }));
