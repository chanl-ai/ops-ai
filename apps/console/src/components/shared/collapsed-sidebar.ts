'use client';

import * as React from 'react';

import { useSidebar } from '@/components/ui/sidebar';

/**
 * Collapses the app sidebar while the calling page is mounted and puts it back as it was on leaving, for a page that
 * needs the full width (the workflow canvas). The sidebar keeps its state in a cookie, so leaving it collapsed would
 * carry over to every other page.
 */
export function useCollapsedSidebar() {
  const { open, setOpen } = useSidebar();
  const was = React.useRef<boolean | null>(null);
  React.useEffect(() => {
    if (was.current === null) was.current = open;
    setOpen(false);
    return () => {
      if (was.current !== null) setOpen(was.current);
    };
    // Runs on mount and unmount only: a person who opens the sidebar on the page keeps it open until they leave.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
