'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { AssuranceFilters, AssuranceTab } from '@/lib/types/assurance';
import type { ListParams } from '@/lib/types/query';

export const ak = {
  list: (p: unknown) => ['assurance', 'list', p] as const,
};

/**
 * One read per tab: the page's stats, the per-tab counts and that tab's rows. The previous result is kept while
 * paging within a tab but not across tabs, because another tab's rows have a different shape.
 */
export const useAssurance = <K extends AssuranceTab>(p: ListParams<AssuranceFilters> & { tab: K }) =>
  useQuery({
    queryKey: ak.list(p),
    queryFn: () => api.assurance.list(p),
    placeholderData: (prev, prevQuery) => ((prevQuery?.queryKey[2] as { tab?: string } | undefined)?.tab === p.tab ? prev : undefined),
  });

/** The export lands in Files, so the files list refreshes too. */
export function useExportBundle() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.assurance.exportBundle(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['files'] }) });
}
