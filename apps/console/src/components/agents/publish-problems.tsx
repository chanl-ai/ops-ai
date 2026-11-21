'use client';

import { TriangleAlert } from 'lucide-react';

import { GateStepChip } from '@/components/assurance/assurance-meta';
import { Button } from '@/components/ui/button';
import { plural } from '@/lib/format';
import type { PublishBlocker, Ref } from '@/lib/types/references';

const HEADING: Record<string, string> = { 'brief.purpose': 'Purpose', 'brief.goal': 'Goal', 'brief.howToAnswer': 'How to answer', 'brief.never': 'Never', 'brief.success': 'Success checks' };

/** Where a problem is, in the words of the page: `Purpose`, or `Never, line 2`. */
export const whereIs = (p: PublishBlocker): string | null => {
  const f = p.position?.field;
  if (!f) return null;
  const name = HEADING[f] ?? f;
  return p.position?.index != null ? `${name}, line ${p.position.index + 1}` : name;
};

const EVAL_KINDS: ReadonlySet<string> = new Set(['eval_failed', 'eval_not_run', 'eval_no_cases', 'eval_setting_unread']);
export const isEvalProblem = (p: PublishBlocker) => EVAL_KINDS.has(p.kind);

/** The gate's steps of one eval problem, each as the Evals page draws it with the service's words beside it. */
export function EvalSteps({ steps }: { steps: NonNullable<PublishBlocker['details']>['steps'] }) {
  if (!steps.length) return null;
  return (
    <ul className="flex w-full flex-col gap-1" data-testid="eval-problem-steps">
      {steps.map((s) => (
        <li key={s.step} className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-testid={`eval-problem-step-${s.step}`}>
          <GateStepChip step={s} />
          <span className="min-w-0">{s.detail}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * What stops the newest draft from publishing, one row each. "Go to it" puts the caret on the heading the problem
 * names; a reference the team still offers but the agent lost offers "Add it back".
 */
export function PublishProblems({ problems, onGoTo, onAddBack, adding, onOpenEvals }: { problems: PublishBlocker[]; onGoTo: (field: string) => void; onAddBack: (ref: Ref) => void; adding?: boolean; onOpenEvals?: () => void }) {
  if (!problems.length) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="publish-problems">
      <p className="flex items-center gap-2 text-sm font-medium">
        <TriangleAlert className="size-4 text-warning-text" aria-hidden />
        {plural(problems.length, 'problem')} to fix before this can publish
      </p>
      <ul className="flex flex-col divide-y rounded-md border bg-card">
        {problems.map((p, i) => {
          const where = whereIs(p);
          const at = p.kind === 'missing_reference' && p.id ? p.id.indexOf(':') : -1;
          const token = at > 0 && p.id ? [p.id.slice(0, at), p.id.slice(at + 1)] : null;
          return (
            <li key={`${p.kind}-${p.id}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm" data-testid="publish-problem">
              <span className="min-w-0 flex-1">
                {where && <span className="font-medium">{where}: </span>}
                {p.message}
              </span>
              {isEvalProblem(p) && p.details?.steps && <EvalSteps steps={p.details.steps} />}
              {isEvalProblem(p) && p.kind !== 'eval_setting_unread' && (
                <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={onOpenEvals} data-testid="publish-problem-evals">
                  Open the Evals tab
                </Button>
              )}
              {token && token.length === 2 && (
                <Button type="button" variant="outline" size="sm" disabled={adding} onClick={() => onAddBack({ kind: token[0] as Ref['kind'], id: token[1] })} data-testid="publish-problem-add-back">
                  Add it back
                </Button>
              )}
              {!isEvalProblem(p) && p.position?.field && (
                <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => onGoTo(p.position!.field)} data-testid="publish-problem-go">
                  Go to it
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
