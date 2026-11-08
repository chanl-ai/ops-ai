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

// What can scroll inside the page: the table primitive's container and any box styled to scroll. Matched by class,
// so a scroller drawn by a primitive is found without props.
const SCROLLERS = '[data-slot=table-container], [class*="overflow-x-auto"], [class*="overflow-y-auto"], [class*="overflow-auto"]';
const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

/**
 * Makes every scrolling box under `root`, and `root` itself, reachable by keyboard while it overflows and holds nothing
 * a keyboard can reach: a focusable region named after its section's heading, so arrow keys scroll it. A box that fits,
 * or whose links and buttons already take focus (the browser scrolls to them), takes no tab stop. Controls disabled by
 * a fieldset count as unreachable. Observers catch a box that appears or grows later. `host` is an element, not a ref, so a host mounted after the
 * first render is still watched.
 */
export function useKeyboardScrollRegions(host: HTMLElement | null): void {
  React.useEffect(() => {
    if (!host) return;
    let frame = 0;
    const reachable = (el: HTMLElement) =>
      [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].some((f) => f !== el && !f.closest('fieldset:disabled') && f.dataset.scrollRegion !== 'on');
    const mark = () => {
      frame = 0;
      for (const el of [host, ...host.querySelectorAll<HTMLElement>(SCROLLERS)]) {
        const ours = el.dataset.scrollRegion === 'on';
        const style = getComputedStyle(el);
        const scrolls = (/(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 1) || (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1);
        if (scrolls && !reachable(el)) {
          if (ours) continue;
          el.dataset.scrollRegion = 'on';
          el.tabIndex = 0;
          el.setAttribute('role', 'region');
          const heading = el.closest('section, [data-slot=card]')?.querySelector('h1, h2, h3, [data-slot=card-title]')?.textContent?.trim()
            ?? el.querySelector('h1, h2')?.textContent?.trim();
          el.setAttribute('aria-label', heading ? `${heading}, scrolls` : 'Scrolling content');
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
    changed.observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
    const resized = new ResizeObserver(soon);
    resized.observe(host);
    return () => {
      cancelAnimationFrame(frame);
      changed.disconnect();
      resized.disconnect();
    };
  }, [host]);
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
