'use client';

import { useHolders, useMe } from '@/hooks/me-queries';

/**
 * Where a person may not do something: "Ask an admin", naming who in the team may (`area.action` from the roles grid,
 * managing the team's apps by default), each a mail link, after `lead` when there is one. Before the answer comes, or
 * when nobody else holds it, it says to ask an admin.
 */
export function AskAnAdmin({ testId, area = 'connections', action = 'manage', lead }: { testId: string; area?: string; action?: string; lead?: string }) {
  const holders = useHolders(area, action, true);
  const me = useMe().data?.user.email?.toLowerCase();
  const people = (holders.data?.holders ?? []).filter((h) => h.email.toLowerCase() !== me);
  return (
    <span className="text-xs text-muted-foreground" data-testid={testId}>
      {lead && `${lead} `}
      Ask an admin
      {people.length > 0 && ': '}
      {people.map((p, i) => (
        <span key={p.id}>
          {i > 0 && (i === people.length - 1 ? ' or ' : ', ')}
          <a href={`mailto:${p.email}`} className="underline-offset-4 hover:underline">
            {p.name}
          </a>
        </span>
      ))}
    </span>
  );
}
