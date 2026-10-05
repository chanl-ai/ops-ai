'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Pause, Play, Plug, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { RunStatusBadge, SCHEDULE_KIND_LABEL, SOURCE_STATUS_LABEL, SOURCE_TYPES, SourceStatusBadge, SourceTypeIcon, scheduleLabel, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { PageLayout } from '@/components/page-layout';
import { AddSourceDialog } from '@/components/sources/add-source-dialog';
import { BulkConfirmDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  useBulkDeleteSources,
  useBulkPauseSources,
  useBulkSyncSources,
  useConnect,
  useConnections,
  useCreateSource,
  useDeleteSource,
  useKnowledgeBases,
  useKnowledgeLookups,
  usePauseSource,
  usePreviewSource,
  useSourcesList,
  useSyncSource,
} from '@/hooks/knowledge-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { Schedule, SourceFilters, SourceRow, SourceStatus } from '@/lib/types/knowledge';

type Row = SourceRow & { onRowClick: (s: SourceRow) => void };
const ALL = { page: 1, pageSize: 100 };
type BulkKind = 'sync' | 'pause' | 'resume' | 'delete';

function columns(actions: { sync: (s: SourceRow) => void; togglePause: (s: SourceRow) => void; remove: (s: SourceRow) => void }): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((s) => s.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
      cell: ({ row }) => (
        <div className="flex max-w-72 min-w-52 items-center gap-2.5">
          <SourceTypeIcon type={row.original.type} />
          <div className="min-w-0">
            <Link href={`/sources/${row.original.id}`} className="block truncate font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
              {row.original.name}
            </Link>
            <div className="truncate font-mono text-xs text-muted-foreground">{row.original.connectionLabel ?? row.original.scopeSummary}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'type', header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />, cell: ({ row }) => <span className="whitespace-nowrap">{sourceTypeMeta(row.original.type).short}</span>, filterFn: facetFilterFn },
    {
      id: 'items',
      accessorFn: (r) => r.itemsIndexed,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Items · failed" />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap tabular-nums">
          {count(row.original.itemsIndexed)}
          <span className="text-muted-foreground"> · </span>
          <span className={row.original.itemsFailed > 0 ? 'text-destructive' : 'text-muted-foreground'}>{count(row.original.itemsFailed)}</span>
        </span>
      ),
    },
    {
      id: 'usedBy',
      accessorFn: (r) => r.usedBy.map((u) => u.id).join(','),
      header: () => <span className="text-xs">Used by</span>,
      cell: ({ row }) =>
        row.original.usedBy.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-default whitespace-nowrap underline decoration-dotted underline-offset-4">{plural(row.original.usedBy.length, 'knowledge base')}</span>
            </TooltipTrigger>
            <TooltipContent>
              {row.original.usedBy.map((u) => (
                <div key={u.id} className="text-xs">
                  {u.name}
                </div>
              ))}
            </TooltipContent>
          </Tooltip>
        ),
      filterFn: () => true,
    },
    { id: 'schedule', accessorFn: (r) => r.schedule.kind, header: () => <span className="text-xs">Schedule</span>, cell: ({ row }) => <span className="whitespace-nowrap">{scheduleLabel(row.original.schedule)}</span>, filterFn: facetFilterFn },
    { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <SourceStatusBadge status={row.original.status} />, filterFn: facetFilterFn },
    {
      id: 'lastSync',
      accessorFn: (r) => r.lastSyncAt ?? '',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Last sync" />,
      cell: ({ row }) => (
        <div className="flex min-w-[8.5rem] flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <RunStatusBadge status={row.original.running ? 'running' : row.original.lastRunStatus} />
            {!row.original.running && row.original.lastSyncAt && <span className="text-xs whitespace-nowrap text-muted-foreground">{relativeTime(row.original.lastSyncAt)}</span>}
          </div>
          {row.original.running && <Progress value={100} className="h-1 w-20 animate-pulse" aria-label="Sync running" />}
        </div>
      ),
    },
    {
      id: 'nextSync',
      accessorFn: (r) => r.nextSyncAt ?? '',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Next sync" />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-muted-foreground">
          {row.original.status === 'paused' ? 'Paused' : row.original.status === 'draft' || row.original.schedule.kind === 'manual' ? '—' : relativeTime(row.original.nextSyncAt)}
        </span>
      ),
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              ...(row.original.status !== 'revoked' && !row.original.running ? [{ label: 'Sync now', icon: RefreshCw, onClick: (r: { original: Row }) => actions.sync(r.original) }] : []),
              ...(row.original.status === 'active' || row.original.status === 'paused'
                ? [{ label: row.original.status === 'paused' ? 'Resume schedule' : 'Pause schedule', icon: row.original.status === 'paused' ? Play : Pause, onClick: (r: { original: Row }) => actions.togglePause(r.original) }]
                : []),
              { label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: (r) => actions.remove(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function SourcesPage() {
  const router = useRouter();
  const list = useListParams<SourceFilters>('name');
  const query = useSourcesList(list.params);
  const all = useSourcesList(ALL);
  const kbs = useKnowledgeBases(ALL);
  const connections = useConnections();
  const lookups = useKnowledgeLookups();
  const create = useCreateSource();
  const preview = usePreviewSource();
  const connect = useConnect();
  const sync = useSyncSource();
  const pause = usePauseSource();
  const remove = useDeleteSource();
  const bulkSync = useBulkSyncSources();
  const bulkPause = useBulkPauseSources();
  const bulkDelete = useBulkDeleteSources();
  const [addOpen, setAddOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<SourceRow | null>(null);
  const deletingShown = useSticky(deleting);
  const [bulk, setBulk] = React.useState<{ kind: BulkKind; rows: SourceRow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((s) => s.name);
  const nameOf = (id: string) => shown?.rows.find((s) => s.id === id)?.name ?? id;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });

  const cols = React.useMemo(
    () =>
      columns({
        sync: (s) => sync.mutate({ id: s.id }, { onSuccess: () => toast.success(`Syncing ${s.name}`), onError: fail('start the sync') }),
        togglePause: (s) =>
          pause.mutate(
            { id: s.id, paused: s.status !== 'paused' },
            { onSuccess: (x) => toast.success(x.status === 'paused' ? `Paused the schedule for ${s.name}` : `Resumed the schedule for ${s.name}`), onError: fail('change the schedule') },
          ),
        remove: setDeleting,
      }),
    [sync, pause], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((s) => ({ ...s, onRowClick: (x: SourceRow) => router.push(`/sources/${x.id}`) })), [query.data, router]);
  const facets = query.data?.facets ?? {};
  const BULK: Record<Exclude<BulkKind, 'delete'>, { title: string; description: string; verb: string; run: (ids: string[]) => ReturnType<typeof bulkSync.mutateAsync> }> = {
    sync: { title: 'Sync now', description: 'An incremental sync starts for each source. Revoked sources and ones already syncing are skipped.', verb: 'Syncing', run: (ids) => bulkSync.mutateAsync(ids) },
    pause: { title: 'Pause schedules', description: 'Scheduled syncs stop; Sync now still works. Drafts and revoked sources are skipped.', verb: 'Paused', run: (ids) => bulkPause.mutateAsync({ ids, paused: true }) },
    resume: { title: 'Resume schedules', description: 'Scheduled syncs start again at their next slot.', verb: 'Resumed', run: (ids) => bulkPause.mutateAsync({ ids, paused: false }) },
  };
  const copy = shown && shown.kind !== 'delete' ? BULK[shown.kind] : null;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };
  const deletingReaders = deletingShown?.usedBy ?? [];

  return (
    <PageLayout
      icon={Plug}
      title="Sources"
      description="Files, sites and apps that feed knowledge bases"
      actions={
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="size-4" /> Add source
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="sources" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search sources…"
          hideViewSwitcher
          initialColumnVisibility={{ nextSync: false }}
          filters={[
            { column: 'type', title: 'Type', options: SOURCE_TYPES.filter((t) => facets.type?.[t.type]).map((t) => ({ label: t.short, value: t.type, count: facets.type?.[t.type] ?? 0 })) },
            { column: 'status', title: 'Status', options: (Object.keys(SOURCE_STATUS_LABEL) as SourceStatus[]).map((s) => ({ label: SOURCE_STATUS_LABEL[s], value: s, count: facets.status?.[s] ?? 0 })) },
            { column: 'schedule', title: 'Schedule', options: (Object.keys(SCHEDULE_KIND_LABEL) as Schedule['kind'][]).map((k) => ({ label: SCHEDULE_KIND_LABEL[k], value: k, count: facets.schedule?.[k] ?? 0 })) },
            { column: 'usedBy', title: 'Knowledge base', options: (kbs.data?.data ?? []).map((k) => ({ label: k.name, value: k.id, count: facets.usedBy?.[k.id] ?? 0 })) },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            { label: 'Sync now', icon: RefreshCw, variant: 'outline', onClick: (r) => setBulk({ kind: 'sync', rows: r }) },
            { label: 'Pause', icon: Pause, variant: 'outline', onClick: (r) => setBulk({ kind: 'pause', rows: r }) },
            { label: 'Resume', icon: Play, variant: 'outline', onClick: (r) => setBulk({ kind: 'resume', rows: r }) },
            { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => setBulk({ kind: 'delete', rows: r }) },
          ]}
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
            <ListEmpty icon={Plug} noun="sources" filtered={list.isFiltered} description="A source is how content gets in: upload files, crawl a site or connect an app." createLabel="Add source" onCreate={() => setAddOpen(true)} />
          }
        />
      )}

      <AddSourceDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        connections={connections.data ?? []}
        knowledgeBases={kbs.data?.data ?? []}
        collections={lookups.data?.collections ?? []}
        existingNames={(all.data?.data ?? []).map((s) => s.name)}
        onPreview={(i) => preview.mutateAsync(i)}
        onConnect={async (type) => {
          try {
            const c = await connect.mutateAsync(type);
            toast.success(`${c.name} connected`, { description: c.connectedAs });
          } catch (e) {
            toast.error('Couldn’t connect', { description: (e as Error).message });
          }
        }}
        isPending={create.isPending}
        onSubmit={async (input, opts) => {
          const s = await create.mutateAsync({ input, ...opts });
          toast.success(s.status === 'draft' ? `Saved ${s.name} as a draft` : opts.sync ? `Created ${s.name}; the first sync has started` : `Created ${s.name}`, {
            description: s.status === 'draft' ? 'Finish setting it up from its page.' : undefined,
          });
          router.push(`/sources/${s.id}`);
        }}
      />

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="source"
        entityName={deletingShown?.name}
        requireNameConfirmation={deletingReaders.length > 0}
        description={`Its sync history and ${plural((deletingShown?.itemsIndexed ?? 0) + (deletingShown?.itemsFailed ?? 0), 'item')} are removed.${deletingReaders.length ? ` Chunks leave ${deletingReaders.map((k) => k.name).join(', ')}.` : ''}`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          const s = deleting!;
          try {
            await remove.mutateAsync(s.id);
            toast.success(`Deleted ${s.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${s.name}`, { description: (e as Error).message });
          }
        }}
      />
      <BulkConfirmDialog
        open={!!copy}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`${copy?.title} · ${plural(names.length, 'source')}`}
        description={copy?.description ?? ''}
        names={names}
        confirmLabel={copy?.title ?? ''}
        isPending={bulkSync.isPending || bulkPause.isPending}
        onConfirm={async () => {
          toastBulk(await copy!.run(bulk!.rows.map((s) => s.id)), copy!.verb, 'source', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="source"
        count={names.length}
        description="Their items and sync history are removed, and their chunks leave every knowledge base that reads them."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          toastBulk(await bulkDelete.mutateAsync(bulk!.rows.map((s) => s.id)), 'Deleted', 'source', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>
    </PageLayout>
  );
}
