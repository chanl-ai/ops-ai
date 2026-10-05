'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Copy, Database, Globe, KeyRound, Play, Plus, RefreshCw, Server, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { CreateKbDialog } from '@/components/knowledge/create-kb-dialog';
import { HEALTH_LABEL, KbDot, KbHealthBadge } from '@/components/knowledge/knowledge-meta';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useBulkDeleteKbs, useBulkRefreshKbs, useCreateKb, useDeleteKb, useDuplicateKb, useKnowledgeBases, useRefreshKb, useSourcesList } from '@/hooks/knowledge-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { KbFilters, KbHealth, KnowledgeBaseRow } from '@/lib/types/knowledge';

type Row = KnowledgeBaseRow & { onRowClick: (k: KnowledgeBaseRow) => void };
const ALL = { page: 1, pageSize: 100 };
const ACCESS = [
  { value: 'members', label: 'All members', icon: Users },
  { value: 'selected', label: 'Selected members', icon: Users },
  { value: 'api', label: 'API keys', icon: KeyRound },
  { value: 'mcp', label: 'MCP', icon: Server },
  { value: 'public', label: 'Public link', icon: Globe },
] as const;

function columns(actions: { open: (k: KnowledgeBaseRow, tab?: string) => void; refresh: (k: KnowledgeBaseRow) => void; duplicate: (k: KnowledgeBaseRow) => void; remove: (k: KnowledgeBaseRow) => void }): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((k) => k.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Knowledge base" />,
      cell: ({ row }) => (
        <div className="flex min-w-56 items-center gap-2">
          <KbDot color={row.original.color} />
          <div className="min-w-0">
            <Link href={`/knowledge/${row.original.id}`} className="block truncate font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
              {row.original.name}
            </Link>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{row.original.slug}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    {
      accessorKey: 'health',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Health" />,
      cell: ({ row }) => (
        <div className="flex flex-col gap-1">
          <KbHealthBadge health={row.original.health} />
          {row.original.indexing && (
            <div className="flex items-center gap-2">
              <Progress value={(row.original.indexing.done / row.original.indexing.total) * 100} className="h-1 w-20" />
              <span className="text-[11px] whitespace-nowrap tabular-nums text-muted-foreground">
                {count(row.original.indexing.done)} of {count(row.original.indexing.total)}
              </span>
            </div>
          )}
        </div>
      ),
      filterFn: facetFilterFn,
    },
    {
      id: 'sources',
      accessorFn: (r) => r.sources.length,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Sources" />,
      cell: ({ row }) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-default tabular-nums underline decoration-dotted underline-offset-4">{row.original.sources.length}</span>
          </TooltipTrigger>
          <TooltipContent>
            {row.original.sourceNames.map((n) => (
              <div key={n} className="text-xs">
                {n}
              </div>
            ))}
          </TooltipContent>
        </Tooltip>
      ),
    },
    { id: 'documents', accessorFn: (r) => r.stats.documents, header: ({ column }) => <DataTableColumnHeader column={column} title="Documents" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.stats.documents)}</span> },
    { id: 'chunks', accessorFn: (r) => r.stats.chunks, header: ({ column }) => <DataTableColumnHeader column={column} title="Chunks" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.stats.chunks)}</span> },
    {
      id: 'agents',
      accessorFn: (r) => r.agentNames.length,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Cited by" />,
      cell: ({ row }) =>
        row.original.agentNames.length ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-default whitespace-nowrap underline decoration-dotted underline-offset-4">{plural(row.original.agentNames.length, 'agent')}</span>
            </TooltipTrigger>
            <TooltipContent>
              {row.original.agentNames.map((n) => (
                <div key={n} className="text-xs">
                  {n}
                </div>
              ))}
            </TooltipContent>
          </Tooltip>
        ) : (
          <span className="text-muted-foreground">None</span>
        ),
    },
    { id: 'refreshed', accessorFn: (r) => r.lastRefreshedAt ?? '', header: ({ column }) => <DataTableColumnHeader column={column} title="Last refreshed" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.lastRefreshedAt)}</span> },
    { id: 'queries', accessorFn: (r) => r.stats.queries7d, header: ({ column }) => <DataTableColumnHeader column={column} title="Queries · 7d" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.stats.queries7d)}</span> },
    {
      id: 'access',
      accessorFn: (r) => r.access.members.mode,
      header: () => <span className="text-xs">Access</span>,
      cell: ({ row }) => {
        const a = row.original.access;
        const on = { members: a.members.mode === 'all', selected: a.members.mode === 'selected', api: a.anyApiKey, mcp: a.mcp.enabled, public: a.publicLink.enabled };
        return (
          <div className="flex items-center gap-1.5">
            {ACCESS.filter((x) => on[x.value]).map((x) => (
              <Tooltip key={x.value}>
                <TooltipTrigger asChild>
                  <x.icon className="size-3.5 text-muted-foreground" aria-label={x.label} />
                </TooltipTrigger>
                <TooltipContent>{x.value === 'mcp' ? `MCP tool ${a.mcp.toolName}` : x.value === 'selected' ? plural(a.members.principals.length, 'member or group', 'members or groups') : x.label}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        );
      },
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
              { label: 'Open playground', icon: Play, onClick: (r) => actions.open(r.original, 'playground') },
              { label: 'Refresh index', icon: RefreshCw, onClick: (r) => actions.refresh(r.original) },
              { label: 'Duplicate', icon: Copy, onClick: (r) => actions.duplicate(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => actions.remove(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function KnowledgeBasesPage() {
  const router = useRouter();
  const list = useListParams<KbFilters>('name');
  const query = useKnowledgeBases(list.params);
  const sources = useSourcesList(ALL);
  const allKbs = useKnowledgeBases(ALL);
  const create = useCreateKb();
  const refresh = useRefreshKb();
  const duplicate = useDuplicateKb();
  const remove = useDeleteKb();
  const bulkRefresh = useBulkRefreshKbs();
  const bulkDelete = useBulkDeleteKbs();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<KnowledgeBaseRow | null>(null);
  const deletingShown = useSticky(deleting);
  const [bulk, setBulk] = React.useState<{ kind: 'refresh' | 'delete'; rows: KnowledgeBaseRow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((k) => k.name);
  const nameOf = (id: string) => shown?.rows.find((k) => k.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const open = React.useCallback((k: KnowledgeBaseRow, tab?: string) => router.push(`/knowledge/${k.id}${tab ? `?tab=${tab}` : ''}`), [router]);
  const cols = React.useMemo(
    () =>
      columns({
        open,
        refresh: (k) => refresh.mutate(k.id, { onSuccess: () => toast.success(`Refreshing ${k.name}`), onError: (e) => toast.error(`Couldn’t refresh ${k.name}`, { description: e.message }) }),
        duplicate: (k) =>
          duplicate.mutate(k.id, {
            onSuccess: (c) => toast.success(`Duplicated as ${c.name}`, { description: 'Settings and source links are copied. Build its index from the Overview tab.' }),
            onError: (e) => toast.error(`Couldn’t duplicate ${k.name}`, { description: e.message }),
          }),
        remove: setDeleting,
      }),
    [open, refresh, duplicate],
  );
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((k) => ({ ...k, onRowClick: (x: KnowledgeBaseRow) => open(x) })), [query.data, open]);
  const facets = query.data?.facets ?? {};

  return (
    <PageLayout
      icon={Database}
      title="Knowledge bases"
      description="Indexes agents search and cite"
      actions={
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> New knowledge base
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError && !query.data ? (
        <QueryError what="knowledge bases" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search knowledge bases…"
          initialColumnVisibility={{ chunks: false }}
          filters={[
            { column: 'health', title: 'Health', options: (Object.keys(HEALTH_LABEL) as KbHealth[]).map((h) => ({ label: HEALTH_LABEL[h], value: h, count: facets.health?.[h] ?? 0 })) },
            { column: 'access', title: 'Access', options: ACCESS.map((a) => ({ label: a.label, value: a.value, count: facets.access?.[a.value] ?? 0 })) },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            { label: 'Refresh', icon: RefreshCw, variant: 'outline', onClick: (r) => setBulk({ kind: 'refresh', rows: r }) },
            { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => setBulk({ kind: 'delete', rows: r }) },
          ]}
          renderGridItem={(k) => (
            <div className="flex h-full flex-col gap-2 rounded-lg border bg-card p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 text-sm font-semibold">
                  <KbDot color={k.color} />
                  <span className="truncate">{k.name}</span>
                </span>
                <KbHealthBadge health={k.health} />
              </div>
              <p className="line-clamp-2 text-xs text-muted-foreground">{k.description}</p>
              <dl className="mt-auto grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-muted-foreground">Documents</dt>
                  <dd className="tabular-nums">{count(k.stats.documents)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Queries 7d</dt>
                  <dd className="tabular-nums">{count(k.stats.queries7d)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Refreshed</dt>
                  <dd>{relativeTime(k.lastRefreshedAt)}</dd>
                </div>
              </dl>
            </div>
          )}
          gridClassName="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
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
              icon={Database}
              noun="knowledge bases"
              filtered={list.isFiltered}
              description="A knowledge base indexes one or more sources so agents can search and cite them."
              createLabel="New knowledge base"
              onCreate={() => setCreateOpen(true)}
            />
          }
        />
      )}

      <CreateKbDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        sources={sources.data?.data ?? []}
        existingNames={(allKbs.data?.data ?? []).map((k) => k.name)}
        isPending={create.isPending}
        onSubmit={async (input) => {
          const kb = await create.mutateAsync(input);
          toast.success(`Created ${kb.name}`, { description: 'The first index build has started.' });
          router.push(`/knowledge/${kb.id}`);
        }}
      />

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="knowledge base"
        entityName={deletingShown?.name}
        description={
          deletingShown?.agentNames.length
            ? `${deletingShown.agentNames.join(', ')} cite this knowledge base and lose access to it. Sources and their items are kept.`
            : 'The index and its retrieval settings are removed. Sources and their items are kept.'
        }
        requireNameConfirmation={!!deletingShown?.agentNames.length}
        isLoading={remove.isPending}
        onConfirm={async () => {
          const k = deleting!;
          try {
            await remove.mutateAsync(k.id);
            toast.success(`Deleted ${k.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${k.name}`, { description: (e as Error).message });
          }
        }}
      />

      <BulkConfirmDialog
        open={bulk?.kind === 'refresh'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Refresh ${plural(names.length, 'knowledge base')}`}
        description="Each index rebuilds from its sources' current items. Ones already refreshing are skipped."
        names={names}
        confirmLabel="Refresh"
        isPending={bulkRefresh.isPending}
        onConfirm={async () => {
          const res = await bulkRefresh.mutateAsync(bulk!.rows.map((k) => k.id));
          toastBulk(res, 'Refreshing', 'knowledge base', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="knowledge base"
        count={names.length}
        description="Indexes and retrieval settings are removed; sources are kept. Knowledge bases an agent cites are skipped."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((k) => k.id));
          toastBulk(res, 'Deleted', 'knowledge base', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>
    </PageLayout>
  );
}
