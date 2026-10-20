'use client';

import { AlertCircle, Users, type LucideIcon } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { teamOfError, useTeam } from '@/hooks/use-team';

/**
 * Error state for a failed query, matching the shared component library's list pages: the section degrades with an
 * honest message and a retry instead of rendering an empty list that reads as "nothing exists".
 */
export function QueryError({
  what,
  onRetry,
  retrying,
  testId,
  error,
}: {
  what: string;
  onRetry: () => void;
  retrying?: boolean;
  testId?: string;
  /** The query's error; a record owned by another team shows who owns it and offers to switch. */
  error?: unknown;
}) {
  const owner = teamOfError(error);
  if (owner) return <OtherTeam what={what} team={owner} />;
  return (
    <EmptyState
      icon={AlertCircle}
      title={`Couldn’t load ${what}`}
      description="The request failed. Nothing has changed on your side; try again in a moment."
      action={{ label: retrying ? 'Retrying…' : 'Try again', onClick: onRetry, disabled: retrying }}
      testId={testId}
    />
  );
}

function OtherTeam({ what, team }: { what: string; team: { id: string; name: string } }) {
  const { switchTeam } = useTeam();
  return (
    <EmptyState
      icon={Users}
      title={`This belongs to ${team.name}`}
      description={`You are viewing a different team, so ${what} is hidden. Switch to ${team.name} to open it.`}
      action={{ label: `Switch to ${team.name}`, onClick: () => switchTeam(team.id) }}
    />
  );
}

/** Empty state for a list, switching copy when filters are what emptied it. */
export function ListEmpty({
  icon,
  noun,
  filtered,
  onClear,
  createLabel,
  onCreate,
  description,
}: {
  icon: LucideIcon;
  noun: string;
  filtered: boolean;
  onClear?: () => void;
  createLabel?: string;
  onCreate?: () => void;
  description: string;
}) {
  if (filtered) {
    return (
      <EmptyState
        icon={icon}
        title={`No ${noun} match these filters`}
        description="Change the search or remove a filter to see more."
        action={onClear ? { label: 'Clear filters', onClick: onClear } : undefined}
      />
    );
  }
  return (
    <EmptyState
      icon={icon}
      title={`No ${noun} yet`}
      description={description}
      action={createLabel && onCreate ? { label: createLabel, onClick: onCreate } : undefined}
    />
  );
}
