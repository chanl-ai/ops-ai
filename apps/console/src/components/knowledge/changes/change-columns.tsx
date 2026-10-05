'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { facetFilterFn } from '@/hooks/use-list-params';
import { plural, relativeTime } from '@/lib/format';
import type { KnowledgeChange } from '@/lib/types/knowledge-changes';

import { ConflictChip, OriginChip, TrustChip } from './change-chips';

export type ChangeRow = KnowledgeChange & { onRowClick: (c: KnowledgeChange) => void; rowTestId: string };

export const changeColumns: ColumnDef<ChangeRow>[] = [
  {
    id: 'summary',
    accessorFn: (c) => `${c.summary} ${c.documentTitle} ${c.id}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Change" />,
    cell: ({ row }) => (
      <div className="max-w-xs min-w-56">
        <div className="truncate font-medium" title={row.original.summary}>
          {row.original.summary}
        </div>
        <div className="truncate text-xs text-muted-foreground" title={`${row.original.documentTitle} · ${row.original.fromVersion} → ${row.original.toVersion}`}>
          <span className="font-mono">{row.original.id}</span> · {row.original.documentTitle} · {row.original.fromVersion} → {row.original.toVersion}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'origin',
    header: ({ column }) => <DataTableColumnHeader column={column} title="From" />,
    cell: ({ row }) => (
      <div className="flex flex-col items-start gap-1">
        <OriginChip origin={row.original.origin} />
        <span className="max-w-36 truncate text-xs text-muted-foreground" title={row.original.proposedBy}>
          {row.original.proposedBy}
        </span>
      </div>
    ),
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    id: 'kbId',
    accessorFn: (c) => c.kbs.map((k) => k.name).join(', '),
    header: ({ column }) => <DataTableColumnHeader column={column} title="Knowledge bases" />,
    cell: ({ row }) => {
      const names = row.original.kbs.map((k) => k.name).join(', ');
      return (
        <span className="block max-w-36 truncate text-muted-foreground" title={names}>
          {names}
        </span>
      );
    },
    // Multi-valued: a row matches when any of its knowledge bases is selected.
    filterFn: (row, _id, value: string[]) => !value?.length || row.original.kbs.some((k) => value.includes(k.id)),
    enableSorting: false,
  },
  {
    id: 'trust',
    header: 'State',
    cell: ({ row }) => (
      <div className="flex flex-col items-start gap-1">
        <TrustChip state={row.original.trust} />
        {row.original.conflict && <ConflictChip resolved={!!row.original.conflict.resolution} />}
      </div>
    ),
  },
  {
    id: 'citedBy',
    header: 'Cited by',
    cell: ({ row }) => {
      const c = row.original.citedBy;
      return (
        <span className="text-xs whitespace-nowrap text-muted-foreground">
          {plural(c.length, 'workflow')} · {plural(c.reduce((n, x) => n + x.tests, 0), 'test')}
        </span>
      );
    },
  },
  {
    accessorKey: 'owner',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />,
    cell: ({ row }) => (
      <span className="block max-w-32 truncate text-muted-foreground" title={row.original.owner}>
        {row.original.owner}
      </span>
    ),
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'createdAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Proposed" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground tabular-nums">{relativeTime(row.original.decidedAt ?? row.original.createdAt)}</span>,
  },
];
