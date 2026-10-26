'use client';

import * as React from 'react';
import { useCurrentPerson } from '@/hooks/auth-queries';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Archive, ArchiveRestore, Bot, Brain, Link2, MessageSquareDashed, MoreHorizontal, Pin, PinOff, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ChatLayout, ChatRailButton } from '@/components/chat/chat-layout';
import { ChatHome } from './chat-home';
import { Composer, KbChips, type KbOption } from '@/components/chat/composer';
import { ThreadSettingsButton } from '@/components/chat/thread-settings';
import { MemorySheet } from '@/components/memory/memory-sheet';
import { ThreadMessages, visibleMessages } from '@/components/chat/thread-messages';
import { useThreadActions } from '@/components/chat/use-thread-actions';
import { ThreadRail } from '@/components/chat/thread-rail';
import { DocumentPanel } from '@/components/knowledge/document-panel';
import { RetrievalTraceView } from '@/components/knowledge/retrieval-trace';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type LiveTurn,
  useChatAgents,
  useDefaultAgent,
  useChatThread,
  useChatThreadPages,
  useCreateThread,
  useDeleteThread,
  useLiveTurn,
  abortAllReplies,
  useSendMessage,
  useStreamingThreadIds,
  useUpdateThread,
} from '@/hooks/chat-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { useSticky } from '@/hooks/use-sticky';
import { teamOfError } from '@/hooks/use-team';
import type { ChatAgent, ChatAttachment, ChatMessage, ChatThread, ChatThreadPatch, ChatThreadRow, MessageFeedback, SendInput, WidgetAction } from '@/lib/types/chat';
import type { RetrievalTrace } from '@/lib/types/knowledge-retrieval';

const ALL = { page: 1, pageSize: 100 };
const RAIL_PAGE = 30;

export function ChatWorkspace({ threadId }: { threadId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const me = useCurrentPerson().name || undefined;
  const [railOpen, setRailOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [debounced, setDebounced] = React.useState('');
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const rail = useChatThreadPages({ pageSize: RAIL_PAGE, search: debounced || undefined, filters: { state: ['active', 'pinned'] } });
  const railThreads = React.useMemo(() => rail.data?.pages.flatMap((p) => p.data), [rail.data]);
  const thread = useChatThread(threadId);
  const agents = useChatAgents();
  const kbList = useKnowledgeBases(ALL);
  const kbs: KbOption[] = React.useMemo(() => (kbList.data?.data ?? []).map((k) => ({ id: k.id, name: k.name, color: k.color })), [kbList.data]);
  // An agent served by the chat service names the knowledge bases it may search; those win over the Knowledge area's
  // list, which may come from another backend (e.g. the Runtime for chat, the mock for everything else).
  const kbsFor = React.useCallback((agentId?: string): KbOption[] => {
    const own = agents.data?.find((a) => a.id === agentId)?.kbs;
    return own ? own.map((k) => ({ id: k.id, name: k.name, color: kbs.find((x) => x.id === k.id)?.color ?? 'teal' })) : kbs;
  }, [agents.data, kbs]);
  const streamingIds = useStreamingThreadIds();
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  // Replies keep streaming while the person moves between conversations, and stop when they leave chat altogether.
  React.useEffect(
    () => () => {
      setTimeout(() => {
        if (!window.location.pathname.startsWith('/chat')) abortAllReplies();
      }, 0);
    },
    [],
  );
  const create = useCreateThread();
  const update = useUpdateThread();
  const remove = useDeleteThread();
  const [deleting, setDeleting] = React.useState<Pick<ChatThreadRow, 'id' | 'title'> | null>(null);
  const deletingShown = useSticky(deleting);
  const [docId, setDocId] = React.useState<string | null>(null);
  // The page a citation named, so the document opens on it; another item opened from the sheet starts at its top.
  const [docPage, setDocPage] = React.useState<number | undefined>();
  const [trace, setTrace] = React.useState<RetrievalTrace | null>(null);
  const [editingTitle, setEditingTitle] = React.useState(false);
  const [titleDraft, setTitleDraft] = React.useState('');

  const patchThread = (id: string, patch: ChatThreadPatch, done?: string, undo?: ChatThreadPatch) =>
    update.mutate(
      { id, patch },
      {
        onSuccess: () => done && toast.success(done, undo ? { action: { label: 'Undo', onClick: () => update.mutate({ id, patch: undo }) } } : undefined),
        onError: (e) => toast.error('Couldn’t update the chat', { description: e.message }),
      },
    );
  const archive = (t: Pick<ChatThreadRow, 'id' | 'title' | 'archived'>) =>
    patchThread(t.id, { archived: !t.archived, ...(t.archived ? {} : { pinned: false }) }, t.archived ? `Restored ${t.title}` : `Archived ${t.title}`, { archived: t.archived });

  const railNode = (
    <ThreadRail
      threads={railThreads}
      loading={rail.isPending}
      hasMore={rail.hasNextPage}
      loadingMore={rail.isFetchingNextPage}
      onLoadMore={() => rail.fetchNextPage()}
      error={rail.isError ? rail.error.message : undefined}
      onRetry={() => rail.refetch()}
      activeId={threadId}
      streamingIds={streamingIds}
      search={search}
      onSearch={setSearch}
      onNew={() => {
        setRailOpen(false);
        router.push('/chat');
      }}
      onNavigate={() => setRailOpen(false)}
      onRename={(t, title) => patchThread(t.id, { title })}
      onTogglePin={(t) => patchThread(t.id, { pinned: !t.pinned }, t.pinned ? 'Unpinned' : 'Pinned')}
      onArchive={archive}
      onDelete={setDeleting}
    />
  );

  const actions = useThreadActions(threadId, thread);
  const copy = actions.copy;

  return (
    <ChatLayout rail={railNode} railOpen={railOpen} onRailOpenChange={setRailOpen}>
      {actions.stepUpDialog}
      {threadId ? (
        <ThreadView
          threadId={threadId}
          query={thread}
          live={live}
          me={me}
          kbs={kbsFor(thread.data?.agentId)}
          agent={agents.data?.find((a) => a.id === thread.data?.agentId)}
          agents={agents.data ?? []}
          editingTitle={editingTitle}
          titleDraft={titleDraft}
          setTitleDraft={setTitleDraft}
          setEditingTitle={setEditingTitle}
          onPatch={patchThread}
          onArchive={archive}
          onDelete={setDeleting}
          onCopy={copy}
          onOpenDocument={(id, page) => (setDocId(id), setDocPage(page))}
          onOpenTrace={setTrace}
          onSend={(input, cutFrom) => chat.send(threadId, input, cutFrom)}
          onStop={() => chat.stop(threadId)}
          onDismissFailed={() => chat.dismiss(threadId)}
          onFeedback={actions.onFeedback}
          onWidgetAction={actions.onWidgetAction}
        />
      ) : (
        <ChatHome
          agents={agents}
          me={me}
          initialAgentId={searchParams.get('agent') ?? undefined}
          header={
            <>
              <ChatRailButton />
              <span className="px-1 text-sm font-semibold">New chat</span>
            </>
          }
          creating={create.isPending}
          onStart={async (agentId, kbIds, text, attachments) => {
            try {
              const t = await create.mutateAsync({ agentId, kbIds });
              chat.send(t.id, { content: text, attachments });
              router.push(`/chat/${t.id}`);
            } catch (e) {
              toast.error('Couldn’t start the chat', { description: (e as Error).message });
            }
          }}
        />
      )}

      <DocumentPanel itemId={docId} page={docPage} onClose={() => setDocId(null)} onOpenItem={(id) => (setDocId(id), setDocPage(undefined))} />
      <DetailSheet open={!!trace} onOpenChange={(o) => !o && setTrace(null)} title="How this answer was found" description={trace ? `“${trace.question}”` : undefined} widthClass="sm:max-w-3xl" testId="chat-trace-sheet">
        {trace && <RetrievalTraceView trace={trace} />}
      </DetailSheet>

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
            if (t.id === threadId) router.push('/chat');
          } catch (e) {
            toast.error(`Couldn’t delete ${t.title}`, { description: (e as Error).message });
          }
        }}
      />
    </ChatLayout>
  );
}


function ThreadView({
  threadId,
  query,
  live,
  me,
  kbs,
  agent,
  agents,
  editingTitle,
  titleDraft,
  setTitleDraft,
  setEditingTitle,
  onPatch,
  onArchive,
  onDelete,
  onCopy,
  onOpenDocument,
  onOpenTrace,
  onSend,
  onStop,
  onDismissFailed,
  onFeedback,
  onWidgetAction,
}: {
  threadId: string;
  query: ReturnType<typeof useChatThread>;
  live?: LiveTurn;
  me?: string;
  kbs: KbOption[];
  agent?: ChatAgent;
  /** Agents the person can hand the chat to with @ (c-174). */
  agents: ChatAgent[];
  editingTitle: boolean;
  titleDraft: string;
  setTitleDraft: (s: string) => void;
  setEditingTitle: (b: boolean) => void;
  onPatch: (id: string, patch: ChatThreadPatch, done?: string) => void;
  onArchive: (t: ChatThread) => void;
  onDelete: (t: ChatThread) => void;
  onCopy: (text: string, what?: string) => void;
  onOpenDocument: (id: string, page?: number) => void;
  onOpenTrace: (trace: RetrievalTrace) => void;
  onSend: (input: SendInput, cutFrom?: string) => void;
  onStop: () => void;
  onDismissFailed: () => void;
  onFeedback: (messageId: string, fb: MessageFeedback | null) => void;
  onWidgetAction: (messageId: string, widgetId: string, action: WidgetAction) => Promise<void>;
}) {
  const t = query.data && query.data.id === threadId ? query.data : undefined;
  const messages = visibleMessages(t, live);
  const streaming = !!live?.streaming;

  const notFound = query.isError && (query.error as { status?: number }).status === 404;
  const owner = !!t && !!me && t.owner === me;
  const readOnly = !t || !owner || t.archived;
  // What I remember is the person's own memories with this agent, so only the chat's owner is offered it (c-206).
  const [memoryOpen, setMemoryOpen] = React.useState(false);
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
  const pausedOnBudget = lastAssistant?.budget?.state === 'waiting';
  // Replies name their agent once the conversation has had more than one (a handover, c-174).
  const severalAgents = !!t?.startAgentId || new Set(messages.flatMap((m) => (m.role === 'assistant' && m.agentName ? [m.agentName] : []))).size > 1;
  const handTo = (to: { id: string; name: string }, back = false) => onPatch(threadId, { agentId: to.id }, back ? `Back to ${to.name}` : `${to.name} has the chat`);

  if (notFound)
    return (
      <>
        <header className="flex min-h-12 items-center gap-2 border-b px-3 py-2">
          <ChatRailButton />
          <span className="px-1 text-sm font-semibold">Chat not found</span>
        </header>
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={MessageSquareDashed}
            title="This chat does not exist"
            description="It may have been deleted, or it belongs to someone who has not shared it. Pick another chat or start a new one."
            action={{ label: 'New chat', href: '/chat' }}
            secondaryAction={{ label: 'All conversations', href: '/chat/conversations' }}
          />
        </div>
      </>
    );

  return (
    <>
      <header className="flex min-h-12 flex-wrap items-center gap-2 border-b px-3 py-2">
        <ChatRailButton />
        <div className="min-w-0 flex-1">
          {t && editingTitle ? (
            <Input
              autoFocus
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={() => {
                if (titleDraft.trim() && titleDraft.trim() !== t.title) onPatch(t.id, { title: titleDraft.trim() });
                setEditingTitle(false);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                if (e.key === 'Escape') setEditingTitle(false);
              }}
              className="h-8 max-w-md"
              aria-label="Chat title"
            />
          ) : t ? (
            <button
              type="button"
              disabled={!owner}
              title={owner ? 'Rename' : undefined}
              className="max-w-full truncate rounded px-1 text-left text-sm font-semibold enabled:hover:bg-accent"
              onClick={() => {
                setTitleDraft(t.title);
                setEditingTitle(true);
              }}
            >
              {t.title}
            </button>
          ) : (
            <Skeleton className="h-5 w-48" />
          )}
          {t && (
            <div className="mt-1 flex flex-wrap items-center gap-2 px-1">
              <Link href={`/agents/${t.agentId}`} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline">
                <Bot className="size-3.5" /> {t.agentName} · v{t.agentVersion}
              </Link>
              {agent && agent.version !== t.agentVersion && <span className="text-[11px] text-muted-foreground">(v{agent.version} is live; new chats use it)</span>}
              <KbChips kbs={kbs} value={t.kbIds} onChange={(ids) => onPatch(t.id, { kbIds: ids }, 'Knowledge updated for the next answer')} disabled={readOnly} agentName={agent?.name} />
            </div>
          )}
        </div>
        {t && (
          <div className="flex items-center gap-1">
            {owner && !t.archived && <ThreadSettingsButton threadId={t.id} />}
            {owner && (
              <Button variant="ghost" size="sm" onClick={() => setMemoryOpen(true)} data-testid="memory-button">
                <Brain className="size-4" /> <span className="sr-only sm:not-sr-only">Memory</span>
              </Button>
            )}
            {owner && <MemorySheet agentId={t.agentId} agentName={t.agentName} open={memoryOpen} onOpenChange={setMemoryOpen} />}
            <Button variant="outline" size="sm" onClick={() => onCopy(`${window.location.origin}/chat/${t.id}`, 'Link copied. People with access to this workspace can open it read-only.')}>
              <Link2 className="size-4" /> <span className="sr-only sm:not-sr-only">Share</span>
            </Button>
            {owner && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="size-8" aria-label="Chat actions">
                    <MoreHorizontal className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {!t.archived && (
                    <DropdownMenuItem onClick={() => onPatch(t.id, { pinned: !t.pinned }, t.pinned ? 'Unpinned' : 'Pinned')}>
                      {t.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />} {t.pinned ? 'Unpin' : 'Pin'}
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem onClick={() => onArchive(t)}>
                    {t.archived ? <ArchiveRestore className="size-4" /> : <Archive className="size-4" />} {t.archived ? 'Restore' : 'Archive'}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onClick={() => onDelete(t)}>
                    <Trash2 className="size-4" /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        )}
      </header>

      {query.isPending && !live ? (
        <div className="mx-auto w-full max-w-3xl flex-1 space-y-4 p-4">
          <Skeleton className="ml-auto h-10 w-2/3 max-w-md" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="ml-auto h-10 w-1/2 max-w-sm" />
        </div>
      ) : query.isError && (!t || teamOfError(query.error)) ? (
        <div className="p-6">
          <QueryError what="this chat" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        </div>
      ) : (
        <ThreadMessages
          threadId={threadId}
          messages={messages}
          live={live}
          kbIds={t?.kbIds ?? []}
          kbNames={t?.kbNames ?? []}
          readOnly={readOnly}
          owner={owner}
          archived={!!t?.archived}
          severalAgents={severalAgents}
          onOpenMemory={owner ? () => setMemoryOpen(true) : undefined}
          onSend={onSend}
          onDismissFailed={onDismissFailed}
          onOpenDocument={onOpenDocument}
          onOpenTrace={onOpenTrace}
          onCopy={onCopy}
          onFeedback={onFeedback}
          onWidgetAction={onWidgetAction}
        />
      )}

      {t && (
        <div className="mx-auto w-full max-w-3xl p-3">
          {t.startAgentId && (
            <Alert className="mb-2" data-testid="handover-notice">
              <Bot className="size-4" />
              <AlertTitle>You are talking to {t.agentName}</AlertTitle>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                <span>This chat started with {t.startAgentName}. Replies now come from {t.agentName}.</span>
                {owner && !t.archived && (
                  <Button size="sm" variant="outline" disabled={streaming} onClick={() => handTo({ id: t.startAgentId!, name: t.startAgentName ?? 'the first agent' }, true)}>
                    Back to {t.startAgentName}
                  </Button>
                )}
              </AlertDescription>
            </Alert>
          )}
          <Composer
            placeholder={`Message ${t.agentName}… Type @ to hand the chat to another agent.`}
            mentions={agents.filter((a) => a.id !== t.agentId).map((a) => ({ id: a.id, name: a.name, role: a.role }))}
            onMention={(a) => handTo(a)}
            streaming={streaming}
            onStop={onStop}
            onSend={(text, files) => onSend({ content: text, attachments: files.length ? files : undefined })}
            disabledReason={
              pausedOnBudget ? (
                'This conversation is paused on its budget. Continue it above to send more.'
              ) : !owner ? (
                `This is ${t.owner}’s chat. You can read it but not continue it.`
              ) : t.archived ? (
                <span className="flex flex-wrap items-center justify-between gap-2">
                  This chat is archived. Restore it to continue.
                  <Button size="sm" variant="outline" onClick={() => onArchive(t)}>
                    <ArchiveRestore className="size-4" /> Restore
                  </Button>
                </span>
              ) : undefined
            }
          />
          <p className="mt-1.5 hidden text-center text-[11px] text-muted-foreground sm:block">Answers can be wrong; check the cited documents. Actions the agent drafts wait for approval.</p>
        </div>
      )}
    </>
  );
}
