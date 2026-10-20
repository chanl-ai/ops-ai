'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { PolicyValue } from '@/lib/types/workspace-policies';

import { useTeam } from './use-team';

const KEY = ['workspace-policies'] as const;

export const useWorkspacePolicies = () => useQuery({ queryKey: KEY, queryFn: () => api.workspacePolicies.list() });
/** Whether the person may change policies in the team they act in, as the server's own permissions say. */
export function usePolicyEditor() {
  // The resolved team: the stored choice may name a team the person is not in, and the requests then act in their first one.
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  return useQuery({ queryKey: [...KEY, 'editor', teamId], queryFn: () => api.workspacePolicies.editor(teamId), enabled: !!teamId });
}
export function useSetWorkspacePolicy() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: { key: string; value: PolicyValue; teamId?: string }) => api.workspacePolicies.set(i.key, i.value, i.teamId), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
