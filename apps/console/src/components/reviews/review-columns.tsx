'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { ConfidenceBar, KIND_LABEL, ReviewStatusBadge, RiskBadge, SlaText } from '@/components/status-badges';
import { selectColumn } from '@/components/shared/select-column';
import { facetFilterFn } from '@/hooks/use-list-params';
import { money } from '@/lib/format';
import type { Review, Risk } from '@/lib/types/domain';

export type ReviewRow = Review & { onRowClick: (r: Review) => void; rowTestId: string };

const RISK_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, low: 3 };
export const isOpen = (r: Pick<Review, 'status'>) => r.status === 'pending' || r.status === 'in_review';

export const reviewColumns: ColumnDef<ReviewRow>[] = [
  selectColumn<ReviewRow>((r) => r.id, (r) => isOpen(r)),
  {
    id: 'title',
    accessorFn: (r) => `${r.title} ${r.customer} ${r.id}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Request" />,
    cell: ({ row }) => (
      <div className="min-w-60">
        <div className="font-medium">{row.original.title}</div>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{row.original.id}</span> · {row.original.customer}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'workflowId',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => <span className="text-muted-foreground">{row.original.workflowName}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'kind',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />,
    cell: ({ row }) => <span className="text-muted-foreground">{KIND_LABEL[row.original.kind]}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'risk',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Risk" />,
    cell: ({ row }) => <RiskBadge risk={row.original.risk} />,
    sortingFn: (a, b) => RISK_ORDER[a.original.risk] - RISK_ORDER[b.original.risk],
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'confidence',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Agent confidence" />,
    cell: ({ row }) => <ConfidenceBar value={row.original.confidence} />,
  },
  {
    accessorKey: 'amount',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Amount" />,
    cell: ({ row }) => (
      <span className="tabular-nums">{row.original.amount !== undefined ? money(row.original.amount, row.original.currency) : '—'}</span>
    ),
    sortUndefined: 'last',
  },
  {
    accessorKey: 'slaMinutes',
    header: ({ column }) => <DataTableColumnHeader column={column} title="SLA" />,
    cell: ({ row }) => <SlaText minutes={row.original.slaMinutes} open={isOpen(row.original)} />,
  },
  {
    accessorKey: 'assignee',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Assignee" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.assignee ?? 'Unassigned'}</span>,
  },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <ReviewStatusBadge status={row.original.status} />,
  },
];
