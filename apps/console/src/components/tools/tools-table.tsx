'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';

import { Badge } from '@/components/ui/badge';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { StopRowClick } from '@/components/shared/form-field';
import { AccessBadge } from '@/components/status-badges';
import { UsedByCell } from '@/components/tools/used-by';
import { facetFilterFn } from '@/hooks/use-list-params';
import type { ToolKind, ToolRow, ToolStatus } from '@/lib/types/tool-directory';
import { appPageHref } from '@/lib/app-links';

export const TOOL_KIND: Record<ToolKind, string> = { app: 'App tool', custom: 'Custom tool', workflow: 'Workflow', agent: 'Agent' };
export const TOOL_STATUS: Record<ToolStatus, { label: string; className: string }> = {
  ready: { label: 'Ready', className: 'border-success/40 bg-success/10 text-success-text' },
  needs_approval: { label: 'Needs approval', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  app_not_connected: { label: 'App not connected', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  needs_your_sign_in: { label: 'Needs your sign-in', className: 'border-warning/40 bg-warning/10 text-warning-text' },
};

/** What a row of the tools table holds: the Tools page's rows, or an app's catalog read as the same rows. */
export type ToolTableRow = Pick<ToolRow, 'id' | 'name' | 'title' | 'access'> & { usedBy: ToolRow['usedBy'] | null } & Partial<Pick<ToolRow, 'app' | 'kind' | 'status'>>;

/**
 * The one set of tools-table columns: the tool, its access and who uses it, and, where the table lists more than one
 * app's tools, its app, kind and status. The Tools page and an app's catalog both build their table from these.
 */
export function toolColumns<T extends ToolTableRow>({ app = false, kind = false, status = false }: { app?: boolean; kind?: boolean; status?: boolean } = {}): ColumnDef<T>[] {
  const cols: (ColumnDef<T> | false)[] = [
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'name',
      accessorFn: (t) => `${t.title ?? ''} ${t.name} ${t.app?.name ?? ''}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tool" />,
      // About half the table: the name reads in full without pushing the short columns to the edge.
      meta: { kind: 'name', className: 'w-1/2' },
      cell: ({ row }) => (
        <div className="flex max-w-72 min-w-44 flex-col" data-testid={`tool-row-${row.original.name}`}>
          <span className="truncate font-medium">{row.original.title ?? row.original.name}</span>
          {row.original.title && row.original.title !== row.original.name && <code className="truncate font-mono text-xs text-muted-foreground">{row.original.name}</code>}
        </div>
      ),
      enableHiding: false,
    },
    app && {
      id: 'app',
      accessorFn: (t) => t.app?.name ?? '',
      // Filtered by the app's id, as the server filters and its facet counts; the column shows the name.
      filterFn: (row, _id, value: string[]) => !value?.length || value.includes(row.original.app?.id ?? ''),
      header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
      meta: { kind: 'status' },
      cell: ({ row }) =>
        row.original.app ? (
          <StopRowClick align="start">
            <Link href={appPageHref(row.original.app.id)} className="inline-flex min-h-6 items-center text-sm underline-offset-4 hover:underline">
              {row.original.app.name}
            </Link>
          </StopRowClick>
        ) : (
          <span className="text-xs text-muted-foreground">Built in</span>
        ),
    },
    kind && {
      accessorKey: 'kind',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Kind" />,
      meta: { kind: 'status' },
      cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.kind ? TOOL_KIND[row.original.kind] : ''}</span>,
      filterFn: facetFilterFn,
    },
    {
      id: 'access',
      accessorFn: (t) => (t.access === 'write' ? 'Write' : t.access === 'read' ? 'Read' : t.access),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Access" />,
      meta: { kind: 'status' },
      cell: ({ row }) => <AccessBadge access={row.original.access} />,
      filterFn: facetFilterFn,
    },
    status && {
      accessorKey: 'status',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      meta: { kind: 'status' },
      cell: ({ row }) =>
        row.original.status ? (
          <Badge variant="outline" className={TOOL_STATUS[row.original.status].className}>
            {TOOL_STATUS[row.original.status].label}
          </Badge>
        ) : null,
      filterFn: facetFilterFn,
    },
    {
      id: 'usedBy',
      accessorFn: (t) => (t.usedBy ? t.usedBy.agents.length + t.usedBy.workflows.length : 0),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
      meta: { className: 'w-56 min-w-40' },
      cell: ({ row }) =>
        row.original.usedBy ? (
          <StopRowClick align="start">
            <UsedByCell usedBy={row.original.usedBy} testId={`used-by-${row.original.name}`} />
          </StopRowClick>
        ) : (
          <span className="text-xs text-muted-foreground" data-testid={`used-by-${row.original.name}`}>
            Not known right now
          </span>
        ),
    },
  ];
  return cols.filter((c): c is ColumnDef<T> => Boolean(c));
}
