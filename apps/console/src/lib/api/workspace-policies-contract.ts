import type { PolicyEditor, PolicyValue, WorkspacePolicy } from '@/lib/types/workspace-policies';

/**
 * The workspace's access policies on platform-service (c-186). Reading needs settings.view and changing settings.manage
 * in the team the request acts in; `editor` reports the second so the console offers a control only to a person who
 * can use it, from the server's own permissions and not from a role named here.
 */
export interface WorkspacePoliciesApi {
  list(): Promise<WorkspacePolicy[]>;
  /** `teamId` names the team a per-team policy (publish review) is set for; the mock needs it, platform-service reads it from X-Team-Id. */
  set(key: string, value: PolicyValue, teamId?: string): Promise<WorkspacePolicy>;
  editor(teamId: string): Promise<PolicyEditor>;
}
