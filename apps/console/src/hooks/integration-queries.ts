'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useLookups } from '@/hooks/queries';
import { useTeam } from '@/hooks/use-team';
import { api } from '@/lib/api';
import type { ConnectInput, IntegrationFilters, IntegrationView } from '@/lib/types/integrations';
import type { ListParams } from '@/lib/types/query';

export const ik = {
  list: (p: unknown) => ['integrations', 'list', p] as const,
  one: (id: string) => ['integrations', 'one', id] as const,
  options: ['integrations', 'options'] as const,
  catalog: ['integrations', 'catalog'] as const,
  impact: (ids: string[]) => ['integrations', 'impact', ids] as const,
};

export const useIntegrations = (p: ListParams<IntegrationFilters> & { view: IntegrationView }) => useQuery({ queryKey: ik.list(p), queryFn: () => api.integrations.list(p), placeholderData: keepPreviousData });
export const useIntegration = (id: string) => useQuery({ queryKey: ik.one(id), queryFn: () => api.integrations.get(id) });
export const useIntegrationOptions = (enabled = true) => useQuery({ queryKey: ik.options, queryFn: api.integrations.options, enabled });
export const useIntegrationCatalog = (enabled = true) => useQuery({ queryKey: ik.catalog, queryFn: api.integrations.catalog, enabled, staleTime: 60_000 });
/** What a revoke would stop, asked of the API when the confirm opens. */
export const useRevokeImpact = (ids: string[]) => useQuery({ queryKey: ik.impact(ids), queryFn: () => api.integrations.impact(ids), enabled: ids.length > 0 });

/** Connection changes show on sources, tool modules, mailboxes and the audit log, so writes refresh them too. */
function useIntegrationWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['integrations', 'knowledge', 'modules', 'tools', 'deployments', 'logs'].map((k) => qc.invalidateQueries({ queryKey: [k] }))) });
}

export const useConnectIntegration = () => useIntegrationWrite((i: ConnectInput) => api.integrations.connect(i));
export const useReconnectIntegration = () => useIntegrationWrite((id: string) => api.integrations.reconnect(id));
export const useRotateIntegration = () => useIntegrationWrite(({ id, credentialRef }: { id: string; credentialRef: string }) => api.integrations.rotate(id, credentialRef));
export const useCheckIntegration = () => useIntegrationWrite((id: string) => api.integrations.check(id));
export const useBulkCheckIntegrations = () => useIntegrationWrite((ids: string[]) => api.integrations.bulkCheck(ids));
export const useRevokeIntegrations = () => useIntegrationWrite(({ ids, reason }: { ids: string[]; reason: string }) => api.integrations.revoke(ids, reason));
export const useRequestScopes = () => useIntegrationWrite(({ id, scopes, justification }: { id: string; scopes: string[]; justification: string }) => api.integrations.requestScopes(id, { scopes, justification }));

/**
 * Everything the connect dialog needs, for any page that offers "Connect a new system" (Integrations, Sources,
 * Tools). Owner choices are the teams; in a team the default owner is that team.
 */
export function useConnectFlow(open: boolean) {
  const catalog = useIntegrationCatalog(open);
  const { team, teams } = useTeam();
  const lookups = useLookups();
  const connect = useConnectIntegration();
  return {
    catalog: catalog.data ?? [],
    catalogState: catalog,
    teams: teams.map((t) => t.name),
    defaultTeam: team?.name ?? '',
    currentUser: lookups.data?.currentUser.name ?? '',
    connecting: connect.isPending,
    connect: connect.mutateAsync,
  };
}
