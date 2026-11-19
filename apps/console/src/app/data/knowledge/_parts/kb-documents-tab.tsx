'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ExternalLink, FileText, RefreshCw, Settings2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DOC_TYPE_LABEL, FreshnessBadge, ITEM_STATUS_LABEL, ItemStatusBadge, MimeIcon, SensitivityBadge } from '@/components/knowledge/knowledge-meta';
import { useAddDataSource } from '@/components/knowledge/add-data-source';
import { DropZone, uploadRule } from '@/components/shared/file-upload';
import { StopRowClick } from '@/components/shared/form-field';
import { PageDropTarget } from '@/components/shared/page-drop-target';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useKbDocuments, useSyncSource } from '@/hooks/knowledge-queries';
import { useUploadLimits } from '@/hooks/file-queries';
import { useCreatedRows } from '@/hooks/use-created-rows';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, relativeTime } from '@/lib/format';
import type { DocType, DocumentFilters, DocumentRow, ItemStatus, KnowledgeBaseDetail } from '@/lib/types/knowledge';

import { DocumentPanel } from '@/components/knowledge/document-panel';
import { serverPagination } from '@/components/shared/server-pagination';

type Row = DocumentRow & { onRowClick: (d: DocumentRow) => void };

/** Where a document came from, under its title: a web page's address, who typed a page, else its source. */
function origin(d: DocumentRow) {
  if (d.docType === 'web' && d.url) return d.url.replace(/^https?:\/\//, '');
  if (d.docType === 'typed') return `Typed by ${d.owner}`;
  return d.sourceName;
}

/**
 * The base's one data sources table: every document with its type, source, status, pieces, freshness, collection and
 * last refresh, filtered by kb-service. Builders add data from the Add data source menu or by dropping files or folders
 * anywhere on the tab. `?status=` and `?freshness=` preset the filters; `?doc=` opens one.
 */
export function KbDocumentsTab({ kb, canBuild }: { kb: KnowledgeBaseDetail; canBuild: boolean }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const created = useCreatedRows<Row>();
  const sync = useSyncSource();
  const limits = useUploadLimits();
  const limit = limits.data?.perPurpose.find((l) => l.purpose === 'knowledge_source');
  const add = useAddDataSource(kb, { pageAdded: (d) => created.show({ ...d, onRowClick: (x: DocumentRow) => setDoc(x.id) }) });
  const initialFilters = React.useMemo(
    () => (['status', 'freshness'] as const).flatMap((k) => (params.get(k) ? [{ id: k, value: [params.get(k)!] }] : [])),
    // Only the URL at mount presets filters; later changes come from the toolbar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const list = useListParams<DocumentFilters>('title', 20);
  const query = useKbDocuments(kb.id, list.params, !!kb.indexing);
  const docId = params.get('doc');
  const setDoc = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set('doc', id);
    else next.delete('doc');
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const docs = query.data?.data ?? [];
  const rows: Row[] = React.useMemo(() => docs.map((d) => ({ ...d, onRowClick: (x: DocumentRow) => setDoc(x.id) })), [docs]); // eslint-disable-line react-hooks/exhaustive-deps
  const idx = docs.findIndex((d) => d.id === docId);
  const facets = query.data?.facets ?? {};

  const refresh = React.useCallback(
    (d: DocumentRow) =>
      // A document is refreshed by syncing the source it came from; kb-service has no per-document refresh.
      sync.mutate({ id: d.sourceId }, { onSuccess: () => toast.success(`Refreshing ${d.sourceName}`, { description: `${d.title} is read again with the rest of its source.` }), onError: (e) => toast.error(`Couldn’t refresh ${d.title}`, { description: e.message }) }),
    [sync],
  );

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: 'title',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Title" />,
        cell: ({ row }) => (
          <div className="flex min-w-56 max-w-80 items-center gap-2">
            <MimeIcon mime={row.original.mimeType} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.title}</div>
              <div className="truncate text-xs text-muted-foreground">{origin(row.original)}</div>
            </div>
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'docType', header: 'Type', cell: ({ row }) => <span className="whitespace-nowrap">{DOC_TYPE_LABEL[row.original.docType] ?? row.original.docType}</span>, filterFn: facetFilterFn },
      { accessorKey: 'sourceId', header: 'Source', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.sourceName}</span>, filterFn: facetFilterFn },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) =>
          row.original.status === 'failed' ? (
            // The reason shows in the row, so a document that never indexed says why without a hover.
            <div className="flex max-w-64 flex-col items-start gap-0.5" data-testid={`doc-failed-${row.original.id}`}>
              <ItemStatusBadge status="failed" />
              {row.original.error && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-xs text-destructive-text break-words whitespace-normal">{row.original.error}</span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">{row.original.error}</TooltipContent>
                </Tooltip>
              )}
            </div>
          ) : row.original.warning ? (
            // Indexed, but some pages could not be read; they say so in the row as a failure's reason does.
            <div className="flex max-w-64 flex-col items-start gap-0.5" data-testid={`doc-warning-${row.original.id}`}>
              <ItemStatusBadge status={row.original.status} />
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="text-xs text-warning-text break-words whitespace-normal">{row.original.warning}</span>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{row.original.warning}</TooltipContent>
              </Tooltip>
            </div>
          ) : (
            <ItemStatusBadge status={row.original.status} />
          ),
        filterFn: facetFilterFn,
      },
      { accessorKey: 'chunkCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Chunks" />, cell: ({ row }) => (row.original.status === 'held' ? <span className="text-muted-foreground">Not indexed</span> : <span className="tabular-nums">{count(row.original.chunkCount)}</span>) },
      { accessorKey: 'freshness', header: 'Freshness', cell: ({ row }) => <FreshnessBadge reviewBy={row.original.reviewBy} freshness={row.original.freshness} />, filterFn: facetFilterFn },
      {
        accessorKey: 'collection',
        header: 'Collection',
        cell: ({ row }) => (
          <Badge variant="secondary" className="font-normal whitespace-nowrap">
            {row.original.collection || 'All'}
          </Badge>
        ),
        filterFn: facetFilterFn,
      },
      { id: 'refreshed', accessorFn: (r) => r.processedAt ?? r.modifiedAt, header: ({ column }) => <DataTableColumnHeader column={column} title="Last refreshed" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.processedAt ?? row.original.modifiedAt)}</span> },
      { accessorKey: 'sensitivity', header: 'Sensitivity', cell: ({ row }) => <SensitivityBadge level={row.original.sensitivity} />, filterFn: facetFilterFn },
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
      {
        id: 'actions',
        meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
        cell: ({ row }) => (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Open', icon: ExternalLink, onClick: (r) => r.original.onRowClick(r.original) },
                ...(canBuild
                  ? [
                      { label: 'Refresh', icon: RefreshCw, onClick: (r: { original: Row }) => refresh(r.original) },
                      { label: 'Settings', icon: Settings2, onClick: (r: { original: Row }) => router.push(`/data/sources/${r.original.sourceId}?tab=settings`) },
                    ]
                  : []),
              ]}
            />
          </StopRowClick>
        ),
        enableHiding: false,
      },
    ],
    [canBuild, refresh, router],
  );

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="documents" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />;

  const rule = limits.isPending ? 'Loading limits…' : uploadRule(limit);
  const facet = (key: keyof DocumentFilters, value: string) => facets[key]?.[value] ?? 0;
  const types = Object.keys(facets.docType ?? {}).sort() as DocType[];

  return (
    <PageDropTarget onFiles={add.addFiles} label={`Drop to add to ${kb.name}`} disabled={!canBuild} className="flex flex-col gap-3">
      {canBuild && <DropZone title="Drop files or a folder here to add them" rule={rule} scanning={limits.data?.scanning} onChoose={() => add.show('files')} onFiles={add.addFiles} testId="kb-documents-drop" />}
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        created={created}
        searchColumn="title"
        searchPlaceholder="Search documents…"
        hideViewSwitcher
        rowNoun="document"
        toolbarExtra={canBuild && add.menu}
        initialColumnFilters={initialFilters}
        initialColumnVisibility={{ docType: true, sourceId: true, status: true, chunkCount: true, freshness: true, collection: true, refreshed: true, sensitivity: false, tags: false }}
        filters={[
          { column: 'docType', title: 'Type', options: types.map((t) => ({ label: DOC_TYPE_LABEL[t] ?? t, value: t, count: facet('docType', t) })) },
          { column: 'status', title: 'Status', options: (['indexed', 'pending', 'processing', 'failed', 'partial'] as ItemStatus[]).map((s) => ({ label: ITEM_STATUS_LABEL[s], value: s, count: facet('status', s) })) },
          { column: 'sourceId', title: 'Source', options: kb.attached.map((a) => ({ label: a.source.name, value: a.sourceId, count: facet('sourceId', a.sourceId) })) },
          { column: 'collection', title: 'Collection', options: Object.keys(facets.collection ?? {}).sort().map((c) => ({ label: c, value: c, count: facet('collection', c) })) },
          { column: 'freshness', title: 'Freshness', options: [{ label: 'Fresh', value: 'fresh', count: facet('freshness', 'fresh') }, { label: 'Stale', value: 'stale', count: facet('freshness', 'stale') }, { label: 'No schedule', value: 'no_schedule', count: facet('freshness', 'no_schedule') }] },
        ]}
        onColumnFiltersChange={list.onColumnFiltersChange}
        serverPagination={serverPagination(list, query)}
        emptyState={
          <ListEmpty
            icon={FileText}
            noun="documents"
            filtered={list.isFiltered}
            description={canBuild ? 'Drop files or a folder above, or choose Add data source to add a website, an app or typed text.' : 'A document is one item a source produced: a file, a page or a set of rows.'}
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
      {add.dialogs}
    </PageDropTarget>
  );
}
