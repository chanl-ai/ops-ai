import type { ChatApi } from '@/lib/api/chat-contract';
import type { OpsApi } from '@/lib/api/contract';
import { ApiError } from '@/lib/api/contract';
import type { KnowledgeApi } from '@/lib/api/knowledge-contract';
import type { ApprovalState, ApprovalWidget, ChatMessage, ChatOverrides, ChatStreamEvent, ChatThread, ChatThreadRow, ChatWidget, ThreadSettings } from '@/lib/types/chat';
import type { Agent, Review, RunStatus, WorkflowRun } from '@/lib/types/domain';
import type { Memory } from '@/lib/types/memory';
import type { PlaygroundAnswer, RetrievalSettings, RetrieveInput } from '@/lib/types/knowledge';

import type { FileLinks } from '../files';
import { bulk, id, list, mode, notFound, respond } from '../runtime';
import { guardTeam, inTeam } from '../teams';
import { GENERAL_SUGGESTIONS, SUGGESTIONS, planTurn, type QueueSla, type TurnPlan } from './scripts';

const ALL = { page: 1, pageSize: 100 };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const NEW_TITLE = 'New chat';
/** Chat replies in words, so a knowledge base saved to return bare chunks still gets a written answer here; everything else comes from each knowledge base's saved settings. */
const CHAT_OVERRIDES: Partial<RetrievalSettings> = { answerShape: 'answer_with_citations' };

/**
 * `?chat=fail-next` makes the next reply stop part-way with an error, so the partial-reply state can be reviewed
 * while every other request still succeeds. `?chat=fail-next:<code>` ends it the way a models-service refusal does,
 * with that code on the error frame (e.g. `fail-next:rate_limited`).
 */
function takeFailNext(): false | { code?: string } {
  if (typeof window === 'undefined') return false;
  try {
    const q = new URLSearchParams(window.location.search).get('chat');
    if (q?.startsWith('fail-next')) sessionStorage.setItem('ops-mock-chat-fail', q);
    const on = sessionStorage.getItem('ops-mock-chat-fail');
    sessionStorage.removeItem('ops-mock-chat-fail');
    return on ? { code: on.split(':')[1] || undefined } : false;
  } catch {
    return false;
  }
}

function assemble(plan: TurnPlan, grounded?: PlaygroundAnswer): Pick<ChatMessage, 'content' | 'toolCalls' | 'widgets' | 'citations' | 'noAnswer' | 'trace'> {
  const toolCalls = plan.steps.map((s) => ({ ...s.call, id: id('tc'), status: 'success' as const }));
  const widgets = plan.steps.flatMap((s) => s.widgets);
  return {
    content: grounded ? grounded.answer : plan.text,
    citations: grounded?.citations.length ? grounded.citations : undefined,
    trace: grounded?.trace,
    noAnswer: grounded?.noAnswer || undefined,
    toolCalls: toolCalls.length ? toolCalls : undefined,
    widgets: widgets.length ? widgets : undefined,
  };
}

const approvalState = (r: Review): ApprovalState =>
  r.status === 'approved' ? 'approved' : r.status === 'rejected' || r.status === 'returned' ? 'rejected' : r.approvals.length ? 'awaiting_second' : 'pending';

type Deps = {
  knowledge: KnowledgeApi;
  /** Synchronous search for seeding threads with real answers and their traces. */
  ground: (input: RetrieveInput) => PlaygroundAnswer;
  /** Agents people may chat with: live ones only. */
  agents: () => Pick<Agent, 'id' | 'name' | 'role' | 'version' | 'model' | 'collections'>[];
  /** Owner of an agent; conversations and the agent picker follow the current team through it. */
  agentOwner: (agentId: string) => string | undefined;
  /** The review flow; approval widgets decide their review through it. */
  reviews: () => OpsApi['reviews'];
  me: string;
  /** Per-queue SLA figures from the cases backend, so chat and the Cases page agree. */
  slaByQueue: () => QueueSla[];
  /** Attachments arrive as file ids; each send records the chat as a reference and refuses quarantined files. */
  files: FileLinks;
  /** Starts the runs of granted workflow tools the question is about; each comes with its gate review when it paused. */
  workflowTools: (agentId: string, question: string) => { toolName: string; workflowName: string; run: WorkflowRun; review: Review | null }[];
};

const RUN_STATE: Record<RunStatus, string> = { waiting_review: 'Waiting on review', running: 'Running', completed: 'Completed', failed: 'Failed' };
// A started run's card and its gate widget share the run id, so deciding the gate can update the card.
const runCardId = (runId: string) => `wfrun-${runId}`;
const gateId = (runId: string) => `wfgate-${runId}`;
/** After a gate decision, the run card reads the state the decision moved the run to. */
const settleRunCard = (widgets: ChatWidget[], gate: ApprovalWidget) => {
  if (!gate.id.startsWith('wfgate-') || gate.state === 'pending' || gate.state === 'awaiting_second') return;
  const card = widgets.find((w) => w.id === runCardId(gate.id.slice('wfgate-'.length)));
  if (card?.kind === 'record') card.status = gate.state === 'approved' ? RUN_STATE.completed : RUN_STATE.failed;
};

export function createChatMock(deps: Deps): ChatApi {
  // Unset until someone picks one, as on a new team before provisioning runs.
  let defaultAgentId: string | undefined;
  const answer = (question: string, kbIds: string[]) => {
    try {
      return deps.ground({ question, kbIds, overrides: CHAT_OVERRIDES });
    } catch {
      return undefined;
    }
  };
  const seed = (
    tid: string,
    title: string,
    agentId: string,
    kbIds: string[],
    minutes: number,
    question: string,
    opts: { grounded?: boolean; owner?: string; pinned?: boolean; archived?: boolean; feedback?: ChatMessage['feedback'] } = {},
  ): ChatThread => {
    const a = deps.agents().find((x) => x.id === agentId);
    const at = minsAgo(minutes);
    const fresh = planTurn(question, { attachments: [], reviewers: 'Card Disputes', sla: deps.slaByQueue() });
    const plan = { ...fresh, steps: fresh.steps.map((s) => ({ ...s, widgets: s.widgets.map((w) => ({ ...w, asOf: at })) })) };
    const messages: ChatMessage[] = [
      { id: `${tid}_u1`, role: 'user', content: question, at },
      { id: `${tid}_a1`, role: 'assistant', at, feedback: opts.feedback, ...assemble(plan, opts.grounded ? answer(question, kbIds) : undefined) },
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
    seed('th_wire', 'New-payee wire hold rule', 'ag_fraud', ['kb_people', 'kb_eng'], 60 * 3, 'What is our new-payee wire hold rule?', { grounded: true, feedback: { rating: 'up' }, pinned: true }),
    seed('th_kyc', 'KYC refresh for Daniel Okoye', 'ag_kyb', ['kb_eng'], 60 * 26, 'Open a KYC refresh request for Daniel Okoye'),
    seed('th_week', 'Case volume this week', 'ag_dispute', ['kb_legal'], 60 * 24 * 3, 'How are we doing this week?'),
    seed('th_fee', 'Annual card fee refunds', 'ag_branch', ['kb_support'], 60 * 24 * 5, 'What is the refund window for an annual card fee?', { grounded: true }),
    seed('th_halifax', 'Halifax wire cut-off', 'ag_branch', ['kb_support'], 60 * 24 * 9, 'What is the wire cut-off time at the Halifax branch?', {
      grounded: true,
      feedback: { rating: 'down', reason: 'Missing from the knowledge base' },
    }),
    seed('th_retention', 'Due diligence record retention', 'ag_kyb', ['kb_eng'], 60 * 24 * 12, 'How long do we keep customer due diligence records?', { grounded: true, archived: true }),
    seed('th_fees', 'Business loan origination fee', 'ag_loan', ['kb_lending'], 60 * 24 * 20, 'What is the origination fee on a small business loan over $250k?', { grounded: true }),
    seed('th_maya', 'Wire release authority', 'ag_fraud', ['kb_people'], 60 * 30, 'What is our new-payee wire hold rule?', { grounded: true, owner: 'Maya Okafor' }),
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
          settleRunCard(t.messages.find((m) => m.widgets?.includes(w))?.widgets ?? [], w);
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

  // Mock thread settings: the defaults an agent with no saved limits gets on the server (its one model, its bases, no
  // added instructions), checked the way the resolver refuses them.
  const overridesByThread = new Map<string, ChatOverrides>();
  const settingsOf = async (tid: string): Promise<ThreadSettings> => {
    const t = threadOr404(tid);
    const a = deps.agents().find((x) => x.id === t.agentId);
    const names = await kbNameMap();
    const byName = new Map([...names].map(([k, v]) => [v, k]));
    const kbIds = (a?.collections ?? []).map((c) => byName.get(c)).filter((x): x is string => !!x);
    const overrides = overridesByThread.get(tid);
    return {
      limits: {
        allowedModels: [a?.model ?? 'default'],
        defaultModel: a?.model ?? 'default',
        knowledgeBases: kbIds.map((id) => ({ id, name: names.get(id) ?? id })),
        // The mock's agents carry no tool grants here, so nothing is offered to switch off.
        switchableTools: [],
        mayAddInstructions: false,
        switchableWidgets: [],
        mayCompose: false,
      },
      ...(overrides ? { overrides } : {}),
      effective: {
        model: overrides?.model ?? a?.model ?? 'default',
        addedInstructions: [],
        toolsOff: overrides?.toolsOff ?? [],
        knowledgeBaseIds: overrides?.knowledgeBaseIds ?? t.kbIds,
        widgetsOff: [],
        composeOff: false,
        sources: { model: 'agent', ...(overrides?.toolsOff ? { toolsOff: 'thread' } : {}) },
      },
    };
  };
  const refuseOverride = (field: string, message: string): never => {
    throw new ApiError(`overrides.thread.${field}: ${message}`, 422, undefined, 'override_outside_limits', { field: `overrides.thread.${field}` });
  };

  // Mock memories: what the demo agents keep about the signed-in person, changed in place like the server.
  let memories: Memory[] = [];
  const memoryOf = (mid: string) => memories.find((m) => m.id === mid) ?? notFound('Memory');

  return {
    memories: {
      list: async (agentId) => respond(() => memories.filter((m) => !agentId || m.agentId === agentId)),
      correct: async (mid, value) =>
        respond(() => {
          const fixed = { ...memoryOf(mid), id: id('mem'), value, confidence: 1, source: 'person' as const };
          memories = [fixed, ...memories.filter((m) => m.id !== mid)];
          return fixed;
        }),
      forget: async (mid) =>
        respond(() => {
          memoryOf(mid);
          memories = memories.filter((m) => m.id !== mid);
        }),
      forgetAgent: async (agentId) =>
        respond(() => {
          const before = memories.length;
          memories = memories.filter((m) => m.agentId !== agentId);
          return { forgotten: before - memories.length };
        }),
      exportAll: async () => respond(() => ({ person: 'you', memories, audit: [] })),
    },
    settings: {
      get: async (tid) => respond(() => null).then(() => settingsOf(tid)),
      save: async (tid, patch) => {
        const current = await settingsOf(tid);
        // Merge like the server: null clears a field, a missing one keeps the thread's.
        const merged: Record<string, unknown> = { ...overridesByThread.get(tid), ...patch };
        const overrides = Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== null && v !== undefined)) as ChatOverrides;
        const off = (overrides.toolsOff ?? []).filter((x) => !current.limits.switchableTools.some((t) => t.id === x));
        if (off.length) refuseOverride('toolsOff', `cannot switch off ${off.join(', ')}.`);
        if (overrides.instructions?.trim() && !current.limits.mayAddInstructions) refuseOverride('instructions', 'this agent does not let callers add instructions.');
        if (overrides.model && !current.limits.allowedModels.includes(overrides.model)) refuseOverride('model', `${overrides.model} is not one of ${current.limits.allowedModels.join(', ')}.`);
        overridesByThread.set(tid, overrides);
        return settingsOf(tid);
      },
      attach: async (file) => respond(() => ({ fileId: id('fl'), name: file.name, size: file.size })),
    },
    defaultAgent: {
      get: () => respond(() => ({ canChange: true, ...(defaultAgentId ? { agentId: defaultAgentId, agentName: deps.agents().find((a) => a.id === defaultAgentId)?.name } : {}) })),
      set: (agentId) =>
        respond(() => {
          const a = deps.agents().find((x) => x.id === agentId);
          if (!a) throw new ApiError('That agent is not live, so new chats cannot start on it.', 422);
          defaultAgentId = a.id;
          return { agentId: a.id, agentName: a.name };
        }),
    },
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
      list: async ({ cursor, ...p }) => {
        const names = await kbNameMap();
        return respond((m) => {
          // Owner only, as the API: a teammate's chat is not listed.
          const sorted = threads.filter((t) => t.owner === deps.me && inTeam(deps.agentOwner(t.agentId))).sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
          const rows = sorted.map((t) => row(t, names));
          // The mock's cursor is the last row's id: the next page is the rows after it, searched and filtered as usual.
          const from = cursor ? rows.findIndex((t) => t.id === cursor) + 1 : 0;
          const page = list(
            rows.slice(from),
            cursor ? { ...p, page: 1 } : p,
            {
              text: (t) => `${t.title} ${t.preview} ${t.agentName}`,
              value: (t, k) => (k === 'state' ? stateOf(t) : k === 'kbIds' ? t.kbIds : String((t as unknown as Record<string, unknown>)[k])),
              facetKeys: ['agentId', 'kbIds', 'state'],
            },
            m,
          );
          const last = page.data.at(-1);
          return { ...page, ...(page.pagination.hasNext && last ? { nextCursor: last.id } : {}) };
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
          const agentId = input.agentId ?? defaultAgentId;
          if (!agentId) throw new ApiError('This team has no default agent yet, so pick an agent; a team admin sets the default in General settings.', 409);
          const a = deps.agents().find((x) => x.id === agentId);
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
          if (patch.agentId && patch.agentId !== t.agentId) {
            const to = deps.agents().find((x) => x.id === patch.agentId);
            if (!to) throw new ApiError('That agent is not live, so the conversation cannot move to it.', 422);
            const back = to.id === t.startAgentId;
            Object.assign(t, { agentId: to.id, agentName: to.name, agentVersion: to.version, startAgentId: back ? undefined : (t.startAgentId ?? t.agentId), startAgentName: back ? undefined : (t.startAgentName ?? t.agentName) });
          }
          const { agentId: _moved, ...rest } = patch;
          Object.assign(t, { ...rest, title: patch.title?.trim() ?? t.title });
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
      if (m === 'error') throw new ApiError('The request failed. Nothing has changed on your side; try again in a moment.', 503);
      const failPart = takeFailNext();
      const t = threadOr404(tid);
      if (t.owner !== deps.me) throw new ApiError('Only the owner can continue this conversation.', 403);
      if (!input.content.trim() && !input.regenerate) throw new ApiError('Type a message first.', 400);
      for (const a of input.attachments ?? []) deps.files.link(a.fileId, { type: 'chat', id: t.id, name: t.title === NEW_TITLE ? input.content.trim().slice(0, 48) : t.title, href: `/chat/${t.id}` }, ['chat_attachment']);
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

      // A granted workflow tool the question is about runs instead of the scripted plan: the agent starts the workflow
      // and the thread shows the run, plus its gate when the run paused for a person.
      const started = input.regenerate ? [] : deps.workflowTools(t.agentId, question);
      if (started.length) {
        plan.steps = [];
        plan.ground = false;
        const asOf = now();
        for (const s of started) {
          const call = { id: id('tc'), name: s.toolName, server: 'Workflows', input: { subject: s.run.subject }, output: { runId: s.run.id, status: s.run.status, reviewId: s.review?.id }, status: 'success' as const, durationMs: 420, gated: s.review ? { gate: s.review.policy.name, reviewers: s.review.policy.reviewers } : undefined };
          msg.toolCalls = [...(msg.toolCalls ?? []), call];
          yield { type: 'status', phase: 'calling_tool' };
          yield { type: 'tool_start', call: structuredClone({ ...call, status: 'running' as const, output: undefined }) };
          await sleep(300);
          yield { type: 'tool_end', call: structuredClone(call) };
          const card: ChatWidget = {
            kind: 'record',
            id: runCardId(s.run.id),
            title: `Started workflow ${s.workflowName}`,
            subtitle: s.run.id,
            status: RUN_STATE[s.run.status],
            app: 'Workflows',
            tool: s.toolName,
            asOf,
            fields: [
              { label: 'Started by', value: (s.run.trigger ?? '').replace(/^Started by /, '') },
              ...(s.review ? [{ label: 'Waiting on', value: `${s.review.policy.reviewers} · SLA ${s.review.policy.sla}` }] : []),
            ],
            href: `/workflows/runs?run=${encodeURIComponent(s.run.id)}`,
          };
          msg.widgets = [...(msg.widgets ?? []), card];
          yield { type: 'widget', widget: structuredClone(card) };
          if (s.review) {
            const gate: ChatWidget = {
              kind: 'approval',
              id: gateId(s.run.id),
              title: s.review.policy.name,
              app: 'Workflows',
              tool: s.toolName,
              asOf,
              reviewId: s.review.id,
              action: `Let ${s.run.id} continue`,
              summary: `${(s.run.trigger ?? '').replace(/^Started by agent /, '')} started this run for: ${s.run.subject}`,
              fields: [
                { label: 'Gate', value: s.review.policy.condition },
                { label: 'Reviewers', value: s.review.policy.reviewers },
                { label: 'Review', value: s.review.id },
              ],
              risk: s.review.risk,
              stepUp: s.review.stepUp,
              state: 'pending',
            };
            msg.widgets = [...msg.widgets, gate];
            yield { type: 'widget', widget: structuredClone(gate) };
          }
        }
        plan.text = started
          .map((s) => (s.review ? `I started ${s.workflowName} as ${s.run.id}. It paused at "${s.review.policy.name}" for ${s.review.policy.reviewers}; it acts only once that review is approved (${s.review.id}).` : `I started ${s.workflowName} as ${s.run.id}. It is running.`))
          .join(' ');
      }

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
          const widget: ChatWidget = w.kind === 'approval' && review ? { ...w, state: approvalState(review), decidedBy: review.decidedAt ? review.assignee : undefined, stepUp: review.stepUp } : w;
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
            // One search across every attached knowledge base, with each one's saved settings and precedence rules.
            const ans = await deps.knowledge.retrieve({ question, kbIds: t.kbIds, overrides: CHAT_OVERRIDES });
            if (stopped()) return;
            msg.trace = ans.trace;
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
        msg.error = failPart.code ? `The model call was refused (${failPart.code}).` : 'The connection to the model dropped. The text above is what arrived.';
        touch(t);
        yield { type: 'error', message: msg.error, partial: snapshot(), code: failPart.code };
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

    // The mock meters no model calls, so its conversations never pause on a budget.
    budget: async () => Promise.reject(new ApiError('Conversation budgets need the agents service.', 501)),
    widgetAction: async (tid, mid, wid, action) => {
      const w = findWidget(tid, mid, wid);
      if (w.kind === 'approval') {
        if (action.type === 'submit') throw new ApiError('An approval is approved or rejected, not submitted.', 400);
        const r = await deps.reviews().decide(w.reviewId, action.type === 'approve' ? { decision: 'approved', stepUpToken: action.stepUpToken } : { decision: 'rejected', reason: action.reason });
        Object.assign(w, { state: approvalState(r), decidedBy: deps.me, reason: action.type === 'reject' ? action.reason : undefined });
        settleRunCard(threadOr404(tid).messages.find((m) => m.id === mid)?.widgets ?? [], w);
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
