'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { GuardrailInput } from '@/lib/api/guardrails-contract';
import type { Guardrail } from '@/lib/types/domain';

// The agent page's pin picker reads the same list (useGuardrails), so every write refreshes both.
const KEY = ['agent-guardrails'] as const;

function useGuardrailMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateGuardrail = () => useGuardrailMutation((i: GuardrailInput) => api.guardrails.create(i));
export const useUpdateGuardrail = () =>
  useGuardrailMutation((i: { id: string; topics: string[]; message: string; scopes?: Record<string, string>; holdUntilChecked?: boolean; note?: string }) =>
    api.guardrails.update(i.id, { topics: i.topics, message: i.message, scopes: i.scopes, holdUntilChecked: i.holdUntilChecked, note: i.note }),
  );
export const useRequestGuardrailPublish = () => useGuardrailMutation((g: Guardrail) => api.guardrails.requestPublish(g.id, g.version, ''));
export const useSetGuardrailStatus = () => useGuardrailMutation((i: { id: string; status: Guardrail['status'] }) => api.guardrails.setStatus(i.id, i.status));
export const useDeleteGuardrail = () => useGuardrailMutation((id: string) => api.guardrails.remove(id));
