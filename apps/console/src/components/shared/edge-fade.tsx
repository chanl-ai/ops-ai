'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * Whether a box that scrolls sideways has more to show past its right edge. Watches `selector` inside `root` (or root
 * itself), so a wrapper can follow a scroller it does not render, such as the table primitive's own container.
 */
export function useMoreToTheRight(root: React.RefObject<HTMLElement | null>, selector?: string): boolean {
  const [more, setMore] = React.useState(false);
  React.useEffect(() => {
    const host = root.current;
    const el = selector ? host?.querySelector<HTMLElement>(selector) : host;
    if (!el) return;
    const measure = () => setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
    measure();
    el.addEventListener('scroll', measure, { passive: true });
    const resized = new ResizeObserver(measure);
    resized.observe(el);
    if (el.firstElementChild) resized.observe(el.firstElementChild);
    return () => {
      el.removeEventListener('scroll', measure);
      resized.disconnect();
    };
  }, [root, selector]);
  return more;
}

/**
 * A fade over the right edge of a sideways scroller while more sits past it, so a phone shows that a table or a tab
 * strip goes on. Drawn in the surface's own token, so it matches light and dark; it never takes a click.
 */
export function EdgeFade({ show, className, ...props }: { show: boolean } & React.ComponentProps<'div'>) {
  return (
    <div
      aria-hidden
      className={cn('pointer-events-none absolute inset-y-0 right-0 w-10 bg-linear-to-l from-card to-transparent transition-opacity', show ? 'opacity-100' : 'opacity-0', className)}
      {...props}
    />
  );
}
