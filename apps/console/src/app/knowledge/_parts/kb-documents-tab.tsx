'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { FileText, MinusCircle, RefreshCw, Tag } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { FreshnessBadge, ITEM_STATUS_LABEL, ItemStatusBadge, MimeIcon, SENSITIVITY_LABEL, SensitivityBadge } from '@/components/knowledge/knowledge-meta';
import { BulkConfirmDialog, BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useExcludeItems, useKbDocuments, useKnowledgeLookups, useReprocessItems, useTagItems } from '@/hooks/knowledge-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, shortDate, dateOnly } from '@/lib/format';
import type { DocumentFilters, DocumentRow, ItemStatus, KnowledgeBaseDetail, Sensitivity } from '@/lib/types/knowledge';

import { DocumentPanel } from '@/components/knowledge/document-panel';

type Row = DocumentRow & { onRowClick: (d: DocumentRow) => void };

/** Every document the knowledge base indexes. `?status=` and `?freshness=` preset the filters; `?doc=` opens one. */
export function KbDocumentsTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const initialFilters = React.useMemo(
    () => (['status', 'freshness'] as const).flatMap((k) => (params.get(k) ? [{ id: k, value: [params.get(k)!] }] : [])),
    // Only the URL at mount presets filters; later changes come from the toolbar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const list = useListParams<DocumentFilters>('title', 20);
  const query = useKbDocuments(kb.id, list.params, !!kb.indexing);
  const lookups = useKnowledgeLookups();
  const reprocess = useReprocessItems();
  const exclude = useExcludeItems();
  const tag = useTagItems();
  const docId = params.get('doc');
  const setDoc = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set('doc', id);
    else next.delete('doc');
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const [bulk, setBulk] = React.useState<{ kind: 'reprocess' | 'exclude' | 'tag'; rows: DocumentRow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((d) => d.title);
  const nameOf = (id: string) => shown?.rows.find((d) => d.id === id)?.title ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const docs = query.data?.data ?? [];
  const rows: Row[] = React.useMemo(() => docs.map((d) => ({ ...d, onRowClick: (x: DocumentRow) => setDoc(x.id) })), [docs]); // eslint-disable-line react-hooks/exhaustive-deps
  const idx = docs.findIndex((d) => d.id === docId);
  const facets = query.data?.facets ?? {};

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      selectColumn<Row>((d) => d.title),
      {
        accessorKey: 'title',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Title" />,
        cell: ({ row }) => (
          <div className="flex min-w-56 max-w-80 items-center gap-2">
            <MimeIcon mime={row.original.mimeType} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.title}</div>
              <div className="truncate text-xs text-muted-foreground">
                {row.original.owner} · <span className="font-mono">{row.original.version}</span> · effective {dateOnly(row.original.effectiveDate)}
              </div>
            </div>
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'sourceId', header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.sourceName}</span>, filterFn: facetFilterFn },
      {
        accessorKey: 'status',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
        cell: ({ row }) =>
          row.original.status === 'failed' ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <ItemStatusBadge status="failed" />
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{row.original.error}</TooltipContent>
            </Tooltip>
          ) : (
            <ItemStatusBadge status={row.original.status} />
          ),
        filterFn: facetFilterFn,
      },
      { accessorKey: 'chunkCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Chunks" />, cell: ({ row }) => (row.original.status === 'held' ? <span className="text-muted-foreground">Not indexed</span> : <span className="tabular-nums">{count(row.original.chunkCount)}</span>) },
      { accessorKey: 'modifiedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Modified" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{shortDate(row.original.modifiedAt)}</span> },
      { accessorKey: 'freshness', header: ({ column }) => <DataTableColumnHeader column={column} title="Freshness" />, cell: ({ row }) => <FreshnessBadge reviewBy={row.original.reviewBy} />, filterFn: facetFilterFn },
      { accessorKey: 'sensitivity', header: ({ column }) => <DataTableColumnHeader column={column} title="Sensitivity" />, cell: ({ row }) => <SensitivityBadge level={row.original.sensitivity} />, filterFn: facetFilterFn },
      {
        id: 'tags',
        accessorFn: (r) => r.tags.join(','),
        header: () => <span className="text-xs">Tags</span>,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.tags.slice(0, 3).map((t) => (
              <Badge key={t} variant="secondary" className="font-normal">
                {t}
              </Badge>
            ))}
          </div>
        ),
        filterFn: () => true,
      },
      { accessorKey: 'queries30d', header: ({ column }) => <DataTableColumnHeader column={column} title="Queries · 30d" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.queries30d)}</span> },
    ],
    [],
  );

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="documents" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  return (
    <>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="title"
        searchPlaceholder="Search by title or path…"
        hideViewSwitcher
        initialColumnFilters={initialFilters}
        initialColumnVisibility={{ queries30d: false, sensitivity: false }}
        filters={[
          { column: 'sourceId', title: 'Source', options: kb.attached.map((a) => ({ label: a.source.name, value: a.sourceId, count: facets.sourceId?.[a.sourceId] ?? 0 })) },
          { column: 'status', title: 'Status', options: (['indexed', 'pending', 'processing', 'failed', 'partial'] as ItemStatus[]).map((s) => ({ label: ITEM_STATUS_LABEL[s], value: s, count: facets.status?.[s] ?? 0 })) },
          { column: 'freshness', title: 'Freshness', options: [{ label: 'Fresh', value: 'fresh', count: facets.freshness?.fresh ?? 0 }, { label: 'Stale', value: 'stale', count: facets.freshness?.stale ?? 0 }] },
          { column: 'sensitivity', title: 'Sensitivity', options: (['internal', 'confidential', 'restricted'] as Sensitivity[]).map((s) => ({ label: SENSITIVITY_LABEL[s], value: s, count: facets.sensitivity?.[s] ?? 0 })) },
          { column: 'tags', title: 'Tag', options: Object.keys(facets.tags ?? {}).sort().map((t) => ({ label: t, value: t, count: facets.tags?.[t] ?? 0 })) },
        ]}
        onColumnFiltersChange={list.onColumnFiltersChange}
        selectionResetKey={resetKey}
        bulkActions={[
          { label: 'Reprocess', icon: RefreshCw, variant: 'outline', onClick: (r) => setBulk({ kind: 'reprocess', rows: r }) },
          { label: 'Add tag', icon: Tag, variant: 'outline', onClick: (r) => setBulk({ kind: 'tag', rows: r }) },
          { label: 'Exclude', icon: MinusCircle, variant: 'destructive', onClick: (r) => setBulk({ kind: 'exclude', rows: r }) },
        ]}
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
            icon={FileText}
            noun="documents"
            filtered={list.isFiltered}
            description={kb.health === 'never' ? 'Documents appear here once the first index build finishes. Start it from the Overview tab.' : 'A document is one item a source produced: a file, a page or a set of rows.'}
          />
        }
      />

      <DocumentPanel
        itemId={docId}
        onClose={() => setDoc(null)}
        onOpenItem={setDoc}
        navigation={
          idx >= 0
            ? {
                currentIndex: idx,
                totalCount: docs.length,
                onPrev: idx > 0 ? () => setDoc(docs[idx - 1].id) : undefined,
                onNext: idx < docs.length - 1 ? () => setDoc(docs[idx + 1].id) : undefined,
              }
            : undefined
        }
      />

      <BulkConfirmDialog
        open={bulk?.kind === 'reprocess' || bulk?.kind === 'exclude'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={shown?.kind === 'exclude' ? `Exclude ${names.length} documents` : `Reprocess ${names.length} documents`}
        description={
          shown?.kind === 'exclude'
            ? 'Each document leaves the index and an exclude rule for its path is added to its source, so the next sync does not bring it back.'
            : 'Each document is parsed and chunked again with its source’s current settings.'
        }
        names={names}
        confirmLabel={shown?.kind === 'exclude' ? 'Exclude' : 'Reprocess'}
        isPending={reprocess.isPending || exclude.isPending}
        onConfirm={async () => {
          const ids = bulk!.rows.map((d) => d.id);
          if (bulk!.kind === 'exclude') toastBulk(await exclude.mutateAsync(ids), 'Excluded', 'document', nameOf);
          else toastBulk(await reprocess.mutateAsync(ids), 'Reprocessing', 'document', nameOf);
          finish();
        }}
      />
      <BulkFieldDialog
        open={bulk?.kind === 'tag'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Tag ${names.length} documents`}
        description="Tags narrow retrieval through the knowledge base’s tag filters."
        fieldLabel="Tag"
        options={lookups.data?.tags ?? []}
        names={names}
        confirmLabel="Add tag"
        isPending={tag.isPending}
        onConfirm={async (t) => {
          toastBulk(await tag.mutateAsync({ ids: bulk!.rows.map((d) => d.id), tag: t }), `Tagged ${t} on`, 'document', nameOf);
          finish();
        }}
      />
    </>
  );
}
