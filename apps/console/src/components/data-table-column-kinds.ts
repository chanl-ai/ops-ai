import { cn } from '@/lib/utils';

/**
 * What a column holds, so every table sizes it the same way: ids, dates and statuses on one line at their own width;
 * a name or title taking the free space and trimmed to one line (the whole value on hover); a description wrapping to
 * two lines then trimmed; numbers and money on one line, right-aligned. A kind cell that draws nothing shows a dash:
 * it is the drawn cell that is checked, not the row's value, so a column wording its own empty state ("Not read") keeps it.
 */
export type ColumnKind = 'id' | 'date' | 'status' | 'name' | 'description' | 'number' | 'money';

export interface ColumnMeta {
  className?: string;
  kind?: ColumnKind;
}

const KIND: Record<ColumnKind, string> = {
  id: 'w-px whitespace-nowrap',
  date: 'w-px whitespace-nowrap',
  status: 'w-px whitespace-nowrap',
  name: 'w-full max-w-0 min-w-60 [&_*]:min-w-0 [&_a]:truncate [&_div]:truncate [&_p]:truncate',
  description: 'min-w-48 max-w-96 whitespace-normal [&_div]:line-clamp-2 [&_p]:line-clamp-2',
  number: 'w-px whitespace-nowrap text-right tabular-nums',
  money: 'w-px whitespace-nowrap text-right tabular-nums',
};

const DASH = "empty:after:text-muted-foreground empty:after:content-['—'] [&>:empty]:after:text-muted-foreground [&>:empty]:after:content-['—']";

/** On a phone the row's select box and its name stay put while the other columns scroll under them. */
const PINNED = 'max-sm:sticky max-sm:z-[1] max-sm:bg-card';
const EDGE = 'max-sm:shadow-[8px_0_8px_-8px_rgb(0_0_0/0.12)]';

/** A cell's or header's classes from its column's kind and its own className. */
export function kindClass(meta: ColumnMeta | undefined, pin: 'select' | 'name' | null, afterSelect: boolean): string {
  return cn(
    meta?.kind && KIND[meta.kind],
    meta?.kind && DASH,
    pin === 'select' && cn(PINNED, 'max-sm:left-0'),
    pin === 'name' && cn(PINNED, EDGE, afterSelect ? 'max-sm:left-10' : 'max-sm:left-0'),
    meta?.className,
  );
}
