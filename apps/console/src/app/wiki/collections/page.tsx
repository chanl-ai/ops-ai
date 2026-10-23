'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { Library } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { GATE_LABEL } from '@/components/wiki/wiki-meta';
import { Badge } from '@/components/ui/badge';
import { useListParams } from '@/hooks/use-list-params';
import { useWikiCollectionsPage } from '@/hooks/wiki-queries';
import { count } from '@/lib/format';
import type { WikiCollection } from '@/lib/types/wiki';

const columns: ColumnDef<WikiCollection>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Collection" />,
    cell: ({ row }) => (
      <div>
        <div className="font-medium">{row.original.name}</div>
        <div className="text-xs text-muted-foreground">{row.original.audience}</div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'pages', header: ({ column }) => <DataTableColumnHeader column={column} title="Pages" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.pages)}</span> },
  {
    accessorKey: 'gate',
    header: 'Gate',
    cell: ({ row }) => (
      <Badge variant="outline" className="font-normal">
        {GATE_LABEL[row.original.gate]}
      </Badge>
    ),
  },
  { id: 'kbs', header: 'Read by knowledge bases', cell: ({ row }) => <span className="text-sm">{row.original.knowledgeBases.length ? row.original.knowledgeBases.join(', ') : <span className="text-muted-foreground">None</span>}</span> },
];

/** Collections decide who may read a group of pages; knowledge bases decide how those pages are searched. */
export default function WikiCollectionsPage() {
  const list = useListParams('name');
  const query = useWikiCollectionsPage(list.params);
  return (
    <PageLayout switcher icon={Library} title="Collections" description="Who may read each group of Wiki pages, and which knowledge bases index it">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="collections" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={query.data?.data ?? []}
          searchColumn="name"
          searchPlaceholder="Search collections…"
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
          hideViewSwitcher
          emptyState={<ListEmpty icon={Library} noun="collections" filtered={list.isFiltered} description="Collections appear when the first pages are synced or written." />}
        />
      )}
    </PageLayout>
  );
}
