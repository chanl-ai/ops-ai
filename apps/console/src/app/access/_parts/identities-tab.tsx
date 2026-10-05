'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertTriangle, Bot } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { useIdentities } from '@/hooks/governance-queries';
import { useListParams } from '@/hooks/use-list-params';
import { plural, relativeTime } from '@/lib/format';
import type { WorkflowIdentity } from '@/lib/types/governance';

type Row = WorkflowIdentity & { onRowClick: (r: WorkflowIdentity) => void };

const columns: ColumnDef<Row>[] = [
  {
    // Holds every searched field so the table's own filter keeps the rows the server matched.
    id: 'identity',
    accessorFn: (r) => `${r.workflowName} ${r.principal}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow identity" />,
    cell: ({ row }) => (
      <div className="flex min-w-56 flex-col">
        <span className="font-medium">{row.original.workflowName}</span>
        <span className="font-mono text-[11px] text-muted-foreground">{row.original.principal}</span>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'team', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span> },
  { accessorKey: 'grants', header: ({ column }) => <DataTableColumnHeader column={column} title="Grants" />, cell: ({ row }) => <span className="tabular-nums">{row.original.grants}</span> },
  {
    accessorKey: 'expiringSoon',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Expiring soon" />,
    cell: ({ row }) =>
      row.original.expiringSoon ? (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
          <AlertTriangle className="size-3.5" /> {row.original.expiringSoon}
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      ),
  },
  {
    accessorKey: 'moneyMovement',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Moves money" />,
    cell: ({ row }) => (row.original.moneyMovement ? <Badge variant="outline" className="border-red-200 bg-red-50 font-normal text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">Yes</Badge> : <span className="text-xs text-muted-foreground">No</span>),
  },
  { accessorKey: 'lastUsedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last call" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Never'}</span> },
];

/** Card view for the grid toggle, adapted from the shared component library's agent identity card. */
function IdentityCard(identity: Row) {
  return (
    <button type="button" onClick={() => identity.onRowClick(identity)} className="flex w-full flex-col rounded-xl border bg-card p-5 text-left transition-colors hover:bg-accent/40">
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
          <Bot className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-medium">{identity.workflowName}</h3>
          <p className="truncate font-mono text-xs text-muted-foreground">{identity.principal}</p>
        </div>
        {identity.moneyMovement && <Badge variant="outline" className="shrink-0 text-[10px]">Moves money</Badge>}
      </div>
      <div className="mt-3 flex items-center justify-between border-t pt-3">
        <div>
          <span className="text-[10px] tracking-wider text-muted-foreground uppercase">Grants</span>
          <p className="text-base font-semibold tabular-nums">{identity.grants}</p>
        </div>
        <div className="text-right">
          <span className="text-[10px] tracking-wider text-muted-foreground uppercase">Last call</span>
          <p className="text-sm text-muted-foreground">{identity.lastUsedAt ? relativeTime(identity.lastUsedAt) : 'Never'}</p>
        </div>
      </div>
      {identity.expiringSoon > 0 && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{plural(identity.expiringSoon, 'grant')} expiring soon</p>}
    </button>
  );
}

/** One identity per workflow. Opening one shows its grants. Identities are created with the workflow, never by hand. */
export function IdentitiesTab({ onOpen }: { onOpen: (workflowId: string) => void }) {
  const list = useListParams('identity');
  const query = useIdentities(list.params);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((r) => ({ ...r, onRowClick: (x: WorkflowIdentity) => onOpen(x.workflowId) })), [query.data, onOpen]);

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={6} />;
  if (query.isError && !query.data) return <QueryError what="workflow identities" onRetry={() => query.refetch()} retrying={query.isFetching} />;
  return (
    <DataTableWithViews
      columns={columns}
      data={rows}
      getRowId={(r) => r.id}
      searchColumn="identity"
      searchPlaceholder="Search workflows or principals…"
      renderGridItem={IdentityCard}
      gridClassName="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
      onColumnFiltersChange={list.onColumnFiltersChange}
      serverPagination={{
        enabled: true,
        total: query.data?.pagination.total ?? 0,
        page: list.pagination.page,
        pageSize: list.pagination.pageSize,
        totalPages: query.data?.pagination.totalPages,
        onPaginationChange: list.setPagination,
        isLoading: query.isFetching && query.isPlaceholderData,
      }}
      emptyState={<ListEmpty icon={Bot} noun="workflow identities" filtered={list.isFiltered} description="Each workflow gets an identity when it is created. This team has no workflows yet." />}
    />
  );
}
