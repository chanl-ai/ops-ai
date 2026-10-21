'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { WorkspaceTeamFilters, WorkspaceTeamInput } from '@/lib/types/team';

const KEY = ['workspace-teams'] as const;

/** Every team of the workspace, one server page at a time (workspace admins, c-198). */
export const useWorkspaceTeams = (params: ListParams<WorkspaceTeamFilters>) =>
  usePagedQuery({ queryKey: [...KEY, params], queryFn: () => api.workspaceTeams.list(params) });

/** Whether the person is a workspace admin who may list and change teams, from the server's permissions. */
export const useWorkspaceTeamsEditor = () => useQuery({ queryKey: [...KEY, 'editor'], queryFn: () => api.workspaceTeams.editor() });

function useTeamWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  // A team change also changes the switcher's list and the person's next token.
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: ['teams'] })]) });
}

export const useCreateWorkspaceTeam = () => useTeamWrite((input: WorkspaceTeamInput) => api.workspaceTeams.create(input));
export const useRenameWorkspaceTeam = () => useTeamWrite(({ id, name }: { id: string; name: string }) => api.workspaceTeams.rename(id, name));
export const useArchiveWorkspaceTeam = () => useTeamWrite((id: string) => api.workspaceTeams.archive(id));
export const useRestoreWorkspaceTeam = () => useTeamWrite((id: string) => api.workspaceTeams.restore(id));
