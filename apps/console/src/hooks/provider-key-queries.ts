'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ChatModelChoice, KeyWhere } from '@/lib/types/provider-keys';
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

/** Asks the provider whether the saved key works. */
export const useCheckProviderKey = () => useMutation({ mutationFn: ({ name, where }: { name: string; where: KeyWhere }) => api.providerKeys.check(name, where) });

/** The models a saved key reaches, once it has passed its check (`where` null until then). */
export const useProviderKeyModels = (name: string, where: KeyWhere | null) =>
  useTeamQuery({ queryKey: [...KEY, name, 'models', where], queryFn: () => api.providerKeys.models(name, where!), enabled: !!where, retry: false });

/** Points chat at a model the saved key lists; aliases and keys are read again after it. */
export function useSetChatModel() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (choice: ChatModelChoice) => api.providerKeys.setChatModel(choice), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
