'use client';

import * as React from 'react';
import { Info } from 'lucide-react';

import { actionLabel, areaLabel } from '@/components/access/access-words';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useWhy } from '@/hooks/me-queries';

/** A list in words: "A", "A and B", "A, B and C". */
const words = (xs: string[]) => (xs.length <= 1 ? (xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/**
 * A control the signed-in person may not use (c-150): shown disabled, with an ⓘ that says why in one line, which roles
 * grant it and who in the team can give roles, from the same check the services run (GET /v1/me/why). The reason is
 * read only when the control is locked.
 */
export function LockedReason({ area, action, label, size = 'default' }: { area: string; action: string; label: string; size?: 'default' | 'sm' }) {
  const why = useWhy(area, action, true);
  const w = why.data;
  const what = `${actionLabel(action)} on ${areaLabel(area)}`;
  const reason = !w
    ? `Needs ${what}.`
    : w.refusedBy?.code === 'own_request'
      ? w.refusedBy.reason
      : `Needs ${what}${w.roles.length ? `; the ${words(w.roles.map((r) => r.name))} ${w.roles.length === 1 ? 'role has' : 'roles have'} it` : ''}.${w.askable.length ? ` Ask ${words(w.askable.slice(0, 3))}.` : ''}`;
  return (
    <span className="flex items-center gap-1.5">
      <Button size={size} disabled data-testid={`locked-${area}-${action}`}>
        {label}
      </Button>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Why can't I ${label.toLowerCase()}?`} data-testid="locked-why">
            <Info className="size-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-72" data-testid="locked-why-text">
          {reason}
        </TooltipContent>
      </Tooltip>
    </span>
  );
}
