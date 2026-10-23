'use client';

import * as React from 'react';
import { keepPreviousData, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import { IdleTimeout, withIdleTimeout } from '@/lib/api/idle';
import { modelRefusalText } from '@/lib/model-refusals';
import type { BudgetAnswer, ChatFilters, ChatMessage, ChatThreadListParams, ChatThreadInput, ChatThreadPatch, MessageFeedback, SendInput, WidgetAction } from '@/lib/types/chat';
import type { ListParams } from '@/lib/types/query';
import { teamKey, useTeamInfiniteQuery, useTeamQuery } from './team-query';

/** Every chat key starts with 'chat', so one invalidation refreshes the rail, the table and the open thread. */
export const ck = {
  agents: ['chat', 'agents'] as const,
  threads: (p: unknown) => ['chat', 'threads', p] as const,
  rail: (p: unknown) => ['chat', 'rail', p] as const,
  thread: (id: string) => ['chat', 'thread', id] as const,
};

export const useChatAgents = () => useTeamQuery({ queryKey: ck.agents, queryFn: api.chat.agents, staleTime: 60_000 });
export const useChatThreads = (p: ListParams<ChatFilters>) => usePagedQuery({ queryKey: ck.threads(p), queryFn: () => api.chat.threads.list(p) });
/** The rail: the first page, then one more page per `fetchNextPage`, each after the last row's cursor. */
export const useChatThreadPages = (p: Omit<ChatThreadListParams, 'page' | 'cursor'>) =>
  useTeamInfiniteQuery({
    queryKey: ck.rail(p),
    queryFn: ({ pageParam }) => api.chat.threads.list({ ...p, page: 1, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
export const useChatThread = (id: string | undefined) => useTeamQuery({ queryKey: ck.thread(id ?? ''), queryFn: () => api.chat.threads.get(id!), enabled: !!id });

function useWrite<A, R>(fn: (a: A) => Promise<R>, alsoRoots: string[] = []) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(['chat', ...alsoRoots].map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

export const useCreateThread = () => useWrite((i: ChatThreadInput) => api.chat.threads.create(i));
export const useUpdateThread = () => useWrite(({ id, patch }: { id: string; patch: ChatThreadPatch }) => api.chat.threads.update(id, patch));
export const useDeleteThread = () => useWrite((id: string) => api.chat.threads.remove(id));
export const useBulkUpdateThreads = () => useWrite(({ ids, patch }: { ids: string[]; patch: Pick<ChatThreadPatch, 'pinned' | 'archived'> }) => api.chat.threads.bulkUpdate(ids, patch));
export const useBulkDeleteThreads = () => useWrite((ids: string[]) => api.chat.threads.bulkRemove(ids));
export const useMessageFeedback = () =>
  useWrite(({ threadId, messageId, feedback }: { threadId: string; messageId: string; feedback: MessageFeedback | null }) => api.chat.feedback(threadId, messageId, feedback));
/**
 * Approving or rejecting from a chat card is a decision on the review, made through Reviews' own route (the review id
 * is the thread id), so the chat, the Reviews queue and the overview counts all refresh.
 */
export const useDecideFromChat = () =>
  useWrite(
    ({ threadId, decision, reason, stepUpToken }: { threadId: string; decision: 'approved' | 'rejected'; reason?: string; stepUpToken?: string }) =>
      api.reviews.decide(threadId, { decision, reason, stepUpToken }),
    ['reviews', 'overview'],
  );
/** Form widgets submit through the chat route; approvals use `useDecideFromChat`. */
export const useWidgetAction = () =>
  useWrite(
    ({ threadId, messageId, widgetId, action }: { threadId: string; messageId: string; widgetId: string; action: WidgetAction }) => api.chat.widgetAction(threadId, messageId, widgetId, action),
    ['reviews', 'overview'],
  );

/** Continue or raise a spent conversation budget (c-103); the server checks who may do which. */
export const useAnswerBudget = () => useWrite(({ threadId, answer }: { threadId: string; answer: BudgetAnswer }) => api.chat.budget(threadId, answer));

// ── Streaming replies ──
// A reply in flight lives outside React, keyed by thread, so it keeps streaming when the person moves from
// /chat to /chat/[id] or opens another conversation, and the rail can show which threads are still answering.

export type LivePhase = 'sending' | 'thinking' | 'retrieving' | 'calling_tool' | 'writing' | 'checking';

export interface LiveTurn {
  threadId: string;
  /** Messages from this id on are being replaced (edit or regenerate) and are hidden while the turn runs. */
  cutFrom?: string;
  userMessage?: ChatMessage;
  assistant: ChatMessage;
  phase: LivePhase;
  streaming: boolean;
  /** The request failed before the server stored anything; the typed message is kept so it can be resent. */
  failed?: { message: string; input: SendInput };
}

let turns: Record<string, LiveTurn> = {};
const controllers: Record<string, AbortController> = {};
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
function patch(threadId: string, fn: (t: LiveTurn) => LiveTurn) {
  const t = turns[threadId];
  if (!t) return;
  turns = { ...turns, [threadId]: fn(t) };
  emit();
}
function clear(threadId: string) {
  const { [threadId]: _, ...rest } = turns;
  turns = rest;
  emit();
}

// The longest a reply may go without any event (text, status, tool) before the page says it failed: tool calls
// and checks send status events, so only a stalled turn reaches this.
const REPLY_IDLE_MS = 120_000;
async function run(qc: QueryClient, threadId: string, input: SendInput, cutFrom?: string) {
  controllers[threadId]?.abort();
  const ctrl = new AbortController();
  controllers[threadId] = ctrl;
  const at = new Date().toISOString();
  turns = {
    ...turns,
    [threadId]: {
      threadId,
      cutFrom,
      userMessage: input.regenerate ? undefined : { id: input.edit ?? 'pending-user', role: 'user', content: input.content, at, attachments: input.attachments },
      assistant: { id: 'pending-assistant', role: 'assistant', content: '', at },
      phase: 'sending',
      streaming: true,
    },
  };
  emit();
  let started = false;
  // A reply ends with `done` or `error`. A stream that stops without either dropped mid-reply (proxy, network, server).
  let ended = false;
  let messageId: string | undefined;
  try {
    for await (const ev of withIdleTimeout(api.chat.send(threadId, input, ctrl.signal), REPLY_IDLE_MS)) {
      if (ev.type === 'done' || ev.type === 'error') ended = true;
      if (ev.type === 'start') {
        messageId = ev.messageId;
        started = true;
        patch(threadId, (t) => ({ ...t, userMessage: ev.userMessage ?? t.userMessage, assistant: { ...t.assistant, id: ev.messageId }, phase: 'thinking' }));
      } else if (ev.type === 'status') patch(threadId, (t) => ({ ...t, phase: ev.phase }));
      else if (ev.type === 'tool_start') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, toolCalls: [...(t.assistant.toolCalls ?? []), ev.call] } }));
      else if (ev.type === 'tool_end') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, toolCalls: (t.assistant.toolCalls ?? []).map((c) => (c.id === ev.call.id ? ev.call : c)) } }));
      else if (ev.type === 'widget') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, widgets: [...(t.assistant.widgets ?? []), ev.widget] } }));
      else if (ev.type === 'part') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, parts: [...(t.assistant.parts ?? []), ev.part] } }));
      else if (ev.type === 'text') patch(threadId, (t) => ({ ...t, phase: 'writing', assistant: { ...t.assistant, content: t.assistant.content + ev.delta } }));
      else if (ev.type === 'replace') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, content: ev.text } }));
      else if (ev.type === 'citations') patch(threadId, (t) => ({ ...t, assistant: { ...t.assistant, citations: ev.citations } }));
      else if (ev.type === 'done') patch(threadId, (t) => ({ ...t, assistant: ev.message }));
      else if (ev.type === 'error') patch(threadId, (t) => ({ ...t, assistant: { ...ev.partial, error: modelRefusalText(ev.code) ?? ev.message } }));
    }
  } catch (e) {
    if (e instanceof IdleTimeout) {
      // The server went quiet without ending the reply: say so and offer to send again, rather than "Thinking" forever.
      ctrl.abort();
      patch(threadId, (t) => ({ ...t, streaming: false, failed: { message: `No reply after ${Math.round(REPLY_IDLE_MS / 60_000)} minutes. The agent may be busy; send it again.`, input } }));
      await qc.invalidateQueries({ queryKey: ['chat'] });
      return;
    }
    if (!ctrl.signal.aborted && !started) {
      patch(threadId, (t) => ({ ...t, streaming: false, failed: { message: (e as Error).message, input } }));
      return;
    }
  } finally {
    if (controllers[threadId] === ctrl) delete controllers[threadId];
  }
  if (started && !ended && !ctrl.signal.aborted) {
    // Dropped mid-reply: keep the server's copy if it stored one, otherwise offer to send again.
    patch(threadId, (t) => ({ ...t, streaming: false }));
    await qc.invalidateQueries({ queryKey: ['chat'] });
    const stored = qc.getQueryData<{ messages?: { id: string }[] }>(teamKey(ck.thread(threadId)))?.messages?.some((m) => m.id === messageId);
    if (!stored) {
      patch(threadId, (t) => ({ ...t, failed: { message: 'The connection dropped before the reply finished. Nothing was lost on your side; send it again.', input } }));
      return;
    }
    if (!controllers[threadId]) clear(threadId);
    return;
  }
  // The server stored the turn (finished, stopped or failed part-way); show its copy, then drop the live one.
  patch(threadId, (t) => ({ ...t, streaming: false }));
  await qc.invalidateQueries({ queryKey: ['chat'] });
  if (!controllers[threadId]) clear(threadId);
}

/** The reply streaming into a thread, if any. */
export function useLiveTurn(threadId: string | undefined) {
  return React.useSyncExternalStore(
    subscribe,
    () => (threadId ? turns[threadId] : undefined),
    () => undefined,
  );
}

const streamingIds = () => Object.values(turns).filter((t) => t.streaming).map((t) => t.threadId).join(',');
/** Threads with a reply in flight, for the rail's activity dots. */
export function useStreamingThreadIds() {
  const ids = React.useSyncExternalStore(subscribe, streamingIds, () => '');
  return React.useMemo(() => new Set(ids ? ids.split(',') : []), [ids]);
}

/** Stops every reply in flight; the chat pages call it when the person leaves chat altogether. */
export const abortAllReplies = () => Object.values(controllers).forEach((c) => c.abort());

export function useSendMessage() {
  const qc = useQueryClient();
  return React.useMemo(
    () => ({
      send: (threadId: string, input: SendInput, cutFrom?: string) => void run(qc, threadId, input, cutFrom),
      stop: (threadId: string) => controllers[threadId]?.abort(),
      dismiss: (threadId: string) => clear(threadId),
    }),
    [qc],
  );
}

/** The agent the team's new chats start on (c-174). */
export const useDefaultAgent = () => useTeamQuery({ queryKey: ['chat', 'default-agent'], queryFn: api.chat.defaultAgent.get, staleTime: 60_000 });
/** Whether agents-service lets the person change the default: the console offers the control only then. */
export const useCanSetDefaultAgent = () => useDefaultAgent().data?.canChange === true;
/** A team admin's: new chats start on `agentId` from now on. */
export const useSetDefaultAgent = () => useWrite((agentId: string) => api.chat.defaultAgent.set(agentId));
