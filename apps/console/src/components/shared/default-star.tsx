'use client';

import { Star } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/**
 * Marks the default among a list's rows with a star. Filled on the default. With `onSet` the star is a button that
 * makes its row the default; without it the star only shows which row is the default (a filled star) and is absent on
 * the rest, so someone who cannot change it sees no control.
 */
export function DefaultStar({
  on,
  label,
  onSet,
  busy,
  testId,
}: {
  on: boolean;
  /** What the default is for, said in the tooltip and to a screen reader: "the team's default". */
  label: string;
  onSet?: () => void;
  busy?: boolean;
  testId?: string;
}) {
  // The word stays in the text for screen readers and for anyone reading the row as text.
  const icon = (
    <>
      <Star className={cn('size-4', on ? 'fill-warning text-warning' : 'text-muted-foreground')} aria-hidden />
      {on && <span className="sr-only">Default</span>}
    </>
  );
  if (!onSet) {
    return on ? (
      <span className="inline-flex" title={`Is ${label}`} data-testid={testId} data-on="true">
        {icon}
      </span>
    ) : null;
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7"
          aria-pressed={on}
          aria-label={on ? `Is ${label}` : `Make ${label}`}
          disabled={on || busy}
          onClick={(e) => (e.stopPropagation(), onSet())}
          data-testid={testId}
          data-on={on ? 'true' : undefined}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{on ? `Is ${label}` : `Make ${label}`}</TooltipContent>
    </Tooltip>
  );
}
