import type { QueryCache } from '@tanstack/react-query';
import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { servicesDown } from '../lib/api/unreachable.ts';

export function readServicesDown(cache: QueryCache): boolean {
  return servicesDown(
    cache.getAll().map((q) => ({
      observers: q.getObserversCount(),
      status: q.state.status,
      error: q.state.error,
      failures: q.state.fetchFailureCount,
      failureReason: q.state.fetchFailureReason,
      side: q.meta?.side === true,
    })),
  );
}

/**
 * Calls `onChange` when the answer changes, never inside the cache's own call. The cache tells its subscribers
 * synchronously when a query is added, and a page adds queries while it renders; updating the banner then updates one
 * component while another renders. The answer is read again in a microtask and passed on only when it differs.
 */
export function watchServicesDown(cache: QueryCache, onChange: (down: boolean) => void): () => void {
  let last = readServicesDown(cache);
  let live = true;
  let queued = false;
  const unsubscribe = cache.subscribe(() => {
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      if (!live) return;
      const next = readServicesDown(cache);
      if (next === last) return;
      last = next;
      onChange(next);
    });
  });
  return () => {
    live = false;
    unsubscribe();
  };
}

/** True while a page read on screen failed because the services did not answer (lib/api/unreachable.ts `servicesDown`). */
export function useServicesDown(): boolean {
  const cache = useQueryClient().getQueryCache();
  const [down, setDown] = React.useState(false);
  React.useEffect(() => {
    setDown(readServicesDown(cache));
    return watchServicesDown(cache, setDown);
  }, [cache]);
  return down;
}
