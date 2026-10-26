'use client';

import * as React from 'react';
import { ChevronDown } from 'lucide-react';

import { KindView } from '@/components/chat/widgets/kind-view';
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
