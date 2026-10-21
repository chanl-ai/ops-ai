'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { WikiFilters, WikiView } from '@/lib/types/wiki';

export const wk = {
  list: (p: unknown) => ['wiki', 'list', p] as const,
  page: (id: string) => ['wiki', 'page', id] as const,
  collections: ['wiki', 'collections'] as const,
};

export const useWikiPages = (p: ListParams<WikiFilters> & { view: WikiView }) => usePagedQuery({ queryKey: wk.list(p), queryFn: () => api.wiki.list(p) });
export const useWikiPage = (id: string | null) => useQuery({ queryKey: wk.page(id ?? ''), queryFn: () => api.wiki.get(id!), enabled: !!id });
export const useWikiCollections = () => useQuery({ queryKey: wk.collections, queryFn: api.wiki.collections });
export const useWikiCollectionsPage = (p: ListParams) => usePagedQuery({ queryKey: [...wk.collections, 'page', p], queryFn: () => api.wiki.collectionsPage(p) });

export function useVerifyWikiPage() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.wiki.verify(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['wiki'] }) });
}
