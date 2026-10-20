'use client';

import * as React from 'react';
import Link from 'next/link';
import { Archive, History, MoreHorizontal, Pencil, Pin, PinOff, Plus, Search, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { SidebarGroup, SidebarGroupLabel, SidebarInput, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton } from '@/components/ui/sidebar';
import { relativeTime } from '@/lib/format';
import type { ChatThreadRow } from '@/lib/types/chat';

const GROUPS = ['Pinned', 'Today', 'Previous 7 days', 'Older'] as const;

function groupOf(t: ChatThreadRow): (typeof GROUPS)[number] {
  if (t.pinned) return 'Pinned';
  const d = new Date(t.lastMessageAt);
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= start) return 'Today';
  if (d.getTime() >= start - 7 * 86_400_000) return 'Previous 7 days';
  return 'Older';
}

export interface ThreadRailProps {
  threads?: ChatThreadRow[];
  loading: boolean;
  /** More rows follow the ones shown; the server pages by cursor. */
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  error?: string;
  onRetry: () => void;
  activeId?: string;
  streamingIds: Set<string>;
  search: string;
  onSearch: (q: string) => void;
  onNew: () => void;
  onNavigate?: () => void;
  onRename: (t: ChatThreadRow, title: string) => void;
  onTogglePin: (t: ChatThreadRow) => void;
  onArchive: (t: ChatThreadRow) => void;
  onDelete: (t: ChatThreadRow) => void;
}

/** The conversation list beside the chat: grouped by recency, pinned first, with inline rename. */
export function ThreadRail({ threads, loading, hasMore, loadingMore, onLoadMore, error, onRetry, activeId, streamingIds, search, onSearch, onNew, onNavigate, onRename, onTogglePin, onArchive, onDelete }: ThreadRailProps) {
  const [renaming, setRenaming] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState('');
  const groups = React.useMemo(() => {
    const out = Object.fromEntries(GROUPS.map((g) => [g, [] as ChatThreadRow[]])) as Record<(typeof GROUPS)[number], ChatThreadRow[]>;
    (threads ?? []).forEach((t) => out[groupOf(t)].push(t));
    return out;
  }, [threads]);

  const commit = (t: ChatThreadRow) => {
    if (draft.trim() && draft.trim() !== t.title) onRename(t, draft.trim());
    setRenaming(null);
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="space-y-2 border-b p-3">
        <Button className="w-full justify-start" size="sm" onClick={onNew}>
          <Plus className="size-4" /> New chat
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute top-2 left-2.5 size-3.5 text-muted-foreground" />
          <SidebarInput value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search chats…" className="pl-8" aria-label="Search chats" />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-3 p-2">
          {loading ? (
            Array.from({ length: 6 }, (_, i) => <SidebarMenuSkeleton key={i} showIcon={false} />)
          ) : error ? (
            <div className="space-y-2 px-2 py-6 text-center text-xs text-muted-foreground">
              <p>Couldn’t load chats. {error}</p>
              <Button variant="outline" size="sm" onClick={onRetry}>
                Retry
              </Button>
            </div>
          ) : !threads?.length ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">{search ? 'No chats match.' : 'No chats yet. Start one to ask an agent.'}</p>
          ) : (
            GROUPS.map((g) =>
              groups[g].length ? (
                <SidebarGroup key={g} className="p-0">
                  <SidebarGroupLabel>{g}</SidebarGroupLabel>
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
                          <SidebarMenuButton asChild size="lg" isActive={t.id === activeId} className="pr-8">
                            <Link href={`/chat/${t.id}`} onClick={onNavigate} aria-current={t.id === activeId ? 'page' : undefined}>
                              <span className="flex min-w-0 flex-col">
                                <span className="flex items-center gap-1.5">
                                  {streamingIds.has(t.id) && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" aria-label="Answering" />}
                                  <span className="truncate text-sm">{t.title}</span>
                                </span>
                                <span className="truncate text-[11px] text-muted-foreground">
                                  {t.agentName} · {relativeTime(t.lastMessageAt)}
                                </span>
                              </span>
                            </Link>
                          </SidebarMenuButton>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <SidebarMenuAction showOnHover className="top-3" aria-label={`Actions for ${t.title}`}>
                              <MoreHorizontal />
                            </SidebarMenuAction>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={() => {
                                setDraft(t.title);
                                setRenaming(t.id);
                              }}
                            >
                              <Pencil className="size-4" /> Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onTogglePin(t)}>
                              {t.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />} {t.pinned ? 'Unpin' : 'Pin'}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onArchive(t)}>
                              <Archive className="size-4" /> Archive
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onClick={() => onDelete(t)}>
                              <Trash2 className="size-4" /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroup>
              ) : null,
            )
          )}
          {!loading && !error && hasMore && (
            <Button variant="ghost" size="sm" className="w-full text-muted-foreground" onClick={onLoadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading…' : 'Show more chats'}
            </Button>
          )}
        </div>
      </div>
      <div className="border-t p-2">
        <Button asChild variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
          <Link href="/chat/conversations" onClick={onNavigate}>
            <History className="size-4" /> All conversations
          </Link>
        </Button>
      </div>
    </div>
  );
}
