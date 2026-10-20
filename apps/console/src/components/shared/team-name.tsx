'use client';

import { useTeam } from '@/hooks/use-team';

/**
 * An owning team's name, read from the person's own teams list so a renamed team shows its new name. Records carry
 * only the team id; a team the person is not in shows that id as another team's.
 */
export function teamLabel(teamId: string | null | undefined, teams: { id: string; name: string }[]): string {
  if (!teamId) return 'No team';
  return teams.find((t) => t.id === teamId)?.name ?? `${teamId} (another team)`;
}

export function TeamName({ teamId, className }: { teamId: string | null | undefined; className?: string }) {
  const { teams } = useTeam();
  return <span className={className}>{teamLabel(teamId, teams)}</span>;
}
