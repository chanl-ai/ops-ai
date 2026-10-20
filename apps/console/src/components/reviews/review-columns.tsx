'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { PanelRight } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StopRowClick } from '@/components/shared/form-field';
import { ConfidenceBar, KIND_LABEL, ReviewStatusBadge, RiskBadge, SlaText } from '@/components/status-badges';
import { selectColumn } from '@/components/shared/select-column';
import { idColumn } from '@/components/shared/id-column';
import { taskView } from '@/components/tasks/task-regions';
import { facetFilterFn } from '@/hooks/use-list-params';
import { money } from '@/lib/format';
import type { Review, Risk } from '@/lib/types/domain';

export type ReviewRow = Review & { onRowClick: (r: Review) => void; onPeek?: (r: Review) => void; rowTestId: string };

const RISK_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, low: 3 };
export const isOpen = (r: Pick<Review, 'status'>) => r.status === 'pending' || r.status === 'in_review';

export const reviewColumns: ColumnDef<ReviewRow>[] = [
  selectColumn<ReviewRow>((r) => r.id, (r) => isOpen(r)),
  idColumn<ReviewRow>((r) => r.id),
  {
    id: 'title',
    accessorFn: (r) => `${questionOf(r)} ${r.customer} ${r.id}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Request" />,
    cell: ({ row }) => (
      <div className="min-w-60">
        <div className="flex items-center gap-2 font-medium">
          {questionOf(row.original)}
          {row.original.origin?.kind === 'chat' && (
            <Badge variant="outline" className="font-normal" data-testid="review-from-chat">
              From chat
            </Badge>
          )}
        </div>
        {/* The step and who it is about; the id has its own column. */}
        <div className="text-xs text-muted-foreground">{[row.original.stepName, row.original.customer].filter(Boolean).join(' · ')}</div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'slaMinutes',
    header: ({ column }) => <DataTableColumnHeader column={column} title="SLA" />,
    cell: ({ row }) => <SlaText minutes={row.original.slaMinutes} open={isOpen(row.original)} />,
  },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <ReviewStatusBadge status={row.original.status} />,
  },
  {
    accessorKey: 'risk',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Risk" />,
    cell: ({ row }) => <RiskBadge risk={row.original.risk} />,
    sortingFn: (a, b) => RISK_ORDER[a.original.risk] - RISK_ORDER[b.original.risk],
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'workflowId',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => {
      const o = row.original.origin;
      return <span className="text-muted-foreground">{o?.kind === 'chat' ? `Chat with ${o.agentName}` : row.original.workflowName}</span>;
    },
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'assignee',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Assignee" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.assignee ?? 'Unassigned'}</span>,
  },
  {
    accessorKey: 'kind',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />,
    cell: ({ row }) => <span className="text-muted-foreground">{KIND_LABEL[row.original.kind]}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
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
      <span className="tabular-nums">{row.original.amount != null ? money(row.original.amount, row.original.currency) : '—'}</span>
    ),
    sortUndefined: 'last',
  },
  {
    // The row opens the task's page; this peeks at it in the queue's side view instead.
    id: 'peek',
    meta: { className: 'w-10' },
    cell: ({ row }) =>
      row.original.onPeek && (
        <StopRowClick>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Quick view" title="Quick view" onClick={() => row.original.onPeek?.(row.original)} data-testid={`review-peek-${row.original.id}`}>
            <PanelRight />
          </Button>
        </StopRowClick>
      ),
    enableHiding: false,
  },
];

/** A row's question: the same words the task page heads with, from the one function that words a task. */
export const questionOf = (r: Review): string => taskView(r).question;
