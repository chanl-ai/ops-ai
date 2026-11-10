'use client';

import { useHolders, useMe } from '@/hooks/me-queries';

/**
 * Where a person may not do something: "Ask an admin", naming the first in the team who may (`area.action` from the
 * roles grid, managing the team's apps by default) as a mail link and how many more may ("Priya Shah and 3 more"), after
 * `lead` when there is one. Before the answer comes, or when nobody else holds it, it says to ask an admin.
 */
export function AskAnAdmin({ testId, area = 'connections', action = 'manage', lead }: { testId: string; area?: string; action?: string; lead?: string }) {
  const holders = useHolders(area, action, true);
  const me = useMe().data?.user.email?.toLowerCase();
  const people = (holders.data?.holders ?? []).filter((h) => h.email.toLowerCase() !== me);
  // One name to ask and how many more hold it, so a team with several admins reads as one line.
  const first = people[0];
  return (
    <span className="text-xs text-muted-foreground" data-testid={testId}>
      {lead && `${lead} `}
      Ask an admin
      {first && ': '}
      {first && (
        <a href={`mailto:${first.email}`} className="underline-offset-4 hover:underline">
          {first.name}
        </a>
      )}
      {people.length > 1 && ` and ${people.length - 1} more`}
    </span>
  );
}
