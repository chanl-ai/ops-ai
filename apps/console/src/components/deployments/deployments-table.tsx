'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowUpCircle, Pause, Play, Plus, Rocket, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { BulkConfirmDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Button } from '@/components/ui/button';
import {
  useBulkDeleteDeployments,
  useBulkUpdateDeployments,
  useCreateDeployment,
  useDeployments,
  usePromoteDeployment,
  useRotateKey,
  useUpdateDeployment,
  useWorkflows,
} from '@/hooks/queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { DeployChannel, Deployment } from '@/lib/types/domain';
import type { DeploymentFilters } from '@/lib/types/query';

import { CreateDeploymentDialog } from './create-deployment-dialog';
import { ChannelBadge, CHANNELS, DeploymentStatusBadge, EnvironmentBadge, VersionCell } from './deployment-meta';
import { DeploymentSheet } from './deployment-sheet';

type Row = Deployment & { onRowClick: (d: Deployment) => void };
const ALL = { page: 1, pageSize: 100 };

function columns(showWorkflow: boolean): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((d) => d.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Deployment" />,
      cell: ({ row }) => (
        <div className="min-w-44">
          <div className="font-medium">{row.original.name}</div>
          {showWorkflow && <div className="text-xs text-muted-foreground">{row.original.workflowName}</div>}
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'workflowId', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
    { accessorKey: 'channel', header: ({ column }) => <DataTableColumnHeader column={column} title="Channel" />, cell: ({ row }) => <ChannelBadge channel={row.original.channel} />, filterFn: facetFilterFn },
    { accessorKey: 'environment', header: ({ column }) => <DataTableColumnHeader column={column} title="Environment" />, cell: ({ row }) => <EnvironmentBadge environment={row.original.environment} />, filterFn: facetFilterFn },
    { accessorKey: 'version', header: ({ column }) => <DataTableColumnHeader column={column} title="Serves" />, cell: ({ row }) => <VersionCell d={row.original} /> },
    { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <DeploymentStatusBadge status={row.original.status} sync={row.original.email?.sync} />, filterFn: facetFilterFn },
    {
      accessorKey: 'traffic24h',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Traffic · 24h" />,
      cell: ({ row }) => (
        <span className="tabular-nums">
          {count(row.original.traffic24h)}
          {row.original.errors24h > 0 && <span className="ml-1.5 text-xs text-red-600 dark:text-red-400">{plural(row.original.errors24h, 'error')}</span>}
        </span>
      ),
    },
    { accessorKey: 'updatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Updated" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.updatedAt)}</span> },
  ];
}

/** Deployment list with create, inspect and bulk actions. Scoped to one workflow when `workflowId` is set. */
export function DeploymentsTable({ workflowId, createOpen, onCreateOpenChange, createChannel }: { workflowId?: string; createOpen: boolean; onCreateOpenChange: (open: boolean) => void; createChannel?: DeployChannel }) {
  const list = useListParams<DeploymentFilters>('name');
  const params = workflowId ? { ...list.params, filters: { ...list.params.filters, workflowId: [workflowId] } } : list.params;
  const query = useDeployments(params);
  const workflows = useWorkflows(ALL);
  const create = useCreateDeployment();
  const update = useUpdateDeployment();
  const rotate = useRotateKey();
  const promote = usePromoteDeployment();
  const bulkUpdate = useBulkUpdateDeployments();
  const bulkDelete = useBulkDeleteDeployments();
  // `?deployment=` opens that deployment's sheet, so other pages (an integration's Used by tab) can link to it.
  const linked = useSearchParams().get('deployment');
  const [activeId, setActiveId] = React.useState<string | null>(linked);
  const [bulk, setBulk] = React.useState<{ kind: 'pause' | 'resume' | 'latest' | 'delete'; rows: Deployment[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);

  const rowsData = query.data?.data ?? [];
  const idx = rowsData.findIndex((d) => d.id === activeId);
  const active = idx >= 0 ? rowsData[idx] : null;
  const rows: Row[] = React.useMemo(() => rowsData.map((d) => ({ ...d, onRowClick: (x: Deployment) => setActiveId(x.id) })), [rowsData]);
  const cols = React.useMemo(() => columns(!workflowId), [workflowId]);
  const facets = query.data?.facets ?? {};
  const names = (shown?.rows ?? []).map((d) => d.name);
  const nameOf = (id: string) => shown?.rows.find((d) => d.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };
  const BULK: Record<'pause' | 'resume' | 'latest', { title: string; description: string; verb: string; patch: { status?: 'active' | 'paused'; toLatest?: boolean } }> = {
    pause: { title: 'Pause', description: 'Channels stop answering. Widgets show an offline message; API calls return 503; email waits.', verb: 'Paused', patch: { status: 'paused' } },
    resume: { title: 'Resume', description: 'Channels start answering again on the version each one serves.', verb: 'Resumed', patch: { status: 'active' } },
    latest: { title: 'Move to latest version', description: 'Each deployment switches to its workflow’s latest published version. Ones already on it are skipped.', verb: 'Updated', patch: { toLatest: true } },
  };
  const copy = shown && shown.kind !== 'delete' ? BULK[shown.kind] : null;

  return (
    <>
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : query.isError && !query.data ? (
        <QueryError what="deployments" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search deployments…"
          initialColumnVisibility={{ workflowId: false, updatedAt: false }}
          filters={[
            { column: 'channel', title: 'Channel', options: (Object.keys(CHANNELS) as Deployment['channel'][]).map((c) => ({ label: CHANNELS[c].label, value: c, count: facets.channel?.[c] ?? 0 })) },
            { column: 'environment', title: 'Environment', options: [{ label: 'Production', value: 'production', count: facets.environment?.production ?? 0 }, { label: 'Staging', value: 'staging', count: facets.environment?.staging ?? 0 }] },
            ...(workflowId ? [] : [{ column: 'workflowId', title: 'Workflow', options: (workflows.data?.data ?? []).map((w) => ({ label: w.name, value: w.id, count: facets.workflowId?.[w.id] ?? 0 })) }]),
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          toolbarExtra={
            workflowId ? (
              <Button size="sm" onClick={() => onCreateOpenChange(true)}>
                <Plus className="size-4" /> New deployment
              </Button>
            ) : undefined
          }
          bulkActions={[
            { label: 'Pause', icon: Pause, variant: 'outline', onClick: (r) => setBulk({ kind: 'pause', rows: r }) },
            { label: 'Resume', icon: Play, variant: 'outline', onClick: (r) => setBulk({ kind: 'resume', rows: r }) },
            { label: 'Move to latest', icon: ArrowUpCircle, variant: 'outline', onClick: (r) => setBulk({ kind: 'latest', rows: r }) },
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
            <ListEmpty
              icon={Rocket}
              noun="deployments"
              filtered={list.isFiltered}
              description="A deployment puts a published workflow on a chat widget, an API endpoint or an email address."
              createLabel="New deployment"
              onCreate={() => onCreateOpenChange(true)}
            />
          }
        />
      )}

      <DeploymentSheet
        deployment={active}
        onOpenChange={(o) => !o && setActiveId(null)}
        navigation={
          active
            ? {
                currentIndex: idx,
                totalCount: rowsData.length,
                onPrev: idx > 0 ? () => setActiveId(rowsData[idx - 1].id) : undefined,
                onNext: idx < rowsData.length - 1 ? () => setActiveId(rowsData[idx + 1].id) : undefined,
              }
            : undefined
        }
        updating={update.isPending}
        onUpdate={(patch, done) =>
          active &&
          update.mutate({ id: active.id, ...patch }, { onSuccess: () => toast.success(done), onError: (e) => toast.error(`Couldn’t update ${active.name}`, { description: e.message }) })
        }
        rotating={rotate.isPending}
        onRotateKey={async () => (await rotate.mutateAsync(active!.id)).key}
        promoting={promote.isPending}
        productionTwins={active ? rowsData.filter((x) => x.environment === 'production' && x.workflowId === active.workflowId && x.channel === active.channel) : []}
        onPromote={async (input) => {
          const p = await promote.mutateAsync({ id: active!.id, ...input });
          toast.success(`${p.name} is live in production`, { description: `Serving ${p.workflowName} v${p.version}.` });
          setActiveId(p.id);
        }}
      />

      <CreateDeploymentDialog
        open={createOpen}
        onOpenChange={onCreateOpenChange}
        workflows={workflows.data?.data ?? []}
        fixedWorkflowId={workflowId}
        initialChannel={createChannel}
        isPending={create.isPending}
        onSubmit={async (input) => {
          const d = await create.mutateAsync(input);
          toast.success(`Deployed ${d.name} to ${d.environment}`, { description: `Serving ${d.workflowName} v${d.version}.` });
          setActiveId(d.id);
        }}
      />

      <BulkConfirmDialog
        open={!!copy}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`${copy?.title} · ${names.length} deployments`}
        description={copy?.description ?? ''}
        names={names}
        confirmLabel={copy?.title ?? ''}
        isPending={bulkUpdate.isPending}
        onConfirm={async () => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((d) => d.id), patch: copy!.patch });
          toastBulk(res, copy!.verb, 'deployment', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="deployment"
        count={names.length}
        description="Active production deployments are skipped; pause them first so customers are not cut off mid-conversation."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((d) => d.id));
          toastBulk(res, 'Deleted', 'deployment', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>
    </>
  );
}
