import type { CaseRecordDetail } from '@/lib/types/case-records';
import type { Review } from '@/lib/types/domain';
import type { DefinitionView, EngineRunDetail } from '@/lib/types/engine';
import type { CardFact, CardStatus, CardStep, OpsCardRef, OpsCardSpec } from '@/lib/types/ops-card';

import { dateTime, money } from './format.ts';

/**
 * A card's record as its card draws it (c-469): the facts a person decides on, formatted by type, never raw JSON or
 * engine keys. Pure, so each record type's rules are tested without a page.
 */

const words = (key: string) => key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
const facts = (list: (CardFact | null | false | '' | undefined)[]): CardFact[] => list.filter((f): f is CardFact => !!f && !!f.value);

const CASE_STATUS: Record<string, CardStatus> = {
  open: { text: 'Open', tone: 'info' },
  waiting_on_customer: { text: 'Waiting on the customer', tone: 'neutral' },
  waiting_on_us: { text: 'Waiting on us', tone: 'warning' },
  resolved: { text: 'Resolved', tone: 'success' },
  closed: { text: 'Closed', tone: 'neutral' },
};

export function caseCard(c: CaseRecordDetail): OpsCardSpec {
  const due = c.timer?.dueAt ?? c.resolutionDueAt;
  const late = (c.timer?.leftS ?? c.resolutionLeftS ?? 1) < 0;
  return {
    id: `case-${c.id}`,
    record: { type: 'case', label: c.caseType ? `Case · ${c.caseType.name}` : 'Case', href: `/cases/${encodeURIComponent(c.id)}`, open: 'Open case' },
    title: c.subject,
    subtitle: c.customerName ?? undefined,
    status: CASE_STATUS[c.status] ?? { text: words(c.status), tone: 'neutral' },
    body: {
      kind: 'facts',
      facts: facts([
        { label: 'Owner', value: c.owner?.name ?? c.assignee ?? 'Nobody yet' },
        { label: 'Priority', value: words(c.priority) },
        due && { label: c.timer?.label ?? 'Due', value: dateTime(due), warn: late },
        c.whatsLeft && c.whatsLeft.items.length > 0 && { label: 'Waiting on', value: c.whatsLeft.items.map((i) => i.what).join('; ') },
      ]),
    },
  };
}

/** Whether a Human Task card offers its decision: open, the reader may decide it, and it is a plain approve or reject. */
export type TaskDecision = 'buttons' | 'open-only' | 'decided';

export function taskDecision(r: Review): TaskDecision {
  if (!['pending', 'in_review'].includes(r.status)) return 'decided';
  if (!r.canDecide) return 'open-only';
  // Options, a read to correct or conditions to attach need the task's own page.
  if ((r.options && r.options.length > 0) || r.read?.editable || r.kind === 'model_validation') return 'open-only';
  return 'buttons';
}

const DECIDED: Record<string, { word: string; tone: CardStatus['tone'] }> = {
  approved: { word: 'Approved', tone: 'success' },
  rejected: { word: 'Rejected', tone: 'danger' },
  returned: { word: 'Returned', tone: 'neutral' },
};

export function taskCard(r: Review): OpsCardSpec {
  const decision = taskDecision(r);
  const done = DECIDED[r.status];
  const status: CardStatus = done
    ? { text: r.decidedBy ? `${done.word} by ${r.decidedBy}` : done.word, tone: done.tone }
    : decision === 'buttons'
      ? { text: 'Waiting for you', tone: 'warning' }
      : { text: `Waiting for ${r.policy?.reviewers ?? 'a reviewer'}`, tone: 'neutral' };
  return {
    id: `task-${r.id}`,
    record: { type: 'task', label: r.workflowName ? `Human Task · ${r.workflowName}` : 'Human Task', href: `/reviews/${encodeURIComponent(r.id)}`, open: 'Open in Human Tasks' },
    title: r.title,
    subtitle: r.customer || undefined,
    status,
    body: {
      kind: 'facts',
      facts: facts([
        r.amount != null && { label: 'Amount', value: money(r.amount, r.currency), warn: !!r.stepUp },
        // A workflow step's proposal is the data it carries, not words; only a sentence is shown.
        r.proposal && !/^\s*[[{]/.test(r.proposal) && { label: 'Proposed', value: r.proposal },
        r.decidedAt && { label: 'Decided', value: dateTime(r.decidedAt) },
        !r.decidedAt && r.createdAt && { label: 'Asked', value: dateTime(r.createdAt) },
      ]),
    },
  };
}

const RUN_STATUS: Record<string, CardStatus> = {
  queued: { text: 'Queued', tone: 'neutral' },
  running: { text: 'Running', tone: 'info' },
  waiting: { text: 'Waiting for a person', tone: 'warning' },
  succeeded: { text: 'Done', tone: 'success' },
  failed: { text: 'Failed', tone: 'danger' },
  cancelled: { text: 'Cancelled', tone: 'neutral' },
};

export function runCard(run: EngineRunDetail): OpsCardSpec {
  const lines = run.story?.lines ?? [];
  const live = ['queued', 'running', 'waiting'].includes(run.status);
  const steps: CardStep[] = lines.slice(-4).map((l) => ({ title: l.text, state: 'done' }));
  if (live) steps.push({ title: run.status === 'waiting' ? 'Waiting for a person to decide' : 'Working on the next step', state: run.status === 'waiting' ? 'pending' : 'running' });
  if (run.status === 'failed' && run.error) steps.push({ title: run.error, state: 'failed' });
  const status = RUN_STATUS[run.status] ?? { text: words(run.status), tone: 'neutral' };
  return {
    id: `run-${run.id}`,
    record: { type: 'run', label: 'Workflow run', href: `/workflows/runs/${encodeURIComponent(run.id)}`, open: 'Open run' },
    title: run.workflowName ?? words(run.workflowId),
    subtitle: run.outcomeText ?? undefined,
    status: run.status === 'succeeded' && run.outcomeText ? { text: run.outcomeText, tone: 'success' } : status,
    body: steps.length ? { kind: 'steps', steps } : { kind: 'none' },
  };
}

export function startCard(d: DefinitionView): OpsCardSpec {
  return {
    id: `start-${d.workflowId}`,
    record: { type: 'start', label: 'Start a workflow', href: `/workflows/definitions/${encodeURIComponent(d.workflowId)}`, open: 'Open workflow' },
    title: d.startForm?.title ?? d.name ?? words(d.workflowId),
    subtitle: d.name && d.startForm?.title !== d.name ? d.name : undefined,
    body: { kind: 'none' },
  };
}

const NOUN: Record<OpsCardRef['type'], string> = { case: 'case', task: 'Human Task', run: 'run', start: 'workflow' };

/** A reference the reader cannot see: gone, or in a team they are not in. It says so and offers nothing. */
export function missingCard(ref: OpsCardRef): OpsCardSpec {
  return {
    id: `missing-${ref.type}-${ref.id}`,
    record: { type: ref.type, label: words(NOUN[ref.type]), href: ref.type === 'task' ? '/reviews' : ref.type === 'case' ? '/cases' : '/workflows', open: 'Go to the list' },
    title: `This ${NOUN[ref.type]} isn’t available to you`,
    subtitle: 'It may have been removed, or it belongs to a team you aren’t in.',
    body: { kind: 'none' },
  };
}
