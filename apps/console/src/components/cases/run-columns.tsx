'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Mail } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { selectColumn } from '@/components/shared/select-column';
import { idColumn } from '@/components/shared/id-column';
import { SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { facetFilterFn } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { RunRow, RunState } from '@/lib/types/cases';
import { cn } from '@/lib/utils';

export type RunTableRow = RunRow & { onRowClick: (r: RunRow) => void; rowTestId: string };

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

const STATE: Record<RunState, { label: string; cls: string }> = {
  waiting: { label: 'Waiting on a person', cls: 'border-warning/40 bg-warning/10 text-warning-text' },
  running: { label: 'Running', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  done: { label: 'Done', cls: 'border-success/40 bg-success/10 text-success-text' },
  failed: { label: 'Failed', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
};

export const RUN_STATE_OPTIONS = (Object.keys(STATE) as RunState[]).map((value) => ({ value, label: STATE[value].label }));

export function RunStateBadge({ state }: { state: RunState }) {
  return <span className={cn(pill, STATE[state].cls)}>{STATE[state].label}</span>;
}

const isOpen = (r: Pick<RunRow, 'state'>) => r.state === 'running' || r.state === 'waiting';

/** "2 approved · 1 pending", or a dash when the agent took no actions. */
export function ActionCounts({ approved, pending }: { approved: number; pending: number }) {
  if (!approved && !pending) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="text-xs whitespace-nowrap tabular-nums">
      {approved} approved
      {pending > 0 && <span className="font-medium text-warning-text"> · {pending} pending</span>}
    </span>
  );
}

export const runColumns: ColumnDef<RunTableRow>[] = [
  selectColumn<RunTableRow>((r) => r.id, (r) => !!r.caseId && isOpen(r)),
  idColumn<RunTableRow>((r) => r.id),
  {
    id: 'subject',
    accessorFn: (r) => `${r.subject} ${r.id}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Subject" />,
    cell: ({ row }) => (
      <div className="min-w-52">
        <div className="font-medium">{row.original.subject}</div>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{row.original.id}</span>
          {row.original.trigger && <> · {row.original.trigger}</>}
          {row.original.caseId && (
            <>
              {' · '}
              <Mail className="inline size-3 align-[-2px]" /> <span className="font-mono">{row.original.caseId}</span>
            </>
          )}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'workflowId',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
    cell: ({ row }) => <span className="whitespace-nowrap">{row.original.workflowName}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  { accessorKey: 'state', header: ({ column }) => <DataTableColumnHeader column={column} title="State" />, cell: ({ row }) => <RunStateBadge state={row.original.state} />, filterFn: facetFilterFn, enableSorting: false },
  // The run that opened this one (`?parent=`); hidden, it only carries the filter.
  { id: 'parent', accessorFn: (r) => r.parentThreadId ?? '', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
  {
    accessorKey: 'queue',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Waiting on" />,
    cell: ({ row }) => <span className={cn('whitespace-nowrap', !row.original.waitingOn && 'text-muted-foreground')}>{row.original.waitingOn ?? '—'}</span>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'slaMinutes',
    header: ({ column }) => <DataTableColumnHeader column={column} title="SLA" />,
    cell: ({ row }) => (row.original.slaMinutes == null ? <span className="text-xs text-muted-foreground">—</span> : <SlaText minutes={row.original.slaMinutes} open={isOpen(row.original)} />),
    enableSorting: false,
  },
  {
    id: 'actions',
    header: 'Agent actions',
    cell: ({ row }) => <ActionCounts approved={row.original.actionsApproved} pending={row.original.actionsPending} />,
  },
  { accessorKey: 'startedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Started" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.startedAt)}</span>, enableSorting: false },
];

/** Context above the step trace when a run opens from the Cases page. */
export function RunSummary({ run }: { run: RunRow }) {
  const items: [string, ReactNode][] = [
    ['Workflow', <Link key="w" href={`/workflows/${run.workflowId}?tab=runs`} className="underline-offset-2 hover:underline">{run.workflowName}</Link>],
    ['State', <RunStateBadge key="s" state={run.state} />],
    ['Waiting on', run.waitingOn ?? '—'],
    ['SLA', run.slaMinutes == null ? '—' : <SlaText key="sla" minutes={run.slaMinutes} open={isOpen(run)} />],
    ['Agent actions', <ActionCounts key="a" approved={run.actionsApproved} pending={run.actionsPending} />],
    ['Assignee', run.assignee ?? '—'],
  ];
  return (
    <div className="flex flex-col gap-3" data-testid="run-summary">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-3">
        {items.map(([k, v]) => (
          <div key={k} className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">{k}</dt>
            <dd className="mt-0.5 font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      {run.caseId && (
        <Button asChild size="sm" variant="outline" className="self-start">
          <Link href={`/cases/${run.caseId}`}>
            <Mail className="size-3.5" /> Open the email and drafted actions
          </Link>
        </Button>
      )}
    </div>
  );
}
