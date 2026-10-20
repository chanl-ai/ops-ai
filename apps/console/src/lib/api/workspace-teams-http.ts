import type { ListResult } from '@/lib/types/query';
import type { WorkspaceTeam } from '@/lib/types/team';

import type { WorkspaceTeamsApi } from './workspace-teams-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

interface Permission {
  area: string;
  action: string;
}

/** platform-service's team routes for workspace admins (GET, POST, PATCH /v1/settings/teams, c-198). */
export function createWorkspaceTeamsHttp(get: Get, send: Send): WorkspaceTeamsApi {
  return {
    list: (p) => {
      const q = new URLSearchParams({ page: String(p.page), pageSize: String(p.pageSize) });
      if (p.search) q.set('search', p.search);
      for (const s of p.filters?.status ?? []) q.append('status', s);
      return get<ListResult<WorkspaceTeam>>(`/settings/teams?${q}`);
    },
    create: (input) => send('POST', '/settings/teams', { name: input.name.trim(), admin: input.admin.trim() }),
    rename: (id, name) => send('PATCH', `/settings/teams/${encodeURIComponent(id)}`, { name: name.trim() }),
    archive: (id) => send('POST', `/settings/teams/${encodeURIComponent(id)}/archive`),
    restore: (id) => send('POST', `/settings/teams/${encodeURIComponent(id)}/restore`),
    // A workspace admin holds the right in every team (`*`), which /me/permissions reports as `workspace` (c-198).
    editor: async () => {
      const me = await get<{ workspace: Permission[] }>('/me/permissions');
      const has = (action: string) => me.workspace.some((p) => p.area === 'access' && p.action === action);
      return { canView: has('view'), canManage: has('manage') };
    },
  };
}
