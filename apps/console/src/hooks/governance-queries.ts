'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { AuditFilters, AuditView, GrantFilters, GrantInput, GrantView, RoleFilters, RoleInput, ToolCallFilters } from '@/lib/types/governance';
import type { ListParams } from '@/lib/types/query';

/** Logs keys start with 'logs', access keys with 'access'; an access write also adds an audit entry. */
export const gk = {
  calls: (p: unknown) => ['logs', 'calls', p] as const,
  call: (id: string) => ['logs', 'call', id] as const,
  audit: (p: unknown) => ['logs', 'audit', p] as const,
  identities: (p: unknown) => ['access', 'identities', p] as const,
  grants: (p: unknown) => ['access', 'grants', p] as const,
  roles: (p: unknown) => ['access', 'roles', p] as const,
  options: ['access', 'options'] as const,
};

const paged = { placeholderData: keepPreviousData };

export const useToolCalls = (p: ListParams<ToolCallFilters>) => useQuery({ queryKey: gk.calls(p), queryFn: () => api.governance.toolCalls.list(p), ...paged });
export const useToolCall = (id: string | null) => useQuery({ queryKey: gk.call(id ?? ''), queryFn: () => api.governance.toolCalls.get(id!), enabled: !!id });
export const useAudit = (p: ListParams<AuditFilters> & { view: AuditView }) => useQuery({ queryKey: gk.audit(p), queryFn: () => api.governance.audit.list(p), ...paged });

export const useIdentities = (p: ListParams) => useQuery({ queryKey: gk.identities(p), queryFn: () => api.governance.access.identities(p), ...paged });
export const useGrants = (p: ListParams<GrantFilters> & { view: GrantView }) => useQuery({ queryKey: gk.grants(p), queryFn: () => api.governance.access.grants(p), ...paged });
export const useRoles = (p: ListParams<RoleFilters>) => useQuery({ queryKey: gk.roles(p), queryFn: () => api.governance.access.roles(p), ...paged });
export const useAccessOptions = () => useQuery({ queryKey: gk.options, queryFn: api.governance.access.options, staleTime: 60_000 });

function useAccessWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['access', 'logs'].map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

export const useGrantAccess = () => useAccessWrite((i: GrantInput) => api.governance.access.grant(i));
export const useRevokeGrants = () => useAccessWrite(({ ids, reason }: { ids: string[]; reason: string }) => api.governance.access.revoke(ids, reason));
export const useExtendGrants = () => useAccessWrite(({ ids, days }: { ids: string[]; days: number }) => api.governance.access.extend(ids, days));
export const useAssignRole = () => useAccessWrite((i: RoleInput) => api.governance.access.assignRole(i));
export const useRemoveRoles = () => useAccessWrite((ids: string[]) => api.governance.access.removeRoles(ids));
