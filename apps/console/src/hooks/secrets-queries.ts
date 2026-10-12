'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

const KEY = ['secrets'] as const;

export const useSecrets = () => useQuery({ queryKey: KEY, queryFn: () => api.secrets.list() });

function useSecretMutation<I>(fn: (i: I) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateSecret = () => useSecretMutation((i: { name: string; value: string }) => api.secrets.create(i.name, i.value));
export const useRotateSecret = () => useSecretMutation((i: { name: string; value: string }) => api.secrets.rotate(i.name, i.value));
export const useDeleteSecret = () => useSecretMutation((name: string) => api.secrets.remove(name));
