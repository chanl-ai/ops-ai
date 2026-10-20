import type { ListParams, ListResult } from '@/lib/types/query';
import type { WorkspaceTeam, WorkspaceTeamFilters, WorkspaceTeamInput } from '@/lib/types/team';

/**
 * Every team of the workspace as workspace admins manage it on platform-service (c-198): a workspace admin holds
 * access.manage in every team (an Admin role in `*`); listing needs access.view there. `editor` reports both from the
 * server's own permissions, so the console offers a control only to a person who can use it.
 */
export interface WorkspaceTeamsApi {
  list(params: ListParams<WorkspaceTeamFilters>): Promise<ListResult<WorkspaceTeam>>;
  create(input: WorkspaceTeamInput): Promise<WorkspaceTeam>;
  rename(id: string, name: string): Promise<WorkspaceTeam>;
  archive(id: string): Promise<WorkspaceTeam>;
  restore(id: string): Promise<WorkspaceTeam>;
  editor(): Promise<{ canView: boolean; canManage: boolean }>;
}
