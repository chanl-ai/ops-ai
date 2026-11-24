'use client';

import * as React from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/**
 * A cell's text on one line, cut with an ellipsis at the column's width, the whole text in the browser's tooltip (the
 * `title`). A table cell holding free text (a finding, a description, a reason) uses this instead of rendering the string raw, so one long
 * value never widens the table or wraps into a tall block. The width cap is a ceiling: a column narrower than it
 * still shrinks the text. Pass `className` (a `max-w-*`) to change the ceiling.
 */
export function TextCell({ children, className }: { children: string; className?: string }) {
  return (
    <span title={children} className={cn('block max-w-[min(24rem,70vw)] truncate', className)}>
      {children}
    </span>
  );
}

/**
 * A list of values in one cell: the first few on one line, then "+N more" that opens every value in a popover. A list
 * that fits shows as it is and still cuts to the column with its full text in a tooltip. `empty` reads when there is
 * nothing to list.
 */
export function ListCell({ values, shown = 3, empty = '—', label, className }: { values: readonly string[]; shown?: number; empty?: string; label?: string; className?: string }) {
  if (!values.length) return <span className="text-muted-foreground">{empty}</span>;
  const head = values.slice(0, shown);
  const rest = values.length - head.length;
  if (!rest) return <TextCell className={className}>{head.join(', ')}</TextCell>;
  return (
    <span className={cn('flex max-w-[min(24rem,70vw)] items-center gap-1.5', className)}>
      <span className="min-w-0 truncate">{head.join(', ')}</span>
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className="shrink-0 rounded-sm text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/50">
            +{rest} more
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-3">
          {label && <p className="mb-2 text-xs font-medium text-muted-foreground">{label}</p>}
          <ul className="max-h-60 overflow-y-auto text-sm">
            {values.map((v, i) => (
              <li key={`${i}-${v}`} className="break-words py-0.5">
                {v}
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    </span>
  );
}
