'use client';

import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { ownTeamId, setCurrentTeamId, teamStore } from '@/lib/api/team-context';
import { wipeSavedQueries } from '@/lib/query-cache';
import { teamToUse } from '@/lib/session-gate';
import type { Team, TeamInput, TeamRef } from '@/lib/types/team';

import { useSessionQuery } from './team-query';

const TEAMS_KEY = ['teams'] as const;
const FRESH = 5 * 60_000;

/** The teams `ids` names that the person may switch to, by id, in one read: a team they do not hold is absent. */
const named = (ids: string[]) => {
  const wanted = [...new Set(ids.filter(Boolean))].sort();
  return {
    queryKey: [...TEAMS_KEY, 'ids', wanted] as const,
    queryFn: async () => new Map((await api.teams.list({ page: 1, pageSize: wanted.length, ids: wanted })).data.map((t) => [t.id, t])),
    enabled: wanted.length > 0,
    staleTime: FRESH,
  };
};

/** The current team and the person's own, the two the gate and every page need, read by id. */
function useHeldTeams(teamId: string) {
  return useSessionQuery(named([teamId, ownTeamId() ?? '']));
}

/**
 * Whether requests may go out for the current team: the person's teams have loaded and the current team is one of
 * them. Until then a team remembered in the tab, or the console default, may be one they do not hold, and its requests
 * would answer 404 or 403. The shell's gate (app-shell.tsx) picks a team they hold when the current one is not.
 */
export function useTeamReady(): boolean {
  const teamId = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  return !!useHeldTeams(teamId).data?.has(teamId);
}

/**
 * The person's teams among `ids`, by id, in one read for the lot: labels for the teams a page's rows name. A team
 * they do not hold is absent, which `teamLabel` shows as another team's.
 */
export function useTeamsNamed(ids: (string | null | undefined)[]): Map<string, Team> {
  return useSessionQuery(named(ids.filter((id): id is string => !!id))).data ?? NONE;
}
const NONE = new Map<string, Team>();

/**
 * The team the user is working as, the switch itself, and what the shell's gate needs when the current team is not
 * one they hold (`pick`: their own team, else their first by name; `noTeams` when they hold none). The teams to
 * switch to are searched on the server (`teamListPage`), never read whole. Every API call carries the current team, so
 * switching clears the cached answers of the previous team.
 */
export function useTeam() {
  const qc = useQueryClient();
  const teamId = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  const held = useHeldTeams(teamId);
  const team = held.data?.get(teamId);
  const missing = !!held.data && !team;
  const first = useSessionQuery({ queryKey: [...TEAMS_KEY, 'first'], queryFn: () => api.teams.list({ page: 1, pageSize: 1 }), enabled: missing, staleTime: FRESH });
  const pick = missing ? teamToUse(teamId, ownTeamId(), [...held.data!.keys(), ...(first.data?.data ?? []).map((t) => t.id)]) : null;
  const noTeams = missing && held.data!.size === 0 && first.data?.pagination.total === 0;
  const failed = held.isError ? held : first.isError ? first : null;

  const switchTeam = React.useCallback(
    (id: string, known?: Team) => {
      if (id === teamStore.get()) return;
      // Nothing saved for the old team outlives the switch.
      void wipeSavedQueries();
      // A team picked from a list is already known: the gate reads it from the cache instead of waiting on a read.
      if (known) {
        const own = ownTeamId() ?? '';
        const before = qc.getQueryData<Map<string, Team>>(named([teamStore.get(), own]).queryKey);
        const ownTeam = before?.get(own);
        qc.setQueryData(named([id, own]).queryKey, new Map([[id, known], ...(ownTeam ? [[own, ownTeam] as const] : [])]));
      }
      setCurrentTeamId(id);
      // Teams are not team-scoped; everything else is answered for the new team.
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== TEAMS_KEY[0] });
    },
    [qc],
  );

  const create = useMutation({
    mutationFn: (input: TeamInput) => api.teams.create!(input),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: TEAMS_KEY });
      switchTeam(t.id);
    },
  });

  return {
    teamId,
    team,
    pick,
    noTeams,
    canCreate: !!api.teams.create,
    isPending: held.isPending || (missing && first.isPending),
    isError: !!failed && !team,
    error: team ? null : (failed?.error ?? null),
    retry: () => void (failed ?? held).refetch(),
    switchTeam,
    create,
  };
}

/** One page of the teams the person may switch to, by name, for the switcher's server search (`useServerList`). */
export const teamListPage = (ask: { page: number; pageSize: number; search?: string }) => api.teams.list(ask);

/** The owning team when a request failed because the record belongs to another team. */
export function teamOfError(error: unknown): TeamRef | null {
  const team = (error as { status?: number; team?: TeamRef } | null)?.team;
  return team && (error as { status?: number }).status === 403 ? team : null;
}
