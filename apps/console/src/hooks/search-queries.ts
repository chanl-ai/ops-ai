'use client';

import * as React from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { SearchHit } from '@/lib/types/search';

const DEBOUNCE_MS = 200;

/** Palette search: debounced, keeps the last results on screen while the next query loads. */
export function useSearch(input: string, enabled: boolean) {
  const [q, setQ] = React.useState(input.trim());
  React.useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [input]);
  const query = useQuery({ queryKey: ['search', q], queryFn: () => api.search.query(q), enabled: enabled && q.length > 0, placeholderData: keepPreviousData, staleTime: 10_000 });
  // While typing, or while the debounced query is in flight, the shown results are for an older query.
  const settling = input.trim() !== q || (query.isFetching && query.isPlaceholderData);
  return { ...query, q, settling };
}

export const useRecentSearches = (enabled: boolean) => useQuery({ queryKey: ['search', 'recent'], queryFn: api.search.recent, enabled });

export function useVisitSearchHit() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (hit: SearchHit) => api.search.visit(hit), onSuccess: () => qc.invalidateQueries({ queryKey: ['search', 'recent'] }) });
}
