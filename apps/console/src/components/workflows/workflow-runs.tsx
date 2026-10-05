'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { useTestFromRun, useWorkflowRuns } from '@/hooks/queries';
import { Button } from '@/components/ui/button';
import { FlaskConical } from 'lucide-react';
import { toast } from 'sonner';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { WorkflowRun } from '@/lib/types/domain';
import type { RunFilters } from '@/lib/types/query';

import { duration, RUN_STATUS_OPTIONS, RunStatusBadge, RunTrace } from './run-trace';

type Row = WorkflowRun & { onRowClick: (r: WorkflowRun) => void };

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'id',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Run" />,
    cell: ({ row }) => (
      <div>
        <div className="font-mono text-xs">{row.original.id}</div>
        <div className="text-sm">{row.original.subject}</div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <RunStatusBadge status={row.original.status} />, filterFn: facetFilterFn },
  {
    id: 'path',
    header: 'Last step',
    cell: ({ row }) => {
      const last = [...row.original.steps].reverse().find((s) => s.status !== 'skipped');
      return <span className="text-muted-foreground">{last?.label ?? '—'}</span>;
    },
  },
  { accessorKey: 'version', header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, cell: ({ row }) => <span className="font-mono text-xs">v{row.original.version}</span> },
  { accessorKey: 'durationMs', header: ({ column }) => <DataTableColumnHeader column={column} title="Duration" />, cell: ({ row }) => <span className="tabular-nums">{duration(row.original.durationMs)}</span> },
  { accessorKey: 'startedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Started" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.startedAt)}</span> },
];

/** Run history for one workflow; a row opens the step trace in a sheet with prev/next. */
export function WorkflowRuns({ workflowId }: { workflowId: string }) {
  const list = useListParams<RunFilters>('id', 20);
  const query = useWorkflowRuns(workflowId, list.params);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const saveAsTest = useTestFromRun();
  const runs = query.data?.data ?? [];
  const idx = runs.findIndex((r) => r.id === activeId);
  const active = idx >= 0 ? runs[idx] : null;
  const rows: Row[] = React.useMemo(() => runs.map((r) => ({ ...r, onRowClick: (x: WorkflowRun) => setActiveId(x.id) })), [runs]);
  const facets = query.data?.facets ?? {};

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="runs" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  return (
    <>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="id"
        searchPlaceholder="Search run ID or customer…"
        filters={[{ column: 'status', title: 'Status', options: RUN_STATUS_OPTIONS.map((o) => ({ ...o, count: facets.status?.[o.value] ?? 0 })) }]}
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
        emptyState={<ListEmpty icon={Activity} noun="runs" filtered={list.isFiltered} description="Runs appear here once the workflow is published and triggered." />}
      />
      <DetailSheet
        open={!!active}
        onOpenChange={(o) => !o && setActiveId(null)}
        title={active ? `${active.id} · ${active.subject}` : ''}
        description={active ? `Started ${relativeTime(active.startedAt)}` : undefined}
        navigation={
          active
            ? {
                currentIndex: idx,
                totalCount: runs.length,
                onPrev: idx > 0 ? () => setActiveId(runs[idx - 1].id) : undefined,
                onNext: idx < runs.length - 1 ? () => setActiveId(runs[idx + 1].id) : undefined,
              }
            : undefined
        }
        testId="run-sheet"
        scrollKey={active?.id}
        footerActions={
          active && (
            <Button
              size="sm"
              variant="outline"
              disabled={saveAsTest.isPending}
              onClick={() =>
                saveAsTest.mutate(active.id, {
                  onSuccess: (t) => toast.success('Saved as a test case', { description: `${t.name}. It runs on every publish request.` }),
                  onError: (e) => toast.error('Couldn’t save the test case', { description: e.message }),
                })
              }
            >
              <FlaskConical className="size-3.5" /> Save as test case
            </Button>
          )
        }
      >
        {active && <RunTrace run={active} />}
      </DetailSheet>
    </>
  );
}
