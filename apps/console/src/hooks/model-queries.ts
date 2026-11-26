'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ModelAliasInput } from '@/lib/types/models';
import type { ListParams } from '@/lib/types/query';

import { usePagedQuery } from './paged-query';
import { useTeamQuery } from './team-query';

const ALIASES = ['model-aliases-admin'] as const;

/** The provider types a connection can be made of, as models-service's registry lists them (account admins only). */
export const useProviderTypes = (enabled = true) => useTeamQuery({ queryKey: ['provider-types'], queryFn: () => api.providerConnections.types(), staleTime: 5 * 60_000, retry: false, enabled });

/** The catalog's models for one connection: what each can do, its context and list price. Read when its sheet opens. */
export const useConnectionCatalog = (providerId: string | null) => useTeamQuery({ queryKey: ['provider-catalog', providerId], queryFn: () => api.providerConnections.catalog(providerId!), enabled: !!providerId, retry: false });

/** The account's aliases, newest version each (account admins only). */
export const useModelAliasList = (p: ListParams, enabled = true) => usePagedQuery({ queryKey: [...ALIASES, p], queryFn: () => api.modelAliases.list(p), retry: false, enabled });

export function useSaveAlias() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, version, input }: { name: string; version: boolean; input: ModelAliasInput }) => (version ? api.modelAliases.newVersion(name, input) : api.modelAliases.create({ ...input, name })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ALIASES });
      qc.invalidateQueries({ queryKey: ['agent-model-aliases'] });
    },
  });
}

/** The settings an agent on `alias` may save: only the knobs its model takes, with their ranges and catalog defaults. */
export const useAliasKnobs = (alias: string, enabled = true) => useTeamQuery({ queryKey: ['alias-knobs', alias], queryFn: () => api.agents.modelAliasKnobs(alias), enabled: enabled && !!alias, retry: false });
