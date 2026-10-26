'use client';

import * as React from 'react';

import { useSidebar } from '@/components/ui/sidebar';

/** Below this width a page with a side rail folds the app sidebar first, so the middle column keeps its room. */
export const FOLD_BELOW = 1440;

// Every page that wants the sidebar folded holds the fold; the sidebar comes back as it was only when the last holder
// lets go. The release waits a microtask, so a page swap inside the same commit (the chat home to a thread) never
// restores the sidebar between the old page's cleanup and the new page's effect. The sidebar keeps its state in a
// cookie, so a fold left in place would carry over to every other page.
const holders = new Set<symbol>();
let before: boolean | null = null;

function useFold(active: boolean) {
  const { open, setOpen } = useSidebar();
  const openNow = React.useRef(open);
  openNow.current = open;
  const id = React.useRef(Symbol('fold'));
  React.useEffect(() => {
    if (!active) return;
    const me = id.current;
    if (before === null) before = openNow.current;
    holders.add(me);
    setOpen(false);
    return () => {
      holders.delete(me);
      queueMicrotask(() => {
        if (holders.size > 0 || before === null) return;
        const was = before;
        before = null;
        setOpen(was);
      });
    };
    // Runs when the fold starts or stops: a person who opens the sidebar on the page keeps it open until they leave.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
}

function useNarrowerThan(px: number): boolean {
  const [narrow, setNarrow] = React.useState(false);
  React.useEffect(() => {
    const q = window.matchMedia(`(max-width: ${px - 1}px)`);
    const on = () => setNarrow(q.matches);
    on();
    q.addEventListener('change', on);
    return () => q.removeEventListener('change', on);
  }, [px]);
  return narrow;
}

/** Folds the app sidebar while the calling page is mounted, for a page that needs the full width (the canvas, the chat home). */
export function useCollapsedSidebar() {
  useFold(true);
}

/**
 * Folds the app sidebar while the calling page is mounted and the window is narrower than {@link FOLD_BELOW}: the
 * pages with a side rail (chat, RecordLayout) give their middle column priority on a 13-inch laptop, and the side rails
 * collapse before it does.
 */
export function useSidebarFoldsWhenNarrow(px = FOLD_BELOW) {
  useFold(useNarrowerThan(px));
}
