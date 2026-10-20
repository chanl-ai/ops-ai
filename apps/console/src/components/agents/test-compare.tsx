'use client';

import * as React from 'react';
import { GitCompare } from 'lucide-react';
import { toast } from 'sonner';

import { Composer } from '@/components/chat/composer';
import { ThreadMessages, visibleMessages } from '@/components/chat/thread-messages';
import { useThreadActions } from '@/components/chat/use-thread-actions';
import { EmptyState } from '@/components/shared/empty-state';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useChatThread, useCreateThread, useLiveTurn, useSendMessage } from '@/hooks/chat-queries';
import type { AgentVersion } from '@/lib/types/domain';
import type { RetrievalTrace } from '@/lib/types/knowledge-retrieval';

/** The panel's own document viewer and trace sheet, so a compare's citations open where Test's do. */
interface Openers {
  onOpenDocument: (id: string, page?: number) => void;
  onOpenTrace: (trace: RetrievalTrace) => void;
}

/** One side of a compare: a test thread on one version, drawn with the chat page's message list and its spend. */
function Side({ label, threadId, open }: { label: string; threadId?: string; open: Openers }) {
  const thread = useChatThread(threadId);
  const live = useLiveTurn(threadId);
  const chat = useSendMessage();
  const actions = useThreadActions(threadId, thread);
  const t = thread.data && thread.data.id === threadId ? thread.data : undefined;
  const messages = visibleMessages(t, live);
  const reply = [...messages].reverse().find((m) => m.role === 'assistant');
  return (
    <section className="flex min-w-0 flex-1 flex-col rounded-md border" aria-label={label} data-testid="compare-side">
      {actions.stepUpDialog}
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs">
        <Badge variant="outline">{label}</Badge>
        {reply?.usage && (
          <span className="text-muted-foreground" data-testid="compare-spent">
            {reply.usage.inputTokens + reply.usage.outputTokens} tokens · {reply.usage.cost}
            {reply.usage.seconds != null ? ` · ${reply.usage.seconds} s` : ''}
          </span>
        )}
      </div>
      {threadId ? (
        <ThreadMessages
          threadId={threadId}
          messages={messages}
          live={live}
          kbIds={t?.kbIds ?? []}
          kbNames={t?.kbNames ?? []}
          readOnly
          owner
          archived={false}
          severalAgents={false}
          onSend={(input, cutFrom) => chat.send(threadId, input, cutFrom)}
          onDismissFailed={() => chat.dismiss(threadId)}
          onOpenDocument={open.onOpenDocument}
          onOpenTrace={open.onOpenTrace}
          onCopy={actions.copy}
          onFeedback={actions.onFeedback}
          onWidgetAction={actions.onWidgetAction}
        />
      ) : null}
    </section>
  );
}

/**
 * Compare (c-286): one question asked of the newest draft and of a saved version, each on its own test thread, with
 * each reply's tokens, cost and seconds beside it. Nothing is counted or remembered, as in Test.
 */
export function TestCompare({ agentId, agentName, newest, versions, open }: { agentId: string; agentName: string; newest: number; versions: AgentVersion[]; open: Openers }) {
  const others = versions.filter((v) => v.version !== newest);
  const [against, setAgainst] = React.useState<number | undefined>(others.find((v) => v.state === 'published')?.version ?? others[0]?.version);
  const [threads, setThreads] = React.useState<{ draft?: string; other?: string }>({});
  const create = useCreateThread();
  const chat = useSendMessage();

  const ask = async (text: string) => {
    if (against === undefined) return;
    try {
      const [draft, other] = await Promise.all([
        create.mutateAsync({ agentId, kbIds: [], test: true }),
        create.mutateAsync({ agentId, kbIds: [], test: true, testVersion: against }),
      ]);
      setThreads({ draft: draft.id, other: other.id });
      chat.send(draft.id, { content: text });
      chat.send(other.id, { content: text });
    } catch (e) {
      toast.error('Couldn’t start the compare', { description: (e as Error).message });
    }
  };

  if (!others.length) {
    return <EmptyState icon={GitCompare} title="Nothing to compare yet" description={`${agentName} has one version. Save a change to compare the draft with it.`} />;
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="shrink-0">Newest v{newest} against</span>
        <Select value={against !== undefined ? String(against) : undefined} onValueChange={(v) => setAgainst(Number(v))}>
          <SelectTrigger className="h-8 w-auto" aria-label="Version to compare with" data-testid="compare-version">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {others.map((v) => (
              <SelectItem key={v.version} value={String(v.version)}>
                v{v.version}
                {v.state === 'published' ? ' (published)' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {threads.draft ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
          <Side label={`v${newest} (newest)`} threadId={threads.draft} open={open} />
          <Side label={`v${against}`} threadId={threads.other} open={open} />
        </div>
      ) : (
        <EmptyState icon={GitCompare} title="Ask both versions" description="The same question goes to each version on its own test thread." />
      )}
      <Composer placeholder={`Ask v${newest} and v${against ?? '?'}…`} streaming={create.isPending} onStop={() => undefined} onSend={(text) => void ask(text)} />
    </div>
  );
}
