'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Archive, History, MoreHorizontal, Pencil, Pin, PinOff, RotateCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { SidebarGroupLabel, SidebarInput, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton } from '@/components/ui/sidebar';
import { useChatThreadPages, useDeleteThread, useStreamingThreadIds, useUpdateThread } from '@/hooks/chat-queries';
import { useSticky } from '@/hooks/use-sticky';
import type { ChatThreadPatch, ChatThreadRow } from '@/lib/types/chat';

const PAGE = 30;
export const CHAT_GROUPS = ['Pinned', 'Today', 'Yesterday', 'Previous 7 days', 'Older'] as const;
export type ChatGroup = (typeof CHAT_GROUPS)[number];

/** The heading a chat sits under, by its last message in the viewer's own day (c-552 adds Yesterday). */
export function chatGroupOf(t: Pick<ChatThreadRow, 'pinned' | 'lastMessageAt'>, now = new Date()): ChatGroup {
  if (t.pinned) return 'Pinned';
  const at = new Date(t.lastMessageAt).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (at >= today) return 'Today';
  if (at >= today - 86_400_000) return 'Yesterday';
  if (at >= today - 7 * 86_400_000) return 'Previous 7 days';
  return 'Older';
}

/**
 * The person's chats inside the app sidebar (c-552), grouped by day with pinned first, each with rename, pin, archive
 * and delete, and an All chats row to the Conversations page. Pages by cursor, so a long history loads on demand and
 * the console's pages below stay in reach. Hidden while the sidebar is folded to icons.
 */
export function SidebarChats({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const activeId = pathname.startsWith('/chat/') && pathname !== '/chat/conversations' ? pathname.split('/')[2] : undefined;
  const pages = useChatThreadPages({ pageSize: PAGE, filters: { state: ['active', 'pinned'] } });
  const threads = React.useMemo(() => pages.data?.pages.flatMap((p) => p.data) ?? [], [pages.data]);
  const streaming = useStreamingThreadIds();
  const update = useUpdateThread();
  const remove = useDeleteThread();
  const [renaming, setRenaming] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState('');
  const [deleting, setDeleting] = React.useState<Pick<ChatThreadRow, 'id' | 'title'> | null>(null);
  const deletingShown = useSticky(deleting);

  const groups = React.useMemo(() => {
    const out = Object.fromEntries(CHAT_GROUPS.map((g) => [g, [] as ChatThreadRow[]])) as Record<ChatGroup, ChatThreadRow[]>;
    threads.forEach((t) => out[chatGroupOf(t)].push(t));
    return out;
  }, [threads]);

  const patch = (id: string, p: ChatThreadPatch, done?: string, undo?: ChatThreadPatch) =>
    update.mutate(
      { id, patch: p },
      {
        onSuccess: () => done && toast.success(done, undo ? { action: { label: 'Undo', onClick: () => update.mutate({ id, patch: undo }) } } : undefined),
        onError: (e) => toast.error('Couldn’t update the chat', { description: e.message }),
      },
    );
  const commit = (t: ChatThreadRow) => {
    if (draft.trim() && draft.trim() !== t.title) patch(t.id, { title: draft.trim() });
    setRenaming(null);
  };

  return (
    <div className="group-data-[collapsible=icon]:hidden" data-testid="sidebar-chats">
      {pages.isPending ? (
        <SidebarMenu data-testid="sidebar-chats-loading">
          {Array.from({ length: 5 }, (_, i) => (
            <SidebarMenuItem key={i}>
              <SidebarMenuSkeleton />
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      ) : pages.isError ? (
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => void pages.refetch()} className="text-muted-foreground" aria-label="Couldn’t load chats. Try again">
              <RotateCw />
              <span>Couldn’t load chats. Try again</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      ) : !threads.length ? (
        <p className="px-2 py-2 text-xs text-muted-foreground" data-testid="sidebar-chats-empty">
          No chats yet. Ask something to start one.
        </p>
      ) : (
        CHAT_GROUPS.map((g) =>
          groups[g].length ? (
            <div key={g} data-chat-group={g}>
              <SidebarGroupLabel className="h-7 text-[11px]">{g}</SidebarGroupLabel>
              <SidebarMenu>
                {groups[g].map((t) => (
                  <SidebarMenuItem key={t.id}>
                    {renaming === t.id ? (
                      <SidebarInput
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={() => commit(t)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commit(t);
                          if (e.key === 'Escape') setRenaming(null);
                        }}
                        aria-label="Chat title"
                      />
                    ) : (
                      <SidebarMenuButton asChild isActive={t.id === activeId} tooltip={t.title}>
                        <Link href={`/chat/${t.id}`} onClick={onNavigate} aria-current={t.id === activeId ? 'page' : undefined} data-testid="sidebar-chat">
                          {streaming.has(t.id) && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" aria-label="Answering" />}
                          <span className="truncate">{t.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    )}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <SidebarMenuAction showOnHover aria-label={`Actions for ${t.title}`}>
                          <MoreHorizontal />
                        </SidebarMenuAction>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" side="right">
                        <DropdownMenuItem
                          onClick={() => {
                            setDraft(t.title);
                            setRenaming(t.id);
                          }}
                        >
                          <Pencil className="size-4" /> Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => patch(t.id, { pinned: !t.pinned }, t.pinned ? 'Unpinned' : 'Pinned')}>
                          {t.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />} {t.pinned ? 'Unpin' : 'Pin'}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => patch(t.id, { archived: true, pinned: false }, `Archived ${t.title}`, { archived: false })}>
                          <Archive className="size-4" /> Archive
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => setDeleting(t)}>
                          <Trash2 className="size-4" /> Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </div>
          ) : null,
        )
      )}
      <SidebarMenu>
        {pages.hasNextPage && (
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => void pages.fetchNextPage()} disabled={pages.isFetchingNextPage} className="text-muted-foreground">
              <span>{pages.isFetchingNextPage ? 'Loading…' : 'Show more chats'}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
        <SidebarMenuItem>
          <SidebarMenuButton asChild isActive={pathname === '/chat/conversations'} className="text-muted-foreground">
            <Link href="/chat/conversations" onClick={onNavigate} data-testid="sidebar-all-chats">
              <History />
              <span>All chats</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
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
            if (t.id === activeId) router.push('/chat');
          } catch (e) {
            toast.error(`Couldn’t delete ${t.title}`, { description: (e as Error).message });
          }
        }}
      />
    </div>
  );
}
