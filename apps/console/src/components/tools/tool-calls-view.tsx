'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertCircle, Ban, Clock, ScrollText, UserCheck } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { Badge } from '@/components/ui/badge';
import { APPROVAL_LABEL, ApprovalCell, cad, CALL_STATUS_LABEL, CallStatusText, GATEWAY_LABEL, GatewayIcon, OPERATION_LABEL, OperationBadge, options } from '@/components/logs/log-meta';
import { FailureReason } from '@/components/logs/failure-reason';
import { ToolCallSheet } from '@/components/logs/tool-call-sheet';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { useToolCall, useToolCalls } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, dateTime, ms, pct, relativeTime } from '@/lib/format';
import type { ToolCallFilters, ToolCallRow } from '@/lib/types/governance';

type Row = ToolCallRow & { onRowClick: (r: ToolCallRow) => void };

const link = 'underline-offset-4 hover:underline';

const columns: ColumnDef<Row>[] = [
  selectColumn<Row>((r) => r.id),
  idColumn<Row>((r) => r.id),
  {
    accessorKey: 'at',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Time" />,
    // On a phone the call's name and why it failed take the row; the time is on the call's details.
    meta: { kind: 'date', className: 'max-sm:hidden' },
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(row.original.at)}>
        {relativeTime(row.original.at)}
      </span>
    ),
  },
  {
    // Holds every searched field so the table's own filter keeps the rows the server matched.
    id: 'target',
    accessorFn: (r) => `${r.title ?? ''} ${r.target} ${r.system} ${r.workflowName} ${r.agentName} ${r.runId} ${r.caseId ?? ''} ${r.record ?? ''}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Tool or model" />,
    // The call's name column, pinned so its failure reason stays on screen however wide the table is.
    meta: { kind: 'name' },
    cell: ({ row }) => (
      <div className="flex max-w-72 min-w-48 items-start gap-2">
        <GatewayIcon gateway={row.original.gateway} className="mt-0.5" />
        <div className="min-w-0">
          {/* A plugin tool reads by its title; the call's name stays beside it. */}
          {row.original.title && <div className="truncate text-sm font-medium">{row.original.title}</div>}
          <code className={`block truncate font-mono ${row.original.title ? 'text-xs text-muted-foreground' : 'text-[13px] font-medium'}`} title={row.original.target}>
            {row.original.target}
          </code>
          <div className="truncate text-xs text-muted-foreground">{row.original.app ?? row.original.system}</div>
          <FailureReason call={row.original} />
        </div>
      </div>
    ),
    enableHiding: false,
  },
  // These three only carry a filter (the run a Cases sheet linked here with, `?run=`), so they are never drawn.
  { accessorKey: 'gateway', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  { accessorKey: 'workflowId', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  { accessorKey: 'runId', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  {
    accessorKey: 'workflowName',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => <NameCell name={row.original.workflowName} />,
  },
  {
    accessorKey: 'agentName',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Agent" />,
    cell: ({ row }) => <NameCell name={row.original.agentName} />,
  },
  {
    // Whose account of the app the call signed in with: a person's own, or the team account.
    id: 'as',
    accessorFn: (r) => (r.runAs?.kind === 'person' ? (r.runAs.email ?? '') : r.runAs?.kind === 'team' ? 'Team account' : ''),
    header: ({ column }) => <DataTableColumnHeader column={column} title="As" />,
    cell: ({ row }) =>
      row.original.runAs?.kind === 'person' ? (
        <span className="block max-w-48 truncate text-sm">{row.original.runAs.email}</span>
      ) : row.original.runAs?.kind === 'team' ? (
        <Badge variant="secondary">Team account</Badge>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
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
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <CallStatusText status={row.original.status} replayOf={row.original.replayOf} />,
    filterFn: facetFilterFn,
  },
  { accessorKey: 'latencyMs', header: ({ column }) => <DataTableColumnHeader column={column} title="Latency" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground tabular-nums">{ms(row.original.latencyMs)}</span> },
  { accessorKey: 'cost', header: ({ column }) => <DataTableColumnHeader column={column} title="Cost" />, cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{row.original.cost != null ? cad(row.original.cost) : '—'}</span> },
];

/** A workflow or agent the API named, or a dash for a call that had none. */
function NameCell({ name }: { name?: string | null }) {
  return name ? (
    <span className="block max-w-56 min-w-28 truncate text-sm" title={name}>
      {name}
    </span>
  ) : (
    <span className="text-xs text-muted-foreground">—</span>
  );
}

/**
 * The tool-call log: every gateway call, newest first, each opening its sheet. The Tool calls page shows all of them;
 * a tool's and an app's Logs tab show the same list fixed to that tool or app, so there is one log, read in one place.
 */
export function ToolCallsView({ fixed, run, q, totals = true, emptyText }: { fixed?: Pick<ToolCallFilters, 'tool' | 'moduleId'>; run?: string | null; q?: string | null; totals?: boolean; emptyText?: string }) {
  const list = useListParams<ToolCallFilters>('target', 20);
  const query = useToolCalls({ ...list.params, filters: { ...list.params.filters, ...fixed } });
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
    <>
      {query.isPending ? (
        <PageSkeleton statCards={totals ? 4 : 0} tableRows={10} />
      ) : query.isError && !query.data ? (
        <QueryError what="tool calls" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="tool-calls">
          {/* The cards show only when the answer carries totals; tools-service's /executions serves none yet. */}
          {!totals || !stats ? null : (
          <StatCardGrid columns={4}>
            <StatCard label="Failed" value={count(stats.failed)} icon={AlertCircle} footer={{ text: `${pct(stats.errorRate ?? 0)} of calls · p95 ${ms(stats.p95Ms ?? 0)}`, subtext: 'Errors returned by the app' }} />
            <StatCard label="Denied" value={count(stats.denied)} icon={Ban} footer={{ text: 'Refused at the gateway', subtext: 'No grant, or an expired one' }} />
            <StatCard label="Writes approved by a person" value={count(stats.writesApprovedByPerson)} icon={UserCheck} footer={{ text: 'Approval token checked at the gateway', subtext: 'Policy approvals counted separately' }} />
            <StatCard label="Awaiting approval" value={count(stats.awaitingApproval)} icon={Clock} footer={{ text: 'Paused until someone decides', subtext: 'Open in Reviews' }} />
          </StatCardGrid>
          )}

          <DataTableWithViews
            columns={columns}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="target"
            initialColumnFilters={[...(q ? [{ id: 'target', value: q }] : []), ...(run ? [{ id: 'runId', value: [run] }] : [])]}
            searchPlaceholder="Search tools, models, runs or cases…"
            // Whom each call ran as and how it ended always show, as the log's frame draws them (Tool, App, As, Status, When).
            initialColumnVisibility={{ gateway: false, workflowId: false, runId: false, record: false, cost: false, run: false, as: true, status: true }}
            filters={[
              { column: 'gateway', title: 'Kind', options: withCounts('gateway', options(GATEWAY_LABEL)) },
              { column: 'workflowId', title: 'Workflow', options: withCounts('workflowId', workflowOptions) },
              { column: 'operation', title: 'Operation', options: withCounts('operation', options(OPERATION_LABEL)) },
              { column: 'approval', title: 'Approval', options: withCounts('approval', options(APPROVAL_LABEL)) },
              { column: 'status', title: 'Status', options: withCounts('status', options(CALL_STATUS_LABEL)) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            serverPagination={serverPagination(list, query)}
            emptyState={<ListEmpty icon={ScrollText} noun="calls" filtered={list.isFiltered} description={emptyText ?? (run ? `No gateway call ran for ${run} yet.` : 'Calls appear here as soon as a workflow in this team runs.')} />}
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
    </>
  );
}
