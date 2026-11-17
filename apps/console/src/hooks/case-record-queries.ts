'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { CaseRecordFilters, CaseRecordPatch } from '@/lib/types/case-records';
import { useTeamQuery } from './team-query';

const root = ['case-records'] as const;

export const useCaseRecords = (p: { page: number; pageSize: number } & CaseRecordFilters) =>
  usePagedQuery({
    queryKey: [...root, 'list', p],
    queryFn: () =>
      sdk((ops) =>
        ops.raw.agents.cases_list_cases({
          query: { page: p.page, pageSize: p.pageSize, search: p.search, status: p.status, priority: p.priority, assignee: p.assignee, overdue: p.overdue },
        }),
      ),
  });
export const useCaseRecord = (id: string) => useTeamQuery({ queryKey: [...root, 'one', id], queryFn: () => api.caseRecords.get(id) });

function useCaseWrite<A>(fn: (a: A) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: root }) });
}

export const useChangeCaseRecord = () => useCaseWrite(({ id, patch }: { id: string; patch: CaseRecordPatch }) => api.caseRecords.change(id, patch));
export const useAddCaseNote = () => useCaseWrite(({ id, text }: { id: string; text: string }) => api.caseRecords.addNote(id, text));
