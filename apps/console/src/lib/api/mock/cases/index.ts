import type { CaseAction, CaseDetail, CaseRow, CaseView, EmailWorkflowConfig, RunRow, RunView, SampleMailResult } from '@/lib/types/cases';
import type { Review, WorkflowRun } from '@/lib/types/domain';

import { ApiError } from '../../contract';
import type { CasesApi } from '../../cases-contract';
import type { FileLinks } from '../files';
import { mimeOf } from '../files';
import { runIdFor } from '../history';
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

/**
 * In-memory cases for the ops workbench. `me` is the signed-in reviewer; they belong to every approver group in the demo.
 * `runs` and `reviews` are the workflow slice's own records: the Cases page lists those runs as they are, so a run reads
 * the same here and under its workflow's Runs tab.
 */
export function createCasesMock(deps: {
  me: string;
  workflowName: (id: string) => string;
  workflowOwner: (id: string) => string | undefined;
  files: FileLinks;
  runs: () => WorkflowRun[];
  reviews: () => Review[];
}) {
  const { me } = deps;
  const cases: CaseDetail[] = seedCases(me, deps.workflowName);
  // Intake stores each attachment through the Files API; the case keeps the file id. Identical content mailed
  // twice is stored once. The first termination letter (an employment dispute) is under legal hold.
  let held = false;
  for (const c of cases)
    for (const m of c.messages)
      m.attachments = m.attachments.map((a) => {
        const f = deps.files.intake({
          name: a.name,
          size: a.size,
          team: deps.workflowOwner(c.workflowId) ?? 'Platform',
          ref: { type: 'case', id: c.id, name: `${c.id} · ${c.subject}`, href: `/cases/${c.id}` },
          infected: a.scan === 'infected',
          hold: a.name === 'termination-letter.pdf' && !held && (held = true) ? { by: 'Legal (Employment)', reason: 'LH-2026-021: wrongful dismissal claim, preserve the borrower file' } : undefined,
        });
        return { ...a, fileId: f.id, mime: mimeOf(a.name), scan: f.scan.status };
      });
  /** Attachments show the file's current scan state; a quarantined one shows why it is blocked. */
  const withFiles = (c: CaseDetail): CaseDetail => ({
    ...c,
    messages: c.messages.map((m) => ({ ...m, attachments: m.attachments.map((a) => ({ ...a, ...deps.files.state(a.fileId) })) })),
  });

  const row = (c: CaseDetail): CaseDetail => {
    const open = isOpen(c);
    // The SLA clock pauses while the case waits on the customer.
    const slaMinutes = open && c.status !== 'waiting_customer' ? Math.round((new Date(c.slaDueAt).getTime() - Date.now()) / 60_000) : null;
    const pend = c.actions.filter(pending);
    return {
      ...withFiles(c),
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
    runs: (p) => listRuns(p),
    run: (id) => getRun(id),
    // The mock keeps no graph state: a run reads as an empty state, so the sheet shows the row and the trace alone.
    runState: (id) => getRun(id).then((r) => ({ threadId: r.id, graph: r.workflowId, version: r.version, status: r.status, values: {}, next: [], interrupt: null })),
    startRun: (input) => respond(() => {
      const run = startRun(input);
      return { threadId: run.id, run };
    }),
    startable: () =>
      respond(() => [
        { name: 'simple_workflow', title: 'Product question', kind: 'code' as const, latestVersion: null, input: [{ name: 'question', label: 'Question', type: 'text' as const, required: true }] },
        { name: 'complex_workflow', title: 'Dispute email', kind: 'code' as const, latestVersion: null, input: [{ name: 'email', label: 'Email', type: 'email' as const, required: true }] },
      ]),
    assignRuns: (ids, assignee) => assignRuns(ids, assignee),
    queues: () => respond(() => ({ queues: QUEUES, assignees: ASSIGNEES, approverGroups: APPROVER_GROUPS })),
  };

  // Each email opened a run of its mailbox workflow. Run ids are positional, so the link is made by id without
  // generating runs (the workflow slice asks `pausedRunIds` while it generates them). The newest case takes the
  // newest run after those held by open reviews and the one still in flight.
  let linked = false;
  const link = () => {
    if (linked) return;
    linked = true;
    const reviews = deps.reviews();
    for (const wid of new Set(cases.map((c) => c.workflowId))) {
      const offset = Math.max(1, reviews.filter((r) => r.workflowId === wid && (r.status === 'pending' || r.status === 'in_review')).length);
      cases
        .filter((c) => c.workflowId === wid)
        .sort((a, b) => b.receivedAt.localeCompare(a.receivedAt))
        .forEach((c, i) => (c.runId = runIdFor(wid, offset + i)));
    }
  };
  /** Runs held for a person by their email case: open, and not waiting on the customer's reply. */
  const pausedRunIds = (wid: string) => {
    link();
    return cases.filter((c) => c.workflowId === wid && c.runId && isOpen(c) && c.status !== 'waiting_customer').map((c) => c.runId!);
  };

  // State is the run's own status, so a run reads the same here and on its workflow's Runs tab.
  const stateOf = (r: WorkflowRun): RunRow['state'] => (r.status === 'completed' ? 'done' : r.status === 'failed' ? 'failed' : r.status === 'running' ? 'running' : 'waiting');
  const isActionStep = (s: WorkflowRun['steps'][number]) => (s.kind === 'tool' || s.kind === 'action') && s.status === 'done';

  const runRow = (r: WorkflowRun, byRun: Map<string, CaseDetail>, reviews: Map<string, Review>): RunRow => {
    const base = { ...r, workflowName: deps.workflowName(r.workflowId), caseId: null, queue: null, assignee: null, slaDueAt: null, slaMinutes: null, waitingOn: null, actionsPending: 0 };
    const c = byRun.get(r.id);
    if (c) {
      const cr = row(c);
      const pend = c.actions.filter(pending);
      const open = isOpen(c);
      const approver = pend[0]?.approverGroup;
      return {
        ...base,
        caseId: c.id,
        queue: c.queue,
        assignee: c.assignee,
        state: stateOf(r),
        waitingOn: r.status !== 'waiting_review' ? null : pend.length ? (approver ?? c.queue) : (c.assignee ?? c.queue),
        slaDueAt: open ? c.slaDueAt : null,
        slaMinutes: cr.slaMinutes,
        actionsApproved: c.actions.filter((a) => a.status === 'approved' || a.status === 'executed').length,
        actionsPending: pend.length,
      };
    }
    const rv = r.reviewId ? reviews.get(r.reviewId) : undefined;
    if (rv) {
      return {
        ...base,
        state: 'waiting',
        queue: rv.policy.reviewers,
        assignee: rv.assignee ?? null,
        waitingOn: rv.assignee ?? rv.policy.reviewers,
        slaDueAt: new Date(Date.now() + (rv.slaMinutes ?? 0) * 60_000).toISOString(),
        slaMinutes: rv.slaMinutes,
        actionsApproved: r.steps.filter(isActionStep).length,
        actionsPending: 1,
      };
    }
    return { ...base, state: stateOf(r), actionsApproved: r.steps.filter(isActionStep).length };
  };

  // Runs started from the console finish at once here; the agents service runs them for real.
  const started: WorkflowRun[] = [];
  const startRun = ({ workflowId, subject }: { workflowId: string; subject: string }): RunRow => {
    const r: WorkflowRun = { id: `RUN-S${started.length + 1}`, workflowId, version: 1, subject, status: 'completed', startedAt: new Date().toISOString(), durationMs: 0, trigger: `Started by ${me}`, steps: [] };
    started.unshift(r);
    return runRow(r, new Map(), new Map());
  };

  /** Every run in the current team, newest first, joined to its email case or review. */
  const runRows = (): RunRow[] => {
    link();
    const byRun = new Map(cases.filter((c) => c.runId).map((c) => [c.runId!, c]));
    const reviews = new Map(deps.reviews().map((r) => [r.id, r]));
    return [...started, ...deps.runs()]
      .filter((r) => inTeam(deps.workflowOwner(r.workflowId)))
      .map((r) => runRow(r, byRun, reviews))
      .sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  };
  const isOpenRun = (r: RunRow) => r.state === 'running' || r.state === 'waiting';
  const inRunView = (r: RunRow, v: RunView) =>
    v === 'needs_person'
      ? r.state === 'waiting'
      : v === 'open'
        ? isOpenRun(r)
        : v === 'past_sla'
          ? isOpenRun(r) && (r.slaMinutes ?? 0) < 0
          : r.state === 'done' && new Date(r.startedAt).toDateString() === new Date().toDateString();
  // Overdue first, then the least time left; runs with no SLA follow, newest first.
  const bySla = (a: RunRow, b: RunRow) => (a.slaMinutes ?? Infinity) - (b.slaMinutes ?? Infinity) || b.startedAt.localeCompare(a.startedAt);

  const listRuns: CasesApi['runs'] = (p) =>
    respond((m) => {
      const rows = runRows();
      const scoped = rows.filter((r) => inRunView(r, p.view));
      if (p.view !== 'done_today') scoped.sort(bySla);
      const result = list(scoped, p, { text: (r) => `${r.id} ${r.subject} ${r.workflowName} ${r.caseId ?? ''}`, value: (r, k) => (k === 'queue' ? (r.queue ? [r.queue] : []) : k === 'parent' ? (r.parentThreadId ? [r.parentThreadId] : []) : String((r as unknown as Record<string, unknown>)[k])), facetKeys: ['workflowId', 'state', 'queue'] }, m);
      const src = m === 'empty' ? [] : rows;
      const count = (v: RunView) => src.filter((r) => inRunView(r, v)).length;
      return { ...result, viewCounts: { needs_person: count('needs_person'), open: count('open'), past_sla: count('past_sla'), done_today: count('done_today') } };
    });
  const getRun: CasesApi['run'] = (id) => respond((m) => (m === 'empty' ? notFound('Run') : (runRows().find((r) => r.id === id) ?? notFound('Run'))));
  const assignRuns: CasesApi['assignRuns'] = (ids, assignee) =>
    respond(() => {
      const rows = new Map(runRows().map((r) => [r.id, r]));
      return bulk(ids, (id) => {
        const r = rows.get(id);
        if (!r) return 'Not found';
        if (r.reviewId) return 'Paused at a review gate; assign it in Reviews';
        if (!r.caseId) return 'Nothing waits on a person';
        const c = caseOr404(r.caseId);
        if (!isOpen(c)) return 'Closed';
        if (c.assignee === assignee) return `Already with ${assignee}`;
        c.assignee = assignee;
        if (c.status === 'new') c.status = 'in_progress';
        log(c, 'assigned', `Assigned to ${assignee}`);
      });
    });

  /** Overview counts: runs across workflows that wait on a person. */
  const runStats = () => {
    const open = runRows().filter((r) => r.state === 'waiting');
    return { open: open.length, breaching: open.filter((r) => (r.slaMinutes ?? 0) < 0).length, awaitingApproval: open.filter((r) => r.actionsPending > 0).length };
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

  return { api, stats: () => runStats(), slaByQueue, pausedRunIds };
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
