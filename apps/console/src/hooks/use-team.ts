'use client';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, setCurrentTeamId, teamStore } from '@/lib/api';
import type { TeamInput, TeamRef } from '@/lib/types/team';

const TEAMS_KEY = ['teams'] as const;

/**
 * The team the user is working as, the teams they can switch to, and the switch itself. Every API call carries
 * the current team, so switching clears the cached answers of the previous team.
 */
export function useTeam() {
  const qc = useQueryClient();
  const teamId = React.useSyncExternalStore(teamStore.subscribe, teamStore.get, teamStore.getServer);
  const teams = useQuery({ queryKey: TEAMS_KEY, queryFn: api.teams.list, staleTime: 5 * 60_000 });
  const team = teams.data?.find((t) => t.id === teamId) ?? teams.data?.[0];

  const switchTeam = React.useCallback(
    (id: string) => {
      if (id === teamStore.get()) return;
      setCurrentTeamId(id);
      // Teams are not team-scoped; everything else is answered for the new team.
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== TEAMS_KEY[0] });
    },
    [qc],
  );

  const create = useMutation({
    mutationFn: (input: TeamInput) => api.teams.create(input),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: TEAMS_KEY });
      switchTeam(t.id);
    },
  });

  return { teamId, team, teams: teams.data ?? [], isPending: teams.isPending, isError: teams.isError && !teams.data, retry: teams.refetch, switchTeam, create };
}

/** The owning team when a request failed because the record belongs to another team. */
export function teamOfError(error: unknown): TeamRef | null {
  const team = (error as { status?: number; team?: TeamRef } | null)?.team;
  return team && (error as { status?: number }).status === 403 ? team : null;
}
