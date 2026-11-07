'use client';

import * as React from 'react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/** A disabled button says why in a tooltip; the wrapper takes the hover because disabled buttons do not. */
export function DisabledReason({ reason, children }: { reason?: string; children: React.ReactElement }) {
  if (!reason) return children;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* A focusable group, so the reason is read on focus; a plain span may not carry a name. */}
        <span tabIndex={0} role="group" aria-label={reason} className="inline-flex">
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{reason}</TooltipContent>
    </Tooltip>
  );
}
