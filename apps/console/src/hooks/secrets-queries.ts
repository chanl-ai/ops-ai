'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';

const KEY = ['secrets'] as const;

export const useSecrets = () => useQuery({ queryKey: KEY, queryFn: () => api.secrets.list() });
export const useSecretsPage = (p: ListParams) => usePagedQuery({ queryKey: [...KEY, 'page', p], queryFn: () => api.secrets.page(p) });

function useSecretMutation<I>(fn: (i: I) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateSecret = () => useSecretMutation((i: { name: string; value: string; teams?: string[] | null }) => api.secrets.create(i.name, i.value, i.teams));
export const useSetSecretScope = () => useSecretMutation((i: { name: string; teams: string[] | null }) => api.secrets.setScope(i.name, i.teams));
export const useRotateSecret = () => useSecretMutation((i: { name: string; value: string }) => api.secrets.rotate(i.name, i.value));
export const useDeleteSecret = () => useSecretMutation((name: string) => api.secrets.remove(name));
