'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { OptionSource } from '@/hooks/options-queries';
import type { ListParams } from '@/lib/types/query';
import type { ChatModelChoice, KeyWhere } from '@/lib/types/provider-keys';
import { useTeamQuery } from './team-query';

const KEY = ['provider-keys'] as const;

/** One page of the account's model provider keys by name (account admins only); a value never comes back. */
export const useProviderKeys = (p: ListParams, enabled = true) => usePagedQuery({ queryKey: [...KEY, p], queryFn: () => api.providerKeys.list(p), retry: false, enabled });

/** Saved keys for a picker: searched on the server as typed, or named by name (a key's name is its id). */
export const providerKeyOptions: OptionSource = {
  key: 'provider-key-options',
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await api.providerKeys.list(ids?.length ? { page: 1, pageSize: Math.min(ids.length, 50), ids } : { page, pageSize: limit, search: search || undefined });
    return { data: res.data.map((k) => ({ id: k.name, label: k.name })), nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null };
  },
};

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
