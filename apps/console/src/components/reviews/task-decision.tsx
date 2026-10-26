'use client';

import * as React from 'react';

import { isOpen } from '@/components/reviews/review-columns';
import { keyFieldsBlock, type ReadChecks } from '@/components/reviews/document-read';
import { ModelValidationDecisionForm } from '@/components/reviews/model-validation';
import { OptionDecisionForm } from '@/components/reviews/option-decision-form';
import { ReviewDecisionForm } from '@/components/reviews/review-detail';
import type { useReviewDecider } from '@/components/reviews/use-review-decider';
import type { TaskView } from '@/components/tasks/task-regions';
import type { Review } from '@/lib/types/domain';

type Decider = ReturnType<typeof useReviewDecider>;

export interface TaskDecisionParts {
  /** What the person chooses between, when the form has a choice of its own (options), else null. */
  choice: React.ReactNode;
  /** The decision itself: the buttons, or the line that says who decides or decided. */
  decide: React.ReactNode;
}

/**
 * How a Human Task is decided, in one place for every surface that decides one (c-460): who decided it once closed;
 * that another team decides it; a model validation's form; a typed task's actions or a step's options; else approve,
 * reject and return. `sheet` is the All tasks quick view, `panel` the queue's decision panel, which keeps Decide in its
 * fixed footer and the choice in its scrolling middle. The forms are imported nowhere else (check-standards).
 */
export function TaskDecision({
  review,
  view,
  checks,
  decider,
  me,
  owners,
  platformTeam,
  layout,
  children,
}: {
  review: Review;
  view: TaskView | null;
  checks: ReadChecks;
  decider: Decider;
  me: string[];
  owners: string[];
  platformTeam: boolean;
  layout: 'sheet' | 'panel';
  children: (parts: TaskDecisionParts) => React.ReactNode;
}) {
  const { onDecide, onOption, pendingDecision, pendingOption } = decider;
  const panel = layout === 'panel';
  if (!isOpen(review))
    return (
      <>
        {children({
          choice: null,
          decide: (
            <p className="text-sm text-muted-foreground" data-testid="task-decided">
              {review.decidedBy ? `Decided by ${review.decidedBy}` : 'Decided'}
              {review.decisionReason ? `: ${review.decisionReason}` : ''}
            </p>
          ),
        })}
      </>
    );
  if (review.canDecide === false)
    return (
      <>
        {children({
          choice: null,
          decide: (
            <p className="text-sm text-muted-foreground" data-testid="review-decided-by">
              A reviewer or admin of the team that reviews this decides it.
            </p>
          ),
        })}
      </>
    );
  if (review.kind === 'model_validation')
    return <>{children({ choice: <ModelValidationDecisionForm review={review} currentUser={me} owners={owners} pending={pendingDecision} onDecide={onDecide} />, decide: null })}</>;
  const actions = view?.actions;
  if (actions?.length)
    return (
      // A typed task decides by its type's actions, each posting its port.
      <OptionDecisionForm
        reviewId={review.id}
        options={actions.map((a) => ({ name: a.port, label: a.label, consequence: a.consequence, inputs: a.inputs, reason: a.reason, tone: a.tone, stepUp: a.port === 'approve' ? review.stepUp : undefined }))}
        blocked={Object.fromEntries(actions.filter((a) => a.requires === 'key_fields_confirmed' || a.port === 'approve').map((a) => [a.port, keyFieldsBlock(view?.read, checks.confirmed)]))}
        suggested={actions.find((a) => a.name === view?.suggested)?.port}
        pending={pendingOption}
        onDecide={onOption}
        layout={panel ? 'panel' : 'sheet'}
        parts={panel ? children : undefined}
      />
    );
  if (review.options?.length)
    return panel ? (
      <OptionDecisionForm reviewId={review.id} options={review.options} pending={pendingOption} onDecide={onOption} layout="panel" parts={children} />
    ) : (
      <>{children({ choice: null, decide: <OptionDecisionForm reviewId={review.id} options={review.options} pending={pendingOption} onDecide={onOption} /> })}</>
    );
  return (
    <>
      {children({
        choice: null,
        decide: (
          <ReviewDecisionForm
            review={review}
            currentUser={me}
            pending={pendingDecision}
            layout={panel ? 'footer' : 'sheet'}
            approveBlocked={keyFieldsBlock(review.read, checks.confirmed)}
            consequence={panel ? view?.consequence || undefined : undefined}
            onDecide={(d, reason, addTestCase) => onDecide(d, reason, undefined, undefined, addTestCase)}
            platformTeam={platformTeam}
          />
        ),
      })}
    </>
  );
}
