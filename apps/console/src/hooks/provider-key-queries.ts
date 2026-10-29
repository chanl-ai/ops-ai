'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { useTeamQuery } from './team-query';

const KEY = ['provider-keys'] as const;

/** The account's model provider keys by name (account admins only); a value never comes back. */
export const useProviderKeys = (enabled = true) => useTeamQuery({ queryKey: KEY, queryFn: () => api.providerKeys.list(), retry: false, enabled });

function useKeyWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useSaveProviderKey = () => useKeyWrite(({ name, value }: { name: string; value: string }) => api.providerKeys.save(name, value));
export const useRemoveProviderKey = () => useKeyWrite((name: string) => api.providerKeys.remove(name));
