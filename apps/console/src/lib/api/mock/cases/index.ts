import type { CaseAction, CaseDetail, CaseRow, CaseView, EmailWorkflowConfig, SampleMailResult } from '@/lib/types/cases';

import { ApiError } from '../../contract';
import type { CasesApi } from '../../cases-contract';
import { bulk, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam } from '../teams';
import { APPROVER_GROUPS, ASSIGNEES, QUEUES } from './configs';
import { seedCases } from './seed';

const now = () => new Date().toISOString();
const isOpen = (c: Pick<CaseDetail, 'status'>) => c.status !== 'closed';
const pending = (a: CaseAction) => a.needsApproval && (a.status === 'drafted' || a.status === 'awaiting_second');

const RESULT: Record<string, string> = {
  send_reply: 'Sent to the customer',
  issue_provisional_credit: 'Provisional credit posted; chargeback opened',
  place_card_block: 'Card blocked; replacement ordered',
  waive_fee: 'Fee reversed on the account',
  update_address: 'Address updated in core banking',
  apply_payment_deferral: 'Deferral applied; customer letter queued',
  send_payoff_statement: 'Payoff statement generated and emailed',
};

/** In-memory cases for the ops workbench. `me` is the signed-in reviewer; they belong to every approver group in the demo. */
export function createCasesMock(deps: { me: string; workflowName: (id: string) => string; workflowOwner: (id: string) => string | undefined }) {
  const { me } = deps;
  const cases: CaseDetail[] = seedCases(me, deps.workflowName);

  const row = (c: CaseDetail): CaseDetail => {
    const open = isOpen(c);
    // The SLA clock pauses while the case waits on the customer.
    const slaMinutes = open && c.status !== 'waiting_customer' ? Math.round((new Date(c.slaDueAt).getTime() - Date.now()) / 60_000) : null;
    const pend = c.actions.filter(pending);
    return {
      ...c,
      workflowName: deps.workflowName(c.workflowId),
      slaMinutes,
      pendingApprovals: pend.length,
      awaitingMe: pend.filter((a) => !a.approvals.some((x) => x.by === me)).length,
    };
  };
  const strip = (c: CaseDetail): CaseRow => {
    const { fields: _f, messages: _m, actions: _a, events: _e, ...r } = c;
    return r;
  };
  const inView = (c: CaseDetail, v: CaseView) =>
    v === 'closed' ? !isOpen(c) : !isOpen(c) ? false : v === 'mine' ? c.assignee === me : v === 'breaching' ? (c.slaMinutes ?? 0) < 0 : v === 'awaiting_me' ? c.awaitingMe > 0 : true;
  const caseOr404 = (id: string) => cases.find((c) => c.id === id) ?? notFound('Case');
  /** Cases belong to the team that owns their workflow. */
  const teamCases = () => cases.filter((c) => inTeam(deps.workflowOwner(c.workflowId)));
  const log = (c: CaseDetail, kind: CaseDetail['events'][number]['kind'], text: string) => c.events.push({ at: now(), kind, text, by: me });

  const stats = () => {
    const rows = teamCases().map(row);
    const open = rows.filter(isOpen);
    const today = new Date().toDateString();
    return {
      open: open.length,
      breaching: open.filter((c) => (c.slaMinutes ?? 0) < 0).length,
      awaitingApproval: open.filter((c) => c.pendingApprovals > 0).length,
      closedToday: rows.filter((c) => !isOpen(c) && c.events.some((e) => e.kind === 'closed' && new Date(e.at).toDateString() === today)).length,
    };
  };

  const api: CasesApi = {
    list: (p) =>
      respond((m) => {
        const rows = teamCases().map(row);
        const scoped = rows.filter((c) => inView(c, p.view)).sort((a, b) => (p.view === 'closed' ? b.receivedAt.localeCompare(a.receivedAt) : (a.slaMinutes ?? 0) - (b.slaMinutes ?? 0)));
        const result = list(scoped.map(strip), p, { text: (c) => `${c.id} ${c.subject} ${c.requester} ${c.account ?? ''}`, value: (c, k) => String((c as unknown as Record<string, unknown>)[k]), facetKeys: ['queue', 'intentId', 'status', 'priority'] }, m);
        const src = m === 'empty' ? [] : rows;
        return {
          ...result,
          viewCounts: { mine: src.filter((c) => inView(c, 'mine')).length, team: src.filter((c) => inView(c, 'team')).length, breaching: src.filter((c) => inView(c, 'breaching')).length, awaiting_me: src.filter((c) => inView(c, 'awaiting_me')).length, closed: src.filter((c) => inView(c, 'closed')).length },
          stats: m === 'empty' ? { open: 0, breaching: 0, awaitingApproval: 0, closedToday: 0 } : stats(),
        };
      }),
    get: (id) => respond((m) => (m === 'empty' ? notFound('Case') : (guardTeam(deps.workflowOwner(caseOr404(id).workflowId), 'case'), row(caseOr404(id))))),
    setField: (id, key, value) =>
      respond(() => {
        const c = caseOr404(id);
        const f = c.fields.find((x) => x.key === key) ?? notFound('Field');
        const before = f.value;
        Object.assign(f, { value, edited: true });
        log(c, 'edited', `${f.label} changed from “${before ?? '—'}” to “${value}”`);
        return row(c);
      }),
    assign: (ids, assignee) =>
      respond(() =>
        bulk(ids, (id) => {
          const c = cases.find((x) => x.id === id);
          if (!c) return 'Not found';
          if (!isOpen(c)) return 'Closed';
          if (c.assignee === assignee) return `Already with ${assignee}`;
          c.assignee = assignee;
          if (c.status === 'new') c.status = 'in_progress';
          log(c, 'assigned', `Assigned to ${assignee}`);
        }),
      ),
    close: (ids, reason) =>
      respond(() => {
        if (!reason.trim()) throw new ApiError('Give a reason for closing.', 400);
        return bulk(ids, (id) => {
          const c = cases.find((x) => x.id === id);
          if (!c) return 'Not found';
          if (!isOpen(c)) return 'Already closed';
          if (c.actions.some(pending)) return 'Has actions waiting for approval';
          c.status = 'closed';
          log(c, 'closed', `Case closed: ${reason}`);
        });
      }),
    decideAction: (caseId, actionId, input) =>
      respond(() => {
        const c = caseOr404(caseId);
        if (!isOpen(c)) throw new ApiError('The case is closed.', 409);
        const a = c.actions.find((x) => x.id === actionId) ?? notFound('Action');
        if (!pending(a)) throw new ApiError('This action is not waiting for a decision.', 409);
        if (input.decision === 'reject') {
          if (!input.reason?.trim()) throw new ApiError('Give a reason for rejecting; the agent learns from it.', 400);
          Object.assign(a, { status: 'rejected', rejectedReason: input.reason });
          log(c, 'rejected', `${a.label} rejected: ${input.reason}`);
        } else {
          if (a.approvals.some((x) => x.by === me)) throw new ApiError('You already approved this. A second person must approve it.', 409);
          a.approvals.push({ by: me, at: now() });
          log(c, 'approved', `${a.label} approved${a.fourEyes ? ` (${a.approvals.length} of 2)` : ''}`);
          if (a.fourEyes && a.approvals.length < 2) a.status = 'awaiting_second';
          else {
            a.status = 'executed';
            a.result = RESULT[a.tool] ?? 'Completed';
            log(c, 'executed', `${a.label}: ${a.result}`);
            if (a.tool === 'send_reply') {
              c.messages.push({ id: `${c.id}-m${c.messages.length + 1}`, direction: 'outbound', from: c.mailbox, to: c.requesterEmail, at: now(), subject: `Re: ${c.subject}`, body: a.input, attachments: [] });
              log(c, 'replied', 'Reply sent to the customer');
            }
          }
        }
        if (!c.actions.some(pending)) c.status = c.actions.some((x) => x.tool === 'send_reply' && x.status === 'executed') ? 'waiting_customer' : 'in_progress';
        else c.status = 'waiting_approval';
        if (!c.assignee) c.assignee = me;
        return a;
      }),
    editAction: (caseId, actionId, input) =>
      respond(() => {
        const c = caseOr404(caseId);
        const a = c.actions.find((x) => x.id === actionId) ?? notFound('Action');
        if (!pending(a) && a.status !== 'drafted') throw new ApiError('Only drafted actions can be edited.', 409);
        if (a.kind === 'tool') {
          try {
            JSON.parse(input);
          } catch {
            throw new ApiError('Tool input must be valid JSON.', 400);
          }
        }
        a.input = input;
        // An edit invalidates approvals given to the earlier version.
        a.approvals = [];
        if (a.status === 'awaiting_second') a.status = 'drafted';
        log(c, 'edited', `${a.label} edited before approval`);
        return a;
      }),
    testSampleMail: (config, input) => respond(() => classify(config, input.subject, input.body, input.from)),
    queues: () => respond(() => ({ queues: QUEUES, assignees: ASSIGNEES, approverGroups: APPROVER_GROUPS })),
  };

  /** Open cases per queue with SLA breaches, for the chat case-engine tools. */
  const slaByQueue = () => {
    const open = teamCases().map(row).filter(isOpen);
    return QUEUES.map((queue) => {
      const q = open.filter((c) => c.queue === queue);
      const breaching = q.filter((c) => (c.slaMinutes ?? 0) < 0);
      return {
        queue,
        open: q.length,
        breaching: breaching.length,
        breachingAwaitingApproval: breaching.filter((c) => c.pendingApprovals > 0).length,
        dueSoon: q.filter((c) => c.slaMinutes != null && c.slaMinutes >= 0 && c.slaMinutes <= 60).length,
        oldestOverMinutes: breaching.length ? Math.max(...breaching.map((c) => -(c.slaMinutes ?? 0))) : null,
      };
    });
  };

  return { api, stats: () => stats(), slaByQueue };
}

const words = (s: string) => new Set(s.toLowerCase().split(/[^a-z0-9$]+/).filter((w) => w.length > 3));

/** Keyword overlap with each intent's name, description and examples; good enough to demonstrate routing. */
function classify(config: EmailWorkflowConfig, subject: string, body: string, _from: string): SampleMailResult {
  const text = `${subject} ${body}`;
  const w = words(text);
  let best: { id: string; score: number } | null = null;
  for (const it of config.intents) {
    const vocab = words(`${it.name} ${it.description} ${it.examples.join(' ')}`);
    const score = [...w].filter((x) => vocab.has(x)).length;
    if (!best || score > best.score) best = { id: it.id, score };
  }
  const intent = best && best.score > 0 ? config.intents.find((i) => i.id === best!.id)! : null;
  const confidence = intent ? Math.min(0.97, 0.5 + best!.score * 0.06) : 0.3;
  const below = confidence < config.confidenceThreshold;
  const route = intent && !below ? config.routes.find((r) => r.intentId === intent.id) : undefined;
  const amount = text.match(/\$\s?([\d,]+(?:\.\d{2})?)/)?.[0] ?? null;
  const card = text.match(/ending (?:in )?(\d{4})/i)?.[1] ?? null;
  const loan = text.match(/\b(\d{4}-\d{5})\b/)?.[1] ?? null;
  const date = text.match(/\b(20\d{2}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2})\b/)?.[1] ?? null;
  const guess: Record<string, string | null> = { amount, card_last4: card, loan_number: loan, transaction_date: date, payoff_date: date, effective_date: date };
  const actions = intent && !below ? intent.actions : [];
  return {
    intentId: intent && !below ? intent.id : null,
    intentName: intent ? (below ? `Unsure (closest: ${intent.name})` : intent.name) : 'No matching intent',
    confidence,
    belowThreshold: below,
    fields: (intent?.fields ?? []).map((f) => ({ key: f.key, label: f.label, value: guess[f.key] ?? null })),
    queue: route?.queue ?? config.fallbackQueue,
    priority: route?.priority ?? 'normal',
    slaHours: route?.slaHours ?? 24,
    actions: actions.map((tool) => {
      const rule = config.approvals.find((a) => a.action === tool);
      return { label: rule?.label ?? tool.replace(/_/g, ' '), kind: tool === 'send_reply' ? 'reply' : 'tool', needsApproval: !!rule, approverGroup: rule?.approverGroup, fourEyes: !!rule?.fourEyes };
    }),
    tookMs: 640 + Math.round(Math.random() * 300),
  };
}
