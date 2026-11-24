'use client';

import * as React from 'react';

import { useKeyboardScrollRegions } from '@/components/shared/edge-fade';
import { StopRowClick } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

const CEILING = 'max-w-[min(24rem,70vw)]';

/** The full list or text in a popover that scrolls by keyboard and names itself to a screen reader. */
function FullValues({ name, children }: { name: string; children: React.ReactNode }) {
  const [host, setHost] = React.useState<HTMLElement | null>(null);
  useKeyboardScrollRegions(host);
  return (
    <PopoverContent align="start" aria-label={name} className="w-64 p-3">
      <div ref={setHost} className="max-h-60 overflow-y-auto text-sm break-words">
        {children}
      </div>
    </PopoverContent>
  );
}

/**
 * A cell's text on one line, cut with an ellipsis at the column's width. While it is cut, it is a button that opens
 * the whole text in a popover (reachable by touch and keyboard), and the `title` shows it on hover; while it fits, it
 * is plain text. A table cell holding free text (a finding, a description, a reason) uses this instead of rendering
 * the string raw, so one long value never widens the table or wraps into a tall block. The width cap is a ceiling: a
 * column narrower than it still shrinks the text. Pass `className` (a `max-w-*`, a font) to change it.
 */
export function TextCell({ children, className }: { children: string; className?: string }) {
  const box = React.useRef<HTMLSpanElement>(null);
  const [cut, setCut] = React.useState(false);
  React.useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const text = el.querySelector<HTMLElement>('[data-text]');
      if (text) setCut(text.scrollWidth > text.clientWidth + 1);
    };
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, [children]);
  return (
    <span ref={box} className={cn('block', CEILING, className)}>
      {cut ? (
        <StopRowClick align="start">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" title={children} className="h-auto w-full min-w-0 justify-start p-0 text-left font-[inherit] text-[length:inherit] hover:bg-transparent">
                <span data-text className="block min-w-0 truncate">
                  {children}
                </span>
              </Button>
            </PopoverTrigger>
            <FullValues name="Full text">{children}</FullValues>
          </Popover>
        </StopRowClick>
      ) : (
        <span data-text title={children} className="block truncate">
          {children}
        </span>
      )}
    </span>
  );
}

/**
 * A list of values in one cell: the first few on one line, then "+N more" that opens every value in a popover. A list
 * that fits shows as text, cut to the column like TextCell. `empty` reads when there is nothing to list; `label` names
 * the popover.
 */
export function ListCell({ values, shown = 3, empty = '—', label, className }: { values: readonly string[]; shown?: number; empty?: string; label?: string; className?: string }) {
  if (!values.length) return <span className="text-muted-foreground">{empty}</span>;
  const head = values.slice(0, shown);
  const rest = values.length - head.length;
  if (!rest) return <TextCell className={className}>{head.join(', ')}</TextCell>;
  return (
    <StopRowClick align="start">
      <span className={cn('flex items-center gap-1.5', CEILING, className)}>
        <span className="min-w-0 truncate">{head.join(', ')}</span>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="link" size="sm" className="h-auto shrink-0 p-0 text-xs text-muted-foreground hover:text-foreground">
              +{rest} more
            </Button>
          </PopoverTrigger>
          <FullValues name={label ?? 'All values'}>
            <ul>
              {values.map((v, i) => (
                <li key={`${i}-${v}`} className="py-0.5">
                  {v}
                </li>
              ))}
            </ul>
          </FullValues>
        </Popover>
      </span>
    </StopRowClick>
  );
}
