'use client';

import * as React from 'react';
import Link from 'next/link';

import { BudgetCard } from '@/components/chat/budget-card';
import { SendFailedAlert } from '@/components/chat/send-failed';
import { AssistantMessage, UserMessage } from '@/components/chat/message-view';
import { ChatConversation } from '@/components/shared/chat-blocks';
import { type LiveTurn, useAnswerBudget } from '@/hooks/chat-queries';
import { useCan } from '@/hooks/me-queries';
import type { ChatMessage, ChatThread, MessageFeedback, SendInput, WidgetAction } from '@/lib/types/chat';
import type { RetrievalTrace } from '@/lib/types/knowledge-retrieval';

export function phaseLabel(t: LiveTurn, kbNames: string[]) {
  if (t.assistant.content) return undefined;
  if (t.phase === 'retrieving') return `Searching ${kbNames.length ? kbNames.join(', ') : 'knowledge'}…`;
  if (t.phase === 'calling_tool') return 'Calling tools…';
  if (t.phase === 'writing') return 'Writing…';
  if (t.phase === 'checking') return 'Checking the answer…';
  return 'Thinking…';
}

/** Thread history with an in-flight turn spliced in: messages being replaced are hidden, the live ones appended. */
export function visibleMessages(thread: ChatThread | undefined, live: LiveTurn | undefined): ChatMessage[] {
  const base = thread?.messages ?? [];
  if (!live) return base;
  const cut = live.cutFrom ? base.findIndex((m) => m.id === live.cutFrom) : -1;
  const kept = (cut >= 0 ? base.slice(0, cut) : base).filter((m) => m.id !== live.userMessage?.id && m.id !== live.assistant.id);
  return [...kept, ...(live.userMessage ? [live.userMessage] : []), ...(live.failed ? [] : [live.assistant])];
}

/**
 * A thread's messages with its in-flight reply: the one renderer for every chat in the console, the chat page and an
 * agent's test panel alike, so a test shows exactly what a person chatting sees.
 */
export function ThreadMessages({
  threadId,
  messages,
  live,
  kbIds,
  kbNames,
  readOnly,
  owner,
  archived,
  severalAgents,
  onOpenMemory,
  onSend,
  onDismissFailed,
  onOpenDocument,
  onOpenTrace,
  onCopy,
  onFeedback,
  onWidgetAction,
}: {
  threadId: string;
  messages: ChatMessage[];
  live?: LiveTurn;
  kbIds: string[];
  kbNames: string[];
  readOnly: boolean;
  owner: boolean;
  archived: boolean;
  /** Replies name their agent once the conversation has had more than one (a handover, c-174). */
  severalAgents: boolean;
  onOpenMemory?: () => void;
  onSend: (input: SendInput, cutFrom?: string) => void;
  onDismissFailed: () => void;
  onOpenDocument: (id: string, page?: number) => void;
  onOpenTrace: (trace: RetrievalTrace) => void;
  onCopy: (text: string, what?: string) => void;
  onFeedback: (messageId: string, fb: MessageFeedback | null) => void;
  onWidgetAction: (messageId: string, widgetId: string, action: WidgetAction) => Promise<void>;
}) {
  const streaming = !!live?.streaming;
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
  const answerBudget = useAnswerBudget();
  // Raise is a team admin's (c-103); the server checks it again from the token.
  const canRaise = useCan('chat', 'manage') === true;
  return (
    <ChatConversation>
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
              phaseLabel={isLive && streaming ? phaseLabel(live, kbNames) : undefined}
              readOnly={readOnly || isLive}
              noAnswerHint={
                kbIds[0] && (
                  <Link href={`/knowledge/${kbIds[0]}?tab=playground`} className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                    See what retrieval found in the playground
                  </Link>
                )
              }
              onOpenDocument={onOpenDocument}
              onOpenTrace={onOpenTrace}
              onCopy={(text) => onCopy(text)}
              onRegenerate={m.id === lastAssistant?.id && !streaming ? () => onSend({ content: '', regenerate: m.id }, m.id) : undefined}
              onFeedback={(fb) => onFeedback(m.id, fb)}
              onWidgetAction={(widgetId, action) => onWidgetAction(m.id, widgetId, action)}
              onReply={streaming ? undefined : (text) => onSend({ content: text })}
              byline={severalAgents ? m.agentName : undefined}
              onOpenMemory={onOpenMemory}
              budgetCard={
                m.budget && (
                  <BudgetCard
                    pause={m.budget}
                    canContinue={owner && !archived && !streaming}
                    canRaise={canRaise && !streaming}
                    onAnswer={(answer) => answerBudget.mutateAsync({ threadId, answer })}
                  />
                )
              }
            />
          );
        })}
        {live?.failed && <SendFailedAlert message={live.failed.message} onRetry={() => onSend(live.failed!.input, live.cutFrom)} onDismiss={onDismissFailed} />}
    </ChatConversation>
  );
}
