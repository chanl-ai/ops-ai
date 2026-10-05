'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertTriangle, Archive, ArchiveRestore, Bot, Link2, MessageSquareDashed, MessagesSquare, MoreHorizontal, Pin, PinOff, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ChatLayout } from '@/components/chat/chat-layout';
import { Composer, KbChips, type KbOption } from '@/components/chat/composer';
import { AssistantMessage, UserMessage } from '@/components/chat/message-view';
import { ThreadRail } from '@/components/chat/thread-rail';
import { DocumentPanel } from '@/components/knowledge/document-panel';
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
  useChatThread,
  useChatThreads,
  useCreateThread,
  useDeleteThread,
  useLiveTurn,
  useMessageFeedback,
  useSendMessage,
  useStreamingThreadIds,
  useUpdateThread,
  useWidgetAction,
} from '@/hooks/chat-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { useLookups } from '@/hooks/queries';
import { useSticky } from '@/hooks/use-sticky';
import { teamOfError } from '@/hooks/use-team';
import type { ChatAgent, ChatAttachment, ChatMessage, ChatThread, ChatThreadPatch, ChatThreadRow, MessageFeedback, SendInput, WidgetAction } from '@/lib/types/chat';

const ALL = { page: 1, pageSize: 100 };

function phaseLabel(t: LiveTurn, kbNames: string[]) {
  if (t.assistant.content) return undefined;
  if (t.phase === 'retrieving') return `Searching ${kbNames.length ? kbNames.join(', ') : 'knowledge'}…`;
  if (t.phase === 'calling_tool') return 'Calling tools…';
  if (t.phase === 'writing') return 'Writing…';
  return 'Thinking…';
}

/** Thread history with an in-flight turn spliced in: messages being replaced are hidden, the live ones appended. */
function visibleMessages(thread: ChatThread | undefined, live: LiveTurn | undefined): ChatMessage[] {
  const base = thread?.messages ?? [];
  if (!live) return base;
  const cut = live.cutFrom ? base.findIndex((m) => m.id === live.cutFrom) : -1;
  const kept = (cut >= 0 ? base.slice(0, cut) : base).filter((m) => m.id !== live.userMessage?.id && m.id !== live.assistant.id);
  return [...kept, ...(live.userMessage ? [live.userMessage] : []), ...(live.failed ? [] : [live.assistant])];
}

export function ChatWorkspace({ threadId }: { threadId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const lookups = useLookups();
  const me = lookups.data?.currentUser.name;
  const [railOpen, setRailOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [debounced, setDebounced] = React.useState('');
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const rail = useChatThreads({ ...ALL, search: debounced || undefined, filters: { state: ['active', 'pinned'], ...(me ? { owner: [me] } : {}) } });
  const thread = useChatThread(threadId);
  const agents = useChatAgents();
  const kbList = useKnowledgeBases(ALL);
  const kbs: KbOption[] = React.useMemo(() => (kbList.data?.data ?? []).map((k) => ({ id: k.id, name: k.name, color: k.color })), [kbList.data]);
  const streamingIds = useStreamingThreadIds();
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  const create = useCreateThread();
  const update = useUpdateThread();
  const remove = useDeleteThread();
  const feedback = useMessageFeedback();
  const widgetAction = useWidgetAction();
  const [deleting, setDeleting] = React.useState<Pick<ChatThreadRow, 'id' | 'title'> | null>(null);
  const deletingShown = useSticky(deleting);
  const [docId, setDocId] = React.useState<string | null>(null);
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
      threads={rail.data?.data}
      loading={rail.isPending}
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

  const copy = (text: string, what = 'Answer copied') =>
    navigator.clipboard.writeText(text).then(
      () => toast.success(what),
      () => toast.error('Couldn’t copy', { description: 'The browser blocked clipboard access.' }),
    );

  return (
    <ChatLayout rail={railNode} railOpen={railOpen} onRailOpenChange={setRailOpen}>
      {threadId ? (
        <ThreadView
          threadId={threadId}
          query={thread}
          live={live}
          me={me}
          kbs={kbs}
          agent={agents.data?.find((a) => a.id === thread.data?.agentId)}
          onOpenRail={() => setRailOpen(true)}
          editingTitle={editingTitle}
          titleDraft={titleDraft}
          setTitleDraft={setTitleDraft}
          setEditingTitle={setEditingTitle}
          onPatch={patchThread}
          onArchive={archive}
          onDelete={setDeleting}
          onCopy={copy}
          onOpenDocument={setDocId}
          onSend={(input, cutFrom) => chat.send(threadId, input, cutFrom)}
          onStop={() => chat.stop(threadId)}
          onDismissFailed={() => chat.dismiss(threadId)}
          onFeedback={(messageId, fb) =>
            feedback.mutate(
              { threadId, messageId, feedback: fb },
              { onSuccess: () => fb?.rating === 'down' && toast.success('Thanks. The agent’s owner will see this.'), onError: (e) => toast.error('Couldn’t save feedback', { description: e.message }) },
            )
          }
          onWidgetAction={async (messageId, widgetId, action) => {
            try {
              const w = await widgetAction.mutateAsync({ threadId, messageId, widgetId, action });
              if (w.kind === 'approval')
                toast.success(
                  w.state === 'approved' ? `Approved ${w.reviewId}` : w.state === 'awaiting_second' ? `Your approval is recorded on ${w.reviewId}` : `Rejected ${w.reviewId}`,
                  { description: w.state === 'awaiting_second' ? 'A second approver must also approve it.' : 'The decision is on the review and in the audit trail.' },
                );
              else if (w.kind === 'form' && w.result) toast.success(w.result);
            } catch (e) {
              toast.error(action.type === 'submit' ? 'Couldn’t submit' : `Couldn’t ${action.type}`, { description: (e as Error).message });
            }
          }}
        />
      ) : (
        <NewChat
          agents={agents}
          kbs={kbs}
          initialAgentId={searchParams.get('agent') ?? undefined}
          onOpenRail={() => setRailOpen(true)}
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

      <DocumentPanel itemId={docId} onClose={() => setDocId(null)} />

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

function RailButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" className="lg:hidden" onClick={onClick}>
      <MessagesSquare className="size-4" /> <span className="sr-only sm:not-sr-only">Chats</span>
    </Button>
  );
}

function NewChat({
  agents,
  kbs,
  initialAgentId,
  onOpenRail,
  creating,
  onStart,
}: {
  agents: ReturnType<typeof useChatAgents>;
  kbs: KbOption[];
  initialAgentId?: string;
  onOpenRail: () => void;
  creating: boolean;
  onStart: (agentId: string, kbIds: string[], text: string, attachments: ChatAttachment[]) => void;
}) {
  const list = agents.data ?? [];
  const [agentId, setAgentId] = React.useState<string | undefined>(initialAgentId);
  const agent: ChatAgent | undefined = list.find((a) => a.id === agentId) ?? list[0];
  const [kbIds, setKbIds] = React.useState<string[] | null>(null);
  const chosenKbs = kbIds ?? agent?.defaultKbIds ?? [];

  return (
    <>
      <header className="flex min-h-12 items-center gap-2 border-b px-3 py-2">
        <RailButton onClick={onOpenRail} />
        <span className="px-1 text-sm font-semibold">New chat</span>
      </header>
      {agents.isPending ? (
        <div className="mx-auto w-full max-w-2xl space-y-4 p-6">
          <Skeleton className="mx-auto h-7 w-64" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : agents.isError ? (
        <div className="p-6">
          <QueryError what="agents" onRetry={() => agents.refetch()} retrying={agents.isFetching} />
        </div>
      ) : !agent ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState icon={Bot} title="No live agents to chat with" description="Chat uses an agent’s published version. Publish an agent, or ask its owner to, and it appears here." action={{ label: 'Open agents', href: '/agents' }} />
        </div>
      ) : (
        <>
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-5 overflow-y-auto px-4 py-8">
            <div className="space-y-1 text-center">
              <h2 className="text-xl font-semibold tracking-tight">What do you need?</h2>
              <p className="max-w-md text-sm text-muted-foreground">The agent answers from the knowledge bases below, looks up live data through its tools, and drafts actions for you to approve.</p>
            </div>
            <div className="flex w-full max-w-xl flex-col gap-3">
              <Select
                value={agent.id}
                onValueChange={(v) => {
                  setAgentId(v);
                  setKbIds(null);
                }}
              >
                <SelectTrigger className="h-auto w-full py-2" aria-label="Agent">
                  <SelectValue>
                    <span className="flex items-center gap-2 text-left">
                      <Bot className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {agent.name} <span className="font-normal text-muted-foreground">· v{agent.version}</span>
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">{agent.role}</span>
                      </span>
                    </span>
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {list.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      <span className="flex flex-col">
                        <span>
                          {a.name} <span className="text-muted-foreground">· v{a.version}</span>
                        </span>
                        <span className="text-xs text-muted-foreground">{a.role}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <KbChips kbs={kbs} value={chosenKbs} onChange={setKbIds} />
            </div>
            <div className="flex max-w-2xl flex-wrap justify-center gap-2">
              {agent.suggestions.map((s) => (
                <Button key={s} variant="outline" size="sm" className="h-auto py-1.5 text-left font-normal whitespace-normal" disabled={creating} onClick={() => onStart(agent.id, chosenKbs, s, [])}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
          <div className="mx-auto w-full max-w-3xl p-3">
            <Composer autoFocus placeholder={`Message ${agent.name}…`} streaming={creating} onStop={() => undefined} onSend={(text, files) => onStart(agent.id, chosenKbs, text, files)} />
            <p className="mt-1.5 hidden text-center text-[11px] text-muted-foreground sm:block">Enter to send, Shift+Enter for a new line. Actions the agent drafts wait for your approval.</p>
          </div>
        </>
      )}
    </>
  );
}

function ThreadView({
  threadId,
  query,
  live,
  me,
  kbs,
  agent,
  onOpenRail,
  editingTitle,
  titleDraft,
  setTitleDraft,
  setEditingTitle,
  onPatch,
  onArchive,
  onDelete,
  onCopy,
  onOpenDocument,
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
  onOpenRail: () => void;
  editingTitle: boolean;
  titleDraft: string;
  setTitleDraft: (s: string) => void;
  setEditingTitle: (b: boolean) => void;
  onPatch: (id: string, patch: ChatThreadPatch, done?: string) => void;
  onArchive: (t: ChatThread) => void;
  onDelete: (t: ChatThread) => void;
  onCopy: (text: string, what?: string) => void;
  onOpenDocument: (id: string) => void;
  onSend: (input: SendInput, cutFrom?: string) => void;
  onStop: () => void;
  onDismissFailed: () => void;
  onFeedback: (messageId: string, fb: MessageFeedback | null) => void;
  onWidgetAction: (messageId: string, widgetId: string, action: WidgetAction) => Promise<void>;
}) {
  const t = query.data && query.data.id === threadId ? query.data : undefined;
  const messages = visibleMessages(t, live);
  const streaming = !!live?.streaming;
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const lastLen = messages[messages.length - 1]?.content.length ?? 0;
  const widgetCount = messages.reduce((n, m) => n + (m.widgets?.length ?? 0) + (m.toolCalls?.length ?? 0), 0);
  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, lastLen, widgetCount, live?.phase]);

  const notFound = query.isError && (query.error as { status?: number }).status === 404;
  const owner = !!t && !!me && t.owner === me;
  const readOnly = !t || !owner || t.archived;
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');

  if (notFound)
    return (
      <>
        <header className="flex min-h-12 items-center gap-2 border-b px-3 py-2">
          <RailButton onClick={onOpenRail} />
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
        <RailButton onClick={onOpenRail} />
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
              <KbChips kbs={kbs} value={t.kbIds} onChange={(ids) => onPatch(t.id, { kbIds: ids }, 'Knowledge updated for the next answer')} disabled={readOnly} />
            </div>
          )}
        </div>
        {t && (
          <div className="flex items-center gap-1">
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
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-5">
            {messages.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">No messages yet. Ask something below.</p>}
            {messages.map((m) => {
              const isLive = !!live && m.id === live.assistant.id;
              if (m.role === 'user')
                return <UserMessage key={m.id} message={m} disabled={streaming || readOnly} onEdit={readOnly ? undefined : (text) => onSend({ content: text, edit: m.id }, m.id)} />;
              return (
                <AssistantMessage
                  key={m.id}
                  message={m}
                  streaming={isLive && streaming && !!m.content}
                  phaseLabel={isLive && streaming ? phaseLabel(live, t?.kbNames ?? []) : undefined}
                  readOnly={readOnly || isLive}
                  noAnswerHint={
                    t?.kbIds[0] && (
                      <Link href={`/knowledge/${t.kbIds[0]}?tab=playground`} className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                        See what retrieval found in the playground
                      </Link>
                    )
                  }
                  onOpenDocument={onOpenDocument}
                  onCopy={(text) => onCopy(text)}
                  onRegenerate={m.id === lastAssistant?.id && !streaming ? () => onSend({ content: '', regenerate: m.id }, m.id) : undefined}
                  onFeedback={(fb) => onFeedback(m.id, fb)}
                  onWidgetAction={(widgetId, action) => onWidgetAction(m.id, widgetId, action)}
                />
              );
            })}
            {live?.failed && (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Your message wasn’t sent</AlertTitle>
                <AlertDescription className="space-y-2">
                  <p>{live.failed.message}</p>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" onClick={() => onSend(live.failed!.input, live.cutFrom)}>
                      Retry
                    </Button>
                    <Button size="sm" variant="ghost" className="text-foreground" onClick={onDismissFailed}>
                      Dismiss
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {t && (
        <div className="mx-auto w-full max-w-3xl p-3">
          <Composer
            placeholder={`Message ${t.agentName}…`}
            streaming={streaming}
            onStop={onStop}
            onSend={(text, files) => onSend({ content: text, attachments: files.length ? files : undefined })}
            disabledReason={
              !owner ? (
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
