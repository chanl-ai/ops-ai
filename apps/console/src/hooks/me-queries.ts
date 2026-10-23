'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { MemberRole } from '@/lib/types/settings';

import { useSession } from './auth-queries';
import { useTeam } from './use-team';
import { useSessionQuery, useTeamQuery } from './team-query';

/** The person's roles from platform-service (GET /v1/me); disabled off platform sign-in, where `teams.me` is absent. */
export const useMe = () => useSessionQuery({ queryKey: ['me'], queryFn: () => api.teams.me!(), enabled: !!api.teams.me, staleTime: 60_000 });

/**
 * The person's role in the team the console acts in. Platform sign-in reads it from /v1/me; the mock and dev sign-ins
 * carry no per-team roles, so their workspace role stands in (member as builder). Undefined while loading.
 */
export function useTeamRole(): MemberRole | undefined {
  const { teamId } = useTeam();
  const me = useMe();
  const { session } = useSession();
  if (api.teams.me) return me.data?.teams.find((t) => t.id === teamId)?.role ?? me.data?.teams[0]?.role;
  const role = session?.user.teamRoles?.[teamId] ?? session?.user.role;
  return role === 'member' ? 'builder' : role;
}

/** What `can()` grants the person in each team and in every team (GET /v1/me/permissions); off platform sign-in, absent. */
export const useMyPermissions = () =>
  useSessionQuery({
    queryKey: ['me', 'permissions'],
    queryFn: () => api.teams.permissions!(),
    enabled: !!api.teams.permissions,
    staleTime: 60_000,
  });

/**
 * Whether the person may take `area.action` in the team the console acts in, as the service will decide it: the
 * team's own answer or one held in every team (a workspace admin). Off platform sign-in, where no grid is served, the
 * session's role stands in (builders and admins build). Undefined while loading, so nothing flashes on and off.
 */
/** Whether the person holds `area.action` across the whole workspace (a workspace admin), not only in a team. */
export function useCanInWorkspace(area: string, action: string): boolean | undefined {
  const perms = useMyPermissions();
  if (!api.teams.permissions) return false;
  if (!perms.data) return undefined;
  return (perms.data.workspace ?? []).some((p) => p.area === area && p.action === action);
}

/** The workspace's roles, one role with its grid, and a person's grants (c-150); disabled off platform sign-in. */
export const useRoles = () => useTeamQuery({ queryKey: ['access', 'roles'], queryFn: () => api.teams.roles!(), enabled: !!api.teams.roles });
export const useRole = (id: string) => useTeamQuery({ queryKey: ['access', 'role', id], queryFn: () => api.teams.role!(id), enabled: !!api.teams.role && !!id });
export const usePersonPermissions = (id: string) =>
  useTeamQuery({ queryKey: ['access', 'person', id], queryFn: () => api.teams.personPermissions!(id), enabled: !!api.teams.personPermissions && !!id });

/** Why the signed-in person may not take `area.action` here, read only for a control that is locked. */
export function useWhy(area: string, action: string, enabled: boolean) {
  const { teamId } = useTeam();
  return useTeamQuery({ queryKey: ['access', 'why', teamId, area, action], queryFn: () => api.teams.why!(area, action), enabled: enabled && !!api.teams.why, staleTime: 60_000 });
}

/** Runs one access check (c-150); a mutation, as each check is written to the audit log. */
export const useCheckAccess = () =>
  useMutation({ mutationFn: (input: { personId: string; area: string; action: string; owner?: string; requestedBy?: string }) => api.teams.checkAccess!(input) });

/** Renames the workspace; the header reads the new name from the next /v1/me. */
export function useRenameWorkspace() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (name: string) => api.teams.renameWorkspace!(name), onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }) });
}

export function useCan(area: string, action: string): boolean | undefined {
  // The team the console acts in: the stored id when it is one of the person's teams, else their first, as useTeam does.
  const { teamId, team } = useTeam();
  const current = team?.id ?? teamId;
  const perms = useMyPermissions();
  const role = useTeamRole();
  if (!api.teams.permissions) return role === undefined ? undefined : role === 'builder' || role === 'admin';
  if (!perms.data) return undefined;
  const held = (list: { area: string; action: string }[]) => list.some((p) => p.area === area && p.action === action);
  const mine = perms.data.teams.find((t) => t.teamId === current);
  // The Security team's actions are held in that team whatever team the console acts in.
  const security = perms.data.teams.some((t) =>
    t.permissions.some((p) => p.area === area && p.action === action && p.securityTeamOnly),
  );
  return held(perms.data.workspace ?? []) || (mine ? held(mine.permissions) : false) || security;
}

/** Who may take `area.action` in the current team, asked only while `enabled` (a "View only" notice is showing). */
/** Who holds `area.action` in `forTeam` (a record's team), else the current team. */
export function useHolders(area: string, action: string, enabled: boolean, forTeam?: string) {
  const { team, teamId } = useTeam();
  return useTeamQuery({
    queryKey: ['holders', forTeam ?? team?.id ?? teamId, area, action],
    queryFn: () => api.teams.holders!(area, action, forTeam),
    enabled: enabled && !!api.teams.holders,
    staleTime: 60_000,
  });
}

/**
 * Whether the person may change the team's `area` records (agents by default): `can(area, edit)`, the cell the
 * services check, so the console and the service never disagree (c-186). False while loading.
 */
export function useCanBuild(area = 'agents'): boolean {
  return useCan(area, 'edit') === true;
}

/**
 * The workspace's name and the signed-in person for the header and sidebar: platform-service's own answer (GET
 * /v1/me) under platform sign-in, and the mock's sample workspace only when the console runs on the mock. The
 * environment is known only on the mock. Undefined while loading.
 */
export function useWorkspaceIdentity(): { workspace: string; environment?: string; user: { name: string; email: string } } | undefined {
  const me = useMe();
  const lookups = useTeamQuery({ queryKey: ['lookups'], queryFn: api.lookups.get, staleTime: 5 * 60_000, enabled: !api.teams.me });
  if (api.teams.me) return me.data ? { workspace: me.data.tenantName ?? me.data.tenantId, user: { name: me.data.user.name, email: me.data.user.email } } : undefined;
  return lookups.data ? { workspace: lookups.data.workspace.name, environment: lookups.data.workspace.environment, user: lookups.data.currentUser } : undefined;
}
