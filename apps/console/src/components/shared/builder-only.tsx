'use client';

import * as React from 'react';
import { Eye } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useCan, useCanBuild, useHolders, useMe } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';

/** Renders its children only for a person `can()` lets change the team's `area` records (agents by default). */
export function BuilderOnly({ children, area }: { children: React.ReactNode; area?: string }) {
  return useCanBuild(area) ? <>{children}</> : null;
}

/**
 * Disables every control inside it for a person who may not change the team's records, so a record page stays
 * readable but cannot be edited. `display: contents` keeps the layout of what it wraps.
 */
export function BuilderFieldset({ children, area, canEdit }: { children: React.ReactNode; area?: string; canEdit?: boolean }) {
  const team = useCanBuild(area);
  // A record's own flag (its detail response) when the page has one; the team's permission otherwise.
  const can = canEdit ?? team;
  return (
    <fieldset disabled={!can} className="contents" data-testid={can ? undefined : 'read-only'}>
      {children}
    </fieldset>
  );
}

/**
 * Says why a page has no edit controls, to whoever `can()` does not let change the record. `noun` is the plural record
 * name; `teamId` is the record's team. On another team's record it names that team, lists who changes it there when the
 * person belongs to it, and offers the switch. It never lists the person reading. It waits for the answer: undefined while the permissions load, so "View only" never flashes.
 */
export function ReadOnlyNotice({ noun, area = 'agents', canEdit, teamId, teamName }: { noun: string; area?: string; canEdit?: boolean; teamId?: string | null; teamName?: string | null }) {
  const team = useCan(area, 'edit');
  const can = canEdit ?? team;
  const { team: current, teams, switchTeam } = useTeam();
  const other = teamId && current && teamId !== current.id ? (teams.find((t) => t.id === teamId) ?? { id: teamId, name: teamName ?? teamId }) : undefined;
  const member = !!other && teams.some((t) => t.id === other.id);
  const me = useMe().data?.user.email?.toLowerCase();
  // The record's own team when it is another one the person belongs to; the holders route refuses a team they are not in.
  const holders = useHolders(area, 'edit', can === false && (!other || member), other?.id);
  if (can !== false) return null;
  const roles = holders.data?.roles.map((r) => r.name) ?? [];
  const people = (holders.data?.holders ?? []).filter((h) => h.email.toLowerCase() !== me).map((h) => h.name);
  return (
    <Alert data-testid="read-only-notice">
      <Eye className="size-4" />
      <AlertTitle>View only</AlertTitle>
      <AlertDescription data-testid="read-only-why">
        {other ? (
          <span>
            This belongs to {other.name}. {member ? (people.length ? `Ask ${list(people)}, or switch to it.` : '') : `Builders and admins of ${other.name} change it.`}{' '}
            {member && (
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => switchTeam(other.id)} data-testid="read-only-switch">
                Switch to {other.name}
              </Button>
            )}
          </span>
        ) : (
          <>
            You can open this team&apos;s {noun}. {roles.length ? `${list(roles)} of the team change them` : 'Builders and admins of the team change them'}
            {people.length ? `; ask ${list(people)}.` : '.'}
          </>
        )}
      </AlertDescription>
    </Alert>
  );
}

/** "a", "a or b", "a, b or c". */
function list(names: string[]): string {
  return names.length < 2 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`;
}
