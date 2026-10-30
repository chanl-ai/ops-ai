'use client';

import * as React from 'react';
import Link from 'next/link';
import { BookOpen, Bot, Clock, ShieldCheck, Users, Wrench } from 'lucide-react';

import { FieldSectionLabel } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows } from '@/components/shared/surface';
import { ConfidenceBar, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { dateTime, money } from '@/lib/format';
import type { OperationSummary, Review, ReviewDecision } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

import { TemplateSubmissionBody } from '@/components/agents/template-review-body';
import { SkillPublishBody } from '@/components/skills/skill-review-body';
import { AgentPublishBody } from '@/components/agents/agent-publish-review-body';

import { DocumentReadSection, type ReadChecks, type ReadEdits, ReplySection } from './document-read';
import { ModelValidationBody, PublishEvalSection } from './model-validation';
import { isOpen } from './review-columns';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <FieldSectionLabel>{title}</FieldSectionLabel>
      {children}
    </section>
  );
}

/** Read-only body of a review: proposal, the gate that paused it, the agent's case, and history. */
function PublishRequestBody({ review }: { review: Review }) {
  const p = review.publish!;
  const v = p.validation;
  return (
    <div className="flex flex-col gap-6">
      <Section title="Publish request">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium">{p.note}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {review.workflowName} · v{p.fromVersion} → v{p.toVersion} · requested by {p.requestedBy}
          </p>
        </div>
      </Section>
      <Section title={`Changes · ${p.changes.length}`}>
        {p.changes.length ? (
          <ul className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
            {p.changes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Only positions changed.</p>
        )}
      </Section>
      <PublishEvalSection review={review} validation={v} />
      {!isOpen(review) && (review.decidedBy || review.decisionReason) && (
        <Section title="Decision">
          <DecidedBy review={review} />
          {review.decisionReason && <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>}
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Approving publishes v{p.toVersion}. Deployments keep serving the version they are on until moved.{' '}
        <Link href={`/workflows/definitions/${encodeURIComponent(review.workflowId)}`} className="underline underline-offset-2">
          Open the workflow
        </Link>
        {' · '}
        <Link href="/assurance?tab=gates" className="underline underline-offset-2" data-testid="open-gate-in-assurance">
          Open gate in Assurance
        </Link>
      </p>
    </div>
  );
}

function OperationRow({ op, tone, note }: { op: OperationSummary; tone: string; note?: string }) {
  return (
    <Row
      title={<code className="font-mono text-sm">{op.name}</code>}
      description={[op.method, op.path].filter(Boolean).join(' ') || undefined}
      trailing={
        <span className="text-[11px] text-muted-foreground">
          {tone} · {op.access}
          {note ? ` · ${note}` : ''}
        </span>
      }
    />
  );
}

/** A tool module review (c-204): what the version adds, removes and changes since the published one, the hosts it
 * would reach and the secrets it reads, as tools-service sent them when the review opened. */
function ToolModuleReviewBody({ review }: { review: Review }) {
  const t = review.toolModule!;
  const d = t.diff;
  const count = d ? d.added.length + d.removed.length + d.changed.length : 0;
  return (
    <div className="flex flex-col gap-6" data-testid="tool-module-review">
      <Section title="Tool module">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <Link href={`/tools/${t.moduleId}`} className="text-sm font-medium underline underline-offset-2" data-testid="review-module-link">
            {review.workflowName}
          </Link>
          <p className="mt-2 text-xs text-muted-foreground">
            v{t.version}
            {review.proposal ? ` · ${review.proposal}` : ''}
          </p>
        </div>
      </Section>
      {d ? (
        <>
          <Section title={`Operations · ${count}`}>
            {count ? (
              <Rows className="rounded-lg border" testId="review-operations">
                {d.added.map((o) => <OperationRow key={`a-${o.name}`} op={o} tone="Added" />)}
                {d.changed.map((o) => <OperationRow key={`c-${o.name}`} op={o} tone="Changed" note={o.fields.join(', ')} />)}
                {d.removed.map((o) => <OperationRow key={`r-${o.name}`} op={o} tone="Removed" />)}
              </Rows>
            ) : (
              <p className="text-sm text-muted-foreground">No operation changed; only settings did.</p>
            )}
          </Section>
          <Section title="Hosts it would reach for the first time">
            {d.hostsAdded.length ? (
              <Rows className="rounded-lg border" testId="review-hosts">
                {d.hostsAdded.map((h) => <Row key={h} title={<code className="font-mono text-sm">{h}</code>} />)}
              </Rows>
            ) : (
              <p className="text-sm text-muted-foreground">None new.</p>
            )}
          </Section>
          <Section title="Secrets its operations read">
            {d.secrets.length ? (
              <Rows className="rounded-lg border" testId="review-secrets">
                {d.secrets.map((s) => <Row key={s} title={<code className="font-mono text-sm">{s}</code>} />)}
              </Rows>
            ) : (
              <p className="text-sm text-muted-foreground">None.</p>
            )}
          </Section>
        </>
      ) : (
        <Section title={`Changes · ${review.reasoning.length}`}>
          <ul className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
            {review.reasoning.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Section>
      )}
      {!isOpen(review) && (review.decidedBy || review.decisionReason) && (
        <Section title="Decision">
          <DecidedBy review={review} />
          {review.decisionReason && <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>}
        </Section>
      )}
    </div>
  );
}

/** A workflow's document check or reply step: what was read, or what will be sent, is the whole case for it (c-169). */
function WorkflowStepBody({ review, edits, onEdit, checks }: { review: Review; edits: ReadEdits; onEdit?: (record: number, key: string, text: string) => void; checks?: ReadChecks }) {
  return (
    <div className="flex flex-col gap-6">
      {review.read && (
        <Section title="Document read">
          <DocumentReadSection read={review.read} open={isOpen(review) && !!onEdit} edits={edits} onEdit={(i, k, t) => onEdit?.(i, k, t)} confirmed={checks?.confirmed} onConfirm={checks?.onConfirm} />
        </Section>
      )}
      {review.reply && (
        <Section title="Reply">
          <ReplySection reply={review.reply} />
        </Section>
      )}
      {!isOpen(review) && (review.decidedBy || review.decisionReason) && (
        <Section title="Decision">
          <DecidedBy review={review} />
          {review.decisionReason && <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>}
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Paused by{' '}
        <Link href={`/workflows/${review.workflowId}`} className="underline underline-offset-2">
          {review.workflowName}
        </Link>
        {review.caseId && (
          <>
            {' '}on case{' '}
            <Link href={`/cases/${review.caseId}`} className="underline underline-offset-2" data-testid="review-case-link">
              {review.caseId}
            </Link>
          </>
        )}
        .
      </p>
    </div>
  );
}

/** `edits` and `onEdit` hold a reviewer's corrections to a document read while the review is open (c-169). */
export function ReviewDetailBody({
  review,
  edits = {},
  onEdit,
  checks,
}: {
  review: Review;
  edits?: ReadEdits;
  onEdit?: (record: number, key: string, text: string) => void;
  checks?: ReadChecks;
}) {
  if (review.read || review.reply) return <WorkflowStepBody review={review} edits={edits} onEdit={onEdit} checks={checks} />;
  if (review.toolModule) return <ToolModuleReviewBody review={review} />;
  if (review.kind === 'publish_request' && review.publish) return <PublishRequestBody review={review} />;
  if (review.kind === 'model_validation' && review.modelValidation) return <ModelValidationBody review={review} />;
  if (review.kind === 'skill_publish' && review.skillPublish) return <SkillPublishBody review={review} />;
  if (review.kind === 'agent_publish' && review.agentPublish) return <AgentPublishBody review={review} />;
  if (review.kind === 'template_submission' && review.templateSubmission) return <TemplateSubmissionBody review={review} />;
  const { policy } = review;
  return (
    <div className="flex flex-col gap-6">
      <Section title="Proposed action">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium leading-relaxed">{review.proposal}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
            {review.amount != null && <span className="font-semibold text-foreground tabular-nums">{money(review.amount, review.currency)}</span>}
            <span className="flex items-center gap-1.5">
              <Wrench className="size-3.5" /> Runs <code className="font-mono text-foreground">{review.actionTool}</code> on approval
            </span>
          </div>
        </div>
      </Section>

      <Section title="Why it needs a person">
        <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-2">
          <div className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">Gate</dt>
            <dd className="font-medium">{policy.name}</dd>
            <dd className="mt-1 font-mono text-xs text-muted-foreground">{policy.condition}</dd>
          </div>
          <div className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">Reviewers</dt>
            <dd className="flex items-center gap-1.5 font-medium">
              <Users className="size-3.5 text-muted-foreground" /> {policy.reviewers}
            </dd>
            {policy.fourEyes && (
              <dd className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck className="size-3.5" /> Two approvers · {review.approvals.length} of 2 so far
              </dd>
            )}
          </div>
          <div className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">SLA · {policy.sla}</dt>
            <dd className="flex items-center gap-1.5">
              <Clock className="size-3.5 text-muted-foreground" /> <SlaText minutes={review.slaMinutes} open={isOpen(review)} />
            </dd>
          </div>
          <div className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">If no decision</dt>
            <dd className="font-medium">{policy.onTimeout}</dd>
          </div>
        </dl>
      </Section>

      <Section title="Agent reasoning">
        <div className="rounded-lg border p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-sm">
              <Bot className="size-4 text-muted-foreground" /> <span className="font-medium">{review.agentName ?? review.agentSlug}</span>
            </span>
            <ConfidenceBar value={review.confidence} />
          </div>
          <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm text-muted-foreground marker:text-muted-foreground/60">
            {review.reasoning.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ol>
        </div>
      </Section>

      <Section title={`Evidence · ${review.evidence.length}`}>
        <Rows className="rounded-lg border">
          {review.evidence.map((e) => (
            <Row
              key={e.label}
              leading={
                <div className="flex size-7 items-center justify-center rounded-md bg-muted">
                  {e.kind === 'tool' ? <Wrench className="size-3.5 text-muted-foreground" /> : <BookOpen className="size-3.5 text-muted-foreground" />}
                </div>
              }
              title={<span className={cn('font-normal', e.kind === 'tool' && 'font-mono text-xs')}>{e.label}</span>}
              description={e.detail}
              trailing={<span className="text-[11px] text-muted-foreground">{e.kind === 'tool' ? 'Tool call' : 'Knowledge'}</span>}
            />
          ))}
        </Rows>
      </Section>

      {!isOpen(review) && (review.decidedBy || review.decisionReason || review.stepUpRef) && (
        <Section title="Decision">
          <DecidedBy review={review} />
          {review.decisionReason && <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>}
          {review.stepUpRef && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="review-step-up">
              <ShieldCheck className="size-3.5 text-success-text" /> Approved with step-up · <code className="font-mono">{review.stepUpRef}</code>
            </p>
          )}
        </Section>
      )}

      {review.origin?.kind === 'chat' ? (
        <p className="text-xs text-muted-foreground">
          Held in a conversation with {review.origin.agentName}; approving here resumes it.{' '}
          <Link href={`/chat/${review.origin.threadId}`} className="underline underline-offset-2" data-testid="review-open-conversation">
            Open the conversation
          </Link>
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Paused by the <Link href="/settings/policies" className="underline underline-offset-2" data-testid="review-gate-link">{policy.name}</Link> gate in{' '}
          <Link href={`/workflows/${review.workflowId}`} className="underline underline-offset-2">
            {review.workflowName}
          </Link>
          .
        </p>
      )}
    </div>
  );
}

const DECIDED: Record<string, string> = { approved: 'Approved', rejected: 'Rejected', returned: 'Returned' };

/** Who decided a review and when, from the API; nothing for a decision recorded before it named the decider. */
export function DecidedBy({ review }: { review: Review }) {
  if (!review.decidedBy) return null;
  return (
    <p className="mb-2 text-sm" data-testid="review-decided-by">
      {DECIDED[review.status] ?? 'Decided'} by <span className="font-medium">{review.decidedBy}</span>
      {review.decidedAt && <span className="text-muted-foreground"> · {dateTime(review.decidedAt)}</span>}
    </p>
  );
}

/**
 * Decision form shown at the bottom of an open review. Approve needs no reason; reject and return do,
 * because the reason is what the agent receives and what auditors read.
 */
export function ReviewDecisionForm({
  review,
  currentUser,
  pending,
  onDecide,
  platformTeam = true,
  layout = 'sheet',
  consequence,
  approveBlocked,
}: {
  review: Review;
  /** `sheet` sticks to the bottom of a side sheet's scroll; `footer` is a row of a page grid that sits below the body. */
  layout?: 'sheet' | 'footer';
  /** The page footer's one line: what the main action does. */
  consequence?: string;
  /** Why Approve waits ("confirm 2 key fields first"); the button says it and stays off. */
  approveBlocked?: string;
  /** Every way the deciding person is recorded: their name, and their email under platform sign-in, where requests record the email. */
  currentUser?: string[];
  pending: ReviewDecision | null;
  /** `addTestCase` is set on reject or return when the review names a suite (`review.testTarget`). */
  onDecide: (decision: ReviewDecision, reason: string, addTestCase?: boolean) => void;
  /** Template submissions are decided by the platform team only. */
  platformTeam?: boolean;
}) {
  const [reason, setReason] = React.useState('');
  const [missing, setMissing] = React.useState(false);
  // On by default: a rejected action is the cheapest test case the suite will ever get.
  const [addTestCase, setAddTestCase] = React.useState(true);
  React.useEffect(() => {
    setReason('');
    setMissing(false);
    setAddTestCase(true);
  }, [review.id]);

  const gate = review.kind === 'publish_request' ? review.publish?.evalGate : undefined;
  const blocked = !!gate?.blockers.length || !!review.agentPublish?.blockers.length;
  const reasonToApprove = !!gate?.reasonRequired || !!review.skillPublish?.failing.length || !!review.agentPublish?.failing;
  const submit = (decision: ReviewDecision) => {
    if ((decision !== 'approved' || reasonToApprove) && !reason.trim()) return setMissing(true);
    setMissing(false);
    onDecide(decision, reason.trim(), decision !== 'approved' && !!review.testTarget && addTestCase);
  };
  const needsSecond = review.policy.fourEyes && review.approvals.length === 0;
  const mine = (who?: string) => !!who && !!currentUser?.includes(who);
  const alreadyApproved = review.approvals.some(mine);
  const ownPublish =
    (review.kind === 'publish_request' && mine(review.publish?.requestedBy)) || (review.kind === 'skill_publish' && mine(review.skillPublish?.requestedBy)) || (review.kind === 'template_submission' && mine(review.templateSubmission?.submittedBy)) ||
    // Maker-checker on agents covers whoever saved the version as well as whoever requested it.
    (review.kind === 'agent_publish' && (mine(review.agentPublish?.requestedBy) || mine(review.agentPublish?.savedBy)));
  const isPublish = review.kind === 'publish_request' || review.kind === 'agent_publish' || review.kind === 'skill_publish' || review.kind === 'template_submission';
  const isTemplate = review.kind === 'template_submission';
  // The page footer is one row until an action needs a reason (or one is being typed); the sheet always shows the box.
  const showReason = layout === 'sheet' || missing || !!reason || reasonToApprove;
  const platformOnly = isTemplate && !platformTeam;
  if (platformOnly)
    return (
      <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground" data-testid="review-decision-platform-only">
        The platform team decides template submissions. You will be notified of the decision.
      </p>
    );

  return (
    <div
      className={cn(
        'flex flex-col gap-3 border-t bg-background',
        layout === 'sheet' ? 'sticky bottom-0 -mx-6 -mb-4 px-6 py-4 shadow-[0_-4px_12px_-8px_rgb(0_0_0/0.15)]' : 'px-4 py-3 lg:px-6',
      )}
      data-testid="review-decision-form"
      data-layout={layout}
    >
      {showReason && (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="decision-reason">
          Reason <span className="font-normal text-muted-foreground">{reasonToApprove ? `(required: explain the failing ${review.kind === 'skill_publish' ? 'tests' : 'evals'} to approve, or to reject or return)` : '(required to reject or return)'}</span>
        </Label>
        <Textarea
          id="decision-reason"
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
            setMissing(false);
          }}
          aria-invalid={missing}
          placeholder={isPublish ? 'e.g. Tests cover the new deferral path; approving for month-end' : 'e.g. Amount matches the statement; customer confirmed by phone'}
          className={cn('resize-none bg-card', layout === 'footer' ? 'min-h-10' : 'min-h-20')}
          rows={layout === 'footer' ? 1 : undefined}
          // In the footer the box appears when an action asks for a reason, so the cursor goes straight to it.
          autoFocus={layout === 'footer'}
        />
        {missing ? (
          <p className="text-xs text-destructive">{reasonToApprove ? 'Add a reason. Approving with failing evals needs one, and so do reject and return.' : 'Add a reason before rejecting or returning this review.'}</p>
        ) : (
          <p className="text-xs text-muted-foreground">Recorded in the audit log and sent to the {isTemplate ? 'submitter' : isPublish ? 'requester' : 'agent'}.</p>
        )}
      </div>
      )}
      {showReason && review.testTarget && (
        <div className="flex items-start gap-2">
          <Checkbox id="add-test-case" checked={addTestCase} onCheckedChange={(v) => setAddTestCase(v === true)} className="mt-0.5" data-testid="add-test-case" />
          <Label htmlFor="add-test-case" className="flex flex-col items-start gap-0.5 font-normal">
            <span>Add this as a test case to {review.testTarget.name}&apos;s suite</span>
            <span className="text-xs text-muted-foreground">Applies when you reject or return. The case is a draft until its owner activates it.</span>
          </Label>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {consequence && (
          <p className="min-w-0 basis-full text-sm sm:flex-1 sm:basis-auto" data-testid="review-consequence">
            {consequence}
          </p>
        )}
        {/* A workflow's own step has no agent or requester to return it to: it is approved or rejected. */}
        {(isPublish || !review.runId) && (
          <Button variant="ghost" size="sm" disabled={!!pending} onClick={() => submit('returned')}>
            {isTemplate ? 'Return to submitter' : isPublish ? 'Return to requester' : 'Return to agent'}
          </Button>
        )}
        <div className={cn('ml-auto flex gap-2', layout === 'footer' && 'max-sm:w-full max-sm:*:flex-1')}>
          <LoadingButton variant="outline" size="sm" isLoading={pending === 'rejected'} disabled={!!pending} onClick={() => submit('rejected')}>
            Reject
          </LoadingButton>
          <LoadingButton size="sm" isLoading={pending === 'approved'} disabled={!!pending || alreadyApproved || ownPublish || blocked || !!approveBlocked} onClick={() => submit('approved')} data-testid="review-approve">
            {approveBlocked ? `Approve · ${approveBlocked}` : blocked ? 'Blocked by evals' : ownPublish ? (isTemplate ? 'Another platform member approves' : 'Another publisher approves') : alreadyApproved ? 'Waiting on second approver' : needsSecond ? 'Approve · 1 of 2' : isTemplate ? 'Approve and publish template' : isPublish ? 'Approve and publish' : 'Approve'}
          </LoadingButton>
        </div>
      </div>
    </div>
  );
}
