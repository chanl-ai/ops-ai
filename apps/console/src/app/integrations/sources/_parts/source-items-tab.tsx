'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { FileSearch } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ERROR_CLASS_LABEL, ITEM_STATUS_LABEL, ItemStatusBadge, itemReason, MimeIcon } from '@/components/knowledge/knowledge-meta';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useSourceItems } from '@/hooks/knowledge-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { bytes, count, mimeLabel, relativeTime, shortDate } from '@/lib/format';
import type { ErrorClass, Item, ItemFilters, ItemStatus, SourceDetail } from '@/lib/types/knowledge';

import { DocumentPanel } from '@/components/knowledge/document-panel';

type Row = Item & { onRowClick: (i: Item) => void };


/** Every item the source fetched. `?status=failed` presets the filter. */
export function SourceItemsTab({ source, onSync }: { source: SourceDetail; onSync: () => void }) {
  const params = useSearchParams();
  const initialFilters = React.useMemo(() => (params.get('status') ? [{ id: 'status', value: [params.get('status')!] }] : []), []); // eslint-disable-line react-hooks/exhaustive-deps
  const list = useListParams<ItemFilters>('title', 30);
  const query = useSourceItems(source.id, list.params, !!source.running);
  const [openId, setOpenId] = React.useState<string | null>(null);

  const items = query.data?.data ?? [];
  const idx = items.findIndex((i) => i.id === openId);
  const rows: Row[] = React.useMemo(() => items.map((i) => ({ ...i, onRowClick: (x: Item) => setOpenId(x.id) })), [items]);
  const facets = query.data?.facets ?? {};

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: 'title',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Title" />,
        cell: ({ row }) => (
          <div className="flex max-w-72 min-w-48 items-center gap-2">
            <MimeIcon mime={row.original.mimeType} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.title}</div>
              <div className="truncate font-mono text-xs text-muted-foreground" title={row.original.url ?? row.original.path}>
                {row.original.url ?? row.original.path}
              </div>
            </div>
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <ItemStatusBadge status={row.original.status} />, filterFn: facetFilterFn },
      { accessorKey: 'chunkCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Chunks" />, cell: ({ row }) => (row.original.status === 'held' ? <span className="text-muted-foreground">Not indexed</span> : <span className="tabular-nums">{count(row.original.chunkCount)}</span>) },
      { accessorKey: 'sizeBytes', header: ({ column }) => <DataTableColumnHeader column={column} title="Size" />, cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{bytes(row.original.sizeBytes)}</span> },
      { accessorKey: 'modifiedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Modified at source" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{shortDate(row.original.modifiedAt)}</span> },
      { id: 'processedAt', accessorFn: (r) => r.processedAt ?? '', header: ({ column }) => <DataTableColumnHeader column={column} title="Last processed" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.processedAt)}</span> },
      { id: 'mime', accessorFn: (r) => r.mimeType, header: () => <span className="text-xs">Type</span>, cell: ({ row }) => <span className="font-mono text-xs">{mimeLabel(row.original.mimeType)}</span>, filterFn: facetFilterFn },
      {
        id: 'reason',
        accessorFn: (r) => itemReason(r) ?? '',
        header: () => <span className="text-xs">Why</span>,
        cell: ({ row }) => {
          const why = itemReason(row.original);
          return why ? (
            <span className="block max-w-64 truncate text-xs text-muted-foreground" title={why}>
              {why}
            </span>
          ) : (
            <span className="text-muted-foreground/60">—</span>
          );
        },
      },
      {
        id: 'errorClass',
        accessorFn: (r) => r.errorClass ?? 'none',
        header: () => <span className="text-xs">Error</span>,
        cell: ({ row }) =>
          row.original.error ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex max-w-48 items-center gap-1.5">
                  {row.original.errorClass && (
                    <Badge variant="outline" className="shrink-0 border-destructive/40 font-normal text-destructive">
                      {ERROR_CLASS_LABEL[row.original.errorClass]}
                    </Badge>
                  )}
                  <span className="truncate text-xs text-muted-foreground">{row.original.error}</span>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-sm">{row.original.error}</TooltipContent>
            </Tooltip>
          ) : (
            <span className="text-muted-foreground/60">—</span>
          ),
        filterFn: facetFilterFn,
      },
    ],
    [],
  );

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="items" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  const mimes = Object.keys(facets.mime ?? {}).sort();
  const classes = Object.keys(facets.errorClass ?? {}).filter((c) => c !== 'none') as ErrorClass[];

  return (
    <>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="title"
        searchPlaceholder="Search title or path…"
        hideViewSwitcher
        initialColumnFilters={initialFilters}
        initialColumnVisibility={{ processedAt: false, sizeBytes: false }}
        filters={[
          { column: 'status', title: 'Status', options: (Object.keys(ITEM_STATUS_LABEL) as ItemStatus[]).map((st) => ({ label: ITEM_STATUS_LABEL[st], value: st, count: facets.status?.[st] ?? 0 })) },
          { column: 'mime', title: 'File type', options: mimes.map((m) => ({ label: mimeLabel(m), value: m, count: facets.mime?.[m] ?? 0 })) },
          { column: 'errorClass', title: 'Error', options: [...classes.map((c) => ({ label: ERROR_CLASS_LABEL[c], value: c, count: facets.errorClass?.[c] ?? 0 })), { label: 'No error', value: 'none', count: facets.errorClass?.none ?? 0 }] },
        ]}
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
        emptyState={
          <ListEmpty
            icon={FileSearch}
            noun="items"
            filtered={list.isFiltered}
            description="Items are the documents, pages or rows this source fetched. None exist until the first sync runs."
            createLabel={source.status === 'revoked' || source.status === 'draft' ? undefined : 'Sync now'}
            onCreate={onSync}
          />
        }
      />

      <DocumentPanel
        itemId={openId}
        onClose={() => setOpenId(null)}
        onOpenItem={setOpenId}
        navigation={
          idx >= 0
            ? { currentIndex: idx, totalCount: items.length, onPrev: idx > 0 ? () => setOpenId(items[idx - 1].id) : undefined, onNext: idx < items.length - 1 ? () => setOpenId(items[idx + 1].id) : undefined }
            : undefined
        }
      />
    </>
  );
}
