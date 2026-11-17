'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { NavNeed } from '@/lib/nav';
import type { ListParams } from '@/lib/types/query';
import type { MemberRole, RoleCell, RoleInput } from '@/lib/types/settings';

import { type OptionSource } from './options-queries';
import { usePagedQuery } from './paged-query';
import { useSession } from './auth-queries';
import { useTeam } from './use-team';
import { useSessionQuery, useTeamQuery } from './team-query';

/** The person's roles from platform-service (GET /v1/me); disabled off platform sign-in, where `teams.me` is absent. */
export const useMe = () => useSessionQuery({ queryKey: ['me'], queryFn: () => api.teams.me!(), enabled: !!api.teams.me, staleTime: 60_000 });

/**
 * The role the person holds in the team the console acts in, to show on their account page (GET /v1/me). It decides
 * nothing: every screen asks `useCan` for the cell it needs. Undefined while loading and off platform sign-in.
 */
export function useTeamRole(): MemberRole | undefined {
  const { teamId } = useTeam();
  const me = useMe();
  return me.data?.teams.find((t) => t.id === teamId)?.role ?? me.data?.teams[0]?.role;
}

/**
 * What `can()` grants the person in each team and in every team, from the same GET /v1/me answer `useMe` reads (one
 * request, one cache entry); off platform sign-in, absent.
 */
export const useMyPermissions = () =>
  useSessionQuery({
    queryKey: ['me'],
    queryFn: () => api.teams.me!(),
    enabled: !!api.teams.me,
    staleTime: 60_000,
    select: (me) => me.permissions,
  });

/**
 * Whether the person may take `area.action` in the team the console acts in, as the service will decide it: the
 * team's own answer or one held in every team (a workspace admin). Off platform sign-in, where no grid is served, a
 * signed-in person may take every action. Undefined while loading, so nothing flashes on and off.
 */
/** Whether the person holds `area.action` across the whole workspace (a workspace admin), not only in a team. */
export function useCanInWorkspace(area: string, action: string): boolean | undefined {
  const perms = useMyPermissions();
  if (!api.teams.me) return false;
  if (!perms.data) return undefined;
  return (perms.data.workspace ?? []).some((p) => p.area === area && p.action === action);
}

/** One page of the workspace's roles, one role with its grid, and a person's grants; disabled off platform sign-in. */
export const useRoles = (p: ListParams) => usePagedQuery({ queryKey: ['access', 'roles', p], queryFn: () => api.teams.roles!(p), enabled: !!api.teams.roles });
/**
 * Roles for a picker: searched on the server as typed, or named by id; a page number is the cursor. `except` leaves a
 * role out of what the picker offers (the role being deleted); `filters` are the server's own (`builtin`,
 * `canDecideReviews`), so each page already holds only what the field offers.
 */
export const rolesWhere = (key: string, except: string[] = [], filters?: Record<string, string[]>): OptionSource => ({
  key,
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await api.teams.roles!(ids?.length ? { page: 1, pageSize: Math.min(ids.length, 50), ids } : { page, pageSize: limit, search: search || undefined, filters });
    return {
      data: res.data.filter((r) => ids?.includes(r.id) || !except.includes(r.id)).map((r) => ({ id: r.id, label: r.name, hint: r.description })),
      nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null,
    };
  },
});
export const useRole = (id: string) => useTeamQuery({ queryKey: ['access', 'role', id], queryFn: () => api.teams.role!(id), enabled: !!api.teams.role && !!id });
/** Saves every cell of a role, or puts a built-in role back to its default; both refresh the role and the role list. */
export function useEditRole(id: string) {
  const qc = useQueryClient();
  const settled = () => Promise.all([qc.invalidateQueries({ queryKey: ['access', 'role', id] }), qc.invalidateQueries({ queryKey: ['access', 'roles'] })]);
  const save = useMutation({ mutationFn: (cells: RoleCell[]) => api.teams.editRole!(id, cells), onSuccess: settled });
  const reset = useMutation({ mutationFn: () => api.teams.resetRole!(id), onSuccess: settled });
  return { save, reset };
}
/** Whether the signed-in person makes and changes the workspace's roles: access.manage, on platform sign-in. */
export function useManagesRoles(): boolean {
  return useCan('access', 'manage') === true && !!api.teams.createRole;
}

/** Makes a custom role; the list refreshes so it shows at once. */
export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (input: RoleInput) => api.teams.createRole!(input), onSuccess: () => qc.invalidateQueries({ queryKey: ['access', 'roles'] }) });
}

/** Renames or deletes a custom role (`moveTo`: the role its holders move to). */
export function useRoleChanges(id: string) {
  const qc = useQueryClient();
  const settled = () => Promise.all([qc.invalidateQueries({ queryKey: ['access', 'role', id] }), qc.invalidateQueries({ queryKey: ['access', 'roles'] })]);
  const rename = useMutation({ mutationFn: (input: { name: string; description?: string }) => api.teams.renameRole!(id, input), onSuccess: settled });
  const remove = useMutation({ mutationFn: (moveTo?: string) => api.teams.deleteRole!(id, moveTo), onSuccess: settled });
  return { rename, remove };
}

/** One page of who holds a role (with the total), read while the delete dialog is open. */
export const useRoleHolders = (id: string, enabled: boolean, p: ListParams = { page: 1, pageSize: 10 }) =>
  useTeamQuery({ queryKey: ['access', 'role', id, 'holders', p], queryFn: () => api.teams.roleHolders!(id, p), enabled: enabled && !!api.teams.roleHolders });

/** The custom roles given to a person, and giving or taking one; their access refreshes after either. */
export function useRoleGrants(personId: string, p: ListParams = { page: 1, pageSize: 20 }) {
  const qc = useQueryClient();
  const grants = useTeamQuery({ queryKey: ['access', 'person', personId, 'grants', p], queryFn: () => api.teams.roleGrants!(personId, p), enabled: !!api.teams.roleGrants && !!personId });
  const settled = () => Promise.all([qc.invalidateQueries({ queryKey: ['access', 'person', personId] }), qc.invalidateQueries({ queryKey: ['access', 'roles'] })]);
  const give = useMutation({ mutationFn: (input: { roleId: string }) => api.teams.giveRole!(personId, input), onSuccess: settled });
  const take = useMutation({ mutationFn: (grantId: string) => api.teams.takeRole!(personId, grantId), onSuccess: settled });
  return { grants, give, take, available: !!api.teams.giveRole };
}

export const usePersonPermissions = (id: string) =>
  useTeamQuery({ queryKey: ['access', 'person', id], queryFn: () => api.teams.personPermissions!(id), enabled: !!api.teams.personPermissions && !!id });

/** Why the signed-in person may not take `area.action` here, read only for a control that is locked. */
export function useWhy(area: string, action: string, enabled: boolean) {
  const { teamId } = useTeam();
  return useTeamQuery({ queryKey: ['access', 'why', teamId, area, action], queryFn: () => api.teams.why!(area, action), enabled: enabled && !!api.teams.why, staleTime: 60_000 });
}

/** Runs one access check; a mutation, as each check is written to the audit log. */
export const useCheckAccess = () =>
  useMutation({ mutationFn: (input: { personId: string; area: string; action: string; owner?: string; requestedBy?: string }) => api.teams.checkAccess!(input) });

/** Renames the workspace; the header reads the new name from the next /v1/me. */
export function useRenameWorkspace() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (name: string) => api.teams.renameWorkspace!(name), onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }) });
}

export function useCan(area: string, action: string, everyTeam = false): boolean | undefined {
  return useCanCheck()(area, action, everyTeam);
}

/**
 * Whether the person may open a nav page with these needs (lib/nav.ts): true for a page that needs nothing, undefined
 * while permissions load. The sidebar, the title switcher and search all read it, so none offers a page that refuses.
 */
export function useNavAllows(): (needs?: NavNeed) => boolean | undefined {
  const can = useCanCheck();
  return (needs) => (needs ? can(needs.area, needs.action, needs.everyTeam) : true);
}

/**
 * useCan as a function, for a list whose checks are known only as data (the sidebar's rows). `everyTeam` asks for the
 * cell held in every team at once (a `*` role), the account admin's check.
 */
export function useCanCheck(): (area: string, action: string, everyTeam?: boolean) => boolean | undefined {
  // The team the console acts in: the stored id when it is one of the person's teams, else their first, as useTeam does.
  const { teamId, team } = useTeam();
  const current = team?.id ?? teamId;
  const perms = useMyPermissions();
  const { session } = useSession();
  return (area, action, everyTeam = false) => {
    // Off platform sign-in no grid is served: a signed-in person may take every action (the mock has no roles to tell them apart).
    if (!api.teams.me) return session ? true : undefined;
    if (!perms.data) return undefined;
    const held = (list: { area: string; action: string }[]) => list.some((p) => p.area === area && p.action === action);
    if (everyTeam) return held(perms.data.workspace ?? []);
    const mine = perms.data.teams.find((t) => t.teamId === current);
    // The Security team's actions are held in that team whatever team the console acts in.
    const security = perms.data.teams.some((t) =>
      t.permissions.some((p) => p.area === area && p.action === action && p.securityTeamOnly),
    );
    return held(perms.data.workspace ?? []) || (mine ? held(mine.permissions) : false) || security;
  };
}

/**
 * The person's teams in which they hold `area.action`: all of them when a workspace role grants it, undefined while
 * permissions load. A list that spans teams shows only these, and a team picker offers only these.
 */
export function useTeamsAllowing(area: string, action: string): string[] | undefined {
  const { team, teamId, teams } = useTeam();
  const perms = useMyPermissions();
  const here = useCanCheck()(area, action);
  // Without per-team permissions only the current team's answer is known.
  if (!api.teams.me) return here === undefined ? undefined : here ? [team?.id ?? teamId] : [];
  if (!perms.data) return undefined;
  const held = (list: { area: string; action: string }[]) => list.some((p) => p.area === area && p.action === action);
  if (held(perms.data.workspace ?? [])) return teams.map((t) => t.id);
  return perms.data.teams.filter((t) => held(t.permissions)).map((t) => t.teamId);
}

/** Who may take `area.action` in the current team, asked only while `enabled` (a "View only" notice is showing). */
/** Who holds `area.action` in `forTeam` (a record's team), else the current team. */
export function useHolders(area: string, action: string, enabled: boolean, forTeam?: string) {
  const { team, teamId } = useTeam();
  // platform-service refuses the holders route to a person without access.view (a Chat user); a notice then names nobody.
  const mayRead = useCan('access', 'view') === true;
  return useTeamQuery({
    queryKey: ['holders', forTeam ?? team?.id ?? teamId, area, action],
    queryFn: () => api.teams.holders!(area, action, forTeam),
    enabled: enabled && mayRead && !!api.teams.holders,
    staleTime: 60_000,
  });
}

/**
 * Whether the person may change the team's `area` records (agents by default): `can(area, edit)`, the cell the
 * services check, so the console and the service never disagree. False while loading.
 */
export function useCanBuild(area = 'agents'): boolean {
  return useCan(area, 'edit') === true;
}

/**
 * The workspace's name and the signed-in person for the header and sidebar: platform-service's own answer (GET
 * /v1/me) under platform sign-in, and the mock's sample workspace only when the console runs on the mock. The
 * environment is known only on the mock. `workspace` is unset when the workspace has no name, so nothing stands in for
 * it. Undefined while loading.
 */
export function useWorkspaceIdentity(): { workspace?: string; environment?: string; user: { name: string; email: string } } | undefined {
  const me = useMe();
  const lookups = useTeamQuery({ queryKey: ['lookups'], queryFn: api.lookups.get, staleTime: 5 * 60_000, enabled: !api.teams.me });
  if (api.teams.me) return me.data ? { workspace: me.data.tenantName ?? undefined, user: { name: me.data.user.name, email: me.data.user.email } } : undefined;
  return lookups.data ? { workspace: lookups.data.workspace.name, environment: lookups.data.workspace.environment, user: lookups.data.currentUser } : undefined;
}
