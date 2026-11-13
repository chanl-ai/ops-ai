'use client';

import * as React from 'react';
import Link from 'next/link';
import { Sparkles } from 'lucide-react';

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

const HOW: Record<string, string> = { picked: 'picked by you', carried: 'carried from the reply before', loaded: 'loaded for this question', always: 'always on' };

/** Which skills a reply used and how each came in; always-on skills are left to the reply's details. */
export function UsedSkills({ skills }: { skills: NonNullable<ChatMessage['skills']> }) {
  const shown = skills.filter((s) => s.how !== 'always' && s.matched !== 'Always on');
  if (!shown.length) return null;
  return (
    <ul className="flex flex-col gap-1 text-xs text-muted-foreground" data-testid="used-skills">
      {shown.map((s) => (
        <li key={`${s.skillId}/${s.part ?? ''}`} className="flex min-w-0 items-center gap-1.5">
          <Sparkles className="size-3 shrink-0" />
          <span className="truncate">
            Used skill <span className="font-medium text-foreground">{s.name}</span>
            {s.part ? ` · ${s.part.replace(/-/g, ' ')}` : ''} v{s.version}
            {s.how ? `, ${HOW[s.how]}` : ''}
            {s.inputs && Object.keys(s.inputs).length ? ` · ${Object.entries(s.inputs).map(([k, v]) => `${k}: ${v}`).join(' · ')}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
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
  /** Replies name their agent once the conversation has had more than one (a handover). */
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
  // Raise is a team admin's; the server checks it again from the token.
  const canRaise = useCan('chat', 'manage') === true;
  return (
    <ChatConversation>
        {messages.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">No messages yet. Ask something below.</p>}
        {messages.map((m, i) => {
          const isLive = !!live && m.id === live.assistant.id;
          if (m.role === 'user') {
            // The reply records the skill this message picked from the / menu.
            const picked = messages[i + 1]?.skills?.find((s) => s.how === 'picked');
            return (
              <UserMessage
                key={m.id}
                message={m}
                skill={picked && (picked.part ? `${picked.name} · ${picked.part.replace(/-/g, ' ')}` : picked.name)}
                disabled={streaming || readOnly}
                onEdit={readOnly ? undefined : (text) => onSend({ content: text, edit: m.id }, m.id)}
              />
            );
          }
          return (
            <React.Fragment key={m.id}>
            {m.skills?.length ? <UsedSkills skills={m.skills} /> : null}
            <AssistantMessage
              message={m}
              streaming={isLive && streaming && !!m.content}
              phaseLabel={isLive && streaming ? phaseLabel(live, kbNames) : undefined}
              readOnly={readOnly || isLive}
              noAnswerHint={
                kbIds[0] && (
                  <Link href={`/data/knowledge/${kbIds[0]}?tab=playground`} className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
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
              followUps={m.id === lastAssistant?.id ? m.followUps : undefined}
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
            </React.Fragment>
          );
        })}
        {live?.failed && <SendFailedAlert message={live.failed.message} onRetry={() => onSend(live.failed!.input, live.cutFrom)} onDismiss={onDismissFailed} />}
    </ChatConversation>
  );
}
