'use client';

import * as React from 'react';
import { FlaskConical, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { TestCompare } from '@/components/agents/test-compare';
import { type HeldTool, TestWhy } from '@/components/agents/test-why';
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useChatThread, useCreateThread, useLiveTurn, useSendMessage } from '@/hooks/chat-queries';
import type { AgentVersion } from '@/lib/types/domain';
import type { RetrievalTrace } from '@/lib/types/knowledge-retrieval';

export const TEST_TABS = ['test', 'why', 'compare', 'versions', 'used'] as const;
export type TestTab = (typeof TEST_TABS)[number];

/**
 * The agent page's right panel (c-285): Test is a real chat on a thread the server marks test (c-284), drawn with the
 * chat page's own message list, composer and cards, so a builder sees exactly what a person chatting gets, on the
 * newest draft. Why explains a reply, Compare asks two versions the same question (c-286); Versions and Used in hold
 * what the page's right column showed before.
 */
export function AgentTestPanel({
  agentId,
  agentName,
  kbNames,
  held,
  tab,
  onTabChange,
  threadId,
  onThreadIdChange,
  versions,
  usedIn,
  newestVersion,
  savedVersions,
}: {
  agentId: string;
  agentName: string;
  kbNames: Record<string, string>;
  /** The tools the draft holds, for Why to name what a reply could have called and which pause. */
  held: HeldTool[];
  tab: TestTab;
  onTabChange: (tab: TestTab) => void;
  /** The test thread, kept by the page: crossing the stacked layout's breakpoint remounts the panel. */
  threadId?: string;
  onThreadIdChange: (id: string | undefined) => void;
  versions: React.ReactNode;
  usedIn: React.ReactNode;
  /** The newest version and every saved one, for Compare (c-286). */
  newestVersion: number;
  savedVersions: AgentVersion[];
}) {
  const thread = useChatThread(threadId);
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  const create = useCreateThread();
  const actions = useThreadActions(threadId, thread);
  const [docId, setDocId] = React.useState<string | null>(null);
  const [docPage, setDocPage] = React.useState<number | undefined>();
  const [trace, setTrace] = React.useState<RetrievalTrace | null>(null);
  const [whyId, setWhyId] = React.useState<string>();

  const t = thread.data && thread.data.id === threadId ? thread.data : undefined;
  const messages = visibleMessages(t, live);
  const streaming = !!live?.streaming;
  const replies = messages.filter((m) => m.role === 'assistant' && !(live && m.id === live.assistant.id && streaming));
  const why = replies.find((m) => m.id === whyId) ?? replies[replies.length - 1];

  const send = async (text: string) => {
    let id = threadId;
    if (!id) {
      try {
        id = (await create.mutateAsync({ agentId, kbIds: [], test: true })).id;
        onThreadIdChange(id);
      } catch (e) {
        toast.error('Couldn’t start the test', { description: (e as Error).message });
        return;
      }
    }
    chat.send(id, { content: text });
  };

  return (
    <div className="flex min-h-[28rem] flex-col rounded-lg border bg-card lg:sticky lg:top-4 lg:h-[calc(100vh-17rem)]" data-testid="agent-test-panel">
      {actions.stepUpDialog}
      <Tabs value={tab} onValueChange={(v) => onTabChange(v as TestTab)} className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="overflow-x-auto border-b px-2 py-1.5">
          <TabsList>
            <TabsTrigger value="test" data-testid="test-tab">
              <FlaskConical className="size-4" /> Test
            </TabsTrigger>
            <TabsTrigger value="why" data-testid="why-tab">
              Why
            </TabsTrigger>
            <TabsTrigger value="compare" data-testid="compare-tab">
              Compare
            </TabsTrigger>
            <TabsTrigger value="versions">Versions</TabsTrigger>
            <TabsTrigger value="used">Used in</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="test" className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
            <Badge variant="outline">Test</Badge>
            <span className="min-w-0 flex-1">Newest draft · not counted or remembered</span>
            {threadId && (
              <Button variant="ghost" size="sm" className="shrink-0" disabled={streaming} onClick={() => (onThreadIdChange(undefined), setWhyId(undefined))} data-testid="new-test">
                <RotateCcw className="size-4" /> New test
              </Button>
            )}
          </div>
          {!threadId ? (
            <EmptyState icon={FlaskConical} title={`Test ${agentName}`} description="Ask what a customer or a colleague would. Try a request that should pause for review." />
          ) : thread.isError && !live ? (
            <div className="p-3">
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
              />
          )}
          <div className="border-t p-2">
            <Composer placeholder={`Message ${agentName}…`} streaming={streaming || create.isPending} onStop={() => threadId && chat.stop(threadId)} onSend={(text) => void send(text)} />
          </div>
        </TabsContent>

        <TabsContent value="why" className="min-h-0 flex-1 overflow-y-auto p-3">
          {why ? (
            <div className="flex flex-col gap-3">
              {replies.length > 1 && (
                <Select value={why.id} onValueChange={setWhyId}>
                  <SelectTrigger className="w-full" aria-label="Reply">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {replies.map((m, i) => (
                      <SelectItem key={m.id} value={m.id}>
                        Reply {i + 1}: {m.content.slice(0, 60) || '(no text)'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <TestWhy message={why} kbNames={kbNames} held={held} />
            </div>
          ) : (
            <p className="py-10 text-center text-sm text-muted-foreground">{streaming ? 'Why appears when the reply finishes.' : 'Send a test message to see what the agent searched, called and loaded to answer it.'}</p>
          )}
        </TabsContent>

        <TabsContent value="compare" className="flex min-h-0 flex-1 flex-col p-3">
          <TestCompare agentId={agentId} agentName={agentName} newest={newestVersion} versions={savedVersions} open={{ onOpenDocument: (id, page) => (setDocId(id), setDocPage(page)), onOpenTrace: setTrace }} />
        </TabsContent>

        <TabsContent value="versions" className="min-h-0 flex-1 overflow-y-auto p-3">
          {versions}
        </TabsContent>
        <TabsContent value="used" className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="flex flex-col gap-4">{usedIn}</div>
        </TabsContent>
      </Tabs>

      <DocumentPanel itemId={docId} page={docPage} onClose={() => setDocId(null)} onOpenItem={(id) => (setDocId(id), setDocPage(undefined))} />
      <DetailSheet open={!!trace} onOpenChange={(o) => !o && setTrace(null)} title="How this answer was found" description={trace ? `“${trace.question}”` : undefined} widthClass="sm:max-w-3xl" testId="test-trace-sheet">
        {trace && <RetrievalTraceView trace={trace} />}
      </DetailSheet>
    </div>
  );
}
