'use client';

import { useHolders, useMe } from '@/hooks/me-queries';

/**
 * Where a person may not connect an app: "Ask an admin", naming who in the team may (connections.manage, from the
 * roles grid), each a mail link. Before the answer comes, or when nobody else holds it, it says to ask a team admin.
 */
export function AskAnAdmin({ testId }: { testId: string }) {
  const holders = useHolders('connections', 'manage', true);
  const me = useMe().data?.user.email?.toLowerCase();
  const people = (holders.data?.holders ?? []).filter((h) => h.email.toLowerCase() !== me);
  return (
    <span className="text-xs text-muted-foreground" data-testid={testId}>
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
