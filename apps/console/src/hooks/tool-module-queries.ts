'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { ApprovalRequestInput, ModuleFilters, ModuleInput, ModuleSource, ModuleTestInput, ModuleView, OperationPatch } from '@/lib/types/tool-modules';

/** Module keys start with 'modules'; module writes also refresh 'tools' (agent grants read operations) and 'agent'. */
export const mk = {
  list: (p: unknown) => ['modules', 'list', p] as const,
  one: (id: string) => ['modules', 'one', id] as const,
  activity: (id: string) => ['modules', 'activity', id] as const,
  catalog: ['modules', 'catalog'] as const,
};

export const useToolModules = (p: ListParams<ModuleFilters> & { view: ModuleView }) => useQuery({ queryKey: mk.list(p), queryFn: () => api.toolModules.list(p), placeholderData: keepPreviousData });
export const useToolModule = (id: string) => useQuery({ queryKey: mk.one(id), queryFn: () => api.toolModules.get(id) });
export const useModuleActivity = (id: string, enabled = true) => useQuery({ queryKey: mk.activity(id), queryFn: () => api.toolModules.activity(id), enabled });
export const useToolCatalog = (enabled = true) => useQuery({ queryKey: mk.catalog, queryFn: api.toolModules.catalog, enabled, staleTime: 60_000 });

function useModuleWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['modules', 'tools', 'agent', 'agents'].map((k) => qc.invalidateQueries({ queryKey: [k] }))) });
}

/** Discovery reads a server or spec and saves nothing, so it invalidates nothing. */
export const useDiscoverModule = () => useMutation({ mutationFn: (source: ModuleSource) => api.toolModules.discover(source) });
export const useTestModule = () => useMutation({ mutationFn: ({ id, ...input }: ModuleTestInput & { id: string }) => api.toolModules.test(id, input) });

export const useCreateModule = () => useModuleWrite((i: ModuleInput) => api.toolModules.create(i));
export const useBulkDeleteModules = () => useModuleWrite((ids: string[]) => api.toolModules.bulkRemove(ids));
export const useDeleteModule = () => useModuleWrite((id: string) => api.toolModules.remove(id));
export const useUpdateOperation = () => useModuleWrite(({ id, operationId, patch }: { id: string; operationId: string; patch: OperationPatch }) => api.toolModules.updateOperation(id, operationId, patch));
export const usePublishModuleVersion = () => useModuleWrite(({ id, note }: { id: string; note: string }) => api.toolModules.publishVersion(id, note));
export const useDiscardModuleChanges = () => useModuleWrite((id: string) => api.toolModules.discardChanges(id));
export const useRequestModuleReview = () => useModuleWrite(({ id, note }: { id: string; note: string }) => api.toolModules.requestReview(id, note));
export const useRequestModuleApproval = () => useModuleWrite(({ id, ...input }: ApprovalRequestInput & { id: string }) => api.toolModules.requestApproval(id, input));
export const useDecideModuleApproval = () =>
  useModuleWrite(({ id, approvalId, decision, reason }: { id: string; approvalId: string; decision: 'approved' | 'rejected'; reason?: string }) => api.toolModules.decideApproval(id, approvalId, decision, reason));
export const useRevokeModuleApprovals = () => useModuleWrite(({ id, approvalIds, reason }: { id: string; approvalIds: string[]; reason: string }) => api.toolModules.revokeApprovals(id, approvalIds, reason));
export const useSetCredentialRef = () => useModuleWrite(({ id, credentialId, secretRef }: { id: string; credentialId: string; secretRef: string }) => api.toolModules.setCredentialRef(id, credentialId, secretRef));
