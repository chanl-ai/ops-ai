import type { AccessCheck, Holders, Me, MyPermissions, PersonPermissions, RoleDetail, RoleSummary, WhyNot } from '@/lib/types/settings';
import type { Team } from '@/lib/types/team';

import type { OpsApi } from './contract';
import { createTransport } from './http';
import { createSignInProvidersHttp } from './sign-in-providers-http';
import { createWorkspacePoliciesHttp } from './workspace-policies-http';
import { createWorkspaceTeamsHttp } from './workspace-teams-http';

/**
 * The teams a person signed in through platform-service belongs to (GET /v1/teams). Their token already names every
 * one of them, so switching changes only the X-Team-Id the console sends. Teams are created by an admin in platform
 * settings, so there is no create.
 */
export function createPlatformTeamsHttp(baseUrl: string): OpsApi['teams'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return {
    list: async () => (await get<Omit<Team, 'icon'>[]>('/teams')).map((t) => ({ ...t, icon: 'team' as const })),
    me: () => get<Me>('/me'),
    roles: () => get<RoleSummary[]>('/roles'),
    role: (id) => get<RoleDetail>(`/roles/${encodeURIComponent(id)}`),
    personPermissions: (id) => get<PersonPermissions>(`/people/${encodeURIComponent(id)}/permissions`),
    why: (area, action) => get<WhyNot>(`/me/why?area=${encodeURIComponent(area)}&action=${encodeURIComponent(action)}`),
    checkAccess: (input) => send<AccessCheck>('POST', '/access/check', input),
    renameWorkspace: (name) => send<{ id: string; name: string }>('PATCH', '/settings/workspace', { name }),
    permissions: () => get<MyPermissions>('/me/permissions'),
    holders: (area, action, team) =>
      get<Holders>(`/access/holders?area=${encodeURIComponent(area)}&action=${encodeURIComponent(action)}${team ? `&team=${encodeURIComponent(team)}` : ''}`),
  };
}

/** The workspace's access policies on platform-service (GET and PUT /v1/policies, c-186). */
export function createPlatformPoliciesHttp(baseUrl: string): OpsApi['workspacePolicies'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createWorkspacePoliciesHttp(get, send);
}

/** The workspace's sign-in providers and their domain proofs (/v1/settings/sign-in/…, c-195). */
export function createPlatformSignInProvidersHttp(baseUrl: string): OpsApi['signInProviders'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return { ...createSignInProvidersHttp(get, send), samlMetadataUrl: `${baseUrl}/v1/auth/saml/metadata` };
}

/** Every team of the workspace, for workspace admins (GET, POST, PATCH /v1/settings/teams, c-198). */
export function createPlatformWorkspaceTeamsHttp(baseUrl: string): OpsApi['workspaceTeams'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createWorkspaceTeamsHttp(get, send);
}
