'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Building2, Pause, Play, Plus, Route, UserCheck } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { selectColumn } from '@/components/shared/select-column';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { LiveBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { WorkflowDialog } from '@/components/workflows/workflow-dialog';
import { useBulkUpdateWorkflows, useCreateWorkflow, useLookups, useWorkflows } from '@/hooks/queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { Workflow } from '@/lib/types/domain';
import type { WorkflowFilters } from '@/lib/types/query';

type Row = Workflow & { onRowClick: (w: Workflow) => void };

const reviewRate = (w: Workflow) => (w.runs24h ? w.reviewed24h / w.runs24h : 0);

const columns: ColumnDef<Row>[] = [
  selectColumn<Row>((w) => w.name),
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => (
      <div className="min-w-52">
        <div className="font-medium">{row.original.name}</div>
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
  { accessorKey: 'stepCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Steps" />, cell: ({ row }) => <span className="tabular-nums">{row.original.stepCount}</span> },
  {
    accessorKey: 'gateCount',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Review gates" />,
    cell: ({ row }) => (
      <span className="inline-flex items-center gap-1.5 tabular-nums">
        <UserCheck className="size-3.5 text-amber-600" /> {row.original.gateCount}
      </span>
    ),
  },
  { accessorKey: 'runs24h', header: ({ column }) => <DataTableColumnHeader column={column} title="Runs · 24h" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.runs24h)}</span> },
  {
    id: 'reviewRate',
    accessorFn: reviewRate,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Sent to review" />,
    cell: ({ row }) => {
      const v = reviewRate(row.original);
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.round(v * 100)}%` }} />
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">{Math.round(v * 100)}%</span>
        </div>
      );
    },
  },
  { accessorKey: 'openReviews', header: ({ column }) => <DataTableColumnHeader column={column} title="Open reviews" />, cell: ({ row }) => <span className="tabular-nums">{row.original.openReviews}</span> },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Stage" />,
    cell: ({ row }) => (
      <div className="flex flex-col items-start gap-1">
        <LiveBadge status={row.original.status} />
        {row.original.pendingPublish && <span className="text-[11px] whitespace-nowrap text-amber-700 dark:text-amber-400">v{row.original.pendingPublish.toVersion} awaiting approval</span>}
      </div>
    ),
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'deploymentCount',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Deployments" />,
    cell: ({ row }) => <span className="tabular-nums text-muted-foreground">{row.original.deploymentCount || '—'}</span>,
  },
  {
    accessorKey: 'updatedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />,
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
  const create = useCreateWorkflow();
  const [createOpen, setCreateOpen] = useCreateParam();
  const { data: lookups } = useLookups();
  const bulkUpdate = useBulkUpdateWorkflows();
  const [bulk, setBulk] = React.useState<{ kind: 'pause' | 'resume' | 'owner'; rows: Workflow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const eligible = (shown?.rows ?? []).filter((x) => x.status !== 'draft');
  const names = (shown?.rows ?? []).map((w) => w.name);
  const nameOf = (id: string) => shown?.rows.find((w) => w.id === id)?.name ?? id;
  const facets = query.data?.facets ?? {};
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((w) => ({ ...w, onRowClick: (x: Workflow) => router.push(`/workflows/${x.id}`), href: `/workflows/${w.id}` })), [query.data, router]);

  return (
    <PageLayout
      icon={Route}
      title="Workflows"
      description="Agents, tools and review gates wired into one run"
      actions={
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> New workflow
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError && !query.data ? (
        <QueryError what="workflows" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={rows}
          getRowId={(r) => r.id}
          initialColumnVisibility={{ agents: false, stepCount: false }}
          searchColumn="name"
          searchPlaceholder="Search workflows…"
          filters={[{ column: 'status', title: 'Status', options: STATUS_OPTIONS.map((o) => ({ ...o, count: facets.status?.[o.value] ?? 0 })) }]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            { label: 'Pause', icon: Pause, variant: 'outline', onClick: (rows) => setBulk({ kind: 'pause', rows }) },
            { label: 'Resume', icon: Play, variant: 'outline', onClick: (rows) => setBulk({ kind: 'resume', rows }) },
            { label: 'Change owner', icon: Building2, variant: 'outline', onClick: (rows) => setBulk({ kind: 'owner', rows }) },
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
              icon={Route}
              noun="workflows"
              filtered={list.isFiltered}
              description="A workflow strings agents, tools and review gates into a run."
              createLabel="New workflow"
              onCreate={() => setCreateOpen(true)}
            />
          }
        />
      )}
      <BulkConfirmDialog
        open={bulk?.kind === 'pause' || bulk?.kind === 'resume'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`${shown?.kind === 'pause' ? 'Pause' : 'Resume'} ${eligible.length === names.length ? plural(names.length, 'workflow') : `${eligible.length} of ${plural(names.length, 'workflow')}`}`}
        description={shown?.kind === 'pause' ? 'New triggers queue instead of running. Open reviews stay open. Drafts are skipped.' : 'Queued triggers run immediately. Drafts are skipped; publish them from the editor.'}
        names={names}
        confirmLabel={shown?.kind === 'pause' ? 'Pause' : 'Resume'}
        isPending={bulkUpdate.isPending}
        onConfirm={async () => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((w) => w.id), patch: { status: bulk!.kind === 'pause' ? 'paused' : 'live' } });
          toastBulk(res, bulk!.kind === 'pause' ? 'Paused' : 'Resumed', 'workflow', nameOf);
          setBulk(null);
          setResetKey((k) => k + 1);
        }}
      />
      <BulkFieldDialog
        open={bulk?.kind === 'owner'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Change owner of ${names.length} workflows`}
        description="The owning team is notified about failed runs and overdue reviews."
        fieldLabel="Team"
        options={lookups?.owners ?? []}
        names={names}
        confirmLabel="Change owner"
        isPending={bulkUpdate.isPending}
        onConfirm={async (owner) => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((w) => w.id), patch: { owner } });
          toastBulk(res, 'Moved', 'workflow', nameOf);
          setBulk(null);
          setResetKey((k) => k + 1);
        }}
      />
      <WorkflowDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        isPending={create.isPending}
        onSubmit={async (input) => {
          const wf = await create.mutateAsync(input);
          toast.success(`Created ${wf.name}`);
          router.push(`/workflows/${wf.id}`);
        }}
      />
    </PageLayout>
  );
}
