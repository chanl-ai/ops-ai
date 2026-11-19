'use client';

/**
 * Guardrails on the generated SDK (agents-service `/v1/guardrails`): the grid's page, one guardrail, the pins an agent
 * holds read by id, and the writes. Types come from the SDK's operations, so a route change shows here as a type error.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { ListParams } from '@/lib/types/query';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { usePagedQuery } from './paged-query';
import { useTeamQuery } from './team-query';

type Agents = OpsAI['raw']['agents'];
type Args<K extends keyof Agents> = NonNullable<Parameters<Agents[K]>[0]>;
type Data<K extends keyof Agents> = Awaited<ReturnType<Agents[K]>>;

export type GuardrailPage = Data<'agents_list_guardrails'>;
export type Guardrail = GuardrailPage['data'][number];
export type GuardrailInput = Args<'agents_create_guardrail'>['body'];
export type GuardrailPatch = Args<'agents_update_guardrail'>['body'];

// Every guardrail read sits under this key, so a write refreshes the grid, a page and the agent page's pins.
const KEY = ['agent-guardrails'] as const;

/** One page of guardrails; the server searches the name and owner and sorts by name. */
export const useGuardrailsPage = (p: ListParams) =>
  usePagedQuery({
    queryKey: [...KEY, 'page', p],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_list_guardrails({ query: { page: p.page, pageSize: p.pageSize, search: p.search, sortBy: p.sortBy, sortOrder: p.sortOrder } })),
  });
export const useGuardrail = (id: string) => useTeamQuery({ queryKey: [...KEY, 'one', id], queryFn: () => sdk((ops) => ops.raw.agents.agents_get_guardrail({ path: { guardrail_id: id } })) });
/** The guardrails an agent pins, named with `ids` (at most 50 are shown on one agent), with the versions each can be pinned at. */
export const useGuardrailsByIds = (ids: string[]) => {
  const sorted = [...ids].sort();
  return useTeamQuery({
    queryKey: [...KEY, 'ids', sorted],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_list_guardrails({ query: { ids: sorted, pageSize: Math.min(sorted.length, 50) } })),
    enabled: sorted.length > 0,
    staleTime: 60_000,
    select: (r) => r.data,
  });
};

function useGuardrailMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateGuardrail = () => useGuardrailMutation((body: GuardrailInput) => sdk((ops) => ops.raw.agents.agents_create_guardrail({ body })));
export const useUpdateGuardrail = () =>
  useGuardrailMutation((i: { id: string; body: GuardrailPatch }) => sdk((ops) => ops.raw.agents.agents_update_guardrail({ path: { guardrail_id: i.id }, body: i.body })));
export const useRequestGuardrailPublish = () =>
  useGuardrailMutation((g: Pick<Guardrail, 'id' | 'version'>) => sdk((ops) => ops.raw.agents.agents_request_guardrail_publish({ path: { guardrail_id: g.id }, body: { version: g.version, note: '' } })));
export const useSetGuardrailStatus = () =>
  useGuardrailMutation((i: { id: string; status: Guardrail['status'] }) => sdk((ops) => ops.raw.agents.agents_set_guardrail_status({ path: { guardrail_id: i.id }, body: { status: i.status } })));
export const useDeleteGuardrail = () => useGuardrailMutation((id: string) => sdk((ops) => ops.raw.agents.agents_delete_guardrail({ path: { guardrail_id: id } })));
