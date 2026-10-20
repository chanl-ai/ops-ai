'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import type { EngineRunStep } from '@/lib/types/engine';

import { RunStatus } from './run-status';

type Row = EngineRunStep & { key: string; name: string; onRowClick: (r: Row) => void };

const started = (s: EngineRunStep) => s.attempts[0]?.startedAt ?? null;
const ended = (s: EngineRunStep) => s.attempts[s.attempts.length - 1]?.finishedAt ?? null;
const time = (iso: string) => new Date(iso).toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/** From the first attempt's start to the last one's end; Running while it has none. */
function took(s: EngineRunStep): string {
  const a = started(s);
  const b = ended(s);
  if (!a) return '—';
  if (!b) return 'Running';
  const ms = new Date(b).getTime() - new Date(a).getTime();
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

/** A run's steps in the order they started; a row opens the step. */
export function StepsTable({ steps, nodeName, onOpen }: { steps: EngineRunStep[]; nodeName: (id: string) => string; onOpen: (index: number) => void }) {
  const rows: Row[] = React.useMemo(() => steps.map((s, i) => ({ ...s, key: `${s.nodeId}-${s.iteration}`, name: nodeName(s.nodeId), onRowClick: () => onOpen(i) })), [steps, nodeName, onOpen]);
  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Step" />, cell: ({ row }) => <span data-testid="run-step" data-node-id={row.original.nodeId}>{row.original.name}</span> },
      { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <RunStatus status={row.original.status} /> },
      { id: 'started', header: 'Started', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground tabular-nums">{started(row.original) ? time(started(row.original)!) : '—'}</span> },
      { id: 'took', header: 'Took', cell: ({ row }) => <span className="whitespace-nowrap tabular-nums" data-testid="run-step-took">{took(row.original)}</span> },
      { id: 'attempts', header: 'Attempts', cell: ({ row }) => <span className="tabular-nums">{row.original.attempts.length}</span> },
      { accessorKey: 'port', header: 'Port', cell: ({ row }) => <span className="font-mono text-xs">{row.original.port ?? '—'}</span> },
      { accessorKey: 'iteration', header: 'Iteration', cell: ({ row }) => <span className="tabular-nums">{row.original.iteration}</span> },
    ],
    [],
  );
  return <DataTableWithViews columns={columns} data={rows} getRowId={(r) => r.key} hideViewSwitcher />;
}
