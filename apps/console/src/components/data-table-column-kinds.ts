import { cn } from '@/lib/utils';

/**
 * What a column holds, so every table sizes it the same way: ids, dates and statuses on one line at their own width;
 * a name or title taking the free space; a description up to its own width. Names, descriptions and plain text columns
 * stay on one line and end in an ellipsis, with the full value on hover (`markTruncated`), so one long value cannot
 * stretch a row or push the other columns off screen. A column whose text a person must read whole sets `wrap: true`
 * and wraps instead. Numbers and money on one line, right-aligned. A kind cell that draws nothing shows a dash:
 * it is the drawn cell that is checked, not the row's value, so a column wording its own empty state ("Not read") keeps it.
 */
export type ColumnKind = 'id' | 'date' | 'status' | 'name' | 'description' | 'number' | 'money' | 'actions';

export interface ColumnMeta {
  className?: string;
  kind?: ColumnKind;
  /** A name or description column that wraps over several lines instead of ending in an ellipsis. */
  wrap?: boolean;
}

/** A cell's text and the text inside its block children end in an ellipsis; the cell is clipped, never grown. */
const ONE_LINE = 'truncate [&_*]:min-w-0 [&_div]:truncate [&_p]:truncate [&_.flex]:min-w-0 [&_.flex>span:not([data-slot=badge])]:truncate [&_.flex>a]:truncate';
const WRAP: Partial<Record<ColumnKind, string>> = {
  name: 'w-full max-w-0 min-w-60 whitespace-normal break-words [&_*]:min-w-0',
  description: 'min-w-48 max-w-96 whitespace-normal break-words',
};
/** A column with no kind whose value is a string gets the description's width cap. */
const PLAIN_TEXT = 'max-w-96 truncate [&_div]:truncate [&_p]:truncate [&_.flex]:min-w-0 [&_.flex>span:not([data-slot=badge])]:truncate [&_.flex>a]:truncate';

const KIND: Record<ColumnKind, string> = {
  // Hidden on a phone, where it took the row beside the pinned name; the record page and a desktop keep it.
  id: 'w-px whitespace-nowrap max-md:hidden',
  date: 'w-px whitespace-nowrap',
  status: 'w-px whitespace-nowrap',
  name: `w-full max-w-0 min-w-60 ${ONE_LINE}`,
  description: `min-w-48 max-w-96 ${ONE_LINE}`,
  number: 'w-px whitespace-nowrap text-right tabular-nums',
  money: 'w-px whitespace-nowrap text-right tabular-nums',
  // A row's menu stays at the right edge on a phone, so it is in reach while the columns before it scroll.
  actions: 'w-px whitespace-nowrap max-sm:sticky max-sm:right-0 max-sm:z-[1] max-sm:bg-card max-sm:shadow-[-8px_0_8px_-8px_var(--color-border)]',
};

const DASH = "empty:after:text-muted-foreground empty:after:content-['—'] [&>:empty]:after:text-muted-foreground [&>:empty]:after:content-['—']";

/** On a phone the row's select box and its name stay put while the other columns scroll under them. */
const PINNED = 'max-sm:sticky max-sm:z-[1] max-sm:bg-card';
const EDGE = 'max-sm:shadow-[8px_0_8px_-8px_var(--color-border)]';

/**
 * A list that marks no name column pins its first data column on a phone instead. It takes half the screen at most and
 * its text ends in an ellipsis, so the columns after it are in reach. On a desktop it keeps the page's
 * own sizing.
 */
const PHONE_NAME = 'max-sm:w-1/2 max-sm:min-w-40 max-sm:max-w-0 max-sm:truncate max-sm:[&_*]:min-w-0 max-sm:[&_div]:truncate max-sm:[&_p]:truncate';

/** A cell's or header's classes from its column's kind and its own className. */
export function kindClass(meta: ColumnMeta | undefined, pin: 'select' | 'name' | null, afterSelect: boolean, plainText = false): string {
  return cn(
    meta?.kind && ((meta.wrap && WRAP[meta.kind]) || KIND[meta.kind]),
    !meta?.kind && plainText && PLAIN_TEXT,
    meta?.kind && meta.kind !== 'actions' && DASH,
    // The select box is 2.5rem wide on a phone, so the pinned name after it starts exactly at its edge (left-10).
    pin === 'select' && cn(PINNED, 'max-sm:left-0 max-sm:w-10 max-sm:min-w-10'),
    pin === 'name' && cn(PINNED, EDGE, afterSelect ? 'max-sm:left-10' : 'max-sm:left-0', meta?.kind !== 'name' && PHONE_NAME),
    meta?.className,
  );
}

/**
 * Gives every clipped piece of text in a table its full value as a hover title: the cell itself, a link or span inside
 * it, a custom renderer's own element. Run after each render and each resize, because whether text is clipped depends
 * on the width the table has now. Clipped means the element's text is wider than its box, so a cell that fits keeps no
 * title, and a title left from a wider layout is removed. The cell also carries the text when anything inside it is
 * clipped, so a pointer anywhere on the cell reveals it.
 */
export function markTruncated(root: HTMLElement) {
  for (const cell of root.querySelectorAll<HTMLElement>('td, th')) {
    let any = false;
    for (const el of [cell, ...cell.querySelectorAll<HTMLElement>('*')]) {
      if (el !== cell && el.closest('svg')) continue;
      const clipped = el.scrollWidth > el.clientWidth + 1;
      const text = el.textContent?.trim();
      if (clipped && text) {
        any = true;
        if (el !== cell && el.title !== text) el.title = text;
      } else if (el !== cell && el.dataset.truncTitle === '1') {
        el.removeAttribute('title');
      }
      if (clipped && text && el !== cell) el.dataset.truncTitle = '1';
    }
    const text = cell.textContent?.trim();
    if (any && text) {
      cell.title = text;
      cell.dataset.truncTitle = '1';
    } else if (cell.dataset.truncTitle === '1') {
      cell.removeAttribute('title');
      delete cell.dataset.truncTitle;
    }
  }
}
