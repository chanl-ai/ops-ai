'use client';

import * as React from 'react';

const WIDE = '(min-width: 1024px)';
const subscribeWide = (onChange: () => void) => {
  const q = window.matchMedia(WIDE);
  q.addEventListener('change', onChange);
  return () => q.removeEventListener('change', onChange);
};

/**
 * Whether the window is at least 1024 px wide (the layout breakpoint). Read as an external store so the layout changes
 * in the same task as the resize, and the first paint is the desktop one, which a phone corrects on hydration.
 */
export const useWide = (): boolean => React.useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => true);
