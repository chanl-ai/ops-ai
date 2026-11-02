'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ProviderConnectionInput } from '@/lib/types/models';
import { useTeamQuery } from './team-query';

const KEY = ['provider-connections'] as const;

/** The account's model provider connections (account admins only): endpoint, type, region and key name, never a key. */
export const useProviderConnections = (enabled = true) => useTeamQuery({ queryKey: KEY, queryFn: () => api.providerConnections.list(), retry: false, enabled });

export function useCreateProviderConnection() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (input: ProviderConnectionInput) => api.providerConnections.create(input), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
