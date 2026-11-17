'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type { WorkspaceTeamFilters, WorkspaceTeamInput } from '@/lib/types/team';
import { useMyPermissions } from './me-queries';
import { useTeamQuery } from './team-query';

const KEY = ['workspace-teams'] as const;

/** Every team of the workspace, one server page at a time (workspace admins). */
/** `enabled` false until the editor's answer says the person may view every team, so no refused request is made. */
export const useWorkspaceTeams = (params: ListParams<WorkspaceTeamFilters>, enabled = true) =>
  usePagedQuery({ queryKey: [...KEY, params], queryFn: () => api.workspaceTeams.list(params), enabled });

/** Whether the person is a workspace admin who may list and change teams, from the server's permissions. */
/**
 * Whether the person may view and manage the workspace's teams: a workspace admin holds `access.view` and
 * `access.manage` in every team, which the one GET /v1/me answer reports as `workspace`; the mock answers its own.
 */
export function useWorkspaceTeamsEditor(): { data?: { canView: boolean; canManage: boolean }; isPending: boolean } {
  const perms = useMyPermissions();
  const sample = useTeamQuery({ queryKey: [...KEY, 'editor'], queryFn: () => api.workspaceTeams.editor!(), enabled: !api.teams.me });
  if (!api.teams.me) return sample;
  const has = (action: string) => !!perms.data?.workspace.some((p) => p.area === 'access' && p.action === action);
  return { data: perms.data ? { canView: has('view'), canManage: has('manage') } : undefined, isPending: perms.isPending };
};

function useTeamWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  // A team change also changes the switcher's list and the person's next token.
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: ['teams'] })]) });
}

export const useCreateWorkspaceTeam = () => useTeamWrite((input: WorkspaceTeamInput) => api.workspaceTeams.create(input));
export const useRenameWorkspaceTeam = () => useTeamWrite(({ id, name }: { id: string; name: string }) => api.workspaceTeams.rename(id, name));
export const useArchiveWorkspaceTeam = () => useTeamWrite((id: string) => api.workspaceTeams.archive(id));
export const useRestoreWorkspaceTeam = () => useTeamWrite((id: string) => api.workspaceTeams.restore(id));
