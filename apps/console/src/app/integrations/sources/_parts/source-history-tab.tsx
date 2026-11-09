'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { History, Square, Undo2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { RunStatusBadge, triggerLabel } from '@/components/knowledge/knowledge-meta';
import { RunSheet, runChecked, runModelUse } from '@/components/sources/run-sheet';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { StopRowClick } from '@/components/shared/form-field';
import { Progress } from '@/components/ui/progress';
import { useCancelRun, useLiftTombstones, useSourceRuns, useSyncRun, useSyncSource, useTombstones } from '@/hooks/knowledge-queries';
import { useListParams } from '@/hooks/use-list-params';
import { count, dateTime, duration, relativeTime } from '@/lib/format';
import type { RunFilters, SourceDetail, SyncRun, Tombstone } from '@/lib/types/knowledge';
import { serverPagination } from '@/components/shared/server-pagination';

type Row = SyncRun & { onRowClick: (r: SyncRun) => void };

const num = (n: number | undefined) => <span className="tabular-nums">{n === undefined ? '—' : count(n)}</span>;

/**
 * Every sync and rebuild of the source with what it checked, changed, removed and failed, and the model calls its AI
 * steps made. A running one can be cancelled; `?run=` opens one with its errors and log. Addresses a sync removed for
 * answering gone twice are listed below, each with Lift.
 */
export function SourceHistoryTab({ source, onSync }: { source: SourceDetail; onSync: () => void }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const list = useListParams<RunFilters>(undefined, 20);
  const query = useSourceRuns(source.id, list.params);
  const runId = params.get('run');
  const run = useSyncRun(runId);
  const sync = useSyncSource();
  const cancel = useCancelRun();
  const setRun = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set('run', id);
    else next.delete('run');
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const cancelRun = React.useCallback(
    (r: SyncRun) =>
      cancel.mutate(r.id, {
        onSuccess: () => toast.success('Run cancelled', { description: 'It stops after the item it is on.' }),
        onError: (e) => toast.error('Couldn’t cancel the run', { description: e.message }),
      }),
    [cancel],
  );

  const runs = query.data?.data ?? [];
  const idx = runs.findIndex((r) => r.id === runId);
  const rows: Row[] = React.useMemo(() => runs.map((r) => ({ ...r, onRowClick: (x: SyncRun) => setRun(x.id) })), [runs]); // eslint-disable-line react-hooks/exhaustive-deps
  const blocked = source.status === 'revoked' ? 'Connection revoked' : source.running ? 'A run is in progress' : undefined;
  const cancelling = cancel.isPending ? cancel.variables : undefined;

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      { accessorKey: 'trigger', header: 'Trigger', cell: ({ row }) => <span className="whitespace-nowrap">{triggerLabel(row.original.trigger)}</span> },
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
      { accessorKey: 'durationSec', header: 'Duration', cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{row.original.status === 'running' ? '—' : duration(row.original.durationSec)}</span> },
      { id: 'checked', header: 'Checked', cell: ({ row }) => num(runChecked(row.original)) },
      { id: 'changed', header: 'Changed', cell: ({ row }) => num(row.original.counts.upserted ?? row.original.counts.rebuilt) },
      { id: 'deleted', header: 'Removed', cell: ({ row }) => num(row.original.counts.deleted) },
      {
        id: 'failed',
        header: 'Failed',
        cell: ({ row }) => <span className={row.original.counts.failed ? 'tabular-nums text-destructive-text' : 'tabular-nums'}>{count(row.original.counts.failed ?? 0)}</span>,
      },
      { id: 'model', header: 'Model use', cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{runModelUse(row.original) ?? '—'}</span> },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <div className="flex flex-col gap-1">
            <RunStatusBadge status={row.original.status} />
            {row.original.status === 'running' && <Progress value={100} className="h-1 w-20 animate-pulse" aria-label="Run in progress" />}
            {row.original.cancelledBy && <span className="text-xs whitespace-nowrap text-muted-foreground">by {row.original.cancelledBy}</span>}
          </div>
        ),
      },
      {
        id: 'actions',
        meta: { className: 'w-24' },
        cell: ({ row }) =>
          row.original.status === 'running' ? (
            <StopRowClick>
              <LoadingButton size="sm" variant="outline" isLoading={cancelling === row.original.id} onClick={() => cancelRun(row.original)} data-testid={`cancel-run-${row.original.id}`}>
                <Square className="size-3.5" /> Cancel
              </LoadingButton>
            </StopRowClick>
          ) : null,
        enableHiding: false,
      },
    ],
    [cancelRun, cancelling],
  );

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={6} />;
  if (query.isError && !query.data) return <QueryError what="sync runs" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />;

  const startRun = (opts: { full?: boolean; retry?: boolean }, done: string) =>
    sync.mutate({ id: source.id, opts }, { onSuccess: (r) => (toast.success(done), setRun(r.id)), onError: (e) => toast.error('Couldn’t start the run', { description: e.message }) });

  return (
    <div className="flex flex-col gap-4">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        hideViewSwitcher
        initialColumnVisibility={{ checked: true, changed: true, deleted: true, failed: true, model: true, status: true }}
        serverPagination={serverPagination(list, query)}
        emptyState={
          <ListEmpty
            icon={History}
            noun="sync runs"
            filtered={list.isFiltered}
            description="The first sync runs when the source is added, then on its schedule. Each run is recorded here."
            createLabel={source.status === 'revoked' || source.status === 'draft' ? undefined : 'Sync now'}
            onCreate={onSync}
          />
        }
      />
      <TombstoneList source={source} />
      <RunSheet
        run={runId ? (run.data ?? null) : null}
        onOpenChange={(o) => !o && setRun(null)}
        navigation={
          idx >= 0
            ? { currentIndex: idx, totalCount: runs.length, onPrev: idx > 0 ? () => setRun(runs[idx - 1].id) : undefined, onNext: idx < runs.length - 1 ? () => setRun(runs[idx + 1].id) : undefined }
            : undefined
        }
        blocked={blocked}
        busy={sync.isPending}
        cancelling={!!run.data && cancelling === run.data.id}
        onCancel={() => run.data && cancelRun(run.data)}
        onRetryFailed={() => startRun({ retry: true }, 'Retrying failed items')}
        onFullSync={() => startRun({ full: true }, 'Full resync started')}
      />
    </div>
  );
}

/** Addresses removed after answering gone twice in a row; a sync leaves them out until a person lifts them. */
function TombstoneList({ source }: { source: SourceDetail }) {
  const query = useTombstones(source.id);
  const lift = useLiftTombstones(source.id);
  const rows = React.useMemo(() => query.data ?? [], [query.data]);
  const lifting = lift.isPending ? lift.variables?.[0] : undefined;
  const columns = React.useMemo<ColumnDef<Tombstone>[]>(
    () => [
      { id: 'address', accessorKey: 'id', header: 'Address', cell: ({ row }) => <span className="block max-w-96 truncate font-mono text-xs" title={row.original.id}>{row.original.id}</span>, enableHiding: false },
      { accessorKey: 'at', header: 'Removed', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.at ? relativeTime(row.original.at) : '—'}</span> },
      { accessorKey: 'reason', header: 'Reason', cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.reason ?? 'Gone at the source'}</span> },
      {
        id: 'lift',
        meta: { className: 'w-24' },
        cell: ({ row }) => (
          <LoadingButton
            size="sm"
            variant="outline"
            isLoading={lifting === row.original.id}
            onClick={() =>
              lift.mutate([row.original.id], {
                onSuccess: () => toast.success('Lifted', { description: 'The next sync takes this address in again.' }),
                onError: (e) => toast.error('Couldn’t lift it', { description: e.message }),
              })
            }
          >
            <Undo2 className="size-3.5" /> Lift
          </LoadingButton>
        ),
        enableHiding: false,
      },
    ],
    [lift, lifting],
  );
  if (query.isError) return <QueryError what="removed addresses" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />;
  return (
    <section className="flex flex-col gap-2" aria-label="Removed addresses">
      <div>
        <h2 className="text-sm font-semibold">Removed addresses</h2>
        <p className="text-xs text-muted-foreground">An address that answers gone on two syncs in a row is removed from search and left out of each sync until it is lifted.</p>
      </div>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        hideViewSwitcher
        hidePaginationOnOnePage
        rowNoun="address"
        emptyState={<p className="py-6 text-center text-sm text-muted-foreground">{query.isPending ? 'Loading…' : 'No address has been removed.'}</p>}
      />
    </section>
  );
}
