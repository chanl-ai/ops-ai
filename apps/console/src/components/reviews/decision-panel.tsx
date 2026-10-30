'use client';

import * as React from 'react';
import Link from 'next/link';
import { UserRoundPlus } from 'lucide-react';

import { EvidenceExportButton } from '@/components/files/file-actions';
import type { ReadChecks, ReadEdits } from '@/components/reviews/document-read';
import { isOpen } from '@/components/reviews/review-columns';
import { TaskDecision } from '@/components/reviews/task-decision';
import type { useReviewDecider } from '@/components/reviews/use-review-decider';
import { KIND_LABEL, ReviewStatusBadge, RiskBadge, SlaText } from '@/components/status-badges';
import { TaskDecide } from '@/components/tasks/task-page';
import type { TaskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import type { Review } from '@/lib/types/domain';

/**
 * The decision, top to bottom (c-460, layout A): where the task comes from and what is asked; what decides it (the
 * task's facts, its write and form, Details) with the choice; then Decide, Reassign and the evidence export. The header
 * and the footer never scroll; only the middle does, and only when the window is too short for it.
 */
export function DecisionPanel({
  review,
  view,
  edits,
  onEdit,
  checks,
  decider,
  me,
  owners,
  reviewers,
  platformTeam,
  onReassign,
  className,
}: {
  review: Review;
  view: TaskView;
  edits: ReadEdits;
  onEdit: (record: number, key: string, text: string) => void;
  checks: ReadChecks;
  decider: ReturnType<typeof useReviewDecider>;
  me: string[];
  owners: string[];
  /** People a review can be assigned to. */
  reviewers: string[];
  platformTeam: boolean;
  onReassign: (to: string) => void;
  className?: string;
}) {
  const open = isOpen(review);
  const canDecide = open && review.canDecide !== false;
  return (
    <aside className={cn('flex min-h-0 min-w-0 flex-col rounded-lg border bg-card', className)} aria-label="Decision" data-testid="decision-panel">
      <header className="flex flex-col gap-2 border-b p-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{KIND_LABEL[review.kind]}</span>
          {review.caseTitle && (
            <>
              <span aria-hidden>·</span>
              <span className="truncate" data-testid="decision-case">
                {review.caseTitle}
              </span>
            </>
          )}
          <span aria-hidden>·</span>
          <SlaText minutes={review.slaMinutes} open={open} />
          <span aria-hidden>·</span>
          <span>{review.assignee ? `Assigned to ${review.assignee}` : 'Unassigned'}</span>
        </div>
        <h2 className="text-base leading-snug font-semibold" data-testid="decision-question">
          {view.question}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <ReviewStatusBadge status={review.status} />
          <span className="inline-flex items-center gap-1.5">
            Risk <RiskBadge risk={review.risk} />
          </span>
          {review.decidingTeam && <span data-testid="task-deciding-team">{review.decidingTeam.name ?? review.decidingTeam.id} decides</span>}
          {review.runId && review.stepName ? (
            <Link href={`/workflows/runs/${review.runId}`} className="underline underline-offset-2" data-testid="review-run-link">
              {review.workflowName}
              {review.workflowVersion != null ? ` v${review.workflowVersion}` : ''} · {review.stepName}
            </Link>
          ) : review.origin?.kind === 'chat' ? (
            <Link href={`/chat/${review.origin.threadId}`} className="underline underline-offset-2" data-testid="review-open-conversation">
              Chat with {review.origin.agentName}
            </Link>
          ) : null}
          {review.customer && <span>{review.customer}</span>}
        </div>
      </header>

      <TaskDecision review={review} view={view} checks={checks} decider={decider} me={me} owners={owners} platformTeam={platformTeam} layout="panel">
        {({ choice, decide }) => (
          <>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="decision-body">
              <TaskDecide review={review} view={view} edits={edits} onEdit={canDecide && review.read?.editable ? onEdit : undefined} checks={canDecide ? checks : undefined} />
              {choice}
            </div>
            {/* Sticky for the one-pane phone view, where the page scrolls; beside the evidence the panel is bounded and never moves. */}
            <footer className="sticky bottom-0 flex flex-col gap-2 rounded-b-lg border-t bg-card p-4 [&_[data-layout=footer]]:border-t-0 [&_[data-layout=footer]]:p-0" data-testid="decision-footer">
              {decide}
              <div className="flex flex-wrap gap-2">
                {open && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button type="button" variant="outline" size="sm" className="flex-1" data-testid="reassign">
                        <UserRoundPlus /> Reassign
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>Reassign this task to</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {reviewers.length ? (
                        reviewers.map((p) => (
                          <DropdownMenuItem key={p} onSelect={() => onReassign(p)} data-testid={`reassign-to-${p}`}>
                            {p}
                          </DropdownMenuItem>
                        ))
                      ) : (
                        <DropdownMenuItem disabled>No one else can be assigned</DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                {(review.kind === 'publish_request' || review.kind === 'model_validation') && <EvidenceExportButton input={{ kind: 'publish_request', reviewId: review.id }} />}
              </div>
            </footer>
          </>
        )}
      </TaskDecision>
    </aside>
  );
}
