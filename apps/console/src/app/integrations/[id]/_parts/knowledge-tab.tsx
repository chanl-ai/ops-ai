'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Plug, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { scheduleLabel, SOURCE_TYPES, SourceStatusBadge } from '@/components/knowledge/knowledge-meta';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { AddSourceDialog } from '@/components/sources/add-source-dialog';
import { NewSourceDialog } from '@/components/sources/new-source-dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useSetIntegrationSwitches, useIntegrationOptions } from '@/hooks/integration-queries';
import { useListParams } from '@/hooks/use-list-params';
import { useCreateSource, useKnowledgeBases, useKnowledgeLookups, useSourcesList, useSyncSource } from '@/hooks/knowledge-queries';
import { count, relativeTime } from '@/lib/format';
import type { IntegrationDetail } from '@/lib/types/integrations';
import type { SourceRow, SourceType } from '@/lib/types/knowledge';

type Row = SourceRow & { onRowClick: (s: SourceRow) => void };
const ALL = { page: 1, pageSize: 100 };

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
    cell: ({ row }) => (
      <Link href={`/integrations/sources/${row.original.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
        {row.original.name}
      </Link>
    ),
    enableHiding: false,
  },
  { id: 'scope', accessorFn: (s) => s.scopeSummary, header: 'What it indexes', cell: ({ row }) => <span className="block max-w-72 truncate text-sm" title={row.original.scopeSummary}>{row.original.scopeSummary}</span> },
  { id: 'schedule', accessorFn: (s) => s.schedule.kind, header: 'Refresh', cell: ({ row }) => <span className="text-sm whitespace-nowrap">{scheduleLabel(row.original.schedule)}</span> },
  { accessorKey: 'lastSyncAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last sync" />, cell: ({ row }) => <span className="text-xs whitespace-nowrap">{row.original.lastSyncAt ? relativeTime(row.original.lastSyncAt) : 'Never'}</span> },
  { accessorKey: 'itemsIndexed', header: ({ column }) => <DataTableColumnHeader column={column} title="Items" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.itemsIndexed)}{row.original.itemsFailed ? <span className="text-destructive"> · {row.original.itemsFailed} failed</span> : null}</span> },
  { id: 'usedBy', accessorFn: (s) => s.usedBy.length, header: 'Knowledge bases', cell: ({ row }) => <span className="text-sm">{row.original.usedBy.map((k) => k.name).join(', ') || <span className="text-muted-foreground">None</span>}</span> },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => <SourceStatusBadge status={row.original.status} /> },
];

/**
 * What a connection syncs into the Wiki and its knowledge bases: the Sync knowledge switch, then one row per source
 * reading through it with what it indexes, how often and when it last ran. Each source's full settings are its own page.
 */
export function KnowledgeTab({ connection }: { connection: IntegrationDetail }) {
  const router = useRouter();
  const list = useListParams('name');
  const query = useSourcesList({ ...list.params, filters: { ...list.params.filters, connectionId: [connection.id] } });
  const switches = useSetIntegrationSwitches();
  const [addOpen, setAddOpen] = React.useState(false);
  const [blankOpen, setBlankOpen] = React.useState(false);
  const connections = useIntegrationOptions(addOpen || blankOpen);
  const sourceType = SOURCE_TYPES.some((t) => t.type === connection.kind) ? (connection.kind as SourceType) : undefined;
  const kbs = useKnowledgeBases(ALL);
  const all = useSourcesList(ALL);
  const lookups = useKnowledgeLookups();
  const create = useCreateSource();
  const syncSource = useSyncSource();
  const rows: Row[] = (query.data?.data ?? []).map((s) => ({ ...s, onRowClick: (x: SourceRow) => router.push(`/integrations/sources/${x.id}`) }));

  return (
    <div className="flex flex-col gap-4" data-testid="connection-knowledge">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 p-3">
        <Switch
          id="sync-knowledge"
          checked={connection.syncKnowledge}
          disabled={connection.status === 'revoked' || switches.isPending}
          onCheckedChange={(v) =>
            switches.mutate({ id: connection.id, patch: { syncKnowledge: v } }, { onSuccess: () => toast.success(v ? `Syncing knowledge from ${connection.name}` : `Stopped syncing knowledge from ${connection.name}`), onError: (e) => toast.error('Couldn’t change the switch', { description: e.message }) })
          }
        />
        <Label htmlFor="sync-knowledge" className="flex flex-col items-start gap-0.5 font-normal">
          <span className="font-medium">Sync knowledge</span>
          <span className="text-xs text-muted-foreground">Content from {connection.name} lands in the Wiki and the knowledge bases that read these sources.</span>
        </Label>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} disabled={connection.status === 'revoked'} data-testid="connection-guided-add">
            Guided add
          </Button>
          <Button size="sm" onClick={() => setBlankOpen(true)} disabled={connection.status === 'revoked'} data-testid="connection-add-source">
            <Plus className="size-4" /> Add source
          </Button>
        </div>
      </div>
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={3} showToolbar={false} />
      ) : query.isError && !query.data ? (
        <QueryError what="the sources on this connection" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search sources…"
          hideViewSwitcher
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
          emptyState={<ListEmpty icon={Plug} noun="sources on this connection" filtered={list.isFiltered} description={`Add a source to say which ${connection.name} paths, spaces or folders to index.`} />}
        />
      )}
      <NewSourceDialog
        open={blankOpen}
        onOpenChange={setBlankOpen}
        connections={connections.data ?? []}
        fixedConnection={sourceType ? { id: connection.id, type: sourceType } : undefined}
        existingNames={(all.data?.data ?? []).map((s) => s.name)}
        isPending={create.isPending}
        onSubmit={(input) => create.mutateAsync({ input, sync: false, kbIds: [] })}
        onSync={(id) => syncSource.mutateAsync({ id })}
        onCreated={(s, synced) => {
          toast.success(synced ? `Syncing ${s.name}` : `Saved ${s.name} as a draft`, { description: synced ? 'Its files are being read and indexed.' : 'Set its scope, ingestion and schedule here, then sync it.' });
          router.push(`/integrations/sources/${s.id}?tab=${synced ? 'items' : 'settings'}`);
        }}
      />
      <AddSourceDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        connections={connections.data ?? []}
        knowledgeBases={kbs.data?.data ?? []}
        collections={lookups.data?.collections ?? []}
        existingNames={(all.data?.data ?? []).map((s) => s.name)}
        newConnectionId={connection.id}
        onConnectNew={() => undefined}
        isPending={create.isPending}
        onSubmit={async (input, opts) => {
          const s = await create.mutateAsync({ input, ...opts });
          toast.success(s.status === 'draft' ? `Saved ${s.name} as a draft` : opts.sync ? `Created ${s.name}; the first sync has started` : `Created ${s.name}`);
          router.push(`/integrations/sources/${s.id}`);
        }}
      />
    </div>
  );
}
