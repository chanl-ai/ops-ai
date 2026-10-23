'use client';

import * as React from 'react';
import { hashKey, keepPreviousData, type QueryKey, type UseQueryOptions, type UseQueryResult } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useTeamQuery } from './team-query';

/**
 * A list that pages, filters or refreshes on the server (docs/console/standards.md, Designed states, Partial). The
 * previous rows stay on screen while the next ones load, and a list that loaded keeps showing when a later fetch fails:
 * a background refetch, or a new page, view or search. React Query drops placeholder data once a new key's fetch
 * fails, so the last loaded data is kept here and the failure is a toast, not a blank page. `isError` and `error` stay
 * as React Query reports them; a page's `isError && !data` gate then shows its error only when nothing ever loaded.
 */
export function usePagedQuery<TQueryFnData, TError = Error, TData = TQueryFnData, TQueryKey extends QueryKey = QueryKey>(
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryKey> & { enabled?: boolean },
): UseQueryResult<TData, TError> {
  const query = useTeamQuery({ ...options, placeholderData: keepPreviousData as never });
  const kept = React.useRef<TData | undefined>(undefined);
  if (query.data !== undefined) kept.current = query.data;
  const { isError, errorUpdatedAt, refetch } = query;
  const id = hashKey(options.queryKey);
  React.useEffect(() => {
    if (!isError || kept.current === undefined) return;
    toast.error('Couldn’t refresh this list', {
      id,
      description: 'Showing the last results that loaded.',
      action: { label: 'Try again', onClick: () => void refetch() },
    });
  }, [isError, errorUpdatedAt, id, refetch]);
  return query.data === undefined && kept.current !== undefined ? ({ ...query, data: kept.current } as UseQueryResult<TData, TError>) : query;
}
