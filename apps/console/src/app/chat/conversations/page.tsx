'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, ArchiveRestore, Bot, ExternalLink, History, Pin, PinOff, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { KbDot } from '@/components/knowledge/knowledge-meta';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Button } from '@/components/ui/button';
import { useBulkDeleteThreads, useBulkUpdateThreads, useChatThreads, useDeleteThread, useUpdateThread } from '@/hooks/chat-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { count, plural, relativeTime } from '@/lib/format';
import type { ChatFilters, ChatThreadRow } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

type Row = ChatThreadRow & { onRowClick: (t: ChatThreadRow) => void; href: string };
const ALL = { page: 1, pageSize: 100 };
const STATE_LABEL: Record<string, string> = { active: 'Active', pinned: 'Pinned', archived: 'Archived' };
const stateOf = (t: ChatThreadRow) => (t.archived ? 'archived' : t.pinned ? 'pinned' : 'active');

type Actions = { pin: (t: ChatThreadRow) => void; archive: (t: ChatThreadRow) => void; remove: (t: ChatThreadRow) => void; colorOf: (kbId: string) => string };

function columns(a: Actions): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((t) => t.title),
    {
      accessorKey: 'title',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Conversation" />,
      cell: ({ row }) => (
        <div className="min-w-64 max-w-md">
          <Link href={row.original.href} className="flex items-center gap-1.5 font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
            {row.original.pinned && <Pin className="size-3 shrink-0 text-muted-foreground" aria-label="Pinned" />}
            <span className="truncate">{row.original.title}</span>
          </Link>
          <p className="truncate text-xs text-muted-foreground">{row.original.preview || 'No messages yet'}</p>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'agentId',
      accessorFn: (r) => r.agentId,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Agent" />,
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <Bot className="size-3.5 text-muted-foreground" /> {row.original.agentName} <span className="text-muted-foreground">v{row.original.agentVersion}</span>
        </span>
      ),
      filterFn: facetFilterFn,
    },
    {
      id: 'kbIds',
      accessorFn: (r) => r.kbIds,
      header: () => <span className="text-xs">Knowledge</span>,
      cell: ({ row }) =>
        row.original.kbIds.length ? (
          <div className="flex max-w-64 flex-wrap gap-1">
            {row.original.kbIds.map((k, i) => (
              <span key={k} className="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[11px] whitespace-nowrap">
                <KbDot color={a.colorOf(k)} className="size-2" /> {row.original.kbNames[i]}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground">None</span>
        ),
      filterFn: (r, id, value: string[]) => !value?.length || (r.getValue(id) as string[]).some((k) => value.includes(k)),
    },
    { id: 'messages', accessorFn: (r) => r.messageCount, header: ({ column }) => <DataTableColumnHeader column={column} title="Messages" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.messageCount)}</span> },
    {
      id: 'artifacts',
      accessorFn: (r) => r.widgets + r.citations,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Widgets · citations" />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap tabular-nums text-muted-foreground">
          {row.original.widgets} · {row.original.citations}
        </span>
      ),
    },
    {
      id: 'state',
      accessorFn: stateOf,
      header: () => <span className="text-xs">State</span>,
      cell: ({ row }) => {
        const s = stateOf(row.original);
        return <span className={cn('rounded-full border px-2 py-0.5 text-[11px]', s === 'archived' && 'bg-muted text-muted-foreground', s === 'pinned' && 'border-primary/30 bg-primary/10 text-primary')}>{STATE_LABEL[s]}</span>;
      },
      filterFn: facetFilterFn,
    },
    { id: 'owner', accessorFn: (r) => r.owner, header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.owner}</span>, filterFn: facetFilterFn },
    {
      id: 'lastMessageAt',
      accessorFn: (r) => r.lastMessageAt,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Last activity" />,
      cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.lastMessageAt)}</span>,
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
              ...(row.original.archived ? [] : [{ label: row.original.pinned ? 'Unpin' : 'Pin', icon: row.original.pinned ? PinOff : Pin, onClick: (r: { original: Row }) => a.pin(r.original) }]),
              { label: row.original.archived ? 'Restore' : 'Archive', icon: row.original.archived ? ArchiveRestore : Archive, onClick: (r) => a.archive(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => a.remove(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function ConversationsPage() {
  const router = useRouter();
  const list = useListParams<ChatFilters>('title');
  const query = useChatThreads(list.params);
  const kbList = useKnowledgeBases(ALL);
  const update = useUpdateThread();
  const remove = useDeleteThread();
  const bulkUpdate = useBulkUpdateThreads();
  const bulkDelete = useBulkDeleteThreads();
  const [deleting, setDeleting] = React.useState<ChatThreadRow | null>(null);
  const deletingShown = useSticky(deleting);
  const [bulk, setBulk] = React.useState<{ kind: 'archive' | 'delete'; rows: ChatThreadRow[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((t) => t.title);
  const nameOf = (id: string) => shown?.rows.find((t) => t.id === id)?.title ?? query.data?.data.find((t) => t.id === id)?.title ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const kbs = kbList.data?.data ?? [];
  const rowsData = query.data?.data ?? [];
  const facets = query.data?.facets ?? {};
  const agentNames = Object.fromEntries(rowsData.map((t) => [t.agentId, t.agentName]));
  const kbNames = Object.fromEntries(kbs.map((k) => [k.id, k.name]));

  const cols = React.useMemo(
    () =>
      columns({
        pin: (t) =>
          update.mutate(
            { id: t.id, patch: { pinned: !t.pinned } },
            { onSuccess: () => toast.success(t.pinned ? `Unpinned ${t.title}` : `Pinned ${t.title}`), onError: (e) => toast.error('Couldn’t update the chat', { description: e.message }) },
          ),
        archive: (t) =>
          update.mutate(
            { id: t.id, patch: { archived: !t.archived } },
            {
              onSuccess: () => toast.success(t.archived ? `Restored ${t.title}` : `Archived ${t.title}`, { action: { label: 'Undo', onClick: () => update.mutate({ id: t.id, patch: { archived: t.archived } }) } }),
              onError: (e) => toast.error('Couldn’t update the chat', { description: e.message }),
            },
          ),
        remove: setDeleting,
        colorOf: (id) => kbList.data?.data.find((k) => k.id === id)?.color ?? 'slate',
      }),
    [update, kbList.data],
  );
  const rows: Row[] = React.useMemo(() => rowsData.map((t) => ({ ...t, href: `/chat/${t.id}`, onRowClick: (x: ChatThreadRow) => router.push(`/chat/${x.id}`) })), [rowsData, router]);
  const options = (key: string, label: (v: string) => string) => Object.keys(facets[key] ?? {}).map((v) => ({ value: v, label: label(v), count: facets[key]?.[v] ?? 0 }));

  return (
    <PageLayout
      icon={History}
      title="Conversations"
      description="Every chat with an agent in this workspace"
      actions={
        <Button onClick={() => router.push('/chat')}>
          <Plus className="size-4" /> New chat
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="conversations" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="title"
          searchPlaceholder="Search titles and messages…"
          initialColumnVisibility={{ artifacts: false }}
          filters={[
            { column: 'agentId', title: 'Agent', options: options('agentId', (v) => agentNames[v] ?? v) },
            { column: 'kbIds', title: 'Knowledge', options: options('kbIds', (v) => kbNames[v] ?? v) },
            { column: 'state', title: 'State', options: options('state', (v) => STATE_LABEL[v] ?? v) },
            { column: 'owner', title: 'Owner', options: options('owner', (v) => v) },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            {
              label: 'Pin',
              icon: Pin,
              variant: 'outline',
              onClick: async (r) => {
                const res = await bulkUpdate.mutateAsync({ ids: r.map((t) => t.id), patch: { pinned: true } });
                toastBulk(res, 'Pinned', 'chat', (id) => r.find((t) => t.id === id)?.title ?? id);
                setResetKey((k) => k + 1);
              },
            },
            { label: 'Archive', icon: Archive, variant: 'outline', onClick: (r) => setBulk({ kind: 'archive', rows: r }) },
            { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => setBulk({ kind: 'delete', rows: r }) },
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
              icon={History}
              noun="conversations"
              filtered={list.isFiltered}
              description="Chats with agents appear here, with the knowledge they used and the actions they drafted."
              createLabel="New chat"
              onCreate={() => router.push('/chat')}
            />
          }
        />
      )}

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="chat"
        entityName={deletingShown?.title}
        description="The conversation and its messages are deleted. Decisions made from its widgets stay on their reviews and in the audit trail."
        isLoading={remove.isPending}
        onConfirm={async () => {
          const t = deleting!;
          try {
            await remove.mutateAsync(t.id);
            toast.success(`Deleted ${t.title}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${t.title}`, { description: (e as Error).message });
          }
        }}
      />
      <BulkConfirmDialog
        open={bulk?.kind === 'archive'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Archive ${plural(names.length, 'chat')}`}
        description="Archived chats leave the sidebar and become read-only until restored. Chats owned by someone else are skipped."
        names={names}
        confirmLabel="Archive"
        isPending={bulkUpdate.isPending}
        onConfirm={async () => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((t) => t.id), patch: { archived: true } });
          toastBulk(res, 'Archived', 'chat', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="chat"
        count={names.length}
        description="Conversations and their messages are deleted. Chats owned by someone else are skipped."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((t) => t.id));
          toastBulk(res, 'Deleted', 'chat', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>
    </PageLayout>
  );
}
