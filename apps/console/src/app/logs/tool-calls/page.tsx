'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertCircle, Ban, Clock, ScrollText, UserCheck } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { APPROVAL_LABEL, ApprovalCell, cad, CALL_STATUS_LABEL, CallStatusText, GATEWAY_LABEL, GatewayIcon, OPERATION_LABEL, OperationBadge, options } from '@/components/logs/log-meta';
import { ToolCallSheet } from '@/components/logs/tool-call-sheet';
import { PageLayout } from '@/components/page-layout';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useToolCall, useToolCalls } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, dateTime, ms, pct, relativeTime } from '@/lib/format';
import type { ToolCallFilters, ToolCallRow } from '@/lib/types/governance';

type Row = ToolCallRow & { onRowClick: (r: ToolCallRow) => void };

const link = 'underline-offset-4 hover:underline';

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'at',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Time" />,
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(row.original.at)}>
        {relativeTime(row.original.at)}
      </span>
    ),
  },
  {
    // Holds every searched field so the table's own filter keeps the rows the server matched.
    id: 'target',
    accessorFn: (r) => `${r.target} ${r.system} ${r.workflowName} ${r.agentName} ${r.runId} ${r.caseId ?? ''} ${r.record ?? ''}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Tool or model" />,
    cell: ({ row }) => (
      <div className="flex max-w-72 min-w-48 items-start gap-2">
        <GatewayIcon gateway={row.original.gateway} className="mt-0.5" />
        <div className="min-w-0">
          <code className="block truncate font-mono text-[13px] font-medium" title={row.original.target}>
            {row.original.target}
          </code>
          <div className="truncate text-xs text-muted-foreground">{row.original.system}</div>
        </div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'gateway', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  { accessorKey: 'workflowId', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  {
    accessorKey: 'workflowName',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => (
      <div className="max-w-56 min-w-36">
        <div className="truncate text-sm" title={row.original.workflowName}>
          {row.original.workflowName}
        </div>
        <div className="truncate text-xs text-muted-foreground" title={row.original.agentName}>
          {row.original.agentName}
        </div>
      </div>
    ),
  },
  {
    id: 'run',
    header: 'Run or case',
    cell: ({ row }) => (
      <StopRowClick align="start">
        <div className="flex flex-col font-mono text-xs whitespace-nowrap">
          <Link href={`/workflows/${row.original.workflowId}?tab=runs`} className={link}>
            {row.original.runId}
          </Link>
          {row.original.caseId && (
            <Link href={`/cases/${row.original.caseId}`} className={`${link} text-muted-foreground`}>
              {row.original.caseId}
            </Link>
          )}
        </div>
      </StopRowClick>
    ),
  },
  { accessorKey: 'operation', header: ({ column }) => <DataTableColumnHeader column={column} title="Operation" />, cell: ({ row }) => <OperationBadge operation={row.original.operation} />, filterFn: facetFilterFn },
  { accessorKey: 'record', header: ({ column }) => <DataTableColumnHeader column={column} title="Bound record" />, cell: ({ row }) => <span className="text-xs whitespace-nowrap">{row.original.record ?? '—'}</span> },
  { id: 'approval', accessorFn: (r) => r.approval.kind, header: ({ column }) => <DataTableColumnHeader column={column} title="Approval" />, cell: ({ row }) => <ApprovalCell approval={row.original.approval} />, filterFn: facetFilterFn },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <CallStatusText status={row.original.status} />, filterFn: facetFilterFn },
  { accessorKey: 'latencyMs', header: ({ column }) => <DataTableColumnHeader column={column} title="Latency" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground tabular-nums">{ms(row.original.latencyMs)}</span> },
  { accessorKey: 'cost', header: ({ column }) => <DataTableColumnHeader column={column} title="Cost" />, cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{row.original.cost != null ? cad(row.original.cost) : '—'}</span> },
];

export default function ToolCallsPage() {
  const list = useListParams<ToolCallFilters>('target', 20);
  const q = useSearchParams().get('q');
  const query = useToolCalls(list.params);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const detail = useToolCall(activeId);

  const calls = query.data?.data ?? [];
  const index = calls.findIndex((c) => c.id === activeId);
  const active = index >= 0 ? calls[index] : null;
  const rows: Row[] = React.useMemo(() => calls.map((c) => ({ ...c, onRowClick: (x: ToolCallRow) => setActiveId(x.id) })), [calls]);

  const stats = query.data?.stats;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const workflowOptions = React.useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of calls) seen.set(c.workflowId, c.workflowName);
    for (const id of Object.keys(facets.workflowId ?? {})) if (!seen.has(id)) seen.set(id, id);
    return [...seen].map(([value, label]) => ({ value, label }));
  }, [calls, facets.workflowId]);

  return (
    <PageLayout icon={ScrollText} title="Tool calls" description="Every tool and model call through the data and AI gateways, with its approval and policy">
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={10} />
      ) : query.isError && !query.data ? (
        <QueryError what="tool calls" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Failed" value={stats ? count(stats.failed) : undefined} icon={AlertCircle} footer={{ text: `${pct(stats?.errorRate ?? 0)} of calls · p95 ${ms(stats?.p95Ms ?? 0)}`, subtext: 'Errors returned by the system' }} />
            <StatCard label="Denied" value={stats ? count(stats.denied) : undefined} icon={Ban} footer={{ text: 'Refused at the gateway', subtext: 'No grant, or an expired one' }} />
            <StatCard label="Writes approved by a person" value={stats ? count(stats.writesApprovedByPerson) : undefined} icon={UserCheck} footer={{ text: 'Approval token checked at the gateway', subtext: 'Policy approvals counted separately' }} />
            <StatCard label="Awaiting approval" value={stats ? count(stats.awaitingApproval) : undefined} icon={Clock} footer={{ text: 'Paused until someone decides', subtext: 'Open in Reviews' }} />
          </StatCardGrid>

          {query.isError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex items-center justify-between gap-2">
                Refreshing the log failed. These are the last results that loaded.
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
            searchColumn="target"
            initialColumnFilters={q ? [{ id: 'target', value: q }] : undefined}
            searchPlaceholder="Search tool, model, workflow, run, case or record…"
            initialColumnVisibility={{ record: false, cost: false, run: false }}
            filters={[
              { column: 'gateway', title: 'Gateway', options: withCounts('gateway', options(GATEWAY_LABEL)) },
              { column: 'workflowId', title: 'Workflow', options: withCounts('workflowId', workflowOptions) },
              { column: 'operation', title: 'Operation', options: withCounts('operation', options(OPERATION_LABEL)) },
              { column: 'approval', title: 'Approval', options: withCounts('approval', options(APPROVAL_LABEL)) },
              { column: 'status', title: 'Status', options: withCounts('status', options(CALL_STATUS_LABEL)) },
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
            emptyState={<ListEmpty icon={ScrollText} noun="calls" filtered={list.isFiltered} description="Calls appear here as soon as a workflow in this team runs." />}
          />
        </div>
      )}

      <ToolCallSheet
        row={active}
        call={detail.data}
        isPending={detail.isPending}
        isError={detail.isError}
        onRetry={() => detail.refetch()}
        onOpenChange={(o) => !o && setActiveId(null)}
        navigation={
          active
            ? {
                currentIndex: index,
                totalCount: calls.length,
                onPrev: index > 0 ? () => setActiveId(calls[index - 1].id) : undefined,
                onNext: index < calls.length - 1 ? () => setActiveId(calls[index + 1].id) : undefined,
              }
            : undefined
        }
      />
    </PageLayout>
  );
}
