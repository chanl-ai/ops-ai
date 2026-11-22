'use client';

import * as React from 'react';

/**
 * Reload after a save refused as stale, finished only once the page's props hold the copy that was read. The refetch
 * resolves before the query cache has passed the new copy to the page, so acting on the resolved promise would start
 * the editor again on the copy read before. `reading` stays true from the click until `current` (the digest the page
 * is drawn from) equals the digest the refetch read; an editor pauses its saves while it is true. `onRead` runs then.
 * An editor that the page remounts on the new copy never reaches `onRead`: the new mount starts from what was carried.
 */
export function useReloadToRead(current: string | null | undefined, refetch: () => Promise<string | null | undefined>, onRead: () => void): { reload: () => Promise<void>; reading: boolean } {
  const [reading, setReading] = React.useState(false);
  const [awaiting, setAwaiting] = React.useState<string | null>(null);
  const read = React.useRef(onRead);
  read.current = onRead;
  const reload = React.useCallback(async () => {
    setReading(true);
    try {
      const digest = await refetch();
      setAwaiting(digest ?? current ?? '');
    } catch {
      // The read failed: the refused save's notice stays, and Reload can be pressed again.
      setReading(false);
    }
  }, [refetch, current]);
  React.useEffect(() => {
    if (awaiting === null || (current ?? '') !== awaiting) return;
    setAwaiting(null);
    setReading(false);
    read.current();
  }, [awaiting, current]);
  return { reload, reading };
}
