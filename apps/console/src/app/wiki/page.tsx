'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Bot, BookOpen, GitCompareArrows, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { PROVENANCE_OPTIONS, ProvenanceChip, VerifiedText } from '@/components/wiki/wiki-meta';
import { WikiPageSheet } from '@/components/wiki/wiki-page-sheet';
import { Badge } from '@/components/ui/badge';
import { useVerifyWikiPage, useWikiCollections, useWikiPage, useWikiPages } from '@/hooks/wiki-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, relativeTime } from '@/lib/format';
import type { WikiFilters, WikiPage, WikiView } from '@/lib/types/wiki';

type Row = WikiPage & { onRowClick: (p: WikiPage) => void; rowTestId: string };

const columns: ColumnDef<Row>[] = [
  {
    id: 'title',
    accessorFn: (p) => p.title,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Page" />,
    cell: ({ row }) => (
      <div className="flex max-w-80 flex-col gap-0.5">
        <span className="flex items-center gap-2">
          <span className="truncate font-medium">{row.original.title}</span>
          {row.original.drifted && (
            <Badge variant="outline" className="border-warning/40 font-normal text-warning-text">
              Drifted
            </Badge>
          )}
        </span>
        <span className="truncate text-xs text-muted-foreground">{row.original.origin}</span>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'collection', header: ({ column }) => <DataTableColumnHeader column={column} title="Collection" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.collection}</span>, filterFn: facetFilterFn },
  { accessorKey: 'provenance', header: 'Provenance', cell: ({ row }) => <ProvenanceChip provenance={row.original.provenance} />, filterFn: facetFilterFn },
  { accessorKey: 'version', header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, cell: ({ row }) => <span className="font-mono text-xs">v{row.original.version}</span> },
  { accessorKey: 'verifiedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Verified" />, cell: ({ row }) => <VerifiedText at={row.original.verifiedAt} />, sortUndefined: 'last' },
  { accessorKey: 'owner', header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />, cell: ({ row }) => <span className="text-xs">{row.original.owner}</span> },
  { accessorKey: 'updatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last edit" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{relativeTime(row.original.updatedAt)}</span> },
  { accessorKey: 'citedBy', header: ({ column }) => <DataTableColumnHeader column={column} title="Cited by" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.citedBy)}</span> },
];

/** The Wiki: every page and document agents read, with where it came from, its version and whether a person verified it. */
export default function WikiPage() {
  const [view, setView] = React.useState<WikiView>('all');
  const list = useListParams<WikiFilters>('title');
  const query = useWikiPages({ ...list.params, view });
  const collections = useWikiCollections();
  const [openId, setOpenId] = React.useState<string | null>(null);
  const page = useWikiPage(openId);
  const verify = useVerifyWikiPage();
  const [resetKey, setResetKey] = React.useState(0);

  const data = query.data?.data ?? [];
  const rows: Row[] = React.useMemo(() => data.map((p) => ({ ...p, onRowClick: (x: WikiPage) => setOpenId(x.id), rowTestId: `wiki-row-${p.id}` })), [data]);
  const facets = query.data?.facets ?? {};
  const counts = query.data?.viewCounts;
  const idx = rows.findIndex((r) => r.id === openId);

  return (
    <PageLayout switcher icon={BookOpen} title="Wiki" description="Pages and documents agents read, with where each came from, its version and whether a person verified it">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="the Wiki" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Wiki views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}` },
              { id: 'needs_verification', label: `Needs verification · ${counts?.needs_verification ?? 0}`, icon: ShieldAlert },
              { id: 'remembered', label: `Remembered · ${counts?.remembered ?? 0}`, icon: Bot },
              { id: 'drifted', label: `Drifted · ${counts?.drifted ?? 0}`, icon: GitCompareArrows },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as WikiView);
              list.reset();
              setResetKey((k) => k + 1);
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            key={resetKey}
            columns={columns}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="title"
            searchPlaceholder="Search pages…"
            initialColumnVisibility={{ owner: false }}
            filters={[
              { column: 'collection', title: 'Collection', options: (collections.data ?? []).map((c) => ({ value: c.name, label: c.name, count: facets.collection?.[c.name] ?? 0 })) },
              { column: 'provenance', title: 'Provenance', options: PROVENANCE_OPTIONS.map((o) => ({ ...o, count: facets.provenance?.[o.value] ?? 0 })) },
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
                icon={BookOpen}
                noun={view === 'all' ? 'pages' : 'pages in this view'}
                filtered={list.isFiltered}
                description={view === 'all' ? 'Turn on Sync knowledge for a connection, upload a document, or write a page.' : 'Nothing matches this view right now.'}
              />
            }
          />
        </div>
      )}
      <WikiPageSheet
        open={!!openId}
        onOpenChange={(o) => !o && setOpenId(null)}
        page={page.data}
        loading={page.isPending}
        navigation={idx >= 0 ? { currentIndex: idx, totalCount: rows.length, onPrev: idx > 0 ? () => setOpenId(rows[idx - 1].id) : undefined, onNext: idx < rows.length - 1 ? () => setOpenId(rows[idx + 1].id) : undefined } : undefined}
        verifying={verify.isPending}
        onVerify={() =>
          openId &&
          verify.mutate(openId, {
            onSuccess: (p) => toast.success(`Verified ${p.title}`, { description: `v${p.version} is marked verified by you.` }),
            onError: (e) => toast.error('Couldn’t verify the page', { description: e.message }),
          })
        }
      />
    </PageLayout>
  );
}
