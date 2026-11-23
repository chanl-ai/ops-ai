'use client';

import { GateStepChip } from '@/components/assurance/assurance-meta';
import type { PublishBlocker } from '@/lib/types/references';

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
