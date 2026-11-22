'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { sdk } from '@/lib/api/ops-sdk';
import type { ListParams } from '@/lib/types/query';
import type { OpsAI } from '@chanl-ai/ops-ai';

type Tools = OpsAI['raw']['tools'];
type Data<K extends keyof Tools> = Awaited<ReturnType<Tools[K]>>;

/** One secret as tools-service lists it: never its value. Headers name it as `{{NAME}}`. */
export type SecretMeta = Data<'secrets_list_secrets'>['data'][number];

const KEY = ['secrets'] as const;

/** One page of the team's secrets (GET /v1/secrets): searched on the name, by name or by `sortBy`; an account's or auth config's secret is read only. */
export const useSecretsPage = (p: ListParams) =>
  usePagedQuery({
    queryKey: [...KEY, 'page', p.page, p.pageSize, p.search ?? '', p.sortBy ?? '', p.sortOrder ?? ''],
    queryFn: () => sdk((ops) => ops.raw.tools.secrets_list_secrets({ query: { page: p.page, pageSize: p.pageSize, search: p.search, sortBy: p.sortBy, sortOrder: p.sortOrder } })),
  });

function useSecretMutation<I>(fn: (i: I) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

export const useCreateSecret = () => useSecretMutation((i: { name: string; value: string }) => sdk((ops) => ops.raw.tools.secrets_create_secret({ body: i })));
export const useRotateSecret = () =>
  useSecretMutation((i: { name: string; value: string }) => sdk((ops) => ops.raw.tools.secrets_rotate_secret({ path: { name: i.name }, body: { value: i.value } })));
export const useRenameSecret = () =>
  useSecretMutation((i: { name: string; to: string }) => sdk((ops) => ops.raw.tools.secrets_rename_secret({ path: { name: i.name }, body: { name: i.to } })));
export const useDeleteSecret = () => useSecretMutation((name: string) => sdk((ops) => ops.raw.tools.secrets_delete_secret({ path: { name } })));
