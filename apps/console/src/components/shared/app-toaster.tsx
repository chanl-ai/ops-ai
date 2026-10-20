'use client';

import * as React from 'react';

import { Toaster } from '@/components/ui/sonner';

const GAP = 16;
const TOAST_WIDTH = 356;

/** Width of the open right-hand sheet, or 0 when none is open. */
function openSheetWidth() {
  const open = document.querySelectorAll<HTMLElement>('[data-slot="sheet-content"][data-state="open"]');
  return Math.max(0, ...[...open].map((el) => el.getBoundingClientRect().width));
}

/** Height a visible sticky save bar takes at the bottom of the viewport, or 0. */
function unsavedBarHeight() {
  const bars = document.querySelectorAll<HTMLElement>('[data-unsaved-bar]');
  return Math.max(0, ...[...bars].map((el) => {
    const r = el.getBoundingClientRect();
    return r.height && r.top < window.innerHeight ? window.innerHeight - r.top : 0;
  }));
}

/**
 * Bottom-right toasts that move left of an open sheet, so a toast never covers the sheet's own footer actions
 * (Approve, Resend), and above a sticky unsaved-changes bar so its Save stays reachable. When the sheet leaves no
 * room beside it (phones), toasts go to the top of the screen.
 */
export function AppToaster() {
  const [sheet, setSheet] = React.useState(0);
  const [bar, setBar] = React.useState(0);
  React.useEffect(() => {
    const update = () => {
      setSheet(openSheetWidth());
      setBar(unsavedBarHeight());
    };
    const observer = new MutationObserver(update);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state'] });
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, []);

  const fits = !sheet || window.innerWidth - sheet >= TOAST_WIDTH + GAP * 2;
  // One instance whose props change, so toasts already showing are kept when a sheet opens or closes.
  const offset = fits && (sheet || bar) ? { ...(sheet ? { right: sheet + GAP } : {}), ...(bar ? { bottom: bar + GAP } : {}) } : undefined;
  return <Toaster position={fits ? 'bottom-right' : 'top-center'} offset={offset} />;
}
