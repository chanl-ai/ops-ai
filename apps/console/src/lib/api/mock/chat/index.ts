import type { ChatApi } from '@/lib/api/chat-contract';
import type { OpsApi } from '@/lib/api/contract';
import { ApiError } from '@/lib/api/contract';
import type { KnowledgeApi } from '@/lib/api/knowledge-contract';
import type { ApprovalState, ApprovalWidget, ChatMessage, ChatStreamEvent, ChatThread, ChatThreadRow, ChatWidget } from '@/lib/types/chat';
import type { Agent, Review } from '@/lib/types/domain';
import type { PlaygroundAnswer } from '@/lib/types/knowledge';

import { defaultRetrieval, playgroundAnswers } from '../knowledge/seed-kbs';
import { bulk, id, list, mode, notFound, respond } from '../runtime';
import { guardTeam, inTeam } from '../teams';
import { GENERAL_SUGGESTIONS, SUGGESTIONS, planTurn, type QueueSla, type TurnPlan } from './scripts';

const ALL = { page: 1, pageSize: 100 };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const NEW_TITLE = 'New chat';

/**
 * `?chat=fail-next` makes the next reply stop part-way with an error, so the partial-reply state can be reviewed
 * while every other request still succeeds.
 */
function takeFailNext() {
  if (typeof window === 'undefined') return false;
  try {
    if (new URLSearchParams(window.location.search).get('chat') === 'fail-next') sessionStorage.setItem('ops-mock-chat-fail', '1');
    const on = sessionStorage.getItem('ops-mock-chat-fail') === '1';
    sessionStorage.removeItem('ops-mock-chat-fail');
    return on;
  } catch {
    return false;
  }
}

function assemble(plan: TurnPlan, grounded?: PlaygroundAnswer): Pick<ChatMessage, 'content' | 'toolCalls' | 'widgets' | 'citations' | 'noAnswer'> {
  const toolCalls = plan.steps.map((s) => ({ ...s.call, id: id('tc'), status: 'success' as const }));
  const widgets = plan.steps.flatMap((s) => s.widgets);
  return {
    content: grounded ? grounded.answer : plan.text,
    citations: grounded?.citations.length ? grounded.citations : undefined,
    noAnswer: grounded?.noAnswer || undefined,
    toolCalls: toolCalls.length ? toolCalls : undefined,
    widgets: widgets.length ? widgets : undefined,
  };
}

const approvalState = (r: Review): ApprovalState =>
  r.status === 'approved' ? 'approved' : r.status === 'rejected' || r.status === 'returned' ? 'rejected' : r.approvals.length ? 'awaiting_second' : 'pending';

type Deps = {
  knowledge: KnowledgeApi;
  /** Agents people may chat with: live ones only. */
  agents: () => Pick<Agent, 'id' | 'name' | 'role' | 'version' | 'model' | 'collections'>[];
  /** Owner of an agent; conversations and the agent picker follow the current team through it. */
  agentOwner: (agentId: string) => string | undefined;
  /** The review flow; approval widgets decide their review through it. */
  reviews: () => OpsApi['reviews'];
  me: string;
  /** Per-queue SLA figures from the cases backend, so chat and the Cases page agree. */
  slaByQueue: () => QueueSla[];
};

export function createChatMock(deps: Deps): ChatApi {
  const answer = (pid: string) => playgroundAnswers.find((a) => a.id === pid);
  const seed = (
    tid: string,
    title: string,
    agentId: string,
    kbIds: string[],
    minutes: number,
    question: string,
    opts: { grounded?: string; owner?: string; pinned?: boolean; archived?: boolean; feedback?: ChatMessage['feedback'] } = {},
  ): ChatThread => {
    const a = deps.agents().find((x) => x.id === agentId);
    const at = minsAgo(minutes);
    const fresh = planTurn(question, { attachments: [], reviewers: 'Card Disputes', sla: deps.slaByQueue() });
    const plan = { ...fresh, steps: fresh.steps.map((s) => ({ ...s, widgets: s.widgets.map((w) => ({ ...w, asOf: at })) })) };
    const messages: ChatMessage[] = [
      { id: `${tid}_u1`, role: 'user', content: question, at },
      { id: `${tid}_a1`, role: 'assistant', at, feedback: opts.feedback, ...assemble(plan, opts.grounded ? answer(opts.grounded) : undefined) },
    ];
    return {
      id: tid,
      title,
      agentId,
      agentName: a?.name ?? agentId,
      agentVersion: a?.version ?? 1,
      kbIds,
      kbNames: [],
      pinned: !!opts.pinned,
      archived: !!opts.archived,
      owner: opts.owner ?? deps.me,
      createdAt: at,
      lastMessageAt: at,
      messageCount: messages.length,
      messages,
    };
  };

  const threads: ChatThread[] = [
    seed('th_sla', 'Breaching SLA cases by queue', 'ag_dispute', ['kb_legal'], 25, 'Show breaching SLA cases by queue', { pinned: true }),
    seed('th_dispute', 'Dispute REV-3020 provisional credit', 'ag_dispute', ['kb_legal'], 48, 'Summarise dispute REV-3020 and draft the credit'),
    seed('th_wire', 'New-payee wire hold rule', 'ag_fraud', ['kb_people', 'kb_eng'], 60 * 3, 'What is our new-payee wire hold rule?', { grounded: 'pa_newpayee', feedback: { rating: 'up' }, pinned: true }),
    seed('th_kyc', 'KYC refresh for Daniel Okoye', 'ag_kyb', ['kb_eng'], 60 * 26, 'Open a KYC refresh request for Daniel Okoye'),
    seed('th_week', 'Case volume this week', 'ag_dispute', ['kb_legal'], 60 * 24 * 3, 'How are we doing this week?'),
    seed('th_fee', 'Annual card fee refunds', 'ag_branch', ['kb_support'], 60 * 24 * 5, 'What is the refund window for an annual card fee?', { grounded: 'pa_card_fee' }),
    seed('th_halifax', 'Halifax wire cut-off', 'ag_branch', ['kb_support'], 60 * 24 * 9, 'What is the wire cut-off time at the Halifax branch?', {
      grounded: 'pa_noanswer',
      feedback: { rating: 'down', reason: 'Missing from the knowledge base' },
    }),
    seed('th_retention', 'Due diligence record retention', 'ag_kyb', ['kb_eng'], 60 * 24 * 12, 'How long do we keep customer due diligence records?', { grounded: 'pa_retention', archived: true }),
    seed('th_fees', 'Business loan origination fee', 'ag_loan', ['kb_lending'], 60 * 24 * 20, 'What is the origination fee on a small business loan over $250k?', { grounded: 'pa_fees' }),
    seed('th_maya', 'Wire release authority', 'ag_fraud', ['kb_people'], 60 * 30, 'What is our new-payee wire hold rule?', { grounded: 'pa_newpayee', owner: 'Maya Okafor' }),
    seed('th_anika', 'Queue breaches for the stand-up', 'ag_dispute', ['kb_legal'], 60 * 24 * 4, 'Show breaching SLA cases by queue', { owner: 'Anika Singh' }),
  ];

  const kbNameMap = async () => {
    try {
      const res = await deps.knowledge.kbs.list(ALL);
      return new Map(res.data.map((k) => [k.id, k.name]));
    } catch {
      return new Map<string, string>();
    }
  };
  const named = (t: ChatThread, names: Map<string, string>): ChatThread => ({ ...t, kbNames: t.kbIds.map((k) => names.get(k) ?? k) });
  const row = (t: ChatThread, names: Map<string, string>): ChatThreadRow => {
    const { messages, ...rest } = named(t, names);
    const last = [...messages].reverse().find((m) => m.content);
    return {
      ...rest,
      messageCount: messages.length,
      preview: (last?.content ?? '').replace(/\[\^?\d+\]|\*\*/g, '').slice(0, 140),
      widgets: messages.reduce((n, m) => n + (m.widgets?.length ?? 0), 0),
      citations: messages.reduce((n, m) => n + (m.citations?.length ?? 0), 0),
    };
  };
  const threadOr404 = (tid: string) => threads.find((t) => t.id === tid) ?? notFound('Conversation');
  const stateOf = (t: Pick<ChatThread, 'archived' | 'pinned'>) => (t.archived ? 'archived' : t.pinned ? 'pinned' : 'active');
  const touch = (t: ChatThread) => {
    t.lastMessageAt = new Date().toISOString();
    t.messageCount = t.messages.length;
  };

  /** Brings approval widgets in line with their reviews, which may have been decided in the Reviews queue. */
  async function syncApprovals(t: ChatThread) {
    const widgets = t.messages.flatMap((m) => m.widgets ?? []).filter((w): w is ApprovalWidget => w.kind === 'approval' && (w.state === 'pending' || w.state === 'awaiting_second'));
    await Promise.all(
      widgets.map(async (w) => {
        try {
          const r = await deps.reviews().get(w.reviewId);
          w.state = approvalState(r);
          if (r.decidedAt) Object.assign(w, { decidedBy: r.assignee, reason: r.decisionReason });
        } catch {
          // Keep the last known state when the review cannot be read.
        }
      }),
    );
  }

  function findWidget(tid: string, mid: string, wid: string) {
    const msg = threadOr404(tid).messages.find((m) => m.id === mid) ?? notFound('Message');
    return (msg.widgets ?? []).find((w) => w.id === wid) ?? notFound('Widget');
  }

  return {
    agents: async () => {
      const names = await kbNameMap();
      const byName = new Map([...names].map(([k, v]) => [v, k]));
      return respond((m) =>
        m === 'empty'
          ? []
          : deps.agents().filter((a) => inTeam(deps.agentOwner(a.id))).map((a) => ({
              id: a.id,
              name: a.name,
              role: a.role,
              version: a.version,
              model: a.model,
              defaultKbIds: a.collections.map((c) => byName.get(c)).filter((x): x is string => !!x),
              suggestions: SUGGESTIONS[a.id] ?? GENERAL_SUGGESTIONS,
            })),
      );
    },

    threads: {
      list: async (p) => {
        const names = await kbNameMap();
        return respond((m) => {
          const sorted = threads.filter((t) => inTeam(deps.agentOwner(t.agentId))).sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
          return list(
            sorted.map((t) => row(t, names)),
            p,
            {
              text: (t) => `${t.title} ${t.preview} ${t.agentName}`,
              value: (t, k) => (k === 'state' ? stateOf(t) : k === 'kbIds' ? t.kbIds : String((t as unknown as Record<string, unknown>)[k])),
              facetKeys: ['agentId', 'kbIds', 'state', 'owner'],
            },
            m,
          );
        });
      },
      get: async (tid) => {
        const t = threads.find((x) => x.id === tid);
        if (t) await syncApprovals(t);
        const names = await kbNameMap();
        return respond(() => {
          const found = threadOr404(tid);
          guardTeam(deps.agentOwner(found.agentId), 'conversation');
          return named(found, names);
        });
      },
      create: async (input) => {
        const names = await kbNameMap();
        return respond(() => {
          const a = deps.agents().find((x) => x.id === input.agentId);
          if (!a) throw new ApiError('That agent is not live, so it cannot be chatted with.', 422);
          const unknown = input.kbIds.filter((k) => !names.has(k));
          if (unknown.length) throw new ApiError(`Knowledge base ${unknown[0]} does not exist or you cannot read it.`, 422);
          const now = new Date().toISOString();
          const t: ChatThread = { id: id('th'), title: input.title?.trim() || NEW_TITLE, agentId: a.id, agentName: a.name, agentVersion: a.version, kbIds: input.kbIds, kbNames: [], pinned: false, archived: false, owner: deps.me, createdAt: now, lastMessageAt: now, messageCount: 0, messages: [] };
          threads.unshift(t);
          return named(t, names);
        });
      },
      update: async (tid, patch) => {
        const names = await kbNameMap();
        return respond(() => {
          const t = threadOr404(tid);
          if (patch.title !== undefined && !patch.title.trim()) throw new ApiError('A conversation needs a title.', 400);
          if (patch.kbIds?.some((k) => !names.has(k))) throw new ApiError('One of those knowledge bases does not exist.', 422);
          Object.assign(t, { ...patch, title: patch.title?.trim() ?? t.title });
          return named(t, names);
        });
      },
      remove: (tid) =>
        respond(() => {
          const i = threads.findIndex((t) => t.id === tid);
          if (i < 0) notFound('Conversation');
          threads.splice(i, 1);
        }),
      bulkUpdate: (ids, patch) =>
        respond(() =>
          bulk(ids, (tid) => {
            const t = threads.find((x) => x.id === tid);
            if (!t) return 'Not found';
            if (t.owner !== deps.me) return 'Owned by someone else';
            if (patch.pinned !== undefined && t.pinned === patch.pinned && patch.archived === undefined) return patch.pinned ? 'Already pinned' : 'Not pinned';
            if (patch.archived !== undefined && t.archived === patch.archived) return patch.archived ? 'Already archived' : 'Not archived';
            Object.assign(t, patch, patch.archived ? { pinned: false } : {});
          }),
        ),
      bulkRemove: (ids) =>
        respond(() =>
          bulk(ids, (tid) => {
            const i = threads.findIndex((x) => x.id === tid);
            if (i < 0) return 'Not found';
            if (threads[i].owner !== deps.me) return 'Owned by someone else';
            threads.splice(i, 1);
          }),
        ),
    },

    async *send(tid, input, signal): AsyncIterable<ChatStreamEvent> {
      const m = mode();
      await sleep(m === 'slow' ? 1500 : 150);
      if (m === 'error') throw new ApiError('The chat service is unavailable (503). Mock outage.', 503);
      const failPart = takeFailNext();
      const t = threadOr404(tid);
      if (t.owner !== deps.me) throw new ApiError('Only the owner can continue this conversation.', 403);
      if (!input.content.trim() && !input.regenerate) throw new ApiError('Type a message first.', 400);
      const now = () => new Date().toISOString();

      let question = input.content.trim();
      let userMessage: ChatMessage | undefined;
      if (input.regenerate) {
        const i = t.messages.findIndex((x) => x.id === input.regenerate);
        if (i < 0) notFound('Message');
        question = [...t.messages.slice(0, i)].reverse().find((x) => x.role === 'user')?.content ?? '';
        t.messages.splice(i);
      } else if (input.edit) {
        const i = t.messages.findIndex((x) => x.id === input.edit);
        if (i < 0) notFound('Message');
        const prior = t.messages[i];
        t.messages.splice(i);
        userMessage = { id: prior.id, role: 'user', content: question, at: now(), attachments: input.attachments };
        t.messages.push(userMessage);
      } else {
        userMessage = { id: id('m'), role: 'user', content: question, at: now(), attachments: input.attachments?.length ? input.attachments : undefined };
        t.messages.push(userMessage);
      }
      if (t.title === NEW_TITLE) t.title = question.length > 48 ? `${question.slice(0, 47).trimEnd()}…` : question;

      const msg: ChatMessage = { id: id('m'), role: 'assistant', content: '', at: now() };
      t.messages.push(msg);
      touch(t);
      const snapshot = () => structuredClone(msg);
      yield { type: 'start', userMessage: userMessage && structuredClone(userMessage), messageId: msg.id };

      const stopped = () => {
        if (!signal?.aborted) return false;
        msg.stopped = true;
        msg.toolCalls = msg.toolCalls?.map((c) => (c.status === 'running' ? { ...c, status: 'failed', output: { error: 'Stopped by the user' } } : c));
        touch(t);
        return true;
      };

      yield { type: 'status', phase: 'thinking' };
      await sleep(450);
      if (stopped()) return;

      let review: Review | undefined;
      if (/rev-3020|provisional credit|duplicate charge|draft the credit/i.test(question)) {
        try {
          review = await deps.reviews().get('REV-3020');
        } catch {
          // The plan falls back to the default reviewer label.
        }
      }
      const plan = planTurn(question, { attachments: (input.attachments ?? []).map((a) => a.name), reviewers: review?.policy.reviewers ?? 'Card Disputes', sla: deps.slaByQueue() });

      for (const step of plan.steps) {
        const call = { ...step.call, id: id('tc'), status: 'running' as const, output: undefined };
        msg.toolCalls = [...(msg.toolCalls ?? []), call];
        yield { type: 'status', phase: 'calling_tool' };
        yield { type: 'tool_start', call: structuredClone(call) };
        await sleep(Math.min(900, step.call.durationMs + 250));
        if (stopped()) return;
        const done = { ...step.call, id: call.id, status: 'success' as const };
        msg.toolCalls = msg.toolCalls.map((c) => (c.id === call.id ? done : c));
        yield { type: 'tool_end', call: structuredClone(done) };
        for (const w of step.widgets) {
          // A drafted approval mirrors its review: if REV-3020 was already decided, the widget says so.
          const widget: ChatWidget = w.kind === 'approval' && review ? { ...w, state: approvalState(review), decidedBy: review.decidedAt ? review.assignee : undefined } : w;
          msg.widgets = [...(msg.widgets ?? []), widget];
          yield { type: 'widget', widget: structuredClone(widget) };
        }
      }

      let text = plan.text;
      if (plan.ground) {
        yield { type: 'status', phase: 'retrieving' };
        if (!t.kbIds.length) {
          text = 'This conversation has no knowledge base, and the question does not match a tool this agent can use. Add a knowledge base from the header to ground answers in your documents.';
          msg.noAnswer = true;
        } else {
          try {
            // Every attached knowledge base is searched; the answer with the strongest accepted chunk wins.
            const answers = await Promise.all(t.kbIds.map((k) => deps.knowledge.kbs.query(k, { question, settings: defaultRetrieval })));
            if (stopped()) return;
            const strength = (a: PlaygroundAnswer) => (a.noAnswer ? -1 : Math.max(0, ...a.chunks.filter((c) => !c.rejected).map((c) => c.score)));
            const ans = answers.reduce((b, a) => (strength(a) > strength(b) ? a : b));
            if (ans.noAnswer || !ans.answer) {
              const names = await kbNameMap();
              text = `I could not find that in ${t.kbIds.map((k) => names.get(k) ?? k).join(' or ')}. Nothing retrieved scored above the relevance threshold, so I have not guessed.`;
              msg.noAnswer = true;
            } else {
              text = ans.answer;
              msg.citations = ans.citations;
            }
          } catch (e) {
            msg.error = (e as Error).message;
            touch(t);
            yield { type: 'error', message: msg.error, partial: snapshot() };
            return;
          }
        }
      }

      yield { type: 'status', phase: 'writing' };
      const stopAt = failPart ? Math.floor(text.length / 2) : text.length;
      let i = 0;
      while (i < stopAt) {
        const n = Math.min(stopAt - i, 2 + Math.floor(Math.random() * 5));
        const delta = text.slice(i, i + n);
        i += n;
        msg.content += delta;
        yield { type: 'text', delta };
        await sleep(16);
        if (stopped()) return;
      }
      if (failPart) {
        msg.error = 'The connection to the model dropped. The text above is what arrived.';
        touch(t);
        yield { type: 'error', message: msg.error, partial: snapshot() };
        return;
      }
      if (msg.citations) yield { type: 'citations', citations: structuredClone(msg.citations) };
      msg.at = now();
      touch(t);
      yield { type: 'done', message: snapshot() };
    },

    feedback: (tid, mid, fb) =>
      respond(() => {
        const msg = threadOr404(tid).messages.find((x) => x.id === mid) ?? notFound('Message');
        msg.feedback = fb ?? undefined;
      }),

    widgetAction: async (tid, mid, wid, action) => {
      const w = findWidget(tid, mid, wid);
      if (w.kind === 'approval') {
        if (action.type === 'submit') throw new ApiError('An approval is approved or rejected, not submitted.', 400);
        const r = await deps.reviews().decide(w.reviewId, action.type === 'approve' ? { decision: 'approved' } : { decision: 'rejected', reason: action.reason });
        Object.assign(w, { state: approvalState(r), decidedBy: deps.me, reason: action.type === 'reject' ? action.reason : undefined });
        return structuredClone(w);
      }
      return respond(() => {
        if (w.kind !== 'form' || action.type !== 'submit') throw new ApiError('This widget has no actions.', 400);
        if (w.state === 'submitted') throw new ApiError('This form was already submitted.', 409);
        const missing = w.fields.find((f) => f.required && !action.values[f.key]?.trim());
        if (missing) throw new ApiError(`${missing.label} is required.`, 400);
        const ref = `KYC-${2040 + threads.length}`;
        const due = action.values.priority?.startsWith('Expedited') ? '1 business day' : '5 business days';
        Object.assign(w, { state: 'submitted', values: action.values, result: `Opened ${ref} in the KYC refresh queue. Due in ${due}.` });
        return w;
      });
    },
  };
}
