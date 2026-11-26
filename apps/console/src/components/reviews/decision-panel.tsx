'use client';

import * as React from 'react';
import Link from 'next/link';
import { ChevronDown, ChevronUp, Ellipsis } from 'lucide-react';

import { EvidenceExportButton } from '@/components/files/file-actions';
import type { ReadChecks, ReadEdits } from '@/components/reviews/document-read';
import { isOpen } from '@/components/reviews/review-columns';
import { TaskDecision } from '@/components/reviews/task-decision';
import type { useReviewDecider } from '@/components/reviews/use-review-decider';
import { KIND_LABEL, ReviewStatusBadge, RiskBadge, SlaText } from '@/components/status-badges';
import { TaskDecide } from '@/components/tasks/task-page';
import { ConnectWait } from '@/components/reviews/connect-wait';
import type { TaskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { money } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Review, ReviewPlace } from '@/lib/types/domain';

/**
 * The decision, top to bottom (layout A): where the task comes from and what is asked; what decides it (the
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
  onAssignToMe,
  place,
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
  /** Takes the task for the person; offered to a decider while it is not already theirs. */
  onAssignToMe: () => void;
  /** Its place in the queue, with a way to open the task either side (the bar's up and down). */
  place?: ReviewPlace & { onGo: (id: string) => void };
  className?: string;
}) {
  const open = isOpen(review);
  const canDecide = open && review.canDecide !== false;
  // Each is offered only when its route will accept it; the server says so per person (hitl_facade.with_rights). The
  // mock sends no rights, so it falls back to whether the person may decide.
  const canAssign = review.canAssign ?? (canDecide && !me.includes(review.assignee ?? ''));
  const canReassign = review.canReassign ?? (canDecide && !!review.assignee);
  // A person who may not act on the task sees no menu at all, as the mock's member view draws it.
  const more = canAssign || canReassign || (canDecide && !!review.caseId);
  return (
    <aside className={cn('flex min-h-0 min-w-0 flex-col rounded-lg border bg-card', className)} aria-label="Decision" data-testid="decision-panel">
      {/* The pinned bar: up and down through the queue, then the task's own actions under More. */}
      <div className="flex items-center gap-1 border-b px-2 py-1.5" data-testid="task-bar">
        {place && (
          <>
            <Button type="button" variant="ghost" size="icon" aria-label="Previous task" disabled={!place.previous} onClick={() => place.previous && place.onGo(place.previous)} data-testid="task-previous">
              <ChevronUp />
            </Button>
            <Button type="button" variant="ghost" size="icon" aria-label="Next task" disabled={!place.next} onClick={() => place.next && place.onGo(place.next)} data-testid="task-next">
              <ChevronDown />
            </Button>
            {place.position != null && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {place.position} of {place.total}
              </span>
            )}
          </>
        )}
        {more && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="outline" size="icon" className="ml-auto" aria-label="More actions" data-testid="task-more">
                <Ellipsis />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {canAssign && !me.includes(review.assignee ?? '') && (
                <DropdownMenuItem onSelect={onAssignToMe} data-testid="assign-to-me">
                  Assign to me
                </DropdownMenuItem>
              )}
              {(canAssign || canReassign) && (
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger data-testid="reassign">{review.assignee ? 'Reassign…' : 'Assign to…'}</DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="w-56">
                    <DropdownMenuLabel>{review.assignee ? 'Reassign this task to' : 'Assign this task to'}</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {reviewers.length ? (
                      reviewers.map((p) => (
                        <DropdownMenuItem key={p} onSelect={() => onReassign(p)} data-testid={`reassign-to-${p}`}>
                          {p}
                        </DropdownMenuItem>
                      ))
                    ) : (
                      <DropdownMenuLabel className="font-normal text-muted-foreground">No one else can be assigned</DropdownMenuLabel>
                    )}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              )}
              {canDecide && review.caseId && (
                <DropdownMenuItem asChild>
                  <Link href={`/work/cases/${review.caseId}`} data-testid="open-case">
                    Open case
                  </Link>
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
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
        {review.amount != null && (
          // The currency the step names, or the bare amount when it names none.
          <p className="text-lg font-semibold tabular-nums" data-testid="decision-amount">
            {money(review.amount, review.currency ?? null)}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <ReviewStatusBadge status={review.status} />
          <RiskBadge risk={review.risk} named />
          {(review.approvalsNeeded ?? 1) > 1 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap" data-testid="task-approvals">
              {review.approvals.length} of {review.approvalsNeeded} approvals
            </span>
          )}
          {review.decidingTeam && <span data-testid="task-deciding-team">{review.decidingTeam.name ?? review.decidingTeam.id} decides</span>}
          {review.runId && review.stepName ? (
            <Link href={`/build/runs/${review.runId}`} className="underline underline-offset-2" data-testid="review-run-link">
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

      {/* A run waiting for a person's account is not decided: the person connects, or the run goes on as the team account. */}
      {review.kind === 'connect_account' ? (
        <ConnectWait review={review} />
      ) : (
      <TaskDecision review={review} view={view} checks={checks} decider={decider} me={me} owners={owners} platformTeam={platformTeam} layout="panel">
        {({ choice, decide }) => (
          <>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="decision-body">
              <TaskDecide review={review} view={view} edits={edits} onEdit={canDecide && review.read?.editable ? onEdit : undefined} checks={canDecide ? checks : undefined} between={choice} />
            </div>
            {/* Sticky for the one-pane phone view, where the page scrolls; beside the evidence the panel is bounded and never moves. */}
            <footer className="sticky bottom-0 flex flex-col gap-2 rounded-b-lg border-t bg-card p-4 [&_[data-layout=footer]]:border-t-0 [&_[data-layout=footer]]:p-0" data-testid="decision-footer">
              {decide}
              <div className="flex flex-wrap gap-2">
                {(review.kind === 'publish_request' || review.kind === 'model_validation') && <EvidenceExportButton input={{ kind: 'publish_request', reviewId: review.id }} />}
              </div>
            </footer>
          </>
        )}
      </TaskDecision>
      )}
    </aside>
  );
}
