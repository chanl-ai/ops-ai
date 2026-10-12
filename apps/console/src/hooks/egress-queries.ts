'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { EgressKind } from '@/lib/types/egress';

const KEY = ['egress'] as const;

export const useEgress = () => useQuery({ queryKey: KEY, queryFn: () => api.egress.list() });

export function useAddEgress() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: { kind: EgressKind; value: string; note: string }) => api.egress.add(i.kind, i.value, i.note), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export function useRemoveEgress() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: { kind: EgressKind; value: string }) => api.egress.remove(i.kind, i.value), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
