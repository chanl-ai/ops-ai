'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertCircle, Workflow as WorkflowIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { RunStatus } from '@/components/workflows/run-journal/run-status';
import { StartedBy } from '@/components/workflows/started-by';
import { useEngineRuns } from '@/hooks/engine-queries';
import { useWorkflows } from '@/hooks/queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { EngineRun } from '@/lib/types/engine';

type Row = EngineRun & { onRowClick: (r: EngineRun) => void; rowTestId: string };

const STATUS_OPTIONS = [
  { label: 'Waiting on a person', value: 'waiting' },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
  { label: 'Succeeded', value: 'succeeded' },
  { label: 'Failed', value: 'failed' },
  { label: 'Cancelled', value: 'cancelled' },
];

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'id',
    header: 'Run',
    meta: { kind: 'name' },
    cell: ({ row }) => (
      <div className="min-w-0">
        <div className="font-medium">{row.original.workflowName ?? row.original.workflowId}</div>
        <div className="font-mono text-xs text-muted-foreground">
          {row.original.id} · version {row.original.version}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'workflowId', header: 'Workflow', filterFn: facetFilterFn, enableHiding: false },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, meta: { kind: 'status' }, cell: ({ row }) => <RunStatus status={row.original.status} testId="runner-run-status" />, filterFn: facetFilterFn },
  {
    // How the run ended: the outcome its End step names, or the error that stopped it.
    accessorKey: 'outcome',
    header: 'Outcome',
    meta: { kind: 'description' },
    cell: ({ row }) =>
      row.original.outcome ? (
        <span data-testid={`run-outcome-${row.original.id}`}>{row.original.outcomeText ?? row.original.outcome}</span>
      ) : row.original.error ? (
        <span className="text-destructive" title={row.original.error} data-testid={`run-outcome-${row.original.id}`}>
          {row.original.error}
        </span>
      ) : null,
  },
  { accessorKey: 'mode', header: 'Mode', meta: { kind: 'status' }, cell: ({ row }) => <span className="capitalize text-muted-foreground">{row.original.mode}</span> },
  { accessorKey: 'createdBy', header: 'Started by', meta: { kind: 'status' }, cell: ({ row }) => <span className="text-muted-foreground"><StartedBy run={row.original} /></span> },
  { accessorKey: 'createdAt', header: 'Started', meta: { kind: 'date' }, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.createdAt)}</span> },
  { accessorKey: 'finishedAt', header: 'Finished', meta: { kind: 'date' }, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.finishedAt ? relativeTime(row.original.finishedAt) : '—'}</span> },
];

/**
 * Runs of the workflows built on the canvas (Runner · v2), from agents-service `GET /v1/runs`: paged, filtered and
 * counted on the server. A row opens the run's own page with its graph and steps.
 */
export function RunnerRuns() {
  const router = useRouter();
  const list = useListParams<{ workflowId?: string[]; status?: string[] }>();
  const filters = list.params.filters ?? {};
  const query = useEngineRuns({ workflowId: filters.workflowId?.[0], status: filters.status, page: list.params.page, pageSize: list.params.pageSize });
  const { data: workflows } = useWorkflows({ page: 1, pageSize: 100 });
  const rows: Row[] = React.useMemo(
    () => (query.data?.data ?? []).map((r) => ({ ...r, onRowClick: (x: EngineRun) => router.push(`/workflows/runs/${encodeURIComponent(x.id)}`), rowTestId: `runner-run-row-${r.id}` })),
    [query.data, router],
  );
  const counts = query.data?.facets?.status ?? {};
  const workflowOptions = (workflows?.data ?? []).filter((w) => w.engine === 'v2').map((w) => ({ label: w.name, value: w.id }));

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="runs" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="runner-runs-error" />;
  return (
    <div className="flex flex-col gap-4" data-testid="runner-runs">
      {query.isError && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertDescription className="flex items-center justify-between gap-2">
            Refreshing runs failed. These are the last results that loaded.
            <Button size="sm" variant="outline" onClick={() => query.refetch()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        initialColumnVisibility={{ workflowId: false }}
        filters={[
          { column: 'workflowId', title: 'Workflow', options: workflowOptions },
          { column: 'status', title: 'Status', options: STATUS_OPTIONS.map((o) => ({ ...o, count: counts[o.value] ?? 0 })) },
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
            icon={WorkflowIcon}
            noun="runs"
            filtered={list.isFiltered}
            createLabel="Go to workflows"
            onCreate={() => router.push('/workflows')}
            description="A run appears here when a workflow built on the canvas starts, from Start run, an email, a schedule or an agent."
          />
        }
      />
    </div>
  );
}
