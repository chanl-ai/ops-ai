'use client';

import * as React from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, UserCheck, X } from 'lucide-react';

import { KindView } from '@/components/chat/widgets/kind-view';
import { PageLayout } from '@/components/page-layout';
import type { ReadChecks, ReadEdits } from '@/components/reviews/document-read';
import { isOpen } from '@/components/reviews/review-columns';
import { ReviewDetailBody } from '@/components/reviews/review-detail';
import { ReviewStatusBadge, RiskBadge, SlaText } from '@/components/status-badges';
import type { TaskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import type { Review } from '@/lib/types/domain';

export interface TaskQueue {
  /** 1-based place in the open queue; absent once the task has left it (decided). */
  position?: number;
  total?: number;
  onPrev?: () => void;
  onNext?: () => void;
  /** Back to the queue. */
  onClose?: () => void;
}

/**
 * A Human Task as a record page. PageLayout draws the header: the question, where the task came from, its status, and
 * the queue's Previous and Next. Its content is a grid of body and footer where only the body scrolls and the footer
 * is a row below it, so the decision never covers what is being read. With evidence (a document, an email) the body
 * is two panes from 1024px, evidence first at 55%; below that one pane at a time behind an Evidence and Decide switch.
 * Without evidence, one column of about 760px.
 */
export function TaskPage({
  review,
  view,
  queue,
  edits,
  onEdit,
  checks,
  footer,
}: {
  review: Review;
  view: TaskView;
  queue: TaskQueue;
  edits: ReadEdits;
  onEdit?: (record: number, key: string, text: string) => void;
  /** Key-field confirmations, while the person may decide. */
  checks?: ReadChecks;
  footer: React.ReactNode;
}) {
  // Two panes only for a file to look at beside the fields; an email or a reply reads above the decision in one column.
  const twoPanes = view.evidence.some((n) => n.type === 'viewer');
  const [pane, setPane] = React.useState<'evidence' | 'decide'>('evidence');
  // Where the task came from, in the names a person uses: the workflow, its step, and who it is about.
  const description = [review.workflowName, review.stepName, review.customer].filter(Boolean).join(' · ');

  const decide = <TaskDecide review={review} view={view} edits={edits} onEdit={onEdit} checks={checks} />;

  return (
    <PageLayout
      icon={UserCheck}
      title={view.question}
      description={description || undefined}
      backHref="/reviews"
      className="min-h-0 flex-1 pb-0"
      contentClassName="grid min-h-0 grid-rows-[minmax(0,1fr)_auto]"
      badge={
        <>
          <ReviewStatusBadge status={review.status} />
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            Risk <RiskBadge risk={review.risk} />
          </span>
          <span className="text-xs text-muted-foreground">
            <SlaText minutes={review.slaMinutes} open={isOpen(review)} />
          </span>
          {review.decidingTeam && (
            <span className="text-xs text-muted-foreground" data-testid="task-deciding-team">
              {review.decidingTeam.name ?? review.decidingTeam.id} decides
            </span>
          )}
        </>
      }
      actions={
        <div className="flex items-center gap-1" data-testid="task-queue">
          {queue.position != null && queue.total != null && (
            <span className="mr-1 text-sm text-muted-foreground tabular-nums" data-testid="task-position">
              {queue.position} of {queue.total}
            </span>
          )}
          <Button variant="outline" size="icon" aria-label="Previous task" disabled={!queue.onPrev} onClick={queue.onPrev} data-testid="task-prev">
            <ChevronLeft />
          </Button>
          <Button variant="outline" size="icon" aria-label="Next task" disabled={!queue.onNext} onClick={queue.onNext} data-testid="task-next">
            <ChevronRight />
          </Button>
          {queue.onClose && (
            <Button variant="outline" onClick={queue.onClose} data-testid="task-close">
              <X /> Close
            </Button>
          )}
        </div>
      }
    >
      <div className="flex min-h-0 flex-col">
        {twoPanes && (
          <Tabs value={pane} onValueChange={(v) => setPane(v as 'evidence' | 'decide')} className="pb-3 lg:hidden">
            <TabsList className="w-full">
              <TabsTrigger value="evidence" data-testid="task-pane-evidence">
                Evidence
              </TabsTrigger>
              <TabsTrigger value="decide" data-testid="task-pane-decide">
                Decide
              </TabsTrigger>
            </TabsList>
          </Tabs>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto pb-4" data-testid="task-body">
          {twoPanes ? (
            <div className="grid w-full gap-4 lg:grid-cols-[minmax(0,55fr)_minmax(0,45fr)]">
              <div className={cn('min-w-0 flex-col gap-4', pane === 'evidence' ? 'flex' : 'hidden', 'lg:flex')} data-testid="task-evidence">
                {view.evidence.map((node, i) => (
                  <KindView key={i} node={node} />
                ))}
              </div>
              <div className={cn(pane === 'decide' ? 'block' : 'hidden', 'min-w-0 lg:block')}>{decide}</div>
            </div>
          ) : (
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
              {view.evidence.length > 0 && (
                <div className="flex min-w-0 flex-col gap-4" data-testid="task-evidence">
                  {view.evidence.map((node, i) => (
                    <KindView key={i} node={node} />
                  ))}
                </div>
              )}
              {decide}
            </div>
          )}
        </div>
      </div>
      <footer className="-mx-6 lg:-mx-8" data-testid="task-footer">
        {footer}
      </footer>
    </PageLayout>
  );
}

/**
 * What the person decides on: the task's regions, or today's body for a type with none, and Details folded below.
 * One component for the task's page and the queue's quick view, so both say the same thing in the same words.
 */
export function TaskDecide({ review, view, edits, onEdit, checks }: { review: Review; view: TaskView; edits: ReadEdits; onEdit?: (record: number, key: string, text: string) => void; checks?: ReadChecks }) {
  const fieldEdits = { open: !!onEdit || !!checks, edits, onEdit: onEdit ?? (() => {}), checks };
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="task-decide">
      {view.legacy ? <ReviewDetailBody review={review} edits={edits} onEdit={onEdit} checks={checks} /> : view.decide.map((node, i) => <KindView key={i} node={node} fieldEdits={fieldEdits} />)}
      {!view.legacy && (view.details.length > 0 || !!view.technical?.length) && (
        <Collapsible className="rounded-lg border" data-testid="task-details">
          <CollapsibleTrigger className="group flex w-full items-center justify-between px-4 py-3 text-sm font-medium" data-testid="task-details-toggle">
            Details
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-3 border-t p-4">
            {view.details.map((node, i) => (
              <KindView key={i} node={node} />
            ))}
            {!!view.technical?.length && (
              // What the engine knows the task by, for whoever needs to trace it; folded again so it never reads as the task.
              <Collapsible data-testid="task-technical">
                <CollapsibleTrigger className="group flex items-center gap-1 text-xs font-medium text-muted-foreground" data-testid="task-technical-toggle">
                  <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
                  Technical details
                </CollapsibleTrigger>
                <CollapsibleContent className="flex flex-col gap-3 pt-3">
                  {view.technical.map((node, i) => (
                    <KindView key={i} node={node} />
                  ))}
                </CollapsibleContent>
              </Collapsible>
            )}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
