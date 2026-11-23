'use client';

import { useTeamsNamed } from '@/hooks/use-team';

/**
 * An owning team's name, read by id from the teams the person may switch to, so a renamed team shows its new name.
 * Records carry only the team id; a team the person is not in shows that id as another team's.
 */
export function teamLabel(teamId: string | null | undefined, teams: { get(id: string): { name: string } | undefined }): string {
  if (!teamId) return 'No team';
  return teams.get(teamId)?.name ?? `${teamId} (another team)`;
}

export function TeamName({ teamId, className }: { teamId: string | null | undefined; className?: string }) {
  const teams = useTeamsNamed([teamId]);
  return <span className={className}>{teamLabel(teamId, teams)}</span>;
}
