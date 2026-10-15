'use client';

import * as React from 'react';
import Link from 'next/link';
import { BookOpen, Bot, Clock, ShieldCheck, Users, Wrench } from 'lucide-react';

import { FieldSectionLabel } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { ConfidenceBar, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { money } from '@/lib/format';
import type { Review, ReviewDecision } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

import { TemplateSubmissionBody } from '@/components/agents/template-review-body';
import { SkillPublishBody } from '@/components/skills/skill-review-body';
import { AgentPublishBody } from '@/components/agents/agent-publish-review-body';

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
      {!isOpen(review) && review.decisionReason && (
        <Section title="Decision">
          <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Approving publishes v{p.toVersion}. Deployments keep serving the version they are on until moved.{' '}
        <Link href={`/workflows/${review.workflowId}?tab=tests`} className="underline underline-offset-2">
          Open the workflow&apos;s tests
        </Link>
        {' · '}
        <Link href="/assurance?tab=gates" className="underline underline-offset-2" data-testid="open-gate-in-assurance">
          Open gate in Assurance
        </Link>
      </p>
    </div>
  );
}

export function ReviewDetailBody({ review }: { review: Review }) {
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
            {review.amount !== undefined && <span className="font-semibold text-foreground tabular-nums">{money(review.amount, review.currency)}</span>}
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
        <ul className="divide-y rounded-lg border">
          {review.evidence.map((e) => (
            <li key={e.label} className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted">
                {e.kind === 'tool' ? <Wrench className="size-3.5 text-muted-foreground" /> : <BookOpen className="size-3.5 text-muted-foreground" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className={cn('truncate text-sm', e.kind === 'tool' && 'font-mono text-xs')}>{e.label}</div>
                <div className="truncate text-xs text-muted-foreground">{e.detail}</div>
              </div>
              <span className="text-[11px] text-muted-foreground">{e.kind === 'tool' ? 'Tool call' : 'Knowledge'}</span>
            </li>
          ))}
        </ul>
      </Section>

      {!isOpen(review) && review.decisionReason && (
        <Section title="Decision">
          <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>
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
          Paused by the <Link href="/reviews/policies" className="underline underline-offset-2">{policy.name}</Link> gate in{' '}
          <Link href={`/workflows/${review.workflowId}`} className="underline underline-offset-2">
            {review.workflowName}
          </Link>
          .
        </p>
      )}
    </div>
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
}: {
  review: Review;
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
  const platformOnly = isTemplate && !platformTeam;
  if (platformOnly)
    return (
      <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground" data-testid="review-decision-platform-only">
        The platform team decides template submissions. You will be notified of the decision.
      </p>
    );

  return (
    <div className="sticky bottom-0 -mx-6 -mb-4 flex flex-col gap-3 border-t bg-background px-6 py-4 shadow-[0_-4px_12px_-8px_rgb(0_0_0/0.15)]" data-testid="review-decision-form">
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
          className="min-h-20 resize-none bg-card"
        />
        {missing ? (
          <p className="text-xs text-destructive">{reasonToApprove ? 'Add a reason. Approving with failing evals needs one, and so do reject and return.' : 'Add a reason before rejecting or returning this review.'}</p>
        ) : (
          <p className="text-xs text-muted-foreground">Recorded in the audit log and sent to the {isTemplate ? 'submitter' : isPublish ? 'requester' : 'agent'}.</p>
        )}
      </div>
      {review.testTarget && (
        <div className="flex items-start gap-2">
          <Checkbox id="add-test-case" checked={addTestCase} onCheckedChange={(v) => setAddTestCase(v === true)} className="mt-0.5" data-testid="add-test-case" />
          <Label htmlFor="add-test-case" className="flex flex-col items-start gap-0.5 font-normal">
            <span>Add this as a test case to {review.testTarget.name}&apos;s suite</span>
            <span className="text-xs text-muted-foreground">Applies when you reject or return. The case is a draft until its owner activates it.</span>
          </Label>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" disabled={!!pending} onClick={() => submit('returned')}>
          {isTemplate ? 'Return to submitter' : isPublish ? 'Return to requester' : 'Return to agent'}
        </Button>
        <div className="ml-auto flex gap-2">
          <LoadingButton variant="outline" size="sm" isLoading={pending === 'rejected'} disabled={!!pending} onClick={() => submit('rejected')}>
            Reject
          </LoadingButton>
          <LoadingButton size="sm" isLoading={pending === 'approved'} disabled={!!pending || alreadyApproved || ownPublish || blocked} onClick={() => submit('approved')}>
            {blocked ? 'Blocked by evals' : ownPublish ? (isTemplate ? 'Another platform member approves' : 'Another publisher approves') : alreadyApproved ? 'Waiting on second approver' : needsSecond ? 'Approve · 1 of 2' : isTemplate ? 'Approve and publish template' : isPublish ? 'Approve and publish' : 'Approve'}
          </LoadingButton>
        </div>
      </div>
    </div>
  );
}
