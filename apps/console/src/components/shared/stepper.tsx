'use client';

import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface StepperProps {
  /** Step labels, in order. The count comes from this — never passed separately. */
  steps: readonly string[];
  /** 1-based index of the active step. */
  current: number;
  className?: string;
  testId?: string;
}

/**
 * The wizard step track, used by every multi-step dialog.
 *
 * Three near-identical copies of this existed before it (the CSV import dialog,
 * the toolset dialog, and the generate-from-call flow), two of them literally
 * the same class strings — so a fix to one silently left the others behind.
 *
 * It spans the full width of its container: each step occupies its own space
 * and the connector between them flexes to fill the remainder, so the track
 * reaches both edges instead of huddling at the left. The connector also
 * carries progress — a filled rule reads as "this stage is behind you" without
 * needing a separate "Step 2 of 3" caption, which is why there isn't one.
 */
export function Stepper({ steps, current, className, testId = 'stepper' }: StepperProps) {
  return (
    <div className={cn('flex w-full items-center', className)} data-testid={testId}>
      {steps.map((label, index) => {
        const step = index + 1;
        const done = step < current;
        const isCurrent = step === current;
        const isLast = step === steps.length;

        return (
          <div key={label} className={cn('flex items-center', !isLast && 'flex-1')}>
            <div className="flex items-center gap-2 whitespace-nowrap">
              <div
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium transition-colors',
                  isCurrent && 'bg-primary text-primary-foreground',
                  done && 'bg-primary/20 text-primary',
                  !isCurrent && !done && 'bg-muted text-muted-foreground'
                )}
                title={label}
                data-testid={`${testId}-step-${step}`}
                aria-current={isCurrent ? 'step' : undefined}
              >
                {done ? <Check className="h-3 w-3" /> : step}
              </div>
              <span
                className={cn(
                  'hidden text-xs sm:inline',
                  isCurrent ? 'font-medium text-foreground' : 'text-muted-foreground'
                )}
              >
                {label}
              </span>
            </div>
            {!isLast && (
              <div
                aria-hidden="true"
                className={cn('mx-3 h-px flex-1', done ? 'bg-primary/30' : 'bg-border')}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
