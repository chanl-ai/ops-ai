'use client';

import { usePathname } from 'next/navigation';
import { AlertCircle, ChevronDown, LogIn, SearchX, ShieldOff, Users, type LucideIcon } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { teamOfError, useTeam } from '@/hooks/use-team';
import { errorKind } from '@/lib/session-gate';

/**
 * The one state for a failed query (c-505), chosen by the answer's status so every page says the same thing for the
 * same failure: 401 asks the person to sign in again, 403 says they have no access here (or names the team that owns
 * the record and offers to switch to it), 404 says it was not found or belongs to another team and offers the switch,
 * and a 5xx or no answer at all offers a retry. Nothing renders an empty list that reads as "nothing exists".
 */
export function QueryError({
  what,
  onRetry,
  retrying,
  testId,
  error,
  back,
}: {
  what: string;
  onRetry: () => void;
  retrying?: boolean;
  /** The test id of the retry state, the one a page's own use cases look for. */
  testId?: string;
  /** The query's error, whose status picks the state. */
  error?: unknown;
  /** Where a record page goes back to when the record is not found. */
  back?: { label: string; href: string };
}) {
  const owner = teamOfError(error);
  if (owner) return <OtherTeam what={what} team={owner} />;
  switch (errorKind(error)) {
    case 'signed_out':
      return <SignedOut what={what} />;
    case 'forbidden':
      return <EmptyState icon={ShieldOff} title="You don’t have access here" description={`Your role in this team doesn’t let you see ${what}. A team admin can change that.`} action={back} testId="query-forbidden" />;
    case 'not_found':
      return <NotFound what={what} back={back} />;
    default:
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
}

function SignedOut({ what }: { what: string }) {
  const here = usePathname();
  return (
    <EmptyState
      icon={LogIn}
      title="Sign in again"
      description={`Your session ended, so ${what} can’t be shown. Sign in again to pick up where you left off.`}
      action={{ label: 'Sign in again', href: `/login?next=${encodeURIComponent(here)}` }}
      testId="query-signed-out"
    />
  );
}

function NotFound({ what, back }: { what: string; back?: { label: string; href: string } }) {
  const { teams, teamId, switchTeam } = useTeam();
  const others = teams.filter((t) => t.id !== teamId);
  return (
    <EmptyState
      icon={SearchX}
      title="Not found, or in another team"
      description={`We couldn’t find ${what} in this team. It may have been deleted, the link may be wrong, or it may belong to a team you aren’t viewing.`}
      secondaryAction={back}
      testId="query-not-found"
    >
      {others.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm">
              Switch team <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center">
            {others.map((t) => (
              <DropdownMenuItem key={t.id} onSelect={() => switchTeam(t.id)}>
                {t.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </EmptyState>
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
