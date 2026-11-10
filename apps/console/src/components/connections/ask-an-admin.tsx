'use client';

import { useHolders, useMe } from '@/hooks/me-queries';
import { askWhom } from '@/lib/ask-an-admin';

/**
 * Where a person may not do something: "Ask an admin", naming the first person granted it in the team itself
 * (`area.action` from the roles grid, managing the team's apps by default) as a mail link and how many more may
 * ("Priya Shah and 3 more"), after `lead` when there is one. Nobody granted in every team only (the install's first
 * admin) is named: with none in the team, it says to ask the team's admins, mailing them (lib/ask-an-admin.ts).
 */
export function AskAnAdmin({ testId, area = 'connections', action = 'manage', lead }: { testId: string; area?: string; action?: string; lead?: string }) {
  const holders = useHolders(area, action, true);
  const me = useMe().data?.user.email;
  const { first, more, all } = askWhom(holders.data?.holders ?? [], me);
  return (
    <span className="text-xs text-muted-foreground" data-testid={testId}>
      {lead && `${lead} `}
      {first ? (
        <>
          Ask an admin:{' '}
          <a href={`mailto:${first.email}`} className="underline-offset-4 hover:underline">
            {first.name}
          </a>
          {more > 0 && ` and ${more} more`}
        </>
      ) : all.length ? (
        <a href={`mailto:${all.map((h) => h.email).join(',')}`} className="underline-offset-4 hover:underline">
          Ask your team’s admins
        </a>
      ) : (
        'Ask an admin'
      )}
    </span>
  );
}
