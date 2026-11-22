'use client';

import { keepPreviousData, type QueryKey } from '@tanstack/react-query';

import type { PaginationMeta } from '@/lib/types/pagination';
import { useDebounced } from './use-debounced';
import { useTeamInfiniteQuery } from './team-query';

/** What `useServerList` asks a list route for: the shared list query (docs/architecture/api.md "Lists and errors"). */
export interface ServerListAsk {
  page: number;
  pageSize: number;
  search?: string;
}

/** One page of a list route's reply: `ListResult` as every paged route answers it. */
export interface ServerListPage<T> {
  data: T[];
  pagination: Pick<PaginationMeta, 'page' | 'hasNext' | 'total'>;
}

/**
 * Rows of a paged list route for a search typed in the browser: the search is sent to the server after a pause, and
 * the next page is asked for when the list scrolls to its end (`fetchNextPage`). Every list that is not an `/options`
 * picker and not a data table (a gallery, the pieces of a document) reads through this, so a team with thousands of
 * rows finds any of them; `useOptionSearch` is the same for `/options` sources.
 */
export function useServerList<T>(
  queryKey: QueryKey,
  fetchPage: (ask: ServerListAsk) => Promise<ServerListPage<T>>,
  { search = '', enabled = true, pageSize = 25 }: { search?: string; enabled?: boolean; pageSize?: number } = {},
) {
  const debounced = useDebounced(search.trim(), 200);
  const query = useTeamInfiniteQuery({
    queryKey: [...queryKey, 'server-list', debounced, pageSize],
    queryFn: ({ pageParam }) => fetchPage({ page: pageParam, pageSize, search: debounced || undefined }),
    initialPageParam: 1,
    getNextPageParam: (last: ServerListPage<T>) => (last.pagination.hasNext ? last.pagination.page + 1 : undefined),
    placeholderData: keepPreviousData,
    enabled,
  });
  const rows = (query.data?.pages ?? []).flatMap((p) => p.data);
  const total = query.data?.pages[0]?.pagination.total;
  return { ...query, rows, total, searching: debounced !== search.trim() || (query.isFetching && query.isPlaceholderData) };
}
