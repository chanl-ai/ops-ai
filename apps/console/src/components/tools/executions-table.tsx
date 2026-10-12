'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { ScrollText } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ApprovalCell, CallerCell, CallStatusText, OperationBadge } from '@/components/logs/log-meta';
import { StopRowClick } from '@/components/shared/form-field';
import { ListEmpty } from '@/components/shared/query-states';
import { dateTime, ms, relativeTime } from '@/lib/format';
import type { ToolCallRow } from '@/lib/types/governance';

type Row = ToolCallRow & { onRowClick: (r: ToolCallRow) => void; rowTestId: string };

const link = 'underline-offset-4 hover:underline';

const columns: ColumnDef<Row>[] = [
  {
    // Holds every searched field so the table's own filter finds a call by caller, run or record too.
    id: 'target',
    accessorFn: (r) => `${r.target} ${r.subject?.name ?? ''} ${r.actor?.name ?? ''} ${r.workflowName} ${r.agentName} ${r.runId} ${r.record ?? ''}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Operation" />,
    cell: ({ row }) => (
      <div className="flex min-w-0 flex-col items-start gap-1">
        <code className="max-w-56 truncate font-mono text-[13px] font-medium" title={row.original.target}>
          {row.original.target}
        </code>
        <OperationBadge operation={row.original.operation} />
      </div>
    ),
    enableHiding: false,
  },
  { id: 'caller', header: 'Caller', cell: ({ row }) => <CallerCell call={row.original} /> },
  {
    id: 'run',
    header: 'Run',
    cell: ({ row }) => (
      <StopRowClick align="start">
        <Link href={`/workflows/${row.original.workflowId}?tab=runs`} className={`${link} font-mono text-xs whitespace-nowrap`}>
          {row.original.caseId ?? row.original.runId}
        </Link>
      </StopRowClick>
    ),
  },
  { accessorKey: 'record', header: 'Record', cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground">{row.original.record ?? '—'}</span> },
  { id: 'decision', header: 'Decision', cell: ({ row }) => <ApprovalCell approval={row.original.approval} /> },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <div className="flex flex-col gap-0.5">
        <CallStatusText status={row.original.status} />
        {row.original.failureSide && (
          <span className="text-xs whitespace-nowrap text-muted-foreground" title={row.original.errorMessage}>
            {row.original.failureSide === 'ours' ? 'Our side' : 'Upstream'} · {row.original.errorCode}
          </span>
        )}
      </div>
    ),
  },
  { accessorKey: 'latencyMs', header: 'Latency', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground tabular-nums">{ms(row.original.latencyMs)}</span> },
  {
    accessorKey: 'at',
    header: 'Time',
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(row.original.at)}>
        {relativeTime(row.original.at)}
      </span>
    ),
  },
];

/** A module's latest calls with who made them; a row opens the call. The full, filterable log is Activity → Tool calls. */
export function ExecutionsTable({ calls, onOpen }: { calls: ToolCallRow[]; onOpen: (id: string) => void }) {
  const rows: Row[] = React.useMemo(() => calls.map((c) => ({ ...c, onRowClick: (x: ToolCallRow) => onOpen(x.id), rowTestId: `execution-row-${c.id}` })), [calls, onOpen]);
  return (
    <DataTableWithViews
      columns={columns}
      data={rows}
      getRowId={(r) => r.id}
      searchColumn="target"
      searchPlaceholder="Search operation, caller, run or record…"
      initialColumnVisibility={{ record: false }}
      emptyState={<ListEmpty icon={ScrollText} noun="calls" filtered={false} description="Calls appear here once a workflow calls this module." />}
    />
  );
}
