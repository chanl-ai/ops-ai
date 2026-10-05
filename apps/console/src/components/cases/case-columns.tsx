'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { selectColumn } from '@/components/shared/select-column';
import { CaseStatusBadge, ConfidenceBar, PriorityBadge, SlaText } from '@/components/status-badges';
import { facetFilterFn } from '@/hooks/use-list-params';
import type { CasePriority, CaseRow } from '@/lib/types/cases';

export type CaseTableRow = CaseRow & { onRowClick: (r: CaseRow) => void; href: string; rowTestId: string };

const PRIORITY_ORDER: Record<CasePriority, number> = { urgent: 0, high: 1, normal: 2, low: 3 };
export const caseIsOpen = (c: Pick<CaseRow, 'status'>) => c.status !== 'closed';

export const caseColumns: ColumnDef<CaseTableRow>[] = [
  selectColumn<CaseTableRow>((r) => r.id, (r) => caseIsOpen(r)),
  {
    id: 'subject',
    accessorFn: (r) => `${r.subject} ${r.requester} ${r.id}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Case" />,
    cell: ({ row }) => (
      <div className="min-w-60">
        <div className="font-medium">{row.original.subject}</div>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{row.original.id}</span> · {row.original.requester}
          {row.original.account && ` · ${row.original.account}`}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'intentId',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Intent" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.intentName}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'queue',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Queue" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.queue}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'priority',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Priority" />,
    cell: ({ row }) => <PriorityBadge priority={row.original.priority} />,
    sortingFn: (a, b) => PRIORITY_ORDER[a.original.priority] - PRIORITY_ORDER[b.original.priority],
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'confidence',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Intent confidence" />,
    cell: ({ row }) => <ConfidenceBar value={row.original.confidence} />,
  },
  {
    accessorKey: 'slaMinutes',
    header: ({ column }) => <DataTableColumnHeader column={column} title="SLA" />,
    cell: ({ row }) => <SlaText minutes={row.original.slaMinutes ?? 0} open={caseIsOpen(row.original)} paused={row.original.status === 'waiting_customer'} />,
  },
  {
    accessorKey: 'pendingApprovals',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Approvals" />,
    cell: ({ row }) =>
      row.original.pendingApprovals ? (
        <span className="whitespace-nowrap text-xs font-medium text-amber-700 dark:text-amber-400">{row.original.pendingApprovals} waiting</span>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      ),
  },
  {
    accessorKey: 'assignee',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Assignee" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.assignee ?? 'Unassigned'}</span>,
  },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <CaseStatusBadge status={row.original.status} />,
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'mailbox',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Mailbox" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{row.original.mailbox}</span>,
    enableSorting: false,
  },
];
