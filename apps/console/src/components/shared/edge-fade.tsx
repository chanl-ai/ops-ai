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
 * Makes every sideways-scrolling table under `root` reachable by keyboard while it overflows: a focusable region
 * named after its section's heading, so arrow keys scroll it. A table that fits takes no tab stop. The table primitive
 * draws the scroller itself (`data-slot=table-container`), so they are found in the page rather than given props, and
 * a table that appears or grows later is caught by the observers.
 */
export function useKeyboardScrollRegions(root: React.RefObject<HTMLElement | null>): void {
  React.useEffect(() => {
    const host = root.current;
    if (!host) return;
    let frame = 0;
    const mark = () => {
      frame = 0;
      for (const el of host.querySelectorAll<HTMLElement>('[data-slot=table-container]')) {
        const ours = el.dataset.scrollRegion === 'on';
        if (el.scrollWidth > el.clientWidth + 1) {
          if (ours) continue;
          el.dataset.scrollRegion = 'on';
          el.tabIndex = 0;
          el.setAttribute('role', 'region');
          const heading = el.closest('section, [data-slot=card]')?.querySelector('h1, h2, h3, [data-slot=card-title]')?.textContent?.trim();
          el.setAttribute('aria-label', heading ? `${heading} table` : 'Table');
        } else if (ours) {
          delete el.dataset.scrollRegion;
          el.removeAttribute('tabindex');
          el.removeAttribute('role');
          el.removeAttribute('aria-label');
        }
      }
    };
    const soon = () => {
      if (!frame) frame = requestAnimationFrame(mark);
    };
    mark();
    const changed = new MutationObserver(soon);
    changed.observe(host, { childList: true, subtree: true });
    const resized = new ResizeObserver(soon);
    resized.observe(host);
    return () => {
      cancelAnimationFrame(frame);
      changed.disconnect();
      resized.disconnect();
    };
  }, [root]);
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
