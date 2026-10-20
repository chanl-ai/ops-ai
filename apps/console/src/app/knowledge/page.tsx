'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Database, Globe, KeyRound, Play, Plus, RefreshCw, Server, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { CreateKbDialog } from '@/components/knowledge/create-kb-dialog';
import { HEALTH_LABEL, KbDot, KbHealthBadge } from '@/components/knowledge/knowledge-meta';
import { retireBase } from '@/components/knowledge/retire-base';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useSession } from '@/hooks/auth-queries';
import { useCreateKb, useDeleteKb, useKnowledgeBases, useRefreshKb } from '@/hooks/knowledge-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { KbFilters, KbHealth, KnowledgeBaseRow } from '@/lib/types/knowledge';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';

type Row = KnowledgeBaseRow & { onRowClick: (k: KnowledgeBaseRow) => void };
const ALL = { page: 1, pageSize: 100 };
const ACCESS = [
  { value: 'members', label: 'All members', icon: Users },
  { value: 'selected', label: 'Selected members', icon: Users },
  { value: 'api', label: 'API keys', icon: KeyRound },
  { value: 'mcp', label: 'MCP', icon: Server },
  { value: 'public', label: 'Public link', icon: Globe },
] as const;

function columns(actions: { open: (k: KnowledgeBaseRow, tab?: string) => void; refresh: (k: KnowledgeBaseRow) => void; remove: (k: KnowledgeBaseRow) => void; canBuild: boolean }): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((r) => r.name),
    idColumn<Row>((r) => r.id),
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
        row.original.agentsKnown === false ? (
          <span className="text-muted-foreground" title="The agents service did not answer">
            Unknown
          </span>
        ) : row.original.agentsElsewhere && !row.original.agentNames.length ? (
          <span className="whitespace-nowrap text-muted-foreground">{plural(row.original.agentsElsewhere, 'agent')} in other teams</span>
        ) : row.original.agentNames.length ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-default whitespace-nowrap underline decoration-dotted underline-offset-4">
                {plural(row.original.agentNames.length, 'agent')}
                {row.original.agentsElsewhere ? ` +${row.original.agentsElsewhere} in other teams` : ''}
              </span>
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
              ...(actions.canBuild
                ? [
                    { label: 'Refresh index', icon: RefreshCw, onClick: (r: { original: Row }) => actions.refresh(r.original) },
                    { label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: (r: { original: Row }) => actions.remove(r.original) },
                  ]
                : []),
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
  const allKbs = useKnowledgeBases(ALL);
  const create = useCreateKb();
  const { session } = useSession();
  const refresh = useRefreshKb();
  const remove = useDeleteKb();
  const [createOpen, setCreateOpen] = React.useState(false);
  const canBuild = useCanBuild();
  const [deleting, setDeleting] = React.useState<KnowledgeBaseRow | null>(null);
  const deletingShown = useSticky(deleting);

  const open = React.useCallback((k: KnowledgeBaseRow, tab?: string) => router.push(`/knowledge/${k.id}${tab ? `?tab=${tab}` : ''}`), [router]);
  const cols = React.useMemo(
    () =>
      columns({
        open,
        refresh: (k) => refresh.mutate(k.id, { onSuccess: () => toast.success(`Refreshing ${k.name}`), onError: (e) => toast.error(`Couldn’t refresh ${k.name}`, { description: e.message }) }),
        remove: setDeleting,
        canBuild,
      }),
    [open, refresh, canBuild],
  );
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((k) => ({ ...k, onRowClick: (x: KnowledgeBaseRow) => open(x) })), [query.data, open]);
  const facets = query.data?.facets ?? {};

  return (
    <PageLayout
      switcher
      icon={Database}
      title="Knowledge bases"
      description="Indexes agents search and cite"
      actions={
        canBuild && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> New knowledge base
          </Button>
        )
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
                  <dt className="text-muted-foreground">Chunks</dt>
                  <dd className="tabular-nums">{count(k.stats.chunks)}</dd>
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
              createLabel={canBuild ? 'New knowledge base' : undefined}
              onCreate={() => setCreateOpen(true)}
            />
          }
        />
      )}

      <CreateKbDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        existingNames={(allKbs.data?.data ?? []).map((k) => k.name)}
        isPending={create.isPending}
        defaultOwner={session?.user.email ?? ''}
        onSubmit={async (input) => {
          const kb = await create.mutateAsync(input);
          toast.success(`Created ${kb.name}`, { description: 'Attach a source on its Sources tab; the first index build starts then.' });
          router.push(`/knowledge/${kb.id}?tab=sources`);
        }}
      />

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="knowledge base"
        entityName={deletingShown?.name}
        description={deletingShown ? retireBase(deletingShown).description : undefined}
        requireNameConfirmation={!!deletingShown && retireBase(deletingShown).requireName}
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
    </PageLayout>
  );
}
