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
  // Hidden on a phone, where it took the row beside the pinned name; the record page and a desktop keep it.
  id: 'w-px whitespace-nowrap max-md:hidden',
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
const EDGE = 'max-sm:shadow-[8px_0_8px_-8px_var(--color-border)]';

/**
 * A list that marks no name column pins its first data column on a phone instead. It takes half the screen at most and
 * its lines wrap to two, so the columns after it are in reach and the name still reads. On a desktop it keeps the
 * page's own sizing.
 */
const PHONE_NAME = 'max-sm:w-1/2 max-sm:min-w-40 max-sm:max-w-0 max-sm:whitespace-normal max-sm:wrap-break-word max-sm:[&_*]:min-w-0 max-sm:[&_.truncate]:line-clamp-2 max-sm:[&_.truncate]:whitespace-normal';

/** A cell's or header's classes from its column's kind and its own className. */
export function kindClass(meta: ColumnMeta | undefined, pin: 'select' | 'name' | null, afterSelect: boolean): string {
  return cn(
    meta?.kind && KIND[meta.kind],
    meta?.kind && DASH,
    // The select box is 2.5rem wide on a phone, so the pinned name after it starts exactly at its edge (left-10).
    pin === 'select' && cn(PINNED, 'max-sm:left-0 max-sm:w-10 max-sm:min-w-10'),
    pin === 'name' && cn(PINNED, EDGE, afterSelect ? 'max-sm:left-10' : 'max-sm:left-0', meta?.kind !== 'name' && PHONE_NAME),
    meta?.className,
  );
}
