import { type ReactNode, useId } from 'react';
import Link from 'next/link';

import { cn } from '@/lib/utils';

// The open control fills its box with an ::after drawn under the content: a click on the content reaches the row's
// own handler, which opens it, and links inside the content keep their clicks; the control is the row's tab stop and
// draws the focus ring. Laid over the content instead, it would take every click aimed at the content's own text.
const STRETCH = "outline-none after:absolute after:inset-0 after:rounded-sm after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring/60";

/**
 * The one tab stop of a table row that opens on click, drawn under the row's name cell's content: a link when the row has an
 * address, a button when it opens a sheet. It is a sibling of the cell's content, never its parent, so a cell that holds
 * its own link (a "secret not set" link on Tools) nests no anchor in another. Its name is the content's text, so a screen
 * reader announces a named control instead of an unlabelled row, and Tab moves once per row. The row stays a plain
 * `<tr>` with its implicit `row` role, since a `button` or `link` role on a `<tr>` removes it from the table. A click
 * anywhere in the box reaches the row's own onClick, which opens it.
 */
export function RowOpen({ href, children, className }: { href?: string; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <div className={cn('relative', className)}>
      <div id={id} className="relative z-[1]">
        {children}
      </div>
      {href ? (
        <Link href={href} aria-labelledby={id} className={STRETCH} data-row-open />
      ) : (
        <button type="button" aria-labelledby={id} className={STRETCH} data-row-open />
      )}
    </div>
  );
}
