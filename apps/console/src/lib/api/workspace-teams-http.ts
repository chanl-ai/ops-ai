import type { ListResult } from '@/lib/types/query';
import type { WorkspaceTeam } from '@/lib/types/team';

import { addSort } from './sort-query';
import type { WorkspaceTeamsApi } from './workspace-teams-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** platform-service's team routes for workspace admins (GET, POST, PATCH /v1/settings/teams). */
export function createWorkspaceTeamsHttp(get: Get, send: Send): WorkspaceTeamsApi {
  return {
    list: (p) => {
      const q = addSort(new URLSearchParams({ page: String(p.page), pageSize: String(p.pageSize) }), p);
      if (p.search) q.set('search', p.search);
      for (const s of p.filters?.status ?? []) q.append('status', s);
      return get<ListResult<WorkspaceTeam>>(`/settings/teams?${q}`);
    },
    create: (input) => send('POST', '/settings/teams', { name: input.name.trim(), admin: input.admin.trim() }),
    rename: (id, name) => send('PATCH', `/settings/teams/${encodeURIComponent(id)}`, { name: name.trim() }),
    archive: (id) => send('POST', `/settings/teams/${encodeURIComponent(id)}/archive`),
    restore: (id) => send('POST', `/settings/teams/${encodeURIComponent(id)}/restore`),
  };
}
