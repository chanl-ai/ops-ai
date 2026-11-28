'use client';

import * as React from 'react';
import { FlaskConical, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { type HeldTool, ShowSteps } from '@/components/agents/test-why';
import { ConnectorsPicker } from '@/components/chat/connectors-picker';
import { Composer } from '@/components/chat/composer';
import { ThreadMessages, visibleMessages } from '@/components/chat/thread-messages';
import { useThreadActions } from '@/components/chat/use-thread-actions';
import { DocumentPanel } from '@/components/knowledge/document-panel';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RetrievalTraceView } from '@/components/knowledge/retrieval-trace';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useChatThread, useCreateThread, useLiveTurn, useSendMessage } from '@/hooks/chat-queries';
import type { SendInput } from '@/lib/types/chat';
import type { RetrievalTrace } from '@/lib/types/knowledge-retrieval';

/**
 * The agent page's side panel: a real chat on a thread the server marks test, drawn with the chat page's own message
 * list and composer (slash for skills, attach, connectors), so a builder sees what a person chatting gets, on the newest
 * draft. Under each reply, Show steps says what the agent did to answer it.
 */
export function AgentTestPanel({
  agentId,
  agentName,
  held,
  threadId,
  onThreadIdChange,
  canTest,
}: {
  agentId: string;
  agentName: string;
  /** The tools the draft holds, for Show steps to name what a reply could have called and which pause. */
  held: HeldTool[];
  /** The test thread, kept by the page: crossing the stacked layout's breakpoint remounts the panel. */
  threadId?: string;
  onThreadIdChange: (id: string | undefined) => void;
  /** Whether the person may run test turns (the agent's edit cell, as agents-service checks). */
  canTest: boolean;
}) {
  const thread = useChatThread(threadId);
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  const create = useCreateThread();
  const actions = useThreadActions(threadId, thread);
  const [docId, setDocId] = React.useState<string | null>(null);
  const [docPage, setDocPage] = React.useState<number | undefined>();
  const [trace, setTrace] = React.useState<RetrievalTrace | null>(null);

  const t = thread.data && thread.data.id === threadId ? thread.data : undefined;
  const messages = visibleMessages(t, live);
  const streaming = !!live?.streaming;

  // One test chat per press: Connectors and the first message both ask for it, and a second ask while it is being made
  // gets the same one.
  const starting = React.useRef<Promise<string | undefined> | null>(null);
  const startThread = (): Promise<string | undefined> => {
    if (threadId) return Promise.resolve(threadId);
    starting.current ??= create
      .mutateAsync({ agentId, kbIds: [], test: true })
      .then((made) => (onThreadIdChange(made.id), made.id))
      .catch((e: unknown) => (toast.error('Couldn’t start the test', { description: (e as Error).message }), undefined))
      .finally(() => {
        starting.current = null;
      });
    return starting.current;
  };
  const send = async (input: SendInput) => {
    const id = await startThread();
    if (id) chat.send(id, input);
  };

  // At the large breakpoint the panel is as tall as the room under the page header and stays there while the settings
  // column scrolls: sticky at the offset it starts at, filling the rest of the scrolling area. Stacked, it keeps its minimum height.
  const root = React.useRef<HTMLDivElement>(null);
  const [fit, setFit] = React.useState<{ top: number; height: number } | null>(null);
  React.useLayoutEffect(() => {
    const anchor = root.current?.parentElement;
    let scroller: HTMLElement | null = anchor?.parentElement ?? null;
    while (scroller && !/(auto|scroll)/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement;
    if (!anchor || !scroller) return;
    const wide = window.matchMedia('(min-width: 1024px)');
    const measure = () => {
      if (!wide.matches) return setFit(null);
      const top = Math.max(0, Math.round(anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop));
      setFit({ top, height: Math.max(448, scroller.clientHeight - top - 16) });
    };
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(scroller);
    if (scroller.firstElementChild) watch.observe(scroller.firstElementChild);
    wide.addEventListener('change', measure);
    return () => {
      watch.disconnect();
      wide.removeEventListener('change', measure);
    };
  }, []);

  return (
    <div ref={root} style={fit ? { top: fit.top, height: fit.height } : undefined} className="flex min-h-[28rem] flex-col rounded-lg border bg-card lg:sticky" data-testid="agent-test-panel">
      {actions.stepUpDialog}
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
        <Badge variant="outline">
          <FlaskConical className="size-3" /> Test
        </Badge>
        <span className="min-w-0 flex-1">Newest draft · not counted or remembered</span>
        {threadId && (
          <Button variant="ghost" size="sm" className="shrink-0" disabled={streaming} onClick={() => onThreadIdChange(undefined)} data-testid="new-test">
            <RotateCcw className="size-4" /> New test
          </Button>
        )}
      </div>
      {!threadId ? (
        <div className="flex min-h-0 flex-1 flex-col justify-center">
          <EmptyState icon={FlaskConical} title={`Test ${agentName}`} description="Ask what a customer or a colleague would. Try a request that should pause for review." />
        </div>
      ) : thread.isError && !live ? (
        <div className="flex-1 p-3">
          <QueryError what="this test" onRetry={() => thread.refetch()} retrying={thread.isFetching} error={thread.error} />
        </div>
      ) : thread.isPending && !live ? (
        <div className="flex-1 space-y-3 p-3">
          <Skeleton className="ml-auto h-10 w-2/3" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : (
        <ThreadMessages
          threadId={threadId}
          messages={messages}
          live={live}
          kbIds={t?.kbIds ?? []}
          kbNames={t?.kbNames ?? []}
          readOnly={!t}
          owner
          archived={false}
          severalAgents={false}
          onSend={(input, cutFrom) => chat.send(threadId, input, cutFrom)}
          onDismissFailed={() => chat.dismiss(threadId)}
          onOpenDocument={(id, page) => (setDocId(id), setDocPage(page))}
          onOpenTrace={setTrace}
          onCopy={actions.copy}
          onFeedback={actions.onFeedback}
          onWidgetAction={actions.onWidgetAction}
          afterReply={(m) => (m.role === 'assistant' ? <ShowSteps message={m} held={held} /> : null)}
        />
      )}
      <div className="border-t p-2">
        <Composer
          draftKey={threadId ?? `test-${agentId}`}
          placeholder={`Message ${agentName}… Type / for a skill.`}
          streaming={streaming || create.isPending}
          onStop={() => threadId && chat.stop(threadId)}
          onSend={(text, files, skill) => void send({ content: text, attachments: files.length ? files : undefined, skill })}
          skillsFor={{ id: agentId, name: agentName }}
          footer={<ConnectorsPicker threadId={threadId} agentId={agentId} ensureThread={startThread} disabled={streaming || !canTest} />}
          disabledReason={canTest ? undefined : 'You can read this agent but not run tests on it.'}
        />
      </div>

      <DocumentPanel itemId={docId} page={docPage} onClose={() => setDocId(null)} onOpenItem={(id) => (setDocId(id), setDocPage(undefined))} />
      <DetailSheet open={!!trace} onOpenChange={(o) => !o && setTrace(null)} title="How this answer was found" description={trace ? `“${trace.question}”` : undefined} widthClass="sm:max-w-3xl" testId="test-trace-sheet">
        {trace && <RetrievalTraceView trace={trace} />}
      </DetailSheet>
    </div>
  );
}
