'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { ProviderConnectionInput } from '@/lib/types/models';

const KEY = ['provider-connections'] as const;

/** The account's model provider connections (account admins only): endpoint, type, region and key name, never a key. */
export const useProviderConnections = (p: ListParams, enabled = true) => usePagedQuery({ queryKey: [...KEY, p], queryFn: () => api.providerConnections.list(p), retry: false, enabled });

export function useCreateProviderConnection() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (input: ProviderConnectionInput) => api.providerConnections.create(input), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
