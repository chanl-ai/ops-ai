import type { ReactNode } from 'react';
import Link from 'next/link';

import { cn } from '@/lib/utils';

const FOCUS = 'rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

/**
 * The one tab stop of a table row that opens on click, drawn around the row's name cell: a link when the row has an
 * address, a button when it opens a sheet. A screen reader announces a named control instead of an unlabelled row,
 * and Tab moves once per row. The row stays a plain `<tr>` with its implicit `row` role, since a `button` or `link`
 * role on a `<tr>` removes it from the table. A click on the button reaches the row's own onClick, which opens it.
 */
export function RowOpen({ href, children, className }: { href?: string; children: ReactNode; className?: string }) {
  if (href)
    return (
      <Link href={href} className={cn('block', FOCUS, className)}>
        {children}
      </Link>
    );
  return (
    <button type="button" className={cn('block w-full text-left', FOCUS, className)}>
      {children}
    </button>
  );
}
