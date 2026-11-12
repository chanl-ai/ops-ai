import type { PolicyEditor } from '@/lib/types/workspace-policies';

import type { WorkspacePoliciesApi } from './workspace-policies-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

interface TeamPermissions {
  teamId: string;
  permissions: { area: string; action: string; roles: { name: string }[] }[];
}

export function createWorkspacePoliciesHttp(get: Get, send: Send): WorkspacePoliciesApi {
  return {
    list: () => get('/policies'),
    set: (key, value) => send('PUT', `/policies/${encodeURIComponent(key)}`, { value }),
    editor: async (teamId): Promise<PolicyEditor> => {
      const me = await get<{ teams: TeamPermissions[] }>('/me/permissions');
      const cells: PolicyEditor['cells'] = {};
      for (const p of me.teams.find((t) => t.teamId === teamId)?.permissions ?? []) cells[`${p.area}.${p.action}`] = [...new Set(p.roles.map((r) => r.name))];
      return { cells };
    },
  };
}
