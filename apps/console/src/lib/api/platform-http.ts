import type { AccessCheck, ApiKey, Holders, Me, PersonPermissions, RoleCreated, RoleDetail, RoleGrant, RoleHolder, RoleSummary, WhyNot } from '@/lib/types/settings';
import type { ListResult } from '@/lib/types/query';
import type { Team } from '@/lib/types/team';

import type { OpsApi } from './contract';
import { createTransport } from './http';
import { createOAuthHttp } from './oauth-http';
import { createSignInProvidersHttp } from './sign-in-providers-http';
import { createWorkspacePoliciesHttp } from './workspace-policies-http';
import { createWorkspaceTeamsHttp } from './workspace-teams-http';

/**
 * The teams a person signed in through platform-service belongs to (GET /v1/teams). Their token already names every
 * one of them, so switching changes only the X-Team-Id the console sends. Teams are created by an admin in platform
 * settings, so there is no create.
 */
export function createPlatformTeamsHttp(baseUrl: string): OpsApi['teams'] {
  const { get, send, qs } = createTransport(`${baseUrl}/v1`);
  return {
    list: async (p) => {
      const page = await get<ListResult<Omit<Team, 'icon'>>>(`/teams?${qs(p)}`);
      return { ...page, data: page.data.map((t) => ({ ...t, icon: 'team' as const })) };
    },
    me: () => get<Me>('/me'),
    roles: (p) => get<ListResult<RoleSummary>>(`/roles?${qs(p)}`),
    role: (id) => get<RoleDetail>(`/roles/${encodeURIComponent(id)}`),
    editRole: (id, permissions) => send<RoleDetail>('PUT', `/roles/${encodeURIComponent(id)}/permissions`, { permissions }),
    resetRole: (id) => send<RoleDetail>('POST', `/roles/${encodeURIComponent(id)}/reset`),
    createRole: (input) => send<RoleCreated>('POST', '/roles', input),
    renameRole: (id, input) => send<RoleDetail>('PATCH', `/roles/${encodeURIComponent(id)}`, input),
    deleteRole: (id, moveTo) => send<void>('DELETE', `/roles/${encodeURIComponent(id)}${moveTo ? `?moveTo=${encodeURIComponent(moveTo)}` : ''}`),
    roleHolders: (id, p) => get<ListResult<RoleHolder>>(`/roles/${encodeURIComponent(id)}/holders?${qs(p)}`),
    roleGrants: (person, p) => get<ListResult<RoleGrant>>(`/people/${encodeURIComponent(person)}/role-grants?${qs(p)}`),
    giveRole: (person, input) => send<RoleGrant>('POST', `/people/${encodeURIComponent(person)}/role-grants`, input),
    takeRole: (person, grant) => send<void>('DELETE', `/people/${encodeURIComponent(person)}/role-grants/${encodeURIComponent(grant)}`),
    personPermissions: (id) => get<PersonPermissions>(`/people/${encodeURIComponent(id)}/permissions`),
    why: (area, action) => get<WhyNot>(`/me/why?area=${encodeURIComponent(area)}&action=${encodeURIComponent(action)}`),
    checkAccess: (input) => send<AccessCheck>('POST', '/access/check', input),
    renameWorkspace: (name) => send<{ id: string; name: string }>('PATCH', '/settings/workspace', { name }),
    holders: (area, action, team) =>
      get<Holders>(`/access/holders?area=${encodeURIComponent(area)}&action=${encodeURIComponent(action)}${team ? `&team=${encodeURIComponent(team)}` : ''}`),
  };
}

/** The workspace's access policies on platform-service (GET and PUT /v1/policies). */
export function createPlatformPoliciesHttp(baseUrl: string): OpsApi['workspacePolicies'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createWorkspacePoliciesHttp(get, send);
}

/** The workspace's sign-in providers and their domain proofs (/v1/settings/sign-in/…). */
export function createPlatformSignInProvidersHttp(baseUrl: string): OpsApi['signInProviders'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return { ...createSignInProvidersHttp(get, send), samlMetadataUrl: `${baseUrl}/v1/auth/saml/metadata` };
}

/** The consent page and the person's connected assistants (/v1/oauth/…). */
export function createPlatformOAuthHttp(baseUrl: string): OpsApi['oauth'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createOAuthHttp(get, send);
}

/** Every team of the workspace, for workspace admins (GET, POST, PATCH /v1/settings/teams). */
export function createPlatformWorkspaceTeamsHttp(baseUrl: string): OpsApi['workspaceTeams'] {
  const { get, send } = createTransport(`${baseUrl}/v1`);
  return createWorkspaceTeamsHttp(get, send);
}

/**
 * The team's API keys (/v1/api-keys), the one list every keys screen reads (Settings › Team › API keys, an MCP link's
 * Keys tab), one page at a time with its search and total. A key's
 * scopes there are `read` and `write`; a console scope that changes anything (`runs:write`) asks for write.
 */
export function createPlatformApiKeysHttp(baseUrl: string): OpsApi['settings']['apiKeys'] {
  const { get, send, qs } = createTransport(`${baseUrl}/v1`);
  return {
    list: (p) => {
      // An MCP link's Keys tab names its link; platform-service keeps the keys made for it. Page, size and search are the service's.
      const link = p.filters?.mcpLink?.[0];
      const q = new URLSearchParams(qs({ ...p, filters: undefined }));
      if (link) {
        q.set('targetKind', 'mcp_link');
        q.set('targetId', link);
      }
      return get<ListResult<ApiKey>>(`/api-keys?${q}`);
    },
    create: async (input) => {
      const scopes = input.target ? ['read'] : input.scopes.some((s) => s === 'write' || s.endsWith(':write')) ? ['read', 'write'] : ['read'];
      const made = await send<{ key: ApiKey; secret: string }>('POST', '/api-keys', { name: input.name, scopes, expiresInDays: input.expiresInDays, ...(input.target ? { target: input.target } : {}) });
      return { key: made.secret, apiKey: made.key };
    },
    revoke: async (id) => {
      await send('POST', `/api-keys/${encodeURIComponent(id)}/revoke`);
    },
  };
}
