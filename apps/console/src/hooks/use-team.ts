'use client';

import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { setCurrentTeamId, teamStore } from '@/lib/api/team-context';
import { wipeSavedQueries } from '@/lib/query-cache';
import type { TeamInput, TeamRef } from '@/lib/types/team';

import { useSessionQuery } from './team-query';

const TEAMS_KEY = ['teams'] as const;
const teamsQuery = { queryKey: TEAMS_KEY, queryFn: () => api.teams.list(), staleTime: 5 * 60_000 };

/**
 * Whether requests may go out for the current team: the person's teams have loaded and the current team is one of
 * them. Until then a team remembered in the tab, or the console default, may be one they do not hold, and its requests
 * would answer 404 or 403 (c-505). The shell's gate (app-shell.tsx) picks a team they hold when the current one is not.
 */
export function useTeamReady(): boolean {
  const teamId = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  const teams = useSessionQuery(teamsQuery);
  return !!teams.data?.some((t) => t.id === teamId);
}

/**
 * The team the user is working as, the teams they can switch to, and the switch itself. Every API call carries
 * the current team, so switching clears the cached answers of the previous team.
 */
export function useTeam() {
  const qc = useQueryClient();
  const teamId = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  const teams = useSessionQuery(teamsQuery);
  const team = teams.data?.find((t) => t.id === teamId) ?? teams.data?.[0];

  const switchTeam = React.useCallback(
    (id: string) => {
      if (id === teamStore.get()) return;
      // Nothing saved for the old team outlives the switch (c-560).
      void wipeSavedQueries();
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

  return { teamId, team, teams: teams.data ?? [], canCreate: !!api.teams.create, isPending: teams.isPending, isError: teams.isError && !teams.data, error: teams.data ? null : teams.error, retry: teams.refetch, switchTeam, create };
}

/** The owning team when a request failed because the record belongs to another team. */
export function teamOfError(error: unknown): TeamRef | null {
  const team = (error as { status?: number; team?: TeamRef } | null)?.team;
  return team && (error as { status?: number }).status === 403 ? team : null;
}
