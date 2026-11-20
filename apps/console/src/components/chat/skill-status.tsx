import { CircleCheck, CircleSlash, ListOrdered, Pause, TriangleAlert, Undo2 } from 'lucide-react';

import { type SkillEnding, endingText, holdsText } from '@/lib/skill-run';
import type { SkillRun } from '@/lib/types/chat';

/**
 * Where a stepped skill is after the newest reply: `Card dispute · step 2 of 4`, and the skill it started shown as
 * `inside`. The Runtime reports it on the reply, so the line is never worked out here. The shared message list draws it
 * at the foot of the list, so every console chat shows the same line; the customer's embedded chat does not use it.
 */
export function SkillTracker({ run }: { run: SkillRun | null | undefined }) {
  const r = run?.running;
  const holds = holdsText(run);
  if (!r && !holds) return null;
  const sub = r?.sub;
  return (
    <div className="flex flex-col gap-0.5 border-t bg-muted/40 px-3 py-1.5 text-xs">
      {r && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5" role="status" data-testid="skill-tracker">
          <ListOrdered className="size-3.5 text-muted-foreground" aria-hidden />
          <span className="font-medium">{r.name}</span>
          <span className="text-muted-foreground tabular-nums">
            step {r.step} of {r.stepsTotal}
          </span>
          {sub && (
            <span className="text-muted-foreground tabular-nums" data-testid="skill-tracker-sub">
              · inside {sub.name}, step {sub.step}
              {sub.stepsTotal ? ` of ${sub.stepsTotal}` : ''}
            </span>
          )}
        </div>
      )}
      {holds && (
        <div className="flex items-center gap-x-2 text-warning-text" role="status" data-testid="skill-holds">
          <Pause className="size-3.5" aria-hidden />
          <span>{holds}</span>
        </div>
      )}
    </div>
  );
}

const ICON = { done: CircleCheck, switched: Undo2, failed: TriangleAlert } as const;

/** How a skill ended, once, under the reply it ended in. The icon and the words both say it; colour is not the only cue. */
export function SkillEnded({ ending }: { ending: SkillEnding }) {
  const Icon = ICON[ending.ended as keyof typeof ICON] ?? CircleSlash;
  const tone = ending.ended === 'failed' ? 'text-destructive-text' : ending.ended === 'done' || ending.ended === 'switched' ? 'text-muted-foreground' : 'text-warning-text';
  return (
    <p className={`flex items-start gap-1.5 text-xs ${tone}`} role="status" data-testid="skill-ended" data-ended={ending.ended}>
      <Icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>{endingText(ending)}</span>
    </p>
  );
}
