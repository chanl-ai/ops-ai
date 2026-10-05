'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ConditionInput, ConditionStatus, ModelRiskFilters, ModelRiskView, TierChangeInput } from '@/lib/types/model-risk';
import type { ListParams } from '@/lib/types/query';

export const mk = {
  list: (p: unknown) => ['model-risk', 'list', p] as const,
  entry: (id: string) => ['model-risk', 'entry', id] as const,
  options: ['model-risk', 'options'] as const,
};

const paged = { placeholderData: keepPreviousData };

export const useModelRisk = (p: ListParams<ModelRiskFilters> & { view: ModelRiskView }) => useQuery({ queryKey: mk.list(p), queryFn: () => api.modelRisk.list(p), ...paged });
export const useModelEntry = (id: string) => useQuery({ queryKey: mk.entry(id), queryFn: () => api.modelRisk.get(id) });
export const useModelRiskOptions = () => useQuery({ queryKey: mk.options, queryFn: api.modelRisk.options, staleTime: 5 * 60_000 });

/** Model risk writes can open reviews and always write the audit log, so those refresh too. */
function useModelRiskWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['model-risk', 'reviews', 'logs', 'notifications'].map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

export const useRequestValidation = () => useModelRiskWrite(({ ids, note }: { ids: string[]; note?: string }) => api.modelRisk.requestValidation(ids, note));
export const useSetNextReview = () => useModelRiskWrite(({ ids, date }: { ids: string[]; date: string }) => api.modelRisk.setNextReview(ids, date));
export const useChangeTier = (id: string) => useModelRiskWrite((i: TierChangeInput) => api.modelRisk.changeTier(id, i));
export const useAddCondition = (id: string) => useModelRiskWrite((i: ConditionInput) => api.modelRisk.addCondition(id, i));
export const useSetConditionStatus = (id: string) =>
  useModelRiskWrite(({ conditionId, status, reason }: { conditionId: string; status: ConditionStatus; reason: string }) => api.modelRisk.setConditionStatus(id, conditionId, status, reason));
