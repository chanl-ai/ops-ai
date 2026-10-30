'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlayCircle, Plus, Route, Trash2, UserCheck } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { LiveBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { StartWorkflowRunDialog } from '@/components/workflows/start-run-dialog';
import { starterDefinition } from '@/components/workflows/definition-editor/starter';
import { WorkflowDialog } from '@/components/workflows/workflow-dialog';
import { useDeleteDefinitions, usePublishDefinition } from '@/hooks/engine-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useWorkflows } from '@/hooks/queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { Workflow } from '@/lib/types/domain';
import type { WorkflowFilters } from '@/lib/types/query';

type Row = Workflow & { onRowClick: (w: Workflow) => void };

const reviewRate = (w: Workflow) => (w.runs24h ? w.reviewed24h / w.runs24h : 0);
const hrefOf = (w: Workflow) => `/workflows/definitions/${encodeURIComponent(w.id)}`;

const columns: ColumnDef<Row>[] = [
  selectColumn<Row>((w) => w.name),
  idColumn<Row>((w) => w.id),
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />, meta: { kind: 'name' },
    cell: ({ row }) => (
      <div className="min-w-52">
        <div className="flex items-center gap-2">
          <span className="font-medium">{row.original.name}</span>
        </div>
        <div className="text-xs text-muted-foreground">Starts when: {row.original.trigger}</div>
      </div>
    ),
    enableHiding: false,
  },
  {
    id: 'agents',
    header: 'Agents',
    cell: ({ row }) => (
      <div className="flex flex-wrap gap-1">
        {row.original.agentSlugs.length ? (
          row.original.agentSlugs.map((a) => (
            <code key={a} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
              {a}
            </code>
          ))
        ) : (
          <span className="text-xs text-muted-foreground">None yet</span>
        )}
      </div>
    ),
  },
  { accessorKey: 'stepCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Steps" />, meta: { kind: 'number' }, cell: ({ row }) => <span className="tabular-nums">{row.original.stepCount}</span> },
  {
    accessorKey: 'gateCount',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Review gates" />, meta: { kind: 'number' },
    cell: ({ row }) => (
      <span className="inline-flex items-center gap-1.5 tabular-nums">
        <UserCheck className="size-3.5 text-warning-text" /> {row.original.gateCount}
      </span>
    ),
  },
  { accessorKey: 'runs24h', header: ({ column }) => <DataTableColumnHeader column={column} title="Runs · 24h" />, meta: { kind: 'number' }, cell: ({ row }) => <span className="tabular-nums">{count(row.original.runs24h)}</span> },
  {
    id: 'reviewRate',
    accessorFn: reviewRate,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Sent to review" />, meta: { kind: 'number' },
    cell: ({ row }) => {
      const v = reviewRate(row.original);
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-warning" style={{ width: `${Math.round(v * 100)}%` }} />
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">{Math.round(v * 100)}%</span>
        </div>
      );
    },
  },
  { accessorKey: 'openReviews', header: ({ column }) => <DataTableColumnHeader column={column} title="Open reviews" />, meta: { kind: 'number' }, cell: ({ row }) => <span className="tabular-nums">{row.original.openReviews}</span> },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Stage" />, meta: { kind: 'status' },
    cell: ({ row }) => (
      <div className="flex flex-col items-start gap-1">
        <LiveBadge status={row.original.status} />
        {row.original.pendingPublish && <span className="text-[11px] whitespace-nowrap text-warning-text">v{row.original.pendingPublish.toVersion} awaiting approval</span>}
      </div>
    ),
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'deploymentCount',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Deployments" />, meta: { kind: 'number' },
    cell: ({ row }) => <span className="tabular-nums text-muted-foreground">{row.original.deploymentCount || '—'}</span>,
  },
  {
    accessorKey: 'updatedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, meta: { kind: 'number' },
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-muted-foreground tabular-nums">
        v{row.original.version} · {relativeTime(row.original.updatedAt)}
      </span>
    ),
  },
];

const STATUS_OPTIONS = [
  { label: 'Live', value: 'live' },
  { label: 'Draft', value: 'draft' },
  { label: 'Paused', value: 'paused' },
];

export default function WorkflowsPage() {
  const router = useRouter();
  const list = useListParams<WorkflowFilters>('name');
  const query = useWorkflows(list.params);
  const publish = usePublishDefinition();
  const deleteDrafts = useDeleteDefinitions();
  const [startOpen, setStartOpen] = React.useState(false);
  const [createOpen, setCreateOpen] = useCreateParam();
  const canBuild = useCanBuild();
  const [bulk, setBulk] = React.useState<{ kind: 'delete'; rows: Workflow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((w) => w.name);
  const nameOf = (id: string) => shown?.rows.find((w) => w.id === id)?.name ?? id;
  const facets = query.data?.facets ?? {};
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((w) => ({ ...w, onRowClick: (x: Workflow) => router.push(hrefOf(x)), href: hrefOf(w) })), [query.data, router]);

  return (
    <PageLayout
      switcher
      icon={Route}
      title="Workflows"
      description="Agents, tools and review gates wired into one run"
      actions={
        <>
          <Button variant="outline" onClick={() => setStartOpen(true)}>
            <PlayCircle className="size-4" /> Start run
          </Button>
          {canBuild && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> New workflow
            </Button>
          )}
        </>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError && !query.data ? (
        <QueryError what="workflows" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={rows}
          getRowId={(r) => r.id}
          // Stage says whether a workflow is live, a draft or in review, so it stays shown past the default of five columns.
          initialColumnVisibility={{ agents: false, stepCount: false, status: true }}
          searchColumn="name"
          searchPlaceholder="Search workflows…"
          filters={[{ column: 'status', title: 'Status', options: STATUS_OPTIONS.map((o) => ({ ...o, count: facets.status?.[o.value] ?? 0 })) }]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={canBuild ? [{ label: 'Delete', icon: Trash2, variant: 'outline', onClick: (rows) => setBulk({ kind: 'delete', rows }) }] : undefined}
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
              icon={Route}
              noun="workflows"
              filtered={list.isFiltered}
              description="A workflow strings agents, tools and review gates into a run."
              createLabel={canBuild ? 'New workflow' : undefined}
              onCreate={() => setCreateOpen(true)}
            />
          }
        />
      )}
      <BulkConfirmDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Delete ${plural(names.length, 'workflow')}`}
        description="Deletes drafts with every version. A workflow that has run is kept."
        names={names}
        confirmLabel="Delete"
        isPending={deleteDrafts.isPending}
        onConfirm={async () => {
          const rows = bulk!.rows;
          const res = await deleteDrafts.mutateAsync(rows.filter((w) => w.status === 'draft').map((w) => w.id));
          const kept = rows.filter((w) => w.status !== 'draft').map((w) => ({ id: w.id, reason: 'It has runs' }));
          toastBulk({ updated: res.updated, skipped: [...res.skipped, ...kept] }, 'Deleted', 'workflow', nameOf);
          setBulk(null);
          setResetKey((k) => k + 1);
        }}
      />
      <StartWorkflowRunDialog open={startOpen} onOpenChange={setStartOpen} />
      <WorkflowDialog
        open={createOpen && canBuild}
        onOpenChange={setCreateOpen}
        isPending={publish.isPending}
        onSubmit={async ({ name, trigger }) => {
          const p = await publish.mutateAsync(starterDefinition(name.trim(), trigger.trim()));
          toast.success(`Created ${name.trim()}`);
          router.push(`/workflows/definitions/${encodeURIComponent(p.workflowId)}`);
        }}
      />
    </PageLayout>
  );
}
