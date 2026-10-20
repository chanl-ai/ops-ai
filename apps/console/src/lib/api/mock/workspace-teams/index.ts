import type { WorkspaceTeamsApi } from '../../workspace-teams-contract';
import type { WorkspaceTeam } from '@/lib/types/team';

const AT = '2026-09-01T09:00:00.000Z';
const SEED: WorkspaceTeam[] = [
  { id: 'team_ops', name: 'Operations', status: 'active', scope: 'owned', createdAt: AT, archivedAt: null, memberCount: 4, adminCount: 1, security: false },
  { id: 'team_security', name: 'Security', status: 'active', scope: 'owned', createdAt: AT, archivedAt: null, memberCount: 2, adminCount: 1, security: true },
  { id: 'team_fraud', name: 'Fraud Operations', status: 'active', scope: 'owned', createdAt: AT, archivedAt: null, memberCount: 2, adminCount: 0, security: false },
];

/** Sample teams for a console with no platform-service: the page over them says so and stores nothing past a reload. */
export function createMockWorkspaceTeams(): WorkspaceTeamsApi {
  const rows = SEED.map((t) => ({ ...t }));
  const find = (id: string) => {
    const row = rows.find((t) => t.id === id);
    if (!row) throw new Error('No such team.');
    return row;
  };
  const taken = (name: string, id?: string) => rows.some((t) => t.id !== id && t.name.toLowerCase() === name.trim().toLowerCase());
  return {
    list: async (p) => {
      const wanted = p.filters?.status ?? [];
      const search = (p.search ?? '').toLowerCase();
      const all = rows.filter((t) => (!wanted.length || wanted.includes(t.status)) && t.name.toLowerCase().includes(search));
      const totalPages = Math.max(1, Math.ceil(all.length / p.pageSize));
      const page = Math.min(p.page, totalPages);
      const data = all.slice((page - 1) * p.pageSize, page * p.pageSize).map((t) => ({ ...t }));
      return { data, pagination: { page, pageSize: p.pageSize, total: all.length, totalPages, hasNext: page < totalPages, hasPrev: page > 1 }, facets: {} };
    },
    create: async (input) => {
      if (taken(input.name)) throw new Error('Another team in this workspace has that name.');
      const row: WorkspaceTeam = { id: `team_${Date.now().toString(36)}`, name: input.name.trim(), status: 'active', scope: 'owned', createdAt: new Date().toISOString(), archivedAt: null, memberCount: 1, adminCount: 1, security: false };
      rows.push(row);
      return { ...row };
    },
    rename: async (id, name) => {
      if (taken(name, id)) throw new Error('Another team in this workspace has that name.');
      const row = find(id);
      row.name = name.trim();
      return { ...row };
    },
    archive: async (id) => {
      const row = find(id);
      if (row.security) throw new Error('The Security team decides workspace settings and cannot be archived.');
      Object.assign(row, { status: 'archived', archivedAt: new Date().toISOString() });
      return { ...row };
    },
    restore: async (id) => ({ ...Object.assign(find(id), { status: 'active' as const, archivedAt: null }) }),
    editor: async () => ({ canView: true, canManage: true }),
  };
}
