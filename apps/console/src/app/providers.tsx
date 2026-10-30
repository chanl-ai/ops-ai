'use client';

import * as React from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';

import { AppToaster } from '@/components/shared/app-toaster';
import { UiFeedback } from '@/components/shared/ui-feedback';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useSession } from '@/hooks/auth-queries';
import { buildCommit, buildTag, cacheSetting, queriesNeedTeam, uiFeedback } from '@/lib/api';
import { isUnreachable } from '@/lib/api/unreachable';
import { teamStore } from '@/lib/api/team-context';
import { cacheBuster, cacheOn, MAX_AGE_MS, openSavedQueries, wipeSavedQueries } from '@/lib/query-cache';

const BUSTER = cacheBuster(buildTag, buildCommit);

/**
 * Shows what this person last saw in this team at once on a reload, and saves it as it changes (c-560). Nothing is
 * read or saved until the session is signed in, and an ended session, from this tab or another, removes every copy.
 */
function SavedQueries() {
  const client = useQueryClient();
  const { session, status } = useSession();
  const team = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  const user = status === 'signed_in' ? (session?.user.id ?? null) : null;

  React.useEffect(() => {
    if (status === 'signed_out' || status === 'expired') void wipeSavedQueries();
  }, [status]);

  React.useEffect(() => {
    const saved = queriesNeedTeam ? openSavedQueries({ client, user, team, buster: BUSTER, setting: cacheSetting }) : null;
    if (!saved) return;
    let live = true;
    let stop: (() => void) | undefined;
    void saved.restore().then(() => {
      if (live) stop = saved.start();
    });
    return () => {
      live = false;
      stop?.();
    };
  }, [client, user, team]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  // One retry keeps a flaky request from flashing an error, without making a real outage slow to surface.
  // 403 and 404 are answers, not flakes: retrying them only delays the "belongs to another team" or not-found state.
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Reads only: mutations keep their default of no retry, so a decision or a save is never sent twice. An outage
            // (a 5xx or no answer) is asked again four times, 1, 2, 4 then 8 seconds apart; anything else once, at once.
            retry: (failures, e) => (isUnreachable(e) ? failures < 4 : ![403, 404].includes((e as { status?: number }).status ?? 0) && failures < 1),
            retryDelay: (failures, e) => (isUnreachable(e) ? Math.min(1000 * 2 ** failures, 8000) : 0),
            // A read the outage left failed asks again every 10 seconds, so the page comes back on its own once the
            // services answer.
            refetchInterval: (query) => (query.state.status === 'error' && isUnreachable(query.state.error) ? 10_000 : false),
            staleTime: 30_000,
            // A saved read is kept as long as the saved cache lasts; with the default 5 minutes, a screen left for longer
            // would drop out of the next save.
            ...(cacheOn(cacheSetting) ? { gcTime: MAX_AGE_MS } : {}),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <SavedQueries />
      <TooltipProvider delayDuration={200}>
        {children}
        <AppToaster />
        <UiFeedback enabled={uiFeedback} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
