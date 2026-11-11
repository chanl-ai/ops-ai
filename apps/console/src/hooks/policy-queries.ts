'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { PolicyValue } from '@/lib/types/workspace-policies';

import { useTeam } from './use-team';
import { useTeamQuery } from './team-query';

const KEY = ['workspace-policies'] as const;

export const useWorkspacePolicies = () => useTeamQuery({ queryKey: KEY, queryFn: () => api.workspacePolicies.list() });
/** Whether the team in view asks before an agent changes an app (appChanges): what an unset write's "Team default" means. */
export function useTeamWritesWait(): boolean {
  const { team } = useTeam();
  const value = useWorkspacePolicies().data?.find((p) => p.key === 'appChanges')?.value;
  const mine = value && typeof value === 'object' && !Array.isArray(value) && team ? (value as Record<string, unknown>)[team.id] : undefined;
  return !!mine && typeof mine === 'object' && (mine as { ask?: boolean }).ask === true;
}
/** Whether the person may change policies in the team they act in, as the server's own permissions say. */
export function usePolicyEditor() {
  // The resolved team: the stored choice may name a team the person is not in, and the requests then act in their first one.
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  return useTeamQuery({ queryKey: [...KEY, 'editor', teamId], queryFn: () => api.workspacePolicies.editor(teamId), enabled: !!teamId });
}
export function useSetWorkspacePolicy() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: { key: string; value: PolicyValue; teamId?: string }) => api.workspacePolicies.set(i.key, i.value, i.teamId), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}
