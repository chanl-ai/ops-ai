'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { Badge } from '@/components/ui/badge';
import type { CasePriority, CaseRecord, CaseStatus } from '@/lib/types/case-records';

export const CASE_STATUS: Record<CaseStatus, string> = {
  open: 'Open',
  waiting_on_us: 'Waiting on us',
  waiting_on_customer: 'Waiting on the customer',
  resolved: 'Resolved',
  closed: 'Closed',
};
export const CASE_PRIORITY: Record<CasePriority, string> = { urgent: 'Urgent', high: 'High', normal: 'Normal', low: 'Low' };
export const STATUS_OPTIONS = (Object.keys(CASE_STATUS) as CaseStatus[]).map((v) => ({ value: v, label: CASE_STATUS[v] }));
export const PRIORITY_OPTIONS = (Object.keys(CASE_PRIORITY) as CasePriority[]).map((v) => ({ value: v, label: CASE_PRIORITY[v] }));

/** "3 h 10 min" from seconds, to the minute, in the largest two units. */
export function span(sec: number): string {
  const m = Math.round(Math.abs(sec) / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}

/**
 * One deadline as a person reads it: the time left, how long overdue, paused while the case waits on the customer, or
 * met. `left` is the server's seconds to the deadline (null while paused, once met, or once resolved).
 */
export function Deadline({ left, at, paused, met, testId }: { left: number | null; at: string; paused: boolean; met: boolean; testId?: string }) {
  const due = new Date(at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  if (paused) return <Badge variant="secondary" title={`Due ${due}, paused`} data-testid={testId} data-state="paused">Paused</Badge>;
  if (met || left === null) return <span className="text-xs text-muted-foreground" title={`Due ${due}`} data-testid={testId} data-state="met">Met</span>;
  if (left < 0)
    return (
      <span className="text-xs font-medium whitespace-nowrap text-destructive" title={`Was due ${due}`} data-testid={testId} data-state="overdue">
        Overdue by {span(left)}
      </span>
    );
  return (
    <span className="text-xs whitespace-nowrap tabular-nums" title={`Due ${due}`} data-testid={testId} data-state="due">
      {span(left)} left
    </span>
  );
}

export const caseRecordColumns: ColumnDef<CaseRecord>[] = [
  {
    id: 'subject',
    accessorKey: 'subject',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Case" />,
    cell: ({ row }) => (
      <Link href={`/cases/${row.original.id}`} className="block min-w-52 hover:underline" data-testid="case-row-link">
        <span className="font-medium">{row.original.subject}</span>
        <span className="block font-mono text-xs text-muted-foreground">{row.original.id}</span>
      </Link>
    ),
    enableHiding: false,
  },
  {
    id: 'customer',
    accessorFn: (r) => r.customerName ?? r.customerId ?? '',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Customer" />,
    cell: ({ row }) => <span className="text-sm">{row.original.customerName ?? row.original.customerId ?? '—'}</span>,
  },
  {
    id: 'status',
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <Badge variant={row.original.status === 'closed' || row.original.status === 'resolved' ? 'outline' : 'secondary'}>{CASE_STATUS[row.original.status]}</Badge>,
  },
  {
    id: 'assignee',
    accessorKey: 'assignee',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />,
    cell: ({ row }) => <span className="text-sm">{row.original.assignee ?? <span className="text-muted-foreground">Unassigned</span>}</span>,
  },
  {
    id: 'priority',
    accessorKey: 'priority',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Priority" />,
    cell: ({ row }) => <span className={row.original.priority === 'urgent' ? 'text-sm font-medium text-destructive' : 'text-sm'}>{CASE_PRIORITY[row.original.priority]}</span>,
  },
  {
    id: 'response',
    header: 'First response',
    cell: ({ row }) => (
      <Deadline left={row.original.responseLeftS} at={row.original.responseDueAt} paused={!!row.original.pausedSince} met={!!row.original.respondedAt} testId="case-response" />
    ),
  },
  {
    id: 'resolution',
    header: 'Resolution',
    cell: ({ row }) => (
      <Deadline left={row.original.resolutionLeftS} at={row.original.resolutionDueAt} paused={!!row.original.pausedSince} met={row.original.status === 'resolved' || row.original.status === 'closed'} testId="case-resolution" />
    ),
  },
];
