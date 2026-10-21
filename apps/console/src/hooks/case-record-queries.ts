'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { CaseRecordFilters, CaseRecordPatch } from '@/lib/types/case-records';

const root = ['case-records'] as const;

export const useCaseRecords = (p: { page: number; pageSize: number } & CaseRecordFilters) =>
  usePagedQuery({ queryKey: [...root, 'list', p], queryFn: () => api.caseRecords.list(p) });
export const useCaseRecord = (id: string) => useQuery({ queryKey: [...root, 'one', id], queryFn: () => api.caseRecords.get(id) });

function useCaseWrite<A>(fn: (a: A) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: root }) });
}

export const useChangeCaseRecord = () => useCaseWrite(({ id, patch }: { id: string; patch: CaseRecordPatch }) => api.caseRecords.change(id, patch));
export const useAddCaseNote = () => useCaseWrite(({ id, text }: { id: string; text: string }) => api.caseRecords.addNote(id, text));
